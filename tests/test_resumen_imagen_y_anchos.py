# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #15: COSTO DIRECTO en negrita, «ir a la selección», copiar el
resumen como imagen y anchos de columna del presupuesto.

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_resumen_imagen_y_anchos.py

Usa una COPIA temporal del seed.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QFont, QFontMetrics                       # noqa: E402
from PySide6.QtWidgets import (QApplication, QHeaderView, QLabel,   # noqa: E402
                               QTreeWidgetItem)

import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_issue15_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
d.init_db()

from views.proyecto_view import (ProyectoView, _PresupuestoTree,    # noqa: E402
                                 expandir_hasta_nivel)
from models.usuario import Usuario                                  # noqa: E402

PID = 186

_VIVAS = []


def _vista(pid=PID) -> ProyectoView:
    v = ProyectoView(pid, Usuario(id=1, nombre="t", rol="admin"))
    v._completar_panel_tabs()
    v._cargar_datos_inicial()
    _VIVAS.append(v)
    return v


def _partida_honda(v):
    """La partida (no título) más profunda del árbol."""
    mejor, prof_mejor = None, -1
    stack = [(v.tree.invisibleRootItem(), 0)]
    while stack:
        it, prof = stack.pop()
        for i in range(it.childCount()):
            h = it.child(i)
            if h.childCount():
                stack.append((h, prof + 1))
            elif prof > prof_mejor:
                mejor, prof_mejor = h, prof
    return mejor, prof_mejor


def test_costo_directo_va_en_negrita():
    v = _vista()
    filas, _ = v._filas_resumen(all_subs=True)
    nombre, _monto, _color, bold = filas[0]
    assert nombre == "COSTO DIRECTO" and bold


def test_ir_a_la_seleccion_abre_lo_necesario():
    v = _vista()
    part, prof = _partida_honda(v)
    assert part is not None and prof >= 1
    v.tree.setCurrentItem(part)
    v._nivel_visible = 1
    expandir_hasta_nivel(v.tree.invisibleRootItem(), 1)
    padre = part.parent()
    assert not padre.isExpanded() or part.isHidden()
    v._ir_a_seleccion()
    assert not part.isHidden()
    p = part.parent()
    while p is not None:
        assert p.isExpanded() and not p.isHidden()
        p = p.parent()
    assert v.tree.currentItem() is part


def test_copiar_como_imagen_es_nitida():
    from utils.captura import imagen_nitida
    w = QLabel("RESUMEN DE COSTOS  S/ 1,234,567.89")
    w.resize(300, 40)
    img = imagen_nitida(w)
    assert (img.width(), img.height()) == (900, 120)
    assert img.devicePixelRatio() == 3.0
    v = _vista()
    v._copiar_resumen_imagen(w)
    assert not QApplication.clipboard().image().isNull()


def test_las_columnas_numericas_crecen_hasta_el_numero_mas_largo():
    v = _vista()
    item = v.tree.topLevelItem(0)
    largo = "COP$ 12.345.678.901,23"
    item.setText(5, largo)
    v._ajustar_anchos_numericos()
    f = QFont(item.font(5)); f.setBold(True)
    assert v.tree.columnWidth(5) >= QFontMetrics(f).horizontalAdvance(largo) + 24
    # Un ancho mayor puesto a mano no se pisa.
    v.tree.setColumnWidth(4, 400)
    v._ajustar_anchos_numericos()
    assert v.tree.columnWidth(4) == 400


def test_la_descripcion_no_se_encoge_por_debajo_del_minimo():
    t = _PresupuestoTree()
    t.setHeaderLabels(["Ítem", "Descripción", "Und.", "Cantidad", "P.U.", "Parcial"])
    hdr = t.header()
    hdr.setStretchLastSection(False)
    for c in range(6):
        hdr.setSectionResizeMode(c, QHeaderView.Stretch if c == 1 else QHeaderView.Interactive)
        if c != 1:
            t.setColumnWidth(c, 90)
    QTreeWidgetItem(t, ["01", "PARTIDA", "m2", "1", "2", "3"])
    t.resize(900, 300)
    t.show()
    _app.processEvents()
    t.ajustar_modo_descripcion()
    assert hdr.sectionResizeMode(1) == QHeaderView.Stretch
    t.resize(400, 300)
    _app.processEvents()
    t.ajustar_modo_descripcion()
    assert hdr.sectionResizeMode(1) == QHeaderView.Interactive
    assert hdr.sectionSize(1) == _PresupuestoTree.DESC_MIN
    t.resize(900, 300)
    _app.processEvents()
    t.ajustar_modo_descripcion()
    assert hdr.sectionResizeMode(1) == QHeaderView.Stretch
    t.hide()
    _VIVAS.append(t)


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in list(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  OK  {nombre}")
            except Exception as e:
                fallos += 1
                import traceback
                traceback.print_exc()
                print(f"  FAIL {nombre}: {e!r}")
    try:
        os.unlink(_tmpdb)
    except OSError:
        pass
    print("TODO OK" if not fallos else f"FALLOS: {fallos}")
    sys.stdout.flush()
    os._exit(1 if fallos else 0)
