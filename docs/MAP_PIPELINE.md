# Map pipeline

## Regla del proyecto

No reconstruimos mapas completos para jugar dentro de ellos. Usamos los mapas Holley/Wemade como fuente para obtener fragmentos y recursos visuales coherentes, y los convertimos en fondos de combate idle.

## Primer prototipo: 01.map

`01.map` es Wemade Mir3 MapType5 y mide 600x600 celdas.

El primer fondo se toma de un fragmento real:

- X: 190
- Y: 484
- ancho: 24 celdas
- alto: 20 celdas
- salida: 1152x640 px

En MapType5 cada celda mide 48x32 px y el back tile ocupa un bloque de 2x2 celdas (96x64 px).

### Mapeo usado en este prototipo

Los ids de libreria originales de MapType5 llevan base 200. Para este fragmento:

- 201 -> `Tiles30c.Zl` (suelo)
- 210 -> `SmObjectsc.Zl` (vegetacion, arboles, piedras y decoracion)

Los ids de imagen guardados en el `.map` son `imageId + 1`, por lo que al leerlos se resta 1 para consultar el `.Zl`.

## Resultado

El recorte elegido contiene suelo verde continuo y decoracion real del propio mapa 01, con una zona central suficientemente abierta para colocar posteriormente personaje y monstruos.

La herramienta `tools/zone_builder/build_zone01.py` reproduce el fondo usando solamente:

- `01.map`
- `Tiles30c.Zl`
- `SmObjectsc.Zl`

No requiere HispaRed ni reconstruir el mapa completo.
