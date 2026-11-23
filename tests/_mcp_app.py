"""App real (offscreen) con el puente encendido, para tests/test_mcp_sesion.py.

Uso: python tests/_mcp_app.py — con XDG_DATA_HOME e
INGEPRESUPUESTOS_MCP_REGISTRO apuntando a carpetas temporales. Cierra cuando
se cierra su stdin. No la recoge pytest (no empieza por test_).
"""
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from pathlib import Path                                    # noqa: E402

from PySide6 import QtCore                                  # noqa: E402
from PySide6.QtCore import QTimer                          # noqa: E402

# Escribe un usuario y la api_key: fuera de la carpeta temporal, ni arranca
# (en macOS la carpeta de datos no se puede redirigir).
_BASE = Path(os.environ['INGEPRESUPUESTOS_PRUEBA']).resolve()
from core.config import USER_DATA_DIR                      # noqa: E402
if _BASE not in Path(USER_DATA_DIR).resolve().parents:
    sys.exit(f'datos sin aislar: {USER_DATA_DIR}')


class _QSettings(QtCore.QSettings):
    """A un .ini temporal: en Windows el de verdad es el registro."""

    def __init__(self, org, app):
        super().__init__(str(_BASE / f'{org}-{app}.ini'),
                         QtCore.QSettings.Format.IniFormat)


QtCore.QSettings = _QSettings
from PySide6.QtWidgets import QApplication                 # noqa: E402

app = QApplication([])
from core.database import get_db, init_db, set_config      # noqa: E402
init_db()
conn = get_db()
conn.execute("INSERT OR IGNORE INTO usuarios (id, nombre, username, email, "
             "password_hash, rol) VALUES (9001,'Prueba','prueba','p@e.x','x','admin')")
conn.commit()
conn.close()
set_config('mcp_activo', '1')
set_config('api_key', 'CLAVE-SECRETA-DE-PRUEBA')

import utils.auth as auth                                  # noqa: E402
from models.usuario import Usuario                         # noqa: E402
from views.main_window import MainWindow                   # noqa: E402

auth._usuario_actual = Usuario(id=9001, nombre='Prueba', rol='admin')
v = MainWindow(usuario=None)
v.show()
v.set_usuario(auth._usuario_actual)
assert v._puente_mcp.encendido


def _fin():
    sys.stdin.read()
    QTimer.singleShot(0, app, app.quit)


threading.Thread(target=_fin, daemon=True).start()
print('LISTA', flush=True)
app.exec()
