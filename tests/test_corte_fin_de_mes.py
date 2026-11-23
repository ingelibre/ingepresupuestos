# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #52: cronogramas con corte a fin de mes calendario, por proyecto."""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication                          # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])
SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_corte_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()
d.init_db()                     # la migración es idempotente

from core import cronograma as C                                    # noqa: E402
from core import pdf_reports as R                                   # noqa: E402

_VIVAS = []


def _proyecto():
    conn = d.get_db()
    pid = conn.execute("INSERT INTO proyectos (nombre, plazo, fecha_inicio,"
                       " salta_no_laborables) VALUES ('Corte',75,'2026-06-15',0)").lastrowid
    rec = conn.execute("SELECT id FROM recursos WHERE tipo='MAT' AND unidad='kg' LIMIT 1"
                       ).fetchone()['id']
    for i, (ini, dur) in enumerate(((1, 20), (10, 50), (40, 33)), 1):
        p = conn.execute("INSERT INTO partidas (proyecto_id,item,descripcion,unidad,"
                         "metrado,precio_unitario,nivel,es_titulo) VALUES (?,?,?,'m2',"
                         "10,?,1,0)", (pid, f'{i:02d}', f'P{i}', 100.0 * i)).lastrowid
        conn.execute("INSERT INTO acu_items (partida_id,recurso_id,cantidad,precio)"
                     " VALUES (?,?,1,?)", (p, rec, 100.0 * i))
        conn.execute("INSERT INTO cronograma_partidas (partida_id,inicio_dia,duracion)"
                     " VALUES (?,?,?)", (p, ini, dur))
    conn.commit()
    conn.close()
    return pid


def _vista(pid):
    from views.cronograma_view import CronogramaView
    conn = d.get_db()
    proy = dict(conn.execute("SELECT * FROM proyectos WHERE id=?", (pid,)).fetchone())
    conn.close()
    v = CronogramaView(pid, proy, on_back=lambda: None)
    v.cargar()
    _VIVAS.append(v)
    return v


def test_por_defecto_meses_de_30_dias_identicos():
    proy = {'fecha_inicio': '2026-06-15'}
    assert C.ventanas_periodos(proy, 75, 30) == [(1, 30), (31, 60), (61, 90)]
    assert C.ventanas_periodos(proy, 5, 7) == [(1, 7)]
    for segs, ini, dur in (('', 3, 41), ('[{"inicio_dia":2,"duracion":9},'
                                         '{"inicio_dia":40,"duracion":20}]', 1, 5)):
        for pd in (7, 30):
            v = C.ventanas_periodos(proy, 75, pd)
            assert C.distribuir_ventanas(segs, ini, dur, 1234.56, v) == \
                C.distribuir_periodos(segs, ini, dur, 1234.56, len(v), pd)


def test_corte_calendario_primer_mes_parcial_y_misma_suma():
    proy = {'fecha_inicio': '2026-06-15', 'corte_mes': 'cal'}
    v = C.ventanas_periodos(proy, 75, 30)
    assert v == [(1, 16), (17, 47), (48, 78)]          # 30-jun, 31-jul, 31-ago
    assert [C.nombre_mes_corte(proy, x) for x in v] == ['Jun 26', 'Jul 26', 'Ago 26']
    assert C.ventanas_periodos(proy, 75, 7) == \
        C.ventanas_periodos({'fecha_inicio': '2026-06-15'}, 75, 7)
    assert abs(sum(C.distribuir_ventanas('', 1, 75, 1000.0, v)) - 1000.0) < 1e-9
    assert C.ventanas_periodos(proy, 10, 30) == [(1, 16)]


def test_las_tres_pestanas_y_los_reportes_coinciden():
    pid = _proyecto()
    v = _vista(pid)
    tabs = (v._valorz_w, v._insumos_w, v._curva_w)
    for w in tabs:
        w.cargar()
        assert w._cmb_per.currentIndex() == 1
    antes = list(v._curva_w._last_data['total_per'])
    v._valorz_w._cmb_per.setCurrentIndex(2)            # fin de mes
    for w in tabs:
        w.cargar()
        assert w._cmb_per.currentIndex() == 2
        assert w._ventanas == [(1, 16), (17, 47), (48, 78)]
    ahora = v._curva_w._last_data['total_per']
    assert ahora != antes and abs(sum(ahora) - sum(antes)) < 1e-6
    assert '15–30 Jun' in v._valorz_w._periodo_label('Mes', 0)
    v._valorz_w._show_fechas = False
    assert v._valorz_w._periodo_label('Mes', 1) == 'Mes 2\nJul 26'

    # El PDF corta igual y da los mismos montos por período.
    conn = d.get_db()
    proy = dict(conn.execute("SELECT * FROM proyectos WHERE id=?", (pid,)).fetchone())
    conn.close()
    items, _ = d.calcular_totales(pid)
    for html in (R._html_cronograma_valorizado(pid, proy, items, escala='mes',
                                               periodos_por_pagina=-1),
                 R._html_cronograma_adquisiciones_v2(pid, proy, items, escala='mes',
                                                     periodos_por_pagina=-1)):
        assert 'Jun 26' in html and 'Ago 26' in html
        texto = re.sub(r'<[^>]+>', ' ', html)
        for monto in ahora:
            assert f"{monto:,.2f}" in texto, monto
    proy['corte_mes'] = ''
    assert 'Jun 26' not in R._html_cronograma_valorizado(pid, proy, items, escala='mes')

    # Otra vista del mismo proyecto (la oculta del Centro) lo ve al recargar.
    v2 = _vista(pid)
    v2._curva_w.cargar()
    assert v2._curva_w._last_data['total_per'] == ahora


def test_duplicar_conserva_el_corte():
    from views.dashboard_view import _clonar_proyecto
    pid = _proyecto()
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET corte_mes='cal' WHERE id=?", (pid,))
    nuevo = _clonar_proyecto(conn, pid, set())
    assert conn.execute("SELECT corte_mes FROM proyectos WHERE id=?",
                        (nuevo,)).fetchone()[0] == 'cal'
    conn.commit()
    conn.close()
