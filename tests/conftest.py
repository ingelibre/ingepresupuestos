"""Shared pytest guard: a test must never block.

Offscreen, a modal QMessageBox waits forever for a click that never comes, and
the whole run hangs with no clue.  Every static message box raises instead,
naming the dialog, so the test fails at once and says why.  A test that
expects a message box patches it itself (monkeypatch wins over this).
"""
import os

import shutil
import tempfile

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _no_modal(kind):
    def _raise(parent=None, title='', text='', *args, **kwargs):
        raise RuntimeError(f"modal QMessageBox.{kind} would block the test: "
                           f"{title!r}: {str(text)[:200]!r}")
    return staticmethod(_raise)


# Cada archivo de pruebas copia el seed (~10 MB) a un temporal que nadie
# borraba: unos 400 MB por corrida en /tmp, que en muchas distros es RAM.
_TMP = tempfile.mkdtemp(prefix='ingepres_tests_')
tempfile.tempdir = _TMP


def pytest_unconfigure(config):
    shutil.rmtree(_TMP, ignore_errors=True)


def pytest_configure(config):
    from PySide6.QtWidgets import QMessageBox
    for kind in ('information', 'warning', 'critical', 'question'):
        setattr(QMessageBox, kind, _no_modal(kind))


# Vistas que las pruebas dejan abiertas.  Con una ventana a la vista al salir
# del proceso, PySide destruye los objetos de Qt en cualquier orden y el árbol
# recalcula su geometría sobre delegados ya borrados: segfault intermitente
# DESPUÉS de que todas las pruebas pasaron.

def _ventanas():
    import sys
    if 'PySide6.QtWidgets' not in sys.modules:
        return []
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    return app.topLevelWidgets() if isinstance(app, QApplication) else []


# Cada archivo apunta `core.database.DB_PATH` a su BD temporal AL IMPORTARSE, y
# pytest importa todos antes de correr el primero: en un solo proceso mandaba
# la del último.  Se recuerda la de cada uno y se repone al ejecutarlo.
_bd_del_modulo = {}


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    import sys
    antes = getattr(sys.modules.get('core.database'), 'DB_PATH', None)
    yield
    if isinstance(collector, pytest.Module):
        despues = getattr(sys.modules.get('core.database'), 'DB_PATH', None)
        if despues != antes:
            _bd_del_modulo[str(collector.path)] = despues


@pytest.fixture(autouse=True, scope='module')
def _reponer_bd_del_modulo(request):
    ruta = _bd_del_modulo.get(str(request.path))
    if ruta is not None:
        import core.database
        core.database.DB_PATH = ruta
    yield


@pytest.fixture(autouse=True, scope='module')
def _ocultar_ventanas_del_modulo():
    """Solo se ocultan: destruirlas aquí (deleteLater) también cae a veces."""
    from shiboken6 import isValid
    yield
    for w in _ventanas():
        if isValid(w):
            w.hide()
