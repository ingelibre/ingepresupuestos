# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Navegación entre un proyecto abierto y las vistas globales.

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_navegacion.py

Fija la regla de `MainWindow._ir_a_vista_global`: al salir de un proyecto
hacia CUALQUIER vista global (Inicio, catálogos, Importar, Exportar,
Configuración, Acerca de) queda el banner «← Volver al proyecto», y sin
proyecto activo no hay banner. Hasta la 3.0.4 lo ponían solo tres destinos y
solo con el sidebar colapsado, así que desde el menú lateral el usuario
perdía el camino de vuelta (reporte de David Ramos, 2 sep 2026).

Usa una copia temporal del seed (MainWindow lee configuración de la BD) y
vistas globales de mentira: lo que se prueba es la navegación, no las vistas.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QWidget

import core.database as d

_app = QApplication.instance() or QApplication([])

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_nav_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb

from views.main_window import MainWindow   # noqa: E402  (después de fijar la BD)

# Todo lo que sale del proyecto hacia una vista global, sea desde el menú
# lateral o desde la barra del proyecto.
DESTINOS = ('_ir_a_dashboard', '_ir_a_recursos', '_ir_a_biblioteca',
            '_ir_a_indices_inei', '_ir_a_importar', '_ir_a_exportar',
            '_ir_a_configuracion', '_ir_a_acerca', '_ir_a_ia')


# ── Andamio ──────────────────────────────────────────────────────────────────

def _ventana() -> MainWindow:
    mw = MainWindow(usuario=None)          # sin usuario no construye el Inicio
    mw._crear_vista = lambda nombre: QWidget()   # vistas globales de mentira
    return mw


def _proyecto_falso(mw: MainWindow, pid: int) -> QWidget:
    """Lo mínimo que MainWindow mira de una ProyectoView: `pid` y el nombre
    de vista con el que la vuelve a encontrar en el stack."""
    w = QWidget()
    w.pid = pid
    w.setProperty("vista_nombre", f"proyecto_{pid}")
    mw.stack.addWidget(w)
    return w


def _banner_visible(mw: MainWindow) -> bool:
    # La ventana no se muestra: isHidden() es el estado explícito del widget.
    return not mw._banner_volver.isHidden()


# ── Tests ────────────────────────────────────────────────────────────────────

def test_salir_de_un_proyecto_deja_el_banner_desde_cualquier_destino():
    mw = _ventana()
    proy = _proyecto_falso(mw, 7)
    for colapsado in (True, False):        # barra del proyecto · menú lateral
        for nombre in DESTINOS:
            mw.stack.setCurrentWidget(proy)
            if colapsado:
                mw._colapsar_sidebar()
            else:
                mw._expandir_sidebar()
            getattr(mw, nombre)()
            assert mw.stack.currentWidget() is not proy, nombre
            assert _banner_visible(mw), f"{nombre}: sin banner (sidebar {colapsado})"
            assert mw._volver_a_pid == 7, nombre
            assert not mw._sb_collapsed, f"{nombre}: el sidebar debe verse"


def test_sin_proyecto_activo_no_hay_banner():
    mw = _ventana()
    for nombre in DESTINOS:
        getattr(mw, nombre)()
        assert not _banner_visible(mw), nombre
        assert mw._volver_a_pid is None, nombre


def test_el_banner_vuelve_al_proyecto_que_seguia_abierto():
    mw = _ventana()
    proy = _proyecto_falso(mw, 7)
    mw.stack.setCurrentWidget(proy)
    mw._ir_a_recursos()
    assert mw.stack.currentWidget() is not proy
    mw._click_banner_volver()
    assert mw.stack.currentWidget() is proy      # la misma vista, no una nueva
    assert not _banner_visible(mw)
    assert mw._volver_a_pid is None


def test_la_regla_del_banner_tiene_un_solo_dueno():
    """Ningún `_ir_a_*` decide por su cuenta el banner ni carga la vista: todos
    pasan por `_ir_a_vista_global`. Así un destino nuevo no puede nacer sin
    camino de vuelta, que es exactamente como se rompió."""
    import inspect
    for nombre, fn in vars(MainWindow).items():
        if not nombre.startswith('_ir_a_') or nombre == '_ir_a_vista_global':
            continue
        fuente = inspect.getsource(fn)
        assert '_ir_a_vista_global(' in fuente, f"{nombre} no pasa por la puerta única"
        for prohibido in ('_cargar_vista(', '_banner_volver(', '_sb_collapsed'):
            assert prohibido not in fuente, f"{nombre} usa {prohibido} por su cuenta"


if __name__ == "__main__":
    fallos = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  OK  {name}")
            except AssertionError as e:
                fallos += 1
                print(f"  FAIL {name}: {e}")
    if os.path.exists(_tmpdb):
        os.unlink(_tmpdb)
    sys.exit(1 if fallos else 0)
