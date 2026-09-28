# Edición Flathub

Esta carpeta es la candidatura a Flathub. Flathub construye desde el fuente
público, y **IngePresupuestos es software libre bajo GPL-3.0-or-later**.

Publicar en Flathub es prioritario por dos razones:

1. **Descubrimiento.** Es el cuello de botella real del proyecto: el Flatpak
   sideload instala, pero no aparece en ninguna tienda. Flathub sí, y con él
   GNOME Software y KDE Discover.
2. **Botón de aporte.** El `<url type="donation">` del metainfo hace aparecer
   un botón «Donar» en la ficha de la app, apuntando a
   <https://liberapay.com/ingelibre/donate>.

## Estado y pendientes

- Los PRs anteriores a Flathub nunca llegaron a mergearse; hay que retomar la
  solicitud desde cero contra `flathub/flathub`.
- `com.ingepresupuestos.IngePresupuestos.metainfo.xml` ya declara
  `<project_license>GPL-3.0-or-later</project_license>`.
- Falta añadir el `<url type="donation">` al metainfo (tarea del plan de la 3.0).

## Relación con la edición sideload

El canal Flatpak que hoy funciona es la **edición sideload**
(`installer/flatpak/`), publicada firmada en R2 vía `publish-flatpak.yml`.
Ambas ediciones instalan el **código fuente `.py`**. **No compilar a bytecode
ni borrar los `.py`** (`compileall -b`).

Diferencia real entre las dos: la sideload usa el LibreOffice del host vía
`flatpak-spawn` para ODT/ODS; en Flathub eso está bloqueado y esos botones se
ocultan (ver `core/soffice.py::odf_export_ofrecible`).
