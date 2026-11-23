# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #33: contraer y expandir los títulos del Gantt, solo en la vista."""
import copy
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt                                       # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])
SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_plegar_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

from views.cronograma_view import CronogramaView                    # noqa: E402

PID = 396
_VIVAS = []


def _gantt():
    conn = d.get_db()
    proy = dict(conn.execute("SELECT * FROM proyectos WHERE id=?", (PID,)).fetchone())
    conn.close()
    v = CronogramaView(PID, proy, lambda: None)
    v.cargar()
    _VIVAS.append(v)
    g = v._gantt_w
    g.cargar()
    return v, g


def _visibles(g):
    return [r for r in range(g.tbl.rowCount()) if not g.tbl.isRowHidden(r)]


def _foto(v, g):
    from core.cronograma import numerar_filas
    return (copy.deepcopy(v._tasks), copy.deepcopy(v._cron_map),
            numerar_filas(v._partidas), [f['id'] for f in v.filas_con_hitos()],
            [g.tbl.item(r, 0).text() for r in range(g.tbl.rowCount())])


def test_contraer_un_titulo_solo_cambia_la_vista():
    v, g = _gantt()
    g.mostrar_hasta_nivel(None)
    n = g.tbl.rowCount()
    assert len(_visibles(g)) == n
    assert g.scene.sceneRect().height() == n * g.ROW_H
    foto = _foto(v, g)
    fila = next(r for r in range(n) if g.tbl.item(r, 2).text().lstrip().startswith('▾')
                and g.tbl.item(r, 0).data(Qt.UserRole) > 0)
    pid = g.tbl.item(fila, 0).data(Qt.UserRole)
    g.tbl.cellClicked.emit(fila, 2)
    vis = _visibles(g)
    assert fila in vis and fila + 1 not in vis
    assert g.tbl.item(fila, 2).text().lstrip().startswith('▸')
    assert g.scene.sceneRect().height() == len(vis) * g.ROW_H
    v._calcular_cpm()                          # recalcular estando contraído
    g._render_gantt(); g._refrescar_filas_es_ef()
    assert _foto(v, g) == foto                 # fechas, #, filas del PDF y de MS Project

    _v2, g2 = _gantt()                         # se recuerda en el presupuesto
    assert g2._plegados() == {pid} and _visibles(g2) == vis
    g2.tbl.cellClicked.emit(fila, 2)
    assert len(_visibles(g2)) == n


def test_hasta_nivel():
    v, g = _gantt()
    filas = v.filas_con_hitos()
    for nivel in (1, 2):
        g.mostrar_hasta_nivel(nivel)
        vis = [filas[r] for r in _visibles(g)]
        assert all(p['es_titulo'] and (p['nivel'] or 1) <= nivel
                   for p in vis if not p.get('_virtual') and p['es_titulo'])
        esperados = [p for p in filas if p.get('_virtual') or
                     (p['es_titulo'] and (p['nivel'] or 1) <= nivel)]
        assert all(p in vis for p in esperados)
    g.mostrar_hasta_nivel(1)
    assert len(_visibles(g)) < len(filas)
    g.mostrar_hasta_nivel(None)
    assert len(_visibles(g)) == len(filas)


def test_contraer_un_subpresupuesto():
    v, g = _gantt()
    g.mostrar_hasta_nivel(None)
    filas = v.filas_con_hitos()
    subs = [r for r, p in enumerate(filas) if p.get('_virtual') == 'subppto']
    assert len(subs) >= 2
    g.tbl.cellClicked.emit(subs[0], 2)
    ocultas = set(range(len(filas))) - set(_visibles(g))
    assert ocultas == set(range(subs[0] + 1, subs[1]))
    g.mostrar_hasta_nivel(None)


def test_pdf_igual_con_todo_contraido():
    v, g = _gantt()
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument

    def texto():                                # páginas pintadas
        ruta = tempfile.mktemp(suffix='.pdf')
        g._render_pdf_completo(ruta, 'varias', 'landscape', True)
        doc = QPdfDocument()
        doc.load(ruta)
        assert doc.pageCount() > 0
        # La imagen vive mientras se compara: sus bits no son una copia.
        return [doc.render(i, QSize(700, 500)).copy()
                for i in range(doc.pageCount())]
    g.mostrar_hasta_nivel(None)
    antes = texto()
    g.mostrar_hasta_nivel(1)
    assert texto() == antes
    g.mostrar_hasta_nivel(None)
