#!/usr/bin/env python3
"""Build ORIGINS IDLE Zone 01 from a real Holley/Wemade Mir3 map fragment.

Current prototype support:
- Wemade Mir3 MapType5 (.map)
- Zircon ZL legacy and ZL2 image libraries
- Back layer from Tiles30c (original map library id 201)
- Middle/front decoration from SmObjectsc (original map library id 210)

Example:
    python build_zone01.py \
      --map 01.map \
      --tiles30 Tiles30c.Zl \
      --smobjects SmObjectsc.Zl \
      --output zone01_background.png
"""

from __future__ import annotations

import argparse
import io
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image

CELL_W = 48
CELL_H = 32
DEFAULT_X = 190
DEFAULT_Y = 484
DEFAULT_W = 24
DEFAULT_H = 20

CODECS = {0: "dxt1", 1: "dxt5", 2: "bgra32", 3: "bc7", 4: "png"}


class ZoneBuildError(RuntimeError):
    pass


def _read(fmt: str, data: bytes, offset: int):
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(data):
        raise ZoneBuildError(f"Truncated data at 0x{offset:X}: {fmt}")
    return struct.unpack_from(fmt, data, offset), offset + size


@dataclass
class ZlImage:
    image_id: int
    present: bool
    position: Optional[int] = None
    width: int = 0
    height: int = 0
    offset_x: int = 0
    offset_y: int = 0
    codec: Optional[str] = None
    image_codec_id: Optional[int] = None
    stored_size: int = 0
    bc7_size: int = 0
    fallback_size: int = 0


@dataclass
class ZlEntry:
    uncompressed: int
    compressed: int
    offset: int
    compression: int


class ZlLibrary:
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        self.kind = ""
        self.version = 0
        self.images: dict[int, ZlImage] = {}
        self.entries: dict[int, ZlEntry] = {}
        if self.data.startswith(b"ZL2"):
            self._parse_zl2()
        else:
            self._parse_legacy()

    def _parse_legacy(self):
        self.kind = "legacy"
        if len(self.data) < 8:
            raise ZoneBuildError(f"{self.path}: invalid ZL")
        (header_size,), _ = _read("<i", self.data, 0)
        header = self.data[4 : 4 + header_size]
        (value,), offset = _read("<i", header, 0)
        self.version = (value >> 25) & 0x7F
        count = (value & 0x1FFFFFF) if self.version else value
        if self.version not in (0, 1):
            raise ZoneBuildError(f"{self.path}: unsupported legacy ZL version {self.version}")
        codec = "dxt1" if self.version == 0 else "dxt5"
        for image_id in range(count):
            (present,), offset = _read("<B", header, offset)
            if not present:
                self.images[image_id] = ZlImage(image_id, False)
                continue
            values, offset = _read("<ihhhhBhhhhhh", header, offset)
            pos, width, height, ox, oy, *_ = values
            self.images[image_id] = ZlImage(
                image_id=image_id,
                present=True,
                position=pos,
                width=width,
                height=height,
                offset_x=ox,
                offset_y=oy,
                codec=codec,
            )

    def _parse_zl2(self):
        self.kind = "zl2"
        offset = 3
        (version, count, _atlas), offset = _read("<iii", self.data, offset)
        self.version = version
        (_, _, _), offset = _read("<BBh", self.data, offset)
        (meta_offset,), offset = _read("<q", self.data, offset)
        (meta_size,), offset = _read("<i", self.data, offset)
        (index_offset,), offset = _read("<q", self.data, offset)
        (index_size,), offset = _read("<i", self.data, offset)

        index = self.data[index_offset : index_offset + index_size]
        (entry_count,), pos = _read("<i", index, 0)
        for _ in range(entry_count):
            (_,), pos = _read("<B", index, pos)
            (entry_id, unc, comp), pos = _read("<iii", index, pos)
            (payload_offset,), pos = _read("<q", index, pos)
            (compression, _codec), pos = _read("<BB", index, pos)
            self.entries[entry_id] = ZlEntry(unc, comp, payload_offset, compression)

        meta = self.data[meta_offset : meta_offset + meta_size]
        pos = 0
        (_meta_ver, meta_count, _group, _page), pos = _read("<iiii", meta, pos)
        if meta_count != count:
            raise ZoneBuildError(f"{self.path}: ZL2 image count mismatch")

        for image_id in range(count):
            (present,), pos = _read("<B", meta, pos)
            if not present:
                self.images[image_id] = ZlImage(image_id, False)
                continue
            values, pos = _read("<ihhhhBhhhhhh", meta, pos)
            entry_id, width, height, ox, oy, *_ = values
            (_,), pos = _read("<i", meta, pos)
            _, pos = _read("<hhhh", meta, pos)
            _, pos = _read("<hhhh", meta, pos)
            (image_codec, _shadow_codec, _overlay_codec, _ip, _sp, _op), pos = _read("<BBBBBB", meta, pos)
            sizes, pos = _read("<iiiiiiiii", meta, pos)
            self.images[image_id] = ZlImage(
                image_id=image_id,
                present=True,
                position=entry_id,
                width=width,
                height=height,
                offset_x=ox,
                offset_y=oy,
                image_codec_id=image_codec,
                stored_size=sizes[0],
                bc7_size=sizes[1],
                fallback_size=sizes[2],
            )

    @staticmethod
    def _blocks(width: int, height: int, bytes_per_block: int) -> int:
        return ((width + 3) // 4) * ((height + 3) // 4) * bytes_per_block

    @staticmethod
    def _dds(width: int, height: int, codec: str, payload_size: int) -> bytes:
        fourcc = b"DXT1" if codec == "dxt1" else b"DXT5"
        flags = 0x2100F
        caps = 0x1000
        header = struct.pack("<IIIII", 124, flags, height, width, payload_size)
        header += struct.pack("<II", 0, 0)
        header += struct.pack("<11I", *([0] * 11))
        header += struct.pack("<II", 32, 4) + fourcc
        header += struct.pack("<5I", 0, 0, 0, 0, 0)
        header += struct.pack("<I", caps) + struct.pack("<4I", 0, 0, 0, 0)
        return b"DDS " + header

    @staticmethod
    def _dds_bc7(width: int, height: int, payload_size: int) -> bytes:
        flags = 0x2100F
        caps = 0x1000
        header = struct.pack("<IIIII", 124, flags, height, width, payload_size)
        header += struct.pack("<II", 0, 0)
        header += struct.pack("<11I", *([0] * 11))
        header += struct.pack("<II", 32, 4) + b"DX10"
        header += struct.pack("<5I", 0, 0, 0, 0, 0)
        header += struct.pack("<I", caps) + struct.pack("<4I", 0, 0, 0, 0)
        return b"DDS " + header + struct.pack("<IIIII", 98, 3, 0, 1, 0)

    @classmethod
    def _decode(cls, payload: bytes, width: int, height: int, codec: str) -> Image.Image:
        if codec == "png":
            return Image.open(io.BytesIO(payload)).convert("RGBA")
        if codec == "bgra32":
            return Image.frombytes("RGBA", (width, height), payload[: width * height * 4], "raw", "BGRA")
        if codec in ("dxt1", "dxt5"):
            size = cls._blocks(width, height, 8 if codec == "dxt1" else 16)
            return Image.open(io.BytesIO(cls._dds(width, height, codec, size) + payload[:size])).convert("RGBA")
        if codec == "bc7":
            size = cls._blocks(width, height, 16)
            return Image.open(io.BytesIO(cls._dds_bc7(width, height, size) + payload[:size])).convert("RGBA")
        raise ZoneBuildError(f"Unsupported codec: {codec}")

    def image(self, image_id: int) -> Optional[Image.Image]:
        meta = self.images.get(image_id)
        if not meta or not meta.present:
            return None

        if self.kind == "legacy":
            codec = meta.codec or "dxt5"
            size = self._blocks(meta.width, meta.height, 8 if codec == "dxt1" else 16)
            start = meta.position or 0
            payload = self.data[start : start + size]
            return self._decode(payload, meta.width, meta.height, codec)

        if meta.position is None or meta.position not in self.entries:
            raise ZoneBuildError(f"Missing ZL2 payload for image {image_id}")
        entry = self.entries[meta.position]
        raw = self.data[entry.offset : entry.offset + entry.compressed]
        if entry.compression == 0:
            payload = raw
        elif entry.compression in (1, 2):
            try:
                payload = zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                payload = zlib.decompress(raw)
        else:
            raise ZoneBuildError(f"Unsupported ZL2 compression {entry.compression}")

        if meta.stored_size:
            return self._decode(payload[: meta.stored_size], meta.width, meta.height, CODECS[meta.image_codec_id or 0])
        if meta.bc7_size:
            start = meta.stored_size
            return self._decode(payload[start : start + meta.bc7_size], meta.width, meta.height, "bc7")
        if meta.fallback_size:
            start = meta.stored_size + meta.bc7_size
            return self._decode(payload[start : start + meta.fallback_size], meta.width, meta.height, "dxt5")
        return None


class MapType5:
    def __init__(self, path: Path):
        self.data = path.read_bytes()
        if not self.data or self.data[0] != 0:
            raise ZoneBuildError("Current prototype expects Wemade Mir3 MapType5")
        self.width = struct.unpack_from("<h", self.data, 22)[0]
        self.height = struct.unpack_from("<h", self.data, 24)[0]
        if self.width <= 0 or self.height <= 0:
            raise ZoneBuildError("Invalid map dimensions")
        self.cells = [[{} for _ in range(self.height)] for _ in range(self.width)]
        self._parse()

    def _parse(self):
        offset = 28
        for x in range(self.width // 2):
            for y in range(self.height // 2):
                file_byte = self.data[offset]
                image = struct.unpack_from("<H", self.data, offset + 1)[0] + 1
                file_id = file_byte + 200 if file_byte != 255 else -1
                for i in range(4):
                    self.cells[x * 2 + (i % 2)][y * 2 + (i // 2)].update(
                        back_file=file_id, back_image=image
                    )
                offset += 3

        offset = 28 + 3 * ((self.width // 2) + (self.width % 2)) * (self.height // 2)
        for x in range(self.width):
            for y in range(self.height):
                flag = self.data[offset]
                offset += 1
                middle_anim = self.data[offset]
                offset += 1
                front_anim = 0 if self.data[offset] == 255 else (self.data[offset] & 0x8F)
                offset += 1
                front_file = self.data[offset] + 200 if self.data[offset] != 255 else -1
                offset += 1
                middle_file = self.data[offset] + 200 if self.data[offset] != 255 else -1
                offset += 1
                middle_image = struct.unpack_from("<H", self.data, offset)[0] + 1
                offset += 2
                front_image = struct.unpack_from("<H", self.data, offset)[0] + 1
                offset += 2
                offset += 3
                light = self.data[offset] & 0x0F
                offset += 2
                self.cells[x][y].update(
                    flag=flag,
                    middle_anim=middle_anim,
                    front_anim=front_anim,
                    middle_file=middle_file,
                    middle_image=middle_image,
                    front_file=front_file,
                    front_image=front_image,
                    light=light,
                )


def build(map_path: Path, tiles_path: Path, smobjects_path: Path, output: Path, x0: int, y0: int, width: int, height: int):
    game_map = MapType5(map_path)
    tiles = ZlLibrary(tiles_path)
    smobjects = ZlLibrary(smobjects_path)

    if x0 % 2 or y0 % 2:
        raise ZoneBuildError("Patch origin must be even so 96x64 back tiles stay aligned")
    if x0 < 0 or y0 < 0 or x0 + width > game_map.width or y0 + height > game_map.height:
        raise ZoneBuildError("Patch is outside map bounds")

    canvas = Image.new("RGBA", (width * CELL_W, height * CELL_H), (0, 0, 0, 255))

    # Back layer. MapType5 stores one 96x64 tile for each 2x2 cell block.
    for gx in range(x0, x0 + width, 2):
        for gy in range(y0, y0 + height, 2):
            cell = game_map.cells[gx][gy]
            if cell.get("back_file") != 201:
                continue
            image_id = cell.get("back_image", 1) - 1
            tile = tiles.image(image_id)
            if tile:
                canvas.alpha_composite(tile, ((gx - x0) * CELL_W, (gy - y0) * CELL_H))

    # Middle/front decorations from SmObjectsc, sorted by Y for natural overlap.
    draw_list = []
    for gx in range(x0, x0 + width):
        for gy in range(y0, y0 + height):
            cell = game_map.cells[gx][gy]
            if cell.get("middle_file") == 210 and cell.get("middle_image") not in (0, 1, 65536):
                draw_list.append((gy * 2, gx, gy, cell["middle_image"] - 1))
            front_image = cell.get("front_image", 0) & 0x7FFF
            if cell.get("front_file") == 210 and front_image not in (0, 1):
                draw_list.append((gy * 2 + 1, gx, gy, front_image - 1))

    for _, gx, gy, image_id in sorted(draw_list):
        sprite = smobjects.image(image_id)
        meta = smobjects.images.get(image_id)
        if not sprite or not meta:
            continue
        anchor_x = (gx - x0) * CELL_W + CELL_W // 2
        anchor_y = (gy - y0) * CELL_H + CELL_H // 2
        px = anchor_x + meta.offset_x
        py = anchor_y + meta.offset_y
        canvas.alpha_composite(sprite, (px, py))

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "PNG", compress_level=9)
    print(f"Generated {output} ({canvas.width}x{canvas.height}) from map patch {x0},{y0} {width}x{height}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--tiles30", type=Path, required=True)
    parser.add_argument("--smobjects", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--x", type=int, default=DEFAULT_X)
    parser.add_argument("--y", type=int, default=DEFAULT_Y)
    parser.add_argument("--width", type=int, default=DEFAULT_W)
    parser.add_argument("--height", type=int, default=DEFAULT_H)
    args = parser.parse_args()
    build(args.map, args.tiles30, args.smobjects, args.output, args.x, args.y, args.width, args.height)


if __name__ == "__main__":
    main()
