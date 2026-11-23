# Conexión con IA (MCP)

IngePresupuestos puede atender a un asistente de IA (Claude, Codex, Gemini,
Cursor, VS Code…) mediante el protocolo MCP. El asistente consulta y edita los
presupuestos **con la aplicación abierta**; lo que hace se ve en la ventana.

## Encenderla

Está apagada por defecto.

1. Inicia sesión en IngePresupuestos.
2. **Configuración → Conexión con IA (MCP)**, o **IA → Conexión con IA
   (MCP)…** dentro de un proyecto. Marca **Conexión encendida**.
3. Elige tu cliente en **Conectar con**, pulsa **Copiar** y pega donde se indica.
   La línea ya es la de tu instalación:

| Instalación | Comando |
|---|---|
| Flatpak | `flatpak run com.ingepresupuestos.IngePresupuestos --mcp` |
| Snap | `snap run ingepresupuestos --mcp` |
| AppImage | `/ruta/IngePresupuestos.AppImage --mcp` |
| Windows | `…\ingepresupuestos-mcp.exe` (junto al programa) |
| Código fuente | `python3 scripts/ingepresupuestos_mcp.py` |

Ejemplo: `claude mcp add ingepresupuestos -- snap run ingepresupuestos --mcp`

La opción se recuerda: al volver a abrir la app e iniciar sesión, se enciende.
Al cerrar sesión se apaga.

## Herramientas

| Leer | |
|---|---|
| `list_projects`, `project_info`, `list_items` | Proyectos, sus datos, el árbol de partidas |
| `get_acu`, `get_metrados`, `totals` | Análisis, planilla, pie del presupuesto |
| `search_library`, `search_resources` | Biblioteca de partidas, catálogo de insumos |
| `validate` | Partidas sin metrado, sin ACU, con precio cero, etc. |
| `screenshot` | La vista del proyecto (nunca Configuración, usuarios ni acceso) |
| `bim_models`, `bim_diff` | Modelos registrados; qué cambió en el modelo |

| Escribir | |
|---|---|
| `create_project`, `add_items` | Proyecto nuevo; títulos y partidas (desde biblioteca, con su ACU) |
| `set_metrado` | Planilla o cantidad. Si ya hay planilla exige `replace: true` |
| `set_acu`, `set_price`, `set_schedule` | Análisis, precio del insumo **en ese proyecto**, cronograma |
| `bim_apply`, `link_elements`, `show_in_model` | Registrar o actualizar el modelo, vincular, señalar en IngeTrazo |
| `export_report` | PDF, o Excel de los reportes que lo tienen, en una ruta absoluta; no sobrescribe sin `overwrite: true` |
| `undo_last` | Deshace el último cambio hecho por el asistente |

Las partidas con elementos BIM vinculados se miden por el modelo: `set_metrado`
se niega en ellas. El catálogo y la biblioteca son de solo lectura.

Los cronogramas que exporta `export_report` son los del reporte general, no el
Gantt con las opciones de la pestaña Cronograma.

## Deshacer

Cada cambio es una sola transacción: si algo falla, no queda nada a medias.
Antes de cambiar, la app guarda el estado del proyecto (hasta 20 cambios, en la
carpeta de datos, `deshacer_ia/`). **Deshacer lo último de la IA** (menú IA
o la ventana de conexión) lo devuelve con los mismos identificadores.

Si editaste el proyecto después, avisa: deshacer también perdería lo tuyo. Solo
continúa si lo confirmas tú en la app; el asistente no puede forzarlo.

Mientras escribes en una celda, tienes un diálogo abierto o especificaciones
sin guardar, los cambios del asistente se rechazan con «ocupado». Las lecturas
sí se atienden.

## Seguridad

- Escucha solo en `127.0.0.1`, en un puerto libre distinto cada vez.
- Cada vez que se enciende crea un token al azar y lo deja en un archivo que solo
  tu usuario puede leer (`0600`). Sin el token no se atiende nada. Lo que no sea
  el protocolo (por ejemplo HTTP desde una página web) corta la conexión.
- No ejecuta código ni SQL. No lee la tabla de usuarios ni la configuración, donde
  están las claves de IA.
- Respeta la sesión: proyectos ajenos no se ven, los invitados solo leen, y un
  proyecto en un estado bloqueado no se edita.
- **Privacidad:** lo que el asistente lee viaja al proveedor de IA que uses.

El token protege de otros usuarios y de páginas web, no de un programa malicioso
que ya corra con tu propia cuenta: ese puede leer tus archivos igualmente.

## Con IngeTrazo, sin IA

**Archivo → Traer de IngeTrazo abierto…** lee los metrados del modelo abierto en
IngeTrazo (con su puente de IA encendido) y abre la ventana BIM. No interviene
ninguna IA. Necesita un IngeTrazo con la herramienta `get_takeoff`.

## Si no conecta

- «No hay ningún IngePresupuestos…»: abre la app, inicia sesión y enciende la
  conexión.
- Flatpak de Flathub: ese paquete no comparte carpetas personales, así que el
  registro no es visible entre procesos. Se arregla con
  `flatpak override --user --filesystem=~/.local/state/ingepresupuestos:create --filesystem=~/.local/state/ingetrazo:ro com.ingepresupuestos.IngePresupuestos`
  (sin verificar). El Flatpak de la web no lo necesita.
- Microsoft Store: la carpeta del paquete puede no ser ejecutable desde otros
  programas. Usa el instalador normal si el cliente no arranca el comando.

## Cómo está hecho

Cliente ⇄ stdio (JSON-RPC) ⇄ `core/mcp_stdio.py` (solo biblioteca estándar; sin
Qt ni SQLite) ⇄ TCP local, una línea JSON por petición ⇄ `views/mcp_puente.py`
(hilo principal de Qt) ⇄ `core/mcp_operaciones.py`.

`core/mcp_esquemas.py` es la fuente única de los esquemas; `core/mcp_registro.py`
publica y descubre instancias; `core/mcp_deshacer.py` guarda y restaura;
`core/ingetrazo_puente.py` habla con IngeTrazo. Pruebas:
`tests/test_mcp_sesion.py` (app y servidor reales), `tests/test_mcp_operaciones.py`
y `tests/test_ingetrazo_puente.py`.
