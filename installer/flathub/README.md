# Edición Flathub — DESCONTINUADA (era GPL, ≤2.8.8)

Esta carpeta era la candidatura a Flathub de la época en que IngePresupuestos
era software libre. **Desde la 2.9.0 el código es propietario y esta edición
NO debe publicarse**: Flathub construye desde el código fuente y este
manifiesto instalaría los `.py` legibles (además de que los PRs a Flathub
nunca llegaron a mergearse).

El canal Flatpak vigente es la **edición sideload** (`installer/flatpak/`),
que desde el cierre instala solo bytecode (`compileall -b` + borrado de
`.py`) y se publica firmada en R2 vía `publish-flatpak.yml`.

Se conserva la carpeta solo como referencia histórica.
