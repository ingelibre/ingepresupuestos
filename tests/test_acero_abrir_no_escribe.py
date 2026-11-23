# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Mirar la planilla de acero no escribe nada; el ACU no corta los montos;
el PDF del valorizado respeta el período."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest                                                       # noqa: E402
from PySide6.QtGui import QFont, QFontMetrics                       # noqa: E402

import core.database as d                                           # noqa: E402
from test_subpartidas_ui import _app, conn, vista                   # noqa: E402,F401


def _acero(conn, pid, kg=0.3021, n=4):                              # noqa: F811
    for i in range(1, n + 1):
        conn.execute("INSERT INTO acero_detalle (partida_id,orden,descripcion,diametro,"
                     "n_estructuras,n_elementos,n_veces,longitud,kg_ml,parcial)"
                     " VALUES (?,?,?,'7mm',1,2,3,11.68,?,?)",
                     (pid, i, f'F{i}', kg, round(70.08 * kg, 4)))
    conn.execute("UPDATE partidas SET metrado=84.68 WHERE id=?", (pid,))
    conn.commit()


def _estado(pid):
    c = d.get_db()
    f = [tuple(r) for r in c.execute("SELECT id,orden,kg_ml,parcial FROM acero_detalle"
                                     " WHERE partida_id=? ORDER BY orden", (pid,))]
    m = c.execute("SELECT metrado FROM partidas WHERE id=?", (pid,)).fetchone()[0]
    c.close()
    return f, m


def test_abrir_la_planilla_no_guarda(vista, conn, monkeypatch):     # noqa: F811
    pid = vista.x['a']
    _acero(conn, pid)
    antes = _estado(pid)
    llamadas = []
    original = vista._acero_guardar_silencioso
    monkeypatch.setattr(vista, '_acero_guardar_silencioso',
                        lambda: (llamadas.append(1), original()))
    vista.tabs.setCurrentIndex(2)
    vista.cargar_acero(pid)
    _app.processEvents()
    assert llamadas == []
    assert _estado(pid) == antes
    assert not vista._acero_loading


def test_editar_guarda_una_vez_y_conserva_el_kg_ml(vista, conn):    # noqa: F811
    pid = vista.x['a']
    _acero(conn, pid)
    vista.cargar_acero(pid)
    vista.tbl_acero.item(0, 1).setText('otro')
    filas, _ = _estado(pid)
    assert len(filas) == 4
    assert [f[2] for f in filas] == [0.3021] * 4
    vista.tbl_acero.item(1, 8).setText('0.5')
    assert [f[2] for f in _estado(pid)[0]] == [0.3021, 0.5, 0.3021, 0.3021]


def test_el_acu_no_corta_montos_grandes(vista, conn):               # noqa: F811
    conn.execute("UPDATE acu_items SET precio=180000000 WHERE partida_id=?",
                 (vista.x['a'],))
    conn.commit()
    vista.cargar_acu(vista.x['a'])
    t = vista.tbl_acu
    f = QFont(t.font())
    f.setPixelSize(11)
    fm = QFontMetrics(f)
    for r in range(t.rowCount()):
        for c in (2, 4, 5, 6):
            if t.columnSpan(r, 0) == 1 and t.item(r, c):
                assert fm.horizontalAdvance(t.item(r, c).text()) + 8 <= t.columnWidth(c)


@pytest.mark.parametrize('dias, esperado', [(7, 'semana'), (30, 'mes')])
def test_el_pdf_del_valorizado_respeta_el_periodo(monkeypatch, dias, esperado):
    import views.cronograma_view as V
    from core import pdf_reports as R
    clase = next(c for c in vars(V).values() if isinstance(c, type)
                 and '_render_pdf_a_archivo_con_dialog' in vars(c))
    visto = {}
    monkeypatch.setattr(R, 'generar_pdf_archivo',
                        lambda *a, **k: visto.update(R._BUILD_HTML_PAPER))
    monkeypatch.setattr(V.QFileDialog, 'getSaveFileName', lambda *a, **k: ('/x.pdf', ''))
    monkeypatch.setattr(V.QMessageBox, 'information', lambda *a, **k: None)
    monkeypatch.setitem(R._BUILD_HTML_PAPER, 'escala', 'otra')
    monkeypatch.setitem(R._BUILD_HTML_PAPER, 'periodos_por_pagina', 0)
    monkeypatch.setitem(R._BUILD_HTML_PAPER, 'show_fechas', False)

    class F:
        _cv = type('C', (), {'pid': 1})
        _period_days = dias
        def _dir_descargas(self): return '/'
        def _save_dir(self, p): pass
    clase._render_pdf_a_archivo_con_dialog(
        F(), {'show_fechas': True, 'periodos_por_pagina': 3})
    assert (visto['escala'], visto['periodos_por_pagina'], visto['show_fechas']) == (
        esperado, 3, True)
