# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec para ingePresupuestos.

Genera:
- Linux: dist/ingepresupuestos/  (carpeta con el binario + libs)
- Windows: dist\\ingepresupuestos\\  (carpeta con ingepresupuestos.exe + DLLs)
- macOS: dist/ingepresupuestos.app  (bundle)

Build:
    venv/bin/pyinstaller ingepresupuestos.spec --noconfirm  (Linux/macOS)
    venv\\Scripts\\pyinstaller.exe ingepresupuestos.spec --noconfirm  (Windows)

El mismo .spec funciona en las 3 plataformas — PyInstaller maneja los
formatos por plataforma automáticamente. Solo `console=False` y el icon
son específicos del SO.
"""
import re
import sys
from pathlib import Path

block_cipher = None

# Repo root (donde está el .spec). Usamos Path absoluto para que funcione
# cualquiera sea el CWD desde el que se invoque pyinstaller.
ROOT = Path(SPECPATH).resolve()

# ── Assets que se bundlean dentro del ejecutable ─────────────────────────────
# Cada tupla = (origen_relativo_al_repo, destino_relativo_al_bundle).
datas = [
    # Licencia y avisos de terceros — NO son opcionales: la GPLv3 §4 obliga a
    # entregar copia de la licencia junto al programa, y el aviso del
    # instalador remite explícitamente a este archivo. Al copiarlos aquí
    # llegan solos al instalador Windows, al .msix y al AppImage, porque los
    # tres empaquetan el output de PyInstaller.
    ('LICENSE',                 '.'),
    # Complementos incluidos (se instalan desde el gestor; son .json y .py que
    # se leen como datos, no entran en el PYZ).
    ('complementos',             'complementos'),
    ('THIRD-PARTY-NOTICES.txt',  '.'),
    ('resources/icons/elementary/24/*.svg',  'resources/icons/elementary/24'),
    ('resources/icons/elementary/24/*.png',  'resources/icons/elementary/24'),
    ('resources/icons/elementary/24/*.ico',  'resources/icons/elementary/24'),
    # Íconos raíz referenciados por el QSS global (check.svg, arrow_down.svg,
    # radio_slate_on.svg…): sin esto los indicadores de checkbox/combo/radio
    # salían como cuadraditos negros en el binario empaquetado.
    ('resources/icons/*.svg',                'resources/icons'),
    ('resources/fonts/*.ttf',                'resources/fonts'),
    ('resources/fonts/*.woff2',              'resources/fonts'),
    ('resources/fonts/*.json',               'resources/fonts'),
    ('resources/styles/*.qss',               'resources/styles'),
    ('presupuestos_seed.db',                 '.'),
    ('ingepresupuesto-icon.svg',             '.'),
    # Base UBIGEO del Perú (INEI) para autocompletar la ubicación.
    ('resources/ubigeo_peru.json',           'resources'),
    # Anexos de la RJ 016-2026-INEI: relación de índices unificados de las
    # dos bases, sus áreas geográficas y el Diccionario de Elementos de la
    # Construcción para fórmulas polinómicas.
    ('resources/indices_inei_oficial.json',  'resources'),
    # El histórico de valores del INEI: sin él una instalación nueva
    # arranca sin la base vigente. Lo regenera
    # scripts/generar_indices_valores.py antes de cada release.
    ('resources/indices_inei_valores.json.gz', 'resources'),
    # El decreto que rige la fórmula polinómica, para poder consultarlo
    # sin internet desde la propia vista.
    ('resources/DS-011-79-VC.pdf',           'resources'),
    # QR de Yape de «Apoya al proyecto» (Acerca de).
    ('resources/qr_yape.png',                'resources'),
    # Traducciones de la interfaz (utils/i18n.py): un JSON por idioma con el
    # texto en español como clave. Sin ellos la app sale toda en español.
    ('resources/i18n/*.json',                'resources/i18n'),
    # Mapa QML (QtLocation/OSM) para marcar la ubicación del proyecto.
    ('resources/map.qml',                    'resources'),
    # Escena 3D del visor BIM (views/bim_visor.py).
    ('resources/bim_visor.qml',              'resources'),
    # Repositorio de proveedores de tiles propio (calle OSM + satélite Esri,
    # sin API key). Reemplaza el servicio hospedado de Qt, ya descontinuado.
    ('resources/osm_providers/street',       'resources/osm_providers'),
    ('resources/osm_providers/satellite',    'resources/osm_providers'),
    # Asociación de archivos .db → icono de documento branded.
    #   - .ico para el instalador de Windows (Inno Setup).
    #   - PNGs del tema hicolor + XML del MIME para la instalación en Linux
    #     (los consume install-linux.sh desde _internal/resources/…).
    ('resources/icons/mimetypes/ingepresupuestos-db.ico', 'resources/icons/mimetypes'),
    ('resources/icons/mimetypes/ingepresupuestos-db.svg', 'resources/icons/mimetypes'),
    # Iconos del tema hicolor para la asociación .db en Linux. Se listan por
    # tamaño con glob (una tupla de directorio NO los bundlea de forma fiable).
    ('resources/icons/hicolor/16x16/mimetypes/*.png',    'resources/icons/hicolor/16x16/mimetypes'),
    ('resources/icons/hicolor/24x24/mimetypes/*.png',    'resources/icons/hicolor/24x24/mimetypes'),
    ('resources/icons/hicolor/32x32/mimetypes/*.png',    'resources/icons/hicolor/32x32/mimetypes'),
    ('resources/icons/hicolor/48x48/mimetypes/*.png',    'resources/icons/hicolor/48x48/mimetypes'),
    ('resources/icons/hicolor/64x64/mimetypes/*.png',    'resources/icons/hicolor/64x64/mimetypes'),
    ('resources/icons/hicolor/128x128/mimetypes/*.png',  'resources/icons/hicolor/128x128/mimetypes'),
    ('resources/icons/hicolor/256x256/mimetypes/*.png',  'resources/icons/hicolor/256x256/mimetypes'),
    ('resources/icons/hicolor/scalable/mimetypes/*.svg', 'resources/icons/hicolor/scalable/mimetypes'),
    ('resources/mime/*.xml',    'resources/mime'),
]

# ── Hidden imports ───────────────────────────────────────────────────────────
# Módulos que PyInstaller no detecta automáticamente (importados dinámicamente
# o vía strings). Si más adelante hay ModuleNotFoundError en runtime,
# agregar aquí.
hiddenimports = [
    # Módulos internos referenciados por import perezoso (dentro de funciones) —
    # PyInstaller normalmente los detecta, pero se listan por seguridad.
    'core.plantillas_estructura',
    # API pública de complementos: la importa código que PyInstaller no ve.
    'ingepresupuestos.api', 'ingepresupuestos.pruebas', 'ingepresupuestos.piezas', 'core.complementos.cli',
    'core.complementos.plantilla', 'core.complementos.reportes',
    'core.complementos.contexto',
    'views.complementos_dialog', 'views.complementos_menu',
    # Módulos de la biblioteca estándar que un complemento puede necesitar.
    'calendar', 'collections', 'csv', 'datetime', 'decimal', 'difflib', 'enum',
    'fractions', 'functools', 'html', 'itertools', 'json', 'math', 'statistics',
    'string', 'textwrap', 'unicodedata', 'xml.etree.ElementTree', 'zipfile',
    # MCP: se importan dentro de funciones.
    'core.mcp_stdio', 'core.mcp_operaciones', 'core.ingetrazo_puente',
    'views.mcp_puente', 'views.mcp_dialog', 'views.ingetrazo_traer',
    # Proveedores IA — se importan dinámicamente según la config del usuario.
    'anthropic',
    'groq',
    'openai',
    'google.genai',
    # PySide6 submódulos que a veces no entran en el grafo de imports.
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    'PySide6.QtPrintSupport',
    # Manejo de docs / spreadsheets / PDF
    'openpyxl',
    'docx',
    'pdfplumber',
    'xlrd',
    'pypdf',
    'reportlab',
    # ODF (odfpy) — submódulos usados por core/odt_reports.py + ods_reports.py
    'odf',
    'odf.opendocument',
    'odf.style',
    'odf.text',
    'odf.table',
    'odf.draw',
    'odf.office',
    # Otros
    'rapidfuzz',
    'werkzeug',
    'PIL',
    'PIL.Image',
    # Lo pide pdfminer.six (importador de PDF) para los PDF cifrados.
    'cryptography',
    'cryptography.hazmat.primitives.serialization',
    'cryptography.hazmat.primitives.asymmetric.padding',
    'cryptography.hazmat.primitives.hashes',
    # ODBC — lectura de .prs (MS Access) en Windows.
    'pyodbc',
    # Fallback para .prs con contraseña (lee MDB sin ODBC).
    'access_parser',
    # Mapa de ubicación (resources/map.qml): QtLocation y QtPositioning se
    # importan SOLO desde el QML, nunca desde Python → PyInstaller no los ve por
    # análisis estático y no los bundlearía. Forzarlos aquí dispara sus hooks
    # (add_qt6_dependencies), que traen los .dll Qt6Location/Qt6Positioning y los
    # módulos QML. Sin esto el mapa carga con error en el binario. Ver más abajo
    # el bundle explícito del plugin de geoservicios.
    'PySide6.QtLocation',
    'PySide6.QtPositioning',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    # Visor BIM: la escena QML importa QtQuick3D y Python crea las mallas.
    'PySide6.QtQuick3D',
    'PySide6.QtQuickWidgets',
    # RAG Fase 2 — model2vec (embeddings estáticos, sin PyTorch) + sus deps que
    # se cargan dinámicamente. El modelo se bundlea como data (ver más abajo).
    'model2vec',
    'model2vec.model',
    'tokenizers',
    'safetensors',
    'huggingface_hub',
]

# ── Plugins/QML del mapa que PyInstaller no recolecta solo ───────────────────
# El plugin Qt de geoservicios (proveedor 'osm', qtgeoservices_osm.{dll,so}) NO
# está en el mapeo automático de PyInstaller (no se asocia al módulo QtLocation),
# así que hay que copiarlo a mano junto con los módulos QML del mapa.
#
# OJO con el layout del wheel, que difiere por plataforma:
#   • Windows: los recursos Qt cuelgan directo de PySide6/  (PySide6/plugins, PySide6/qml)
#   • Linux/macOS: cuelgan de PySide6/Qt/  (PySide6/Qt/plugins, PySide6/Qt/qml)
# El destino en el bundle debe ESPEJAR esa ruta relativa (es donde apunta el
# qt.conf generado). Antes se asumía siempre PySide6/plugins → en Linux el
# `if exists()` saltaba todo en silencio y el AppImage cargaba el mapa con error.
# Derivar el destino de la ruta real evita ese sesgo de plataforma.
import PySide6 as _pyside6
_PS6 = Path(_pyside6.__file__).resolve().parent
_QT_BASE = (_PS6 / 'Qt') if (_PS6 / 'Qt').is_dir() else _PS6   # Linux/macOS vs Windows
for _sub in (
    'plugins/geoservices',   # qtgeoservices_osm.{dll,so} (proveedor de tiles)
    'plugins/position',      # plugins de posicionamiento (por si QtPositioning los pide)
    'qml/QtLocation',
    'qml/QtPositioning',
):
    _src = _QT_BASE / _sub
    if _src.exists():
        # 'PySide6/plugins/geoservices' en Win · 'PySide6/Qt/plugins/geoservices' en Linux
        datas.append((str(_src), str(Path('PySide6') / _src.relative_to(_PS6))))

# ── Modelo de embeddings RAG Fase 2 (model2vec int8, ~147 MB) ────────────────
# Gitignored: en el build se baja de R2 a resources/models/ ANTES de PyInstaller
# (ver el step "Descargar modelo RAG" en los workflows + RELEASE_CHECKLIST). Si
# no está, el bundle sale sin él y la app degrada a fuzzy (Fase 1) — no rompe.
_modelo_rag = ROOT / 'resources' / 'models' / 'potion-multilingual-128M'
if _modelo_rag.is_dir():
    datas.append((str(_modelo_rag), 'resources/models/potion-multilingual-128M'))

# ── IfcOpenShell (geometría del visor BIM) ───────────────────────────────────
# Opcional: sin él la app funciona y el visor explica que falta. Carga sus
# núcleos con dlopen, así que PyInstaller no los ve; se listan SOLO los que el
# visor usa (esquemas, conversión y OpenCASCADE) y PyInstaller trae sus
# dependencias. Quedan fuera los de exportar (COLLADA, glTF, STEP, SVG…), CGAL,
# wgpu y los datos de ifcopenshell.util/api/express: de 203 MB a unos 60.
binaries = []
import importlib.util as _ilu
_ifc = _ilu.find_spec('ifcopenshell')
if _ifc is not None:
    _ifc_dir = Path(_ifc.origin).parent
    for _patron in ('ifcopenshell_parse_schema_*', 'ifcopenshell_geometry_mapping_*',
                    'ifcopenshell_geometry_kernel_opencascade*',
                    'ifcopenshell_document_rdb*'):
        for _f in sorted(_ifc_dir.glob(_patron)):
            if _f.suffix in ('.so', '.dll', '.dylib'):
                binaries.append((str(_f), 'ifcopenshell'))
    hiddenimports += ['ifcopenshell', 'ifcopenshell.geom',
                      'ifcopenshell.util.mvd_info', 'ifcopenshell.util.schema']

# ── Exclusiones — reducen tamaño del binario ────────────────────────────────
excludes = [
    'tkinter',          # no usado, viene con Python por defecto
    'matplotlib',       # no usado
    'numpy.tests',
    'pandas',           # no usado
    'IPython',
    'jupyter',
    # IfcOpenShell: partes que el visor no usa.
    'ifcopenshell.api',
    'ifcopenshell.express',
    'shapely',
]

a = Analysis(
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Ícono por plataforma. PyInstaller acepta .ico (Windows), .icns (macOS),
# .png (cualquier plataforma). Usamos .svg → si falla en build, generamos
# .ico/.icns aparte. Por ahora, sin ícono específico para evitar fallos.
icon = None
if sys.platform == 'win32':
    win_ico = ROOT / 'resources' / 'icons' / 'elementary' / '24' / 'ingepresupuestos.ico'
    if win_ico.exists():
        icon = str(win_ico)
elif sys.platform == 'darwin':
    mac_icns = ROOT / 'resources' / 'icons' / 'elementary' / '24' / 'ingepresupuestos.icns'
    if mac_icns.exists():
        icon = str(mac_icns)

# Versión visible en Propiedades ▸ Detalles de los .exe (solo Windows).
def _version_win(descripcion, archivo):
    if sys.platform != 'win32':
        return None
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
        VarStruct, VSVersionInfo)
    ver = re.search(r'CURRENT_VERSION\s*=\s*"([\d.]+)"',
                    (ROOT / 'core' / 'update_manager.py').read_text(encoding='utf-8')).group(1)
    nums = tuple((list(map(int, ver.split('.'))) + [0, 0, 0, 0])[:4])
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[StringFileInfo([StringTable('0C0A04B0', [
                  StringStruct('CompanyName', 'Marco Sumari'),
                  StringStruct('FileDescription', descripcion),
                  StringStruct('FileVersion', ver),
                  StringStruct('OriginalFilename', archivo),
                  StringStruct('ProductName', 'IngePresupuestos'),
                  StringStruct('ProductVersion', ver)])]),
              VarFileInfo([VarStruct('Translation', [0x0C0A, 1200])])])


exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ingepresupuestos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX comprime pero a veces rompe PySide6
    console=False,              # False = sin terminal (app GUI)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
    version=_version_win('IngePresupuestos', 'ingepresupuestos.exe'),
)

# ── ingepresupuestos-mcp: programa de CONSOLA para los clientes MCP ─────────
# Hablan por stdin/stdout y un .exe de ventana puede no tenerlos. Solo stdlib
# y comparte el mismo _internal/. En Linux y macOS basta `ingepresupuestos
# --mcp`, pero el binario se incluye igual para que el bundle sea uno solo.
mcp_a = Analysis(
    ['scripts/ingepresupuestos_mcp.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=['core.mcp_stdio'],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes + ['PySide6', 'numpy'],
    noarchive=False,
)
mcp_pyz = PYZ(mcp_a.pure)
mcp_exe = EXE(
    mcp_pyz,
    mcp_a.scripts,
    [],
    exclude_binaries=True,
    name='ingepresupuestos-mcp',
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=icon,
    version=_version_win('IngePresupuestos (MCP)', 'ingepresupuestos-mcp.exe'),
)

coll = COLLECT(
    exe,
    mcp_exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    mcp_a.binaries,
    mcp_a.zipfiles,
    mcp_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ingepresupuestos',
)

# ── macOS .app bundle (solo si compilamos en macOS) ──────────────────────────
if sys.platform == 'darwin':
    # La versión del bundle sale de la misma constante que usa la app, para
    # que Finder ▸ Obtener información no muestre una versión vieja.
    _m = re.search(r'^CURRENT_VERSION\s*=\s*"([^"]+)"',
                   (ROOT / 'core' / 'update_manager.py').read_text(encoding='utf-8'), re.M)
    _version = _m.group(1) if _m else '0.0.0'
    app = BUNDLE(
        coll,
        name='ingepresupuestos.app',
        icon=icon,
        bundle_identifier='pe.tuxiasumari.ingepresupuestos',
        info_plist={
            'CFBundleDisplayName': 'ingePresupuestos',
            'CFBundleShortVersionString': _version,
            'CFBundleVersion': _version,
            'LSBackgroundOnly': False,
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
        },
    )
