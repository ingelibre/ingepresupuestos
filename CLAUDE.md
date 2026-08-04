# IngePresupuestos

App de escritorio PySide6 (Qt 6) multiplataforma para la elaboración de **presupuestos de obra** (ingeniería y arquitectura): análisis de costos unitarios (ACU), cronograma Gantt valorizado con ruta crítica (CPM), metrados (incluido acero), fórmula polinómica e índices INEI, Control de Obra y 13 reportes profesionales.

**Autor:** Ing. Marco Sumari · **Software libre — GPL-3.0-or-later** · Versión actual: **2.8.6**

> Software libre y gratuito desde 2.8.0: todas las funciones incluidas. El sistema de licencia es **vestigial** (`core/licencia.py::puede_premium()` → `True`; queda como limpieza opcional). El changelog detallado vive en `git log`.

Repo: `github.com/ingelibre/ingepresupuestos` · Web: `ingepresupuestos.com` · Docs: `docs.ingepresupuestos.com`

---

## Entorno

```bash
# Python 3.12+ · PySide6 6.x
cd /home/sumaritux/Proyectos/ingepresupuestos/app
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 main.py          # o ./iniciar.sh   (Wayland: INGEPPTO_FORCE_XCB=1 fuerza xcb)
```

Tests sin GUI (usan copia temporal de `presupuestos_seed.db`, nunca la BD activa):
```bash
QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_reglas_negocio.py   # reglas de negocio
venv/bin/python3 tests/test_core.py
# también: test_almacen.py · test_curva_s.py · test_valorizacion.py
```

---

## Arquitectura

| Capa | Tecnología | Carpeta |
|------|-----------|---------|
| UI | PySide6 6.x (Qt 6) + QtPdf/QtPdfWidgets | `views/`, `widgets/` |
| Backend | Python 3 puro | `core/`, `utils/` |
| BD | SQLite 3 (`presupuestos.db`) | — |
| Reportes PDF | QTextDocument + QPdfWriter + QPainter | `core/pdf_reports.py` |
| Reportes Word | python-docx | `core/word_reports.py` |
| Reportes ODT/ODS | LibreOffice headless (conversión) | `core/odt_reports.py`, `core/ods_reports.py`, `core/soffice.py` |
| Excel | openpyxl | `core/exporter.py` |
| Importación | openpyxl + xlrd + pdfplumber + mdbtools/pyodbc | `core/importer.py` y siblings |
| IA (opcional) | Anthropic/Groq/OpenRouter/Gemini/OpenAI/Ollama | `core/ai_specs.py` |
| Fuzzy / RAG | rapidfuzz + model2vec int8 (sin PyTorch) | `core/asistente_local.py`, `core/biblioteca_embeddings.py` |
| Empaquetado | PyInstaller 6 + GitHub Actions | `ingepresupuestos.spec`, `.github/workflows/` |

Rutas (`core/config.py`): `BASE_DIR` (read-only; bajo PyInstaller = `_internal/`), `USER_DATA_DIR` (Linux `~/.local/share/ingepresupuestos/`, Windows `%APPDATA%/ingepresupuestos/`, macOS `~/Library/Application Support/…`), `DB_PATH = USER_DATA_DIR/presupuestos.db`. `_sembrar_db_si_falta` copia el seed solo si la BD no existe.

`main.py` NO procesa `sys.argv` para abrir un archivo pasado (la asociación de `.db` es solo cosmética — ver abajo).

---

## Reglas críticas de negocio (NO romper)

```python
# Precios por proyecto — siempre COALESCE
COALESCE(ai.precio, r.precio, 0)

# Cantidad MO en ACU — y equipo por hora (unidad hh/hm): se DERIVA de la cuadrilla.
#   Helper proyecto_view._recurso_por_hora(tipo, unidad) (también en recurso_selector_dialog).
cantidad = (cuadrilla / rendimiento) * jornada_laboral
# MO/EQ por DÍA (unidad día/jor): cuadrilla habilitada pero SIN jornada →
#   cantidad = cuadrilla / rendimiento   (rendimiento ya es por día). Helper _recurso_por_dia.
# EXCEPCIÓN — partida GLOBAL (unidad glb/gbl/est/serv, como PowerCost): sin cuadrilla;
#   cantidad y precio directos en TODOS los insumos (incluida MO). Helper _partida_global(unidad);
#   flag _acu_partida_global seteado en cargar_acu.

# Decimales — 3 claves GLOBALES en tabla `configuracion` (estilo S10 «Datos Adicionales»):
#   decimales_presupuesto (montos PU/parciales, def 2) · decimales_metrado (def 2)
#   · decimales_cantidad_acu (def 4). Getters en core/database.py.
# parcial_wysiwyg redondea el metrado a decimales_metrado y el monto a decimales_presupuesto.

# Pie de presupuesto
Total = cantidad * (%part/100) * precio

# Overhead (%MO / %MAT) — parcial REAL en get_acu_items (segunda pasada).
#   DEBE aparecer en Insumos y Adquisiciones. NO filtrar con SUBSTR != '%'.

# sqlite3.Row NO tiene .get()  →  row['col'] or default

# Cronograma — UNIQUE(partida_id) → INSERT OR REPLACE; dur puede ser None: (dur or 0) > 0
# Duración tarea Gantt = ⌈metrado / rendimiento⌉  (rendimiento = producción/día del ACU)
```

**Sub-presupuestos en la UI y los reportes (2026-08-04).** Helpers en `core/pdf_reports.py`: **`subpresupuestos_de(pid)`** → `[{'id': None|int, 'nombre'}]` en orden de pestaña (el Principal es `id=None`, sus partidas tienen `sub_presupuesto_id IS NULL`) y **`agrupar_items_por_sub(pid, items)`** → `[(nombre, [items…])]`. **Ambos devuelven lista VACÍA cuando el proyecto tiene un solo sub**, así los reportes hacen `if grupos:` y salen planos como siempre (verificado contra proyectos del seed sin subs). Con varios: el **Presupuesto** intercala una banda oscura (`_od`) con nombre + CD antes de la 1ª partida de cada bloque; el **Resumen Ejecutivo** agrupa la «Estructura del Presupuesto» con una fila de cabecera por sub; la **Hoja de Metrados** emite el nombre del sub de forma **perezosa** (muchas partidas se saltan por no tener planilla → la cabecera debe salir junto a la primera que realmente se imprime, no marcando la primera del grupo); **Insumos** tiene un tipo nuevo **`insumos_sub`** («Insumos por Sub-presupuesto») que reusa `_html_insumos_bloque(pid, proy, insumos)` con `get_insumos_para_partidas` por sub — la tarjeta se **oculta** en `reportes_view` si el proyecto no tiene subs. En `proyecto_view`: rótulo `_lbl_sub_activo` encima del árbol (solo con >1 sub; las pestañas viven ABAJO y van elididas), `text-align:left` en las pestañas (QPushButton centra por defecto) y tooltip con posición + nombre completo.
  - **Estilo (decisión del autor, 2026-08-04): el nombre del sub va SUBRAYADO, sin fondo sólido ni línea divisoria** — mismo criterio que los títulos N1 (`text-decoration:underline`). Se probó con banda oscura de fondo en el Presupuesto y con `border-bottom` en Resumen/Insumos/Metrados y se descartó («se ve horrible»). Vale para PDF, Word/ODT y Excel/ODS.
  - **Otros formatos:** Word/ODT solo cubren `resumen` (`word_reports.tipos_soportados()`), donde la Estructura del Presupuesto mezcla en `filas` dicts `{'sub','cd'}` con entradas normales; `_set_cell_text` ganó `underline=` y `space_before=`. Excel/ODS cubren `presupuesto` (fila-cabecera merge A:F + CD en G), `metrados` (cabecera perezosa igual que el PDF) e `insumos_sub` (**una HOJA por sub**: `exportar_insumos(pid, por_sub=True)` itera `_bloques` y crea hojas con `wb.create_sheet()`; el título de hoja se sanea a 31 chars sin `[]:*?/\`). ODS sale de convertir el XLSX, así que basta registrar el tipo en `ods_reports._GENERADORES` y en `_EXCEL_TIPOS` de `reportes_view`.

**Coherencia de totales:** `calcular_totales(pid)` → `(items, {cd, gf, utilidad, subtotal, igv, total})`. **Presupuesto Total = `total`** (CD+GG+Utilidad+IGV), NO solo CD. Param `all_subs=True` para totales project-wide (Resumen/Pie).

**Funciones clave `core/database.py`:** `_r2`, `get_db()` (Row + FK ON), `calcular_totales`, `_recalcular_pu` / `_pu_desde_items`, `get_acu_items` (retorna `(items, totales_tipo)`), `get_insumos_proyecto` / `get_insumos_para_partidas` (distribución proporcional al CD), `parcial_wysiwyg`, `precios_inconsistentes` / `unificar_precio_recurso`, `partidas_pu_inconsistente` (detector PU≠ACU), `_orden_mo` (Capataz<Operario<Oficial<Peón).

---

## Sistema de diseño — `utils/theme.py`

Tokens centralizados. **NO hardcodear hex.**
- Paleta: `C.brand = '#F37329'` (naranja). Tipos recurso: MO `#F39C12` · MAT `#27AE60` · EQ `#607D8B` · SC `#7A36B1`.
- Niveles de título (`NIVEL_ESTILO`): N1 rojo `#B71C1C`, N2 arándano `#0D52BF`, N3 morado `#6A1B9A`, N4 rosa `#AD1457`.
- `accent_color(*, on_dark=False)` = acento ambiental (topbars); NO en CTAs/focus (esos siempre naranjas). `accent_reportes()` → `('#273445','#1F2A38','#F1F5F9')`.
- **Modo sobrio es el único modo** — no reintroducir toggles de tema.
- Fuente **Inter** estática (NO Variable) bundleada en `resources/fonts/`, auto-instalada system-wide (`core/fonts_installer.py`).

---

## Reportes (PDF · Excel · ODS · Word · ODT)

- **PDF:** HTML → `QTextDocument.setHtml()` → `drawContents()` → `QPdfWriter`; header/pie/portada en `QPainter`.
- **Word:** python-docx; header/footer tabla 1×3 con NUMPAGES; `_set_table_fixed_layout` obligatorio.
- **Excel:** openpyxl; pie tripartito `oddFooter`; **Excel = PDF visible, no PDF CSS**.
- **ODT/ODS:** se genera el `.docx`/`.xlsx` nativo y se convierte con **LibreOffice headless** (`core/soffice.py`). Sin LibreOffice → aviso, sin crash.

### Datos de empresa y logo — UNA sola fuente: las claves `rep_*`
`FORMATO_CLAVES` en `core/pdf_reports.py` (nombre, subtítulo, **RUC/dirección/teléfono**, color, logo, escala, pies). Las editan **dos puertas al mismo dato**: «Editar formato» (Centro de Reportes / Gantt) y Configuración → «Datos de empresa». Antes esa tarjeta guardaba su propio juego `empresa_*` y solo copiaba nombre y logo —y solo si no estaban vacíos—, así que había dos verdades y quitar el logo allí no lo quitaba del PDF. Los valores viejos se migran y **se borran** una vez en `init_db` (flag `empresa_unificada`); NO reintroducir un fallback de lectura a `empresa_*` — resucitaría el logo al borrarlo. Fuera de reportes usar `pdf_reports.empresa_info()`.
- **Logo y razón social conviven** (antes eran excluyentes: poner logo borraba el nombre). Con logo, la columna izquierda se ensancha (175→245 px en reportes, mm(50)→mm(72) en el Gantt) y el cuerpo baja un punto, o el nombre se corta a media palabra.
- **RUC/dirección/teléfono** salen al pie de la **portada** del PDF. No caben en el encabezado.
- **Logo en Word/Excel** (antes solo PDF y Gantt): Word lo pone encima del nombre en la celda izquierda del header 1×3; Excel lo ancla en `A1` y **mueve la razón social a la fila 2** — el bloque izquierdo son ~28 unidades y una celda COMBINADA recorta en su borde (no desborda), así que logo y nombre no caben en la misma línea. El cuerpo del nombre se calcula por longitud (~8.1 caracteres·punto por unidad de columna): a 12 pt fijos ya se cortaba desde ~19 caracteres, con o sin logo.

### QTextDocument — gotchas
- `<table width="100%">` como **atributo HTML** (CSS solo no basta). NO soporta SVG (generar PNG con QPainter). NO centra `<table align=center>` (dibujar con QPainter).
- Selectores Qt CSS no aceptan `_` → usar `#objectName`. `QPainter.setRenderHint`: atributo de la CLASE.
- **Sangría en celda: NO `padding-left`/`margin-left`** (los ignora) → tabla-espaciador anidada, o `Alignment(indent=N)` en Excel. Profundidad = `item.count('.') - min_dots`.
- **Divisorias verticales: NO `border-left/right`** (entrecortadas) → columna-espaciador con `background`, ancho como atributo `width`. Verificar renderizando el PDF headless.

### Centro de Reportes — `views/reportes_view.py`
Anclada al `_root_stack`. Reporte Completo = merge `pypdf` + numeración global 2-pass; secciones configurables (casillas + tarjetas reordenables por arrastre; persistencia por proyecto en QSettings). Papel default A4; **Gantt** usa pipeline propio (auto A4→A0).
- **LibreOffice en Flathub:** los botones ODT/ODS/Pack-LibreOffice se ocultan cuando `core.soffice.odf_export_ofrecible()` es False (edición Flatpak sin LibreOffice del host). En instalación nativa sin LibreOffice quedan visibles con aviso de instalación.

---

## Vista de proyecto — `views/proyecto_view.py`

Topbar (← Inicio · pestañas · Total) + toolbar + `QSplitter` H/V. Panel derecho con pestañas **ACU · Insumos · Metrados · Especificaciones · Resumen · Memoria**.
- Layout responsivo: `< 1050` oculta ACU. NUNCA dos `resizeEvent` en la misma clase.
- Panel ACU: cabeceras MO/MAT/EQ/SC con `_acu_row_ids[row]==-1` → saltar en edit/menu/delegate.
- Vistas ancladas al `_root_stack` (NO diálogos): Pie, Cronograma, Reportes, Metrados, Fórmula, Memoria Descriptiva.
- **Panel Metrados/Acero:** solo se recarga cuando su pestaña está visible. Recuerda su partida dueña en `_met_panel_pid`; los 4 caminos de guardado (acero/metrados, silencioso/explícito) escriben SIEMPRE a `_met_panel_pid`, nunca a la partida seleccionada en el árbol (si difieren, evitaba copiar la planilla a otra partida).

---

## Cronograma + Fórmula + INEI

- **CPM** forward+backward+ruta crítica; dependencias FS/FF/SS/SF con lag y pct; hitos.
- **Numeración "#" y filas virtuales (estilo MS Project)** — el "#" numera TODAS las filas posicionalmente (`core/cronograma.py`); DEBE coincidir con las predecesoras. `_partidas` se carga AGRUPADO por subpresupuesto; cambiar orden/inserción rompe la numeración (prever migración).
- **Predecesoras:** la celda (col 7) sigue siendo texto libre («3, 7CC+2»), pero además hay selector por descripción — clic derecho sobre la tarea → «Predecesoras…» (`views/predecesoras_dialog.py`). Reusa `_build_pred_token`/`_evita_ciclo`/`_parse_preds` del arrastre entre barras, así ambas vías generan el MISMO texto. Los tokens que el diálogo no representa (lag en %, `TN%`, referencia por ítem) se conservan crudos como «avanzado» — NO destruirlos al editar. `parse_predecesoras` descarta en silencio los `#` inexistentes ⇒ `_avisar_preds_invalidas` avisa al escribir a mano (solo avisa, no revierte).
- **Fórmula Polinómica:** `calcular_desde_acu(pid)` auto-deriva J/M/E. NO aplica en admin. directa. Validaciones D.S. 011-79-VC.
- **INEI:** 72 códigos × 6 áreas, auto-detección por HEAD requests.
- **Export MS Project (MSPDI XML):** formato abierto (abre en ProjectLibre/GanttProject). Reglas críticas: `Manual=0` (sin esto → duración 0), NO emitir `Finish`/`ManualFinish`; tareas sin predecesora → SNET; `id` incrustado en Text29 «IngeID».

---

## Control de Obra — `views/control_obra_view.py` + `core/{valorizacion,parte_diario,almacen,curva_s,requerimientos}.py`

Vista anclada al `_root_stack`, botón «Control de Obra» en el topbar tras Cronogramas. Pestañas del flujo de obra: **Requerimientos · Almacén · Cuaderno · Valorizaciones · Curva S real** (Liquidación oculta para versión futura). Reportes generados DESDE la vista (no en el Centro de Reportes). Tests: `test_{valorizacion,almacen,curva_s}.py`.
- **Valorizaciones:** solo LEEN del presupuesto/ACU. Dato base = `metrado_periodo`; todo lo demás deriva en `valorizacion.get_valorizacion_detalle`. 2 tablas (`valorizaciones` + `valorizacion_detalle`, origen `manual`|`diario`). Cerrada = no editable.
- **Almacén:** kárdex de MATERIALES (Pedido/Ingresado/Consumido/Stock/Por llegar) + entradas con fecha + kárdex por día.
- **Curva S:** programado vs reprogramado vs real; denominador = presupuesto contractual; cortes semana/mes/mes_cal.
- **Cuaderno/parte diario:** metrado ejecutado por día; push parte→valorización (`metrado_periodo = Σ metrado_dia` en el rango); celda de valorización solo-lectura cuando `origen='diario'`.

---

## Importadores nativos peruanos — `views/importar_view.py` + `core/*_importer.py`

| Software | Formato | Soporte |
|----------|---------|---------|
| Delphin Express | `.sqlite` | ✅ proyecto + biblioteca + INEI |
| PowerCost | `.prs` | ✅ mdbtools (Linux) / pyodbc+access_parser (Windows) |
| S10 | `.S2K` / `.bak` / `.bkf` | ✅ vía IngeConverter (complemento externo gratuito) |
| PowerCost/S10/Delphin | `.xlsx` | ✅ |
| BIM | `.ifc` | ✅ |
| IngePresupuestos | `.db` | ✅ ATTACH DATABASE |

**Patrones críticos:**
- **`.prs` con VARIOS sub-presupuestos (decisión del autor, 2026-08-04):** la unidad de importación es el **PROYECTO**; sus sub-presupuestos entran **todos DENTRO del mismo proyecto** (pestañas), replicando la estructura de PowerCost. NO importarlos como proyectos separados — se implementó así y el autor lo corrigió. Antes se tomaba solo el primer `IdSubPpto>0` **en silencio**: una base con 1 proyecto y 7 subs traía 1 de 7. Mecánica: `import_powercost_prs` sin `id_subppto` recorre todos los subs (ordenados por `Orden`); el primero es el Principal (`info['sub_presupuesto']`, partidas con `sub_ref=None`) y los demás marcan cada partida con `sub_ref=<NomSubPpto>` (desambiguado con « (2)» si se repite). Como cada sub numera sus ítems desde 01, `acus_data`/`metrados_data` se indexan por **`item_origen` = `"<IdSubPpto>|<item>"`** (también en cada partida). `guardar_importacion` crea las filas de `sub_presupuestos` a partir de `sub_ref` por orden de aparición, cuelga `partidas.sub_presupuesto_id` y registra en `partida_map` ambas claves (`item` e `item_origen` — solo la segunda es única entre subs). `IdSubPpto=0` es la fila TOTAL del proyecto, se omite. El diálogo de selección sigue listando **proyectos** (`listar_proyectos_powercost`) — sirve para `.prs` con muchos proyectos. Test: `test_importador_prs_subpresupuestos_dentro_del_proyecto` (usa `~/Descargas/p/base de datos mantenimiento.prs`: 1 proyecto, 7 subs, CD por sub cuadra con `SubPptos.CD`).
  - **La numeración de títulos raíz es CONTINUA entre subs** (`raiz_sig` en el bucle): sub 1 → `01..03`, sub 2 → `04..07`, sub 3 → `08..10`… igual que PowerCost y sus reportes. Los niveles anidados sí reinician por padre. **No es cosmético, es un requisito duro:** `calcular_totales` (`database.py:885`) indexa los parciales en un **dict por `item`**, así que con los ítems repetidos entre subs solo sobrevivía el último → el CD del proyecto salía truncado (33 363,94 en vez de 103 344,17) y `subtotal_de(prefijo)` mezclaba títulos de subs distintos (el Resumen Ejecutivo repetía «01 PINTURA / 01 MOVIMIENTO DE TIERRAS…» todos con el mismo monto). Con un solo sub la numeración arranca en `01` igual que siempre.
- `.prs` con contraseña: fallback a `access_parser` + monkey-patch. Sub-análisis (`IdSubAnalisis≠0`) → SC con precio = CU recursivo. Numeración de ítems JERÁRQUICA por posición de hermano (NO usar `TxItem`/`IdItem`). Validado con bases reales; test `test_importador_prs_reconcilia`.
- **`.prs` bajo Flatpak:** `core/powercost_prs_importer.py` prefiere el `mdb-export` LOCAL (`shutil.which`) — embebido en `/app/bin` en la edición Flathub, o del sistema en nativo — y solo usa `flatpak-spawn --host` si no hay binario local (edición sideload). En Flathub `flatpak-spawn --host` está bloqueado, así que enrutar al host rompería la importación.
- Reúso de insumos por `(tipo, desc, unidad)` aunque cambie el código (el precio NO se comparte). Al importar, el pie se siembra TODO desactivado.

---

## Distribución + Backups + Update

**Empaquetado** (`ingepresupuestos.spec` + `.github/workflows/`): tag `vX.Y.Z` → workflows Linux+Windows → binarios (Win installer+portable, Linux AppImage+tar.gz) publicados en GitHub Releases y subidos a Cloudflare R2 (`downloads.ingepresupuestos.com/vX.Y.Z/`) + `version.json` regenerado (feed del auto-updater). `CURRENT_VERSION` en `core/update_manager.py` lo bumpea `release.sh`.

> **El mensaje del tag ES el changelog que ve el usuario** al actualizar: `build-linux.yml` lo copia a `version.json`. Pasarlo siempre — `./release.sh X.Y.Z "Lo nuevo…"` o `-F notas.md`. Ojo: `actions/checkout` clona en superficial y NO trae el objeto del tag anotado, así que hay que hacer `git fetch` del tag antes de leerlo; sin eso `%(contents)` cae al mensaje del commit y el aviso de actualización mostraba «chore: bump version to X.Y.Z» (v2.8.6). Al agregar un paquete pip: `requirements.txt` + `hiddenimports` en el `.spec`.

**Canales:**
- **GitHub Releases + R2** — automático en cada tag.
- **winget** (`installer/winget/`, `MarcoSumari.IngePresupuestos`, `InstallerType: inno`) — publicado. `publish-winget.yml` (winget-releaser) abre el PR a `microsoft/winget-pkgs`; requiere el secret `WINGET_TOKEN`. **NO se dispara con `on: release`**: el Release lo crea `action-gh-release` con el `GITHUB_TOKEN` por defecto y GitHub no lanza workflows desde eventos generados con ese token (acumuló 0 ejecuciones hasta la v2.8.6). Por eso lo invoca `build-windows.yml` vía `workflow_call` dentro de la misma corrida, y además admite `workflow_dispatch` con el tag. Los `installer/winget/*.yaml` del repo son solo referencia — el manifiesto real lo genera winget-releaser desde el `.exe` del Release.
- **Microsoft Store (MSIX)** (`installer/msix/package-msix.ps1`) — el `.msix` se genera en el build Windows y queda como **artifact privado** (`ingepresupuestos-msix`, retención 90 días); NO se publica en R2 ni en Releases. Se sube A MANO a Partner Center (sin firmar; Microsoft firma). Empaquetado vía mapping file (`/f`) excluyendo `docx/templates/...` (nombres OPC reservados que rompían `makeappx` con `0x8007007b`).
- **Flathub** (`installer/flathub/`) — edición separada: base-app `io.qt.PySide.BaseApp` sobre `org.kde.Platform`, deps Python offline, mdbtools embebido, SIN escape al host → ODT/ODS deshabilitados (PDF/Word/Excel son nativos). `x-checker-data` en la fuente → el bot de Flathub propone las nuevas versiones. El manifiesto y sus archivos deben ir a la raíz de la rama del PR (contra `new-pr`).
- **Edición Flatpak sideload** (`installer/flatpak/`) — COMPLETA (usa el host para ODT/ODS vía `flatpak-spawn`). NO mezclar con la de Flathub.

**Asociación de archivos `.db`** — icono de documento branded (hoja + badge naranja, estilo Office). **Cosmético**: da personalidad al icono, no abre nada. Windows: ProgID en `installer/ingepresupuestos.iss` (`ChangesAssociations=yes`). Linux: MIME propio `application/x-ingepresupuestos-db` (`resources/mime/`) que reclama `*.db`; iconos hicolor en `resources/icons/hicolor/` (bundleados por globs en el `.spec` — una tupla de directorio NO los empaqueta) + registro en `install-linux.sh`. Fuente vectorial: `resources/icons/mimetypes/ingepresupuestos-db.svg` (render con Inkscape + Pillow; sin filtros SVG porque Inkscape headless descarta los grupos con `feDropShadow`).

**Firma de código Windows:** el `.exe` NO está firmado → SmartScreen muestra «editor desconocido» (winget y Store vienen firmados por Microsoft, sin aviso). Fix real = firmar (pendiente cert gratis de SignPath Foundation para OSS). Reportar el `.exe` a SmartScreen es por-archivo, no una cura.

**Backups:** atomic `sqlite3.Connection.backup()`. Retención daily(7) · on-exit(10) · manual(10).

**Ícono producto** (`ingepresupuestos.png/.ico`) ≠ **Tuxia** (asistente IA). NO mezclar.

---

## Gotchas críticos (no repetir)

**Delegates / tablas:** `self.parent()` en delegates = padre del constructor (pasar `self` explícito). `setModelData` que recarga tabla → `QTimer.singleShot(0, …)`. Filas-cabecera ACU (`_acu_row_ids[row]==-1`): saltar.

**Stylesheet:** `QWidget { background: X }` afecta a TODOS los descendientes → `setObjectName` + `#foo` + `Qt.WA_StyledBackground`. `QLabel` con `setStyleSheet` parcial → siempre `background:transparent; border:none;`. Botones circulares: subclasear + `paintEvent` (el QSS cascade pisa `border-radius` tras hide/show). `::indicator` con QSS propio: usar `border`+`background` sólidos (no SVG semitransparente, invisible en Linux/Win).

**Papel grande (A3/A1/A0):** el header del Gantt está cotado en **mm físicos**, así que la hoja crece y el logo/textos NO → en A1 se veían ~2.8× más chicos (bug reportado). `pdf_reports.escala_papel(PG_W, dpi)` da el factor (A4 apaisado = 1, ley de potencia 0.7 para no llegar a 4× en A0); se aplica al `mm` local del header Y a los `setPointSizeF`. Al pintar un logo usar **`pdf_reports._rect_logo(img, box_w, box_h)`**: recortar el ancho sin recalcular el alto deformaba los wordmarks (4:1 salían a 3.2:1). Tamaño manual del logo: `rep_logo_escala` (%, 50–200) en Formato de reporte.

**Layouts:** `layout.takeAt(0)` solo desconecta → `item.widget().setParent(None); deleteLater()`.

**Wayland:** `self.move()` no funciona → `startSystemMove()` diferido a mouseMoveEvent. Fractional scaling Qt 6.11: `INGEPPTO_FORCE_XCB=1`.

**QDialog + QThread:** override `done()`, NO `closeEvent`. Workers QThread: `parent=self`.

**Metrados:** `tree.blockSignals(True)` durante el guardado silencioso. Metrado manual inline vs planilla: limpiar `tbl_met`/`tbl_acero` si muestran esa partida (el guard `_met_tiene_datos()`/`_acero_tiene_datos()` corta el re-guardado que borraría el valor manual). Acero: `orden` secuencial al guardar (saltar filas en blanco); diámetro asume pulgadas sin comilla (`_normalizar_diametro_acero`).

**Color «post-it» de proyecto** (`proyectos.color` hex; vacío ⇒ card BLANCA — ver `utils.theme.color_postit`). **NO heredar el color del portafolio**: se implementó así y se revirtió — teñir en masa por portafolio se confundía con la etiqueta de portafolio, que ya se comunica con su chip. La card ya usaba color para 5 cosas distintas (estado en la franja de 4 px + badge · fondo = reciente/seleccionado · chip portafolio · estrella favorito · borde hover), así que el post-it **reemplaza** un canal, no agrega uno: se quedó con el **fondo**, y «Reciente» cedió el fondo amarillo y conserva solo su chip etiquetado (afecta a UNA card — es el último proyecto ABIERTO, de QSettings, no una fecha). Pintar SIEMPRE con `theme.tinte(hex, POSTIT_ALPHA_BG)`, nunca a saturación: el texto es SLATE_700. En **modo lista** el color va en una barra de 6 px (col 0), NO tiñendo la fila — pelea con la zebra; `hh.setMinimumSectionSize(4)` ANTES del `setColumnWidth`, si no Qt clampa a ~30 px. **El color DEBE entrar en la huella `fp` de `_renderizar`** o cambiarlo no repinta nada. `trg_proy_upd` bumpea `modificado_en` en cualquier UPDATE ⇒ cambiar el color invalida el caché de totales de esa card y la sube en «Más recientes».

**Dashboard 400+ proyectos:** cards/celdas **pintadas a mano** con QPainter (1 widget c/u, no ~15 sub-widgets/card) + hit-testing; caché de totales `_tot_cache` (NUNCA `calcular_totales` por card) con cálculo diferido en lotes; sin scrollbar horizontal.

---

## Convenciones rápidas

- **Diálogos modales:** `setWindowModality(Qt.WindowModal)` (NO `setModal(True)`); mejor anclar al `_root_stack`.
- **Iconografía:** SVGs elementary OS vía `utils/icons.py::icon("alias")`. NO emojis para UI.
- **Árboles: padre por prefijo de ítem SIEMPRE con dict ítem→nodo** (O(1); iterar es O(n²)).
- **ProyectoView abre en 2 etapas:** pestaña visible con árbol → `_completar_panel_tabs` (30 ms después). NO acceder a widgets del panel tabs antes de esa cadena.
- **`QT_SCALE_FACTOR`** leído ANTES de `QApplication()`. Stylesheet global + Inter registrados en `main.py` antes de las ventanas.
- **Migraciones:** `ALTER TABLE ADD COLUMN` en try/except dentro de `init_db()`.

---

## Monedas · Auth · Estados · IA · i18n

- **Monedas/formato** (`config.py`, `utils/formatting.py`): `fmt`/`fmt_num`/`parse_num` (`.` y `,`)/`pad_codigo`/`norm_busqueda`.
- **Auth** (`utils/auth.py`): roles admin·usuario·invitado; primer usuario = admin.
- **Estados:** solo `elaboracion` es editable; `_require_editable(nivel)`.
- **IA (opcional, `core/ai_specs.py`):** 6 proveedores (clave del usuario). Specs/rendimiento por partida; validar_proyecto, memoria descriptiva. Override `done()` en diálogos IA.
- **«Sugerir partidas» (RAG):** la IA arma la estructura, la biblioteca/proyectos ponen los costos. Fase 1 fuzzy + Fase 2 semántica (`core/biblioteca_embeddings.py`, model2vec int8, sin PyTorch), fusión RRF; el modelo se baja de R2 al build (si falta, degrada a fuzzy). Corre en QThread.
- **i18n** (`utils/i18n.py`): `tr("texto español")`, importar dentro del método. Cobertura parcial.
- **Contacto** (`views/acerca_view.py` → `worker/contacto.js`): POST → Cloudflare Worker → Resend. User-Agent `IngePresupuestos/X.Y.Z` obligatorio. El payload lleva `Email` (remitente) y el Worker lo pone en `reply_to` — validado ANTES de usarlo como cabecera (llega de fuera, y un valor basura hace que Resend responda 422 y se pierda el mensaje). Es opcional: sin él se avisa una vez y se envía anónimo. **El Worker se despliega A MANO** (pegar en el editor de Cloudflare + Deploy): si no se redespliega, `Email` se ignora en silencio.

---

## Trabajo futuro — «Partida como sub-análisis» (NO implementado)

**Estado actual:** NO existe el concepto. `SC` es solo un tipo de recurso más (`recursos.tipo='SC'`, etiqueta «Sub-contratos / Servicios») con **precio fijo tecleado a mano**. El importador `.prs` resuelve los sub-análisis de PowerCost recursivamente **en tiempo de importación** (`powercost_prs_importer.py:512-616`, `_cu_analisis` con anti-ciclos `_stack`) y **aplana** el resultado a un precio literal — el vínculo se pierde. Pedido recurrente de usuarios que vienen de S10/PowerCost/Delphin, donde una partida aparece dentro del ACU de otra con su propio desglose y CU recalculable.

### Modelo de datos elegido (opción A, estilo S10)
`partidas.es_subanalisis INTEGER DEFAULT 0` + `acu_items.sub_partida_id INTEGER NULL REFERENCES partidas(id)` (migración estilo `database.py:526`; relajar `recurso_id` a nullable). Default `0` ⇒ proyectos existentes intactos y **sin migración de numeración del cronograma**.
Descartadas: (B) reusar `biblioteca_cu` — es global, rompe precios por proyecto (`ai.precio`); (C) referenciar cualquier partida sin flag — doble conteo garantizado.

### Decisiones de negocio PENDIENTES (preguntar al autor antes de codificar)
1. ¿La base de `%MO`/`%MAT` del padre incluye la MO que vive dentro de la sub-partida? (criterio S10 = **no**, entra como bloque).
2. ¿Un solo nivel de anidamiento o multinivel? (un nivel simplifica UI+reportes; multinivel es donde aparecen los ciclos reales).

### Los 4 problemas difíciles
- **Ciclos** A→B→A: stack de visitados en el recálculo. Precedente: `powercost_prs_importer.py:512-542`.
- **Cascada:** `_recalcular_pu` (`database.py:966`) se llama desde ~15 sitios y recalcula UNA partida. Meter la cascada (subir por `sub_partida_id`) **dentro** de `_recalcular_pu` ⇒ los 15 call-sites siguen sin tocarse.
- **Explosión de insumos:** `get_insumos_para_partidas` (`database.py:1077`) es JOIN plano de 1 nivel (`:1117`). Debe dar `cant_hoja × cant_sub_en_padre × metrado_padre`. El invariante `sum(insumos) == CD` (distribución proporcional, `:1120-1122`) **se conserva** si los ratios se encadenan multiplicativamente — testear.
- **Doble conteo:** `calcular_totales` (`:838`) suma TODA partida con `es_titulo=0`. Sin el filtro de exclusión contamina CD, Insumos, Gantt, Curva S y valorizaciones.

### Radio de impacto medido
- **129** `FROM partidas` en `core/` + `views/`, de los cuales **62** son listados `WHERE proyecto_id=?` que necesitan `AND es_subanalisis=0`. Concentrados en `proyecto_view.py` (42), `ai_specs.py` (17), `exporter.py` (11).
- **9** escritores de `acu_items`. `ingepresupuestos_db_importer.py` usa columnas dinámicas (OK); `exporter.py` usa `INSERT INTO acu_items VALUES (?)` **posicional** — revisar.
- **UI:** el `QTableWidget` plano ALCANZA, NO migrar a `QTreeWidget` (rompería los 4 delegates, `_instalar_nav` y el contrato `_acu_row_ids`). Extender el sentinel `-1` con un array paralelo de «kind»; indentación por delegate; expandir/colapsar con `setRowHidden`. Los 4 puntos que comparan `== -1`: `proyecto_view.py:674, :7183, :7203, :7277`. **Ojo:** `_aplicar_cambio_acu` (`:7208-7271`) propaga el precio editado a TODO el proyecto por `recurso_id` → debe saltar filas sub-análisis (precio derivado, solo lectura). `recurso_selector_dialog.py` necesita pestaña nueva para elegir partida.
- **Reportes:** 3 críticos (`pdf_reports.py:613` `_html_acus`, `exporter.py:936` `exportar_acus`, hoja ACUs `exporter.py:2349`) + **2 legacy con SQL crudo** (`exporter.py:2362`, `:2816`) que divergirían en silencio. Indentación ya disponible: `_ind()` (`pdf_reports.py:477`) y `Alignment(indent=N)`. **Riesgo:** el Excel reordena filas por tipo (`exporter.py:1114-1130`) → rompe el anidamiento.
- **Fórmula polinómica:** `formula_polinomica.py:55-88` agrupa por `r.tipo` con SQL plano y SC cae en MAT (`:70`) → sin explosión recursiva la MO interna desaparece de **J** y los coeficientes salen sesgados.
- **Requerimientos:** 4 sitios de SQL plano (`requerimientos.py:225-235, :290, :297, :326-337`) — la sub-partida saldría como «insumo comprable».
- **Cronograma:** `cronograma.py` filtra solo por `es_titulo` → una sub-partida ocuparía fila y **rompería la numeración «#»** de las predecesoras. Excluir en `filas_slots`/`numerar_filas`.
- **Sin impacto directo:** `valorizacion.py`, `almacen.py`, `curva_s.py` (leen `metrado × precio_unitario`, no el ACU) — pero heredan el doble conteo si falla la exclusión.
- **`partidas_pu_inconsistente`** (`database.py:980`): con precio derivado, `COALESCE(ai.precio, r.precio, 0)` deja de ser la fuente de verdad → resolver el CU del hijo antes de comparar, o toda partida padre saldrá inconsistente.

### Plan por fases
1. **Núcleo + tests, sin UI:** migración, explosión recursiva con anti-ciclos, cascada en `_recalcular_pu`, exclusión en `calcular_totales`/`get_insumos_proyecto`. Tests nuevos en `test_reglas_negocio.py`: ciclo detectado, `sum(insumos) == CD` con anidamiento, CD sin doble conteo.
2. **UI panel ACU:** fila expandible + selector de sub-partida + precio derivado solo lectura.
3. **Reportes:** los 3 críticos; migrar los 2 de SQL crudo a `get_acu_items`.
4. **Periféricos:** fórmula polinómica, requerimientos, cronograma.
5. **Bonus:** el importador `.prs` deja de aplanar y preserva el vínculo real.
