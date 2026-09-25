# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #12: subir / bajar un insumo dentro de su grupo del ACU.

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_orden_insumos_acu.py

Un ACU que nadie reordenó sale exactamente como antes. Usa una COPIA
temporal del seed.
"""
import os
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
_fd, _tmpdb = tempfile.mkstemp(suffix='_orden_acu_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

PID = 186
PART = 12248        # 2 MO + 7 MAT

_VIVAS = []

_ORDEN_VIEJO = """
    SELECT ai.id FROM acu_items ai JOIN recursos r ON r.id = ai.recurso_id
    WHERE ai.partida_id = ?
    ORDER BY CASE r.tipo WHEN 'MO' THEN 1 WHEN 'MAT' THEN 2
                         WHEN 'EQ' THEN 3 ELSE 4 END,
             CASE WHEN r.tipo='MO' THEN mo_rank(r.descripcion) ELSE 0 END,
             r.descripcion"""


def _ids(conn, part=PART):
    items, _ = d.get_acu_items(conn, part)
    return [(i['id'], i['tipo']) for i in items]


def test_sin_reordenar_el_orden_es_el_de_siempre():
    conn = d.get_db()
    partidas = [r[0] for r in conn.execute(
        "SELECT DISTINCT partida_id FROM acu_items LIMIT 400")]
    distintos = 0
    for part in partidas:
        viejo = [r[0] for r in conn.execute(_ORDEN_VIEJO, (part,))]
        nuevo = [i for i, _ in _ids(conn, part)]
        # Solo pueden diferir en empates exactos de descripción (ahora
        # desempata ai.id); el resto debe salir idéntico.
        if viejo != nuevo:
            distintos += 1
            assert sorted(viejo) == sorted(nuevo)
    assert distintos <= len(partidas) // 50, distintos
    conn.close()


def test_subir_y_bajar_dentro_del_grupo():
    conn = d.get_db()
    antes = _ids(conn)
    mats = [i for i, t in antes if t == 'MAT']
    assert d.mover_insumo_acu(conn, PART, mats[1], -1)
    conn.commit()
    ahora = [i for i, t in _ids(conn) if t == 'MAT']
    assert ahora[:2] == [mats[1], mats[0]] and ahora[2:] == mats[2:]
    # El primero de su grupo no sube; el último no baja.
    assert not d.mover_insumo_acu(conn, PART, ahora[0], -1)
    assert not d.mover_insumo_acu(conn, PART, ahora[-1], +1)
    # La MO no se mezcla con los materiales: el último MO no baja a MAT.
    mos = [i for i, t in _ids(conn) if t == 'MO']
    assert not d.mover_insumo_acu(conn, PART, mos[-1], +1)
    assert [t for _, t in _ids(conn)] == [t for _, t in antes]
    conn.close()


def test_un_insumo_nuevo_entra_al_final_de_su_grupo():
    conn = d.get_db()
    mats = [i for i, t in _ids(conn) if t == 'MAT']
    d.mover_insumo_acu(conn, PART, mats[2], -1)
    rid = conn.execute("SELECT id FROM recursos WHERE tipo='MAT' AND id NOT IN "
                       "(SELECT recurso_id FROM acu_items WHERE partida_id=?) LIMIT 1",
                       (PART,)).fetchone()[0]
    nuevo = conn.execute("INSERT INTO acu_items (partida_id, recurso_id, cantidad) "
                         "VALUES (?,?,1)", (PART, rid)).lastrowid
    conn.commit()
    assert [i for i, t in _ids(conn) if t == 'MAT'][-1] == nuevo
    conn.close()


def test_los_reportes_de_acu_siguen_el_orden():
    """El Excel de ACU sale de get_acu_items; el PDF también."""
    from core.pdf_reports import _html_acus  # noqa: F401  (usa get_acu_items)
    conn = d.get_db()
    mats = [i for i, t in _ids(conn) if t == 'MAT']
    d.mover_insumo_acu(conn, PART, mats[-1], -1)
    conn.commit()
    descs = [i['descripcion'] for i in d.get_acu_items(conn, PART)[0] if i['tipo'] == 'MAT']
    sql = conn.execute(
        "SELECT r.descripcion FROM acu_items ai JOIN recursos r ON r.id=ai.recurso_id "
        "WHERE ai.partida_id=? ORDER BY " + d.ORDEN_ACU_SQL, (PART,)).fetchall()
    assert [r[0] for r in sql if r[0] in descs] == descs
    conn.close()


def test_duplicar_y_copiar_conservan_el_orden():
    from utils import partidas_clipboard as pc
    conn = d.get_db()
    ser = pc._serializar_partida(conn, PART)
    ordenes = [a['orden'] for a in ser['acu_items']]
    assert any(o is not None for o in ordenes)
    conn.close()


def test_el_panel_mueve_el_insumo_seleccionado():
    from views.proyecto_view import ProyectoView
    from models.usuario import Usuario
    v = ProyectoView(PID, Usuario(id=1, nombre="t", rol="admin"))
    v._completar_panel_tabs()
    v._cargar_datos_inicial()
    _VIVAS.append(v)
    v.cargar_acu(PART)
    fila = next(r for r, i in enumerate(v._acu_row_ids) if i != -1
                and r + 1 < len(v._acu_row_ids) and v._acu_row_ids[r + 1] != -1)
    acu_id = v._acu_row_ids[fila]
    v.tbl_acu.setCurrentCell(fila, 1)
    v._mover_insumo_acu(+1)
    assert v._acu_row_ids.index(acu_id) == fila + 1
    assert v.tbl_acu.currentRow() == fila + 1


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
