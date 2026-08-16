# Procedencia de la iconografía

> **Estado: iconos de elementary restaurados** (15 de agosto de 2026, v3.0).
>
> Los 55 iconos de Tabler que entraron en la 2.9.0 fueron sustituidos por los
> originales de elementary de la v2.8.8. El motivo del cambio anterior ya no
> existe: se reemplazaron porque eran GPL/CC-BY-SA y el producto pasaba a ser
> propietario. **IngePresupuestos volvió a ser software libre bajo
> GPL-3.0-or-later, y con esa licencia los iconos de elementary son
> plenamente compatibles.**

## Set actual — `elementary/24/`

61 archivos (48 SVG · 11 PNG · 2 ICO).

| Contenido | Origen | Licencia |
|---|---|---|
| Iconos de UI del tema elementary | [elementary/icons](https://github.com/elementary/icons) © elementary, Inc. y colaboradores | GPL-3.0-or-later |
| Iconos provenientes de elementary-xfce | [shimmerproject/elementary-xfce](https://github.com/shimmerproject/elementary-xfce) | GPL-3.0 (relicenciado desde GPL-2.0 por el proyecto original) |
| `ingepresupuestos.png/.ico`, `tuxia.png/.ico` y demás identidad propia | dibujados para el proyecto © Marco Sumari | GPL-3.0-or-later |

La carpeta conserva el nombre `elementary/24/` y los archivos sus nombres
históricos (`document-save.svg`, `go-home.svg`, …) porque los ~cientos de
call-sites de `utils/icons.py::icon()` los referencian así.

`document-save-as.svg` y `text-html.svg` existían en la 2.8.8 pero no se
usaban en el código; **no se restauraron**.

## Compatibilidad de licencias — por qué esto ahora sí se puede

IngePresupuestos se distribuye bajo **GPL-3.0-or-later**. Los iconos de
elementary son **GPL-3.0-or-later** y los de elementary-xfce **GPL-3.0**:
misma familia de licencia, sin conflicto. Obra derivada y programa comparten
términos, y este archivo cumple la atribución que la GPL exige.

Si en el futuro alguien encuentra un icono heredado de una versión de
elementary-xfce anterior a su paso a GPLv3, la solución es traer el archivo
equivalente del upstream actual, que ya es GPL-3.0.

## Reglas para iconos nuevos

1. Preferir el upstream de [elementary/icons](https://github.com/elementary/icons)
   para mantener coherencia visual con el set.
2. Cualquier otro origen debe ser **compatible con GPL-3.0-or-later**:
   sirven GPL-3.0, GPL-2.0-**or-later**, MIT, Apache-2.0, CC-BY y CC-BY-SA 4.0.
   **No sirve** GPL-2.0-**only** ni nada con cláusula «no comercial».
3. Anotar aquí todo icono nuevo con su origen y licencia. Esa anotación **es**
   el cumplimiento de la atribución, no un trámite.
4. PNG de tamaño fijo: renderizar el SVG con `QSvgRenderer` al tamaño y color
   deseados (ver los existentes como referencia).

## Otras carpetas

- `hicolor/` — icono MIME propio (`application-x-ingepresupuestos-db`),
  dibujado para el proyecto. © Marco Sumari, GPL-3.0-or-later.
- `mimetypes/` — fuente vectorial del icono de documento.
