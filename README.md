# ORIGINS IDLE

Nuevo proyecto limpio para construir un idle inspirado en Legend of Mir usando recursos Zircon/Holley como fuente visual.

## Fase actual: mapas

Primer objetivo: crear fondos de combate por zonas, sin reconstruir mapas completos.

### Zone 01 prototype

La primera zona se genera a partir de un fragmento real de `01.map`:

- mapa fuente: `01.map` (Wemade Mir3 MapType5, 600x600)
- terreno principal: `Map Data/Tiles30c.Zl`
- decoracion: `Map Data/SmObjectsc.Zl`
- recorte de prueba: X=190, Y=484, ancho=24 celdas, alto=20 celdas
- salida nativa: 1152x640 px

El fondo generado se guarda en `assets/zones/zone01/zone01_background.png`.

La herramienta reproducible estara en `tools/zone_builder/`.
