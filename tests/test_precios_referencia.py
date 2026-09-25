# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #11: los ACU de la biblioteca traen precios de referencia del Perú.

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_precios_referencia.py

En un proyecto en otra moneda se avisa y se puede traer solo la estructura
(rendimientos y cantidades). Un insumo que el proyecto ya usa conserva su
precio en los dos modos. Usa una COPIA temporal del seed y un QSettings
temporal.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QSettings                                # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

_QS_DIR = tempfile.mkdtemp(suffix='_qs')
QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, _QS_DIR)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, _QS_DIR)

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_precios_ref_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

CU_ID = 1     # CARTEL DE IDENTIFICACION… — 6 insumos, uno de ellos en %MO


def _proyecto(moneda='Pesos Colombianos') -> int:
    conn = d.get_db()
    pid = conn.execute(
        "INSERT INTO proyectos (nombre, moneda) VALUES (?, ?)",
        (f"prueba {moneda}", moneda)).lastrowid
    conn.commit()
    conn.close()
    return pid


def _partida(conn, pid, item='01.01', desc='partida') -> int:
    return conn.execute(
        "INSERT INTO partidas (proyecto_id, item, descripcion, unidad, metrado,"
        " nivel, es_titulo, rendimiento) VALUES (?,?,?,'und',1,2,0,1)",
        (pid, item, desc)).lastrowid


def _items_bib(conn):
    return conn.execute(
        "SELECT * FROM biblioteca_acu_items WHERE cu_id=?", (CU_ID,)).fetchall()


def _precios(conn, part_id):
    return {r['recurso_id']: (r['precio'], r['unidad'])
            for r in conn.execute(
                "SELECT ai.recurso_id, ai.precio, r.unidad FROM acu_items ai"
                " JOIN recursos r ON r.id = ai.recurso_id WHERE partida_id=?",
                (part_id,))}


def test_solo_estructura_deja_en_cero_los_insumos_nuevos():
    pid = _proyecto()
    conn = d.get_db()
    part = _partida(conn, pid)
    items = _items_bib(conn)
    n = d.copiar_items_acu(conn, part, items, proyecto_id=pid, solo_estructura=True)
    assert n == len(items) == 6
    precios = _precios(conn, part)
    for rid, (precio, unidad) in precios.items():
        if (unidad or '').startswith('%'):
            continue
        assert precio == 0.0, (rid, precio)
    # Las cantidades y cuadrillas sí vienen de la biblioteca.
    orig = {i['recurso_id']: (i['cuadrilla'], i['cantidad']) for i in items}
    for r in conn.execute("SELECT * FROM acu_items WHERE partida_id=?", (part,)):
        assert (r['cuadrilla'], r['cantidad']) == orig[r['recurso_id']]
    assert d._recalcular_pu(conn, part) == 0.0
    conn.close()


def test_con_precios_trae_los_de_la_biblioteca():
    pid = _proyecto()
    conn = d.get_db()
    part = _partida(conn, pid)
    items = _items_bib(conn)
    d.copiar_items_acu(conn, part, items, proyecto_id=pid)
    precios = _precios(conn, part)
    for i in items:
        assert precios[i['recurso_id']][0] == (i['precio'] or None)
    assert d._recalcular_pu(conn, part) > 0
    conn.close()


def test_un_insumo_que_el_proyecto_ya_usa_conserva_su_precio():
    """Regla «un insumo = un precio por proyecto», en los dos modos."""
    for solo in (False, True):
        pid = _proyecto()
        conn = d.get_db()
        items = _items_bib(conn)
        rid = next(i['recurso_id'] for i in items
                   if not str(conn.execute("SELECT unidad FROM recursos WHERE id=?",
                                           (i['recurso_id'],)).fetchone()[0]
                              or '').startswith('%'))
        previa = _partida(conn, pid, '01.01', 'previa')
        conn.execute("INSERT INTO acu_items (partida_id, recurso_id, cuadrilla,"
                     " cantidad, precio) VALUES (?,?,0,1,12345.0)", (previa, rid))
        part = _partida(conn, pid, '01.02', 'nueva')
        d.copiar_items_acu(conn, part, items, proyecto_id=pid, solo_estructura=solo)
        assert _precios(conn, part)[rid][0] == 12345.0, solo
        conn.close()


def test_sugerir_partidas_solo_estructura_recalcula_el_cu():
    from core.ai_specs import importar_partidas_con_biblioteca
    pid = _proyecto()
    conn = d.get_db()
    desc = conn.execute("SELECT descripcion, unidad FROM biblioteca_cu WHERE id=?",
                        (CU_ID,)).fetchone()
    conn.close()
    partidas = [{'item': '01', 'descripcion': 'OBRAS PROVISIONALES', 'es_titulo': 1},
                {'item': '01.01', 'descripcion': desc['descripcion'],
                 'unidad': desc['unidad'], 'metrado_sugerido': 1}]
    creadas, con_acu = importar_partidas_con_biblioteca(
        pid, partidas, usar_biblioteca=True, solo_estructura=True)
    assert (creadas, con_acu) == (2, 1)
    conn = d.get_db()
    p = conn.execute("SELECT id, precio_unitario FROM partidas WHERE proyecto_id=?"
                     " AND es_titulo=0", (pid,)).fetchone()
    assert p['precio_unitario'] == 0.0      # no el CU en soles de la biblioteca
    assert conn.execute("SELECT COUNT(*) FROM acu_items WHERE partida_id=?",
                        (p['id'],)).fetchone()[0] == 6
    conn.close()


def test_el_aviso_no_sale_en_soles_y_recuerda_la_eleccion():
    from views import aviso_precios_dialog as av
    assert av.preguntar_precios(None, 'Soles') == av.CON_PRECIOS
    qs = QSettings("ingePresupuestos", "avisos")
    qs.setValue(av._QS_CLAVE, av.SOLO_ESTRUCTURA)
    qs.sync()
    assert av.preguntar_precios(None, 'Pesos Colombianos') == av.SOLO_ESTRUCTURA
    qs.remove(av._QS_CLAVE)
    pid = _proyecto('Quetzales')
    assert av.moneda_de_proyecto(pid) == 'Quetzales'


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
    sys.exit(1 if fallos else 0)
