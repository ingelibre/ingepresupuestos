# Procedencia de la iconografía

> **Estado: RESUELTO** (7 de agosto de 2026). Los 49 iconos copiados de los
> temas elementary / elementary-xfce (GPL / CC-BY-SA) fueron reemplazados por
> **Tabler Icons** (MIT) antes del cierre del código en la 2.9.0.

## Set actual — `elementary/24/`

La carpeta conserva su nombre y los archivos sus nombres históricos
(`document-save.svg`, `go-home.svg`, …) para no tocar los ~cientos de
call-sites de `utils/icons.py::icon()`. El contenido, sin embargo, ya no es
del tema elementary:

| Contenido | Origen | Licencia |
|---|---|---|
| 46 SVG de UI (trazo 2 px, color por defecto `#37474F`) | [Tabler Icons](https://github.com/tabler/tabler-icons) © Paweł Kuna | MIT |
| `starred.svg` (estrella rellena `#F9C440`) | Tabler Icons (variante *filled*) | MIT |
| 9 PNG (128/48 px) renderizados desde SVG de Tabler con color propio | Tabler Icons | MIT |
| `psychology.svg` | [Material Symbols](https://fonts.google.com/icons) © Google | Apache-2.0 |
| `brain.svg` | icono de trazo estilo Tabler/Lucide | permisiva |
| `ingepresupuestos.png/.ico`, `tuxia.png/.ico` | identidad propia del proyecto | © Sumari SAC |

`document-save-as.svg` y `text-html.svg` (copias de elementary sin ningún uso
en el código) se eliminaron.

### Reglas para iconos nuevos

1. Traer SVG *outline* de Tabler y reemplazar `stroke="currentColor"` por
   `stroke="#37474F"` — `colorize_svg` (utils/icons.py) re-tiñe ese hex para
   el sidebar oscuro.
2. PNG de tamaño fijo: renderizar el SVG de Tabler con `QSvgRenderer` al
   tamaño y color deseados (ver los 9 existentes como referencia).
3. **NUNCA volver a copiar archivos de temas de iconos del sistema**
   (elementary, Adwaita, Yaru, Papirus, elementary-xfce…): son GPL/CC-BY-SA
   y no pueden distribuirse en el producto propietario.

## Otras carpetas

- `hicolor/` — icono MIME propio (`application-x-ingepresupuestos-db`),
  dibujado para el proyecto. © Sumari SAC.
- `mimetypes/` — fuente vectorial del icono MIME. © Sumari SAC.
- SVG sueltos de la raíz (`check*.svg`, `arrow_down.svg`, `icon-256.png`) —
  dibujados para los widgets del proyecto. © Sumari SAC.

## Historial

La verificación que destapó el problema (comparación MD5 contra
`elementary-icon-theme 8.1.0-2` y `elementary-xfce-icon-theme 0.22-1`):

```bash
apt-get download elementary-icon-theme elementary-xfce-icon-theme
for d in *.deb; do dpkg-deb -x "$d" ext/; done
find ext -type f \( -name '*.svg' -o -name '*.png' \) -exec md5sum {} + | sort > elem.md5
md5sum resources/icons/elementary/24/* | sort > app.md5
join <(awk '{print $1" "$2}' elem.md5) <(awk '{print $1" "$2}' app.md5)
```

Hoy debe devolver **cero coincidencias**. Ejecutarla de nuevo si alguna vez se
agregan iconos de origen dudoso.
