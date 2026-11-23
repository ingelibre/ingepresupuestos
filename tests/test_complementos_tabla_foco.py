# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""En la tabla de un complemento se escribe en la columna donde se hace clic."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, Qt                               # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

_app = QApplication.instance() or QApplication([])

from ingepresupuestos import api                                    # noqa: E402
from views.complementos_menu import _TablaDatos                     # noqa: E402


def _tabla():
    cols = [api.Dato('e', 'Elemento', 'texto', 'C1'),
            api.Dato('l', 'Luz', 'numero', 0.0, 0, 100),
            api.Dato('n', 'Nota', 'texto', '')]
    w = _TablaDatos(api.Dato('t', 'T', 'tabla', [{}, {}], columnas=cols))
    w.resize(950, 300)
    w.show()
    w.activateWindow()
    _app.processEvents()
    return w


def _col_con_foco(w):
    f = _app.focusWidget()
    for r in range(w.t.rowCount()):
        for c in range(w.t.columnCount()):
            x = w.t.cellWidget(r, c)
            if f is x or (f and x.isAncestorOf(f)):
                return r, c


def _clic(w, r, c):
    x = w.t.cellWidget(r, c)
    QTest.mouseClick(x, Qt.LeftButton, Qt.NoModifier, QPoint(8, x.height() // 2))
    _app.processEvents()


def test_el_clic_se_queda_en_su_columna_y_marca_la_fila():
    w = _tabla()
    for r in (0, 1):
        for c in range(3):
            _clic(w, r, c)
            assert _col_con_foco(w) == (r, c)
            assert w._actual() == r


def test_tab_pasa_al_campo_siguiente():
    w = _tabla()
    _clic(w, 0, 0)
    vistos = []
    for _ in range(3):
        QTest.keyClick(_app.focusWidget(), Qt.Key_Tab)
        _app.processEvents()
        vistos.append(_col_con_foco(w))
    assert vistos == [(0, 1), (0, 2), (1, 0)]


def test_escribir_en_la_ultima_columna():
    w = _tabla()
    _clic(w, 1, 2)
    QTest.keyClicks(_app.focusWidget(), 'hola')
    assert [f['n'] for f in w.filas()] == ['', 'hola']
    assert [f['e'] for f in w.filas()] == ['C1', 'C1']
