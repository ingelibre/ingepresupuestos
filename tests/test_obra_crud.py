# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Tests del ciclo de vida común de los documentos de Control de Obra.

Corre con:  venv/bin/python3 tests/test_obra_crud.py

Requerimientos, partes diarios y valorizaciones tenían su propio `get`,
`listar`, `cerrar`, `reabrir` y guardado de detalle, todos con el mismo cuerpo.
Ahora salen de `core/obra_crud.py`. Estos tests fijan esa conducta y, sobre
todo, la trampa que hace peligrosa la unificación: **las valorizaciones usan
`'abierta'`/`'cerrada'` y los otros dos `'abierto'`/`'cerrado'`**. Hay consultas
por todo el proyecto que filtran por esas cadenas exactas.

Usa una COPIA temporal de presupuestos_seed.db, nunca la BD activa.
"""
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import core.config as cfg
import core.database as d

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_tmpdb = None


def _preparar():
    """BD temporal sembrada y con el esquema al día. Devuelve un proyecto."""
    global _tmpdb
    if _tmpdb is None:
        fd, _tmpdb = tempfile.mkstemp(suffix='_obra.db')
        os.close(fd)
        shutil.copy(SEED, _tmpdb)
        d.DB_PATH = _tmpdb
        cfg.DB_PATH = _tmpdb
        d.init_db()
    conn = d.get_db()
    pid = conn.execute(
        "SELECT proyecto_id FROM partidas GROUP BY proyecto_id "
        "ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
    conn.close()
    return pid


def _estado_crudo(tabla, doc_id):
    """Lee `estado` por SQL directo: lo que de verdad quedó escrito."""
    c = sqlite3.connect(_tmpdb)
    r = c.execute(f"SELECT estado FROM {tabla} WHERE id=?", (doc_id,)).fetchone()
    c.close()
    return r[0] if r else None


# ── La trampa: el género del estado ──────────────────────────────────────────

def test_las_valorizaciones_usan_estado_en_femenino():
    """No es un descuido: hay consultas que filtran por la cadena exacta.

    Unificar los tres documentos con un solo 'cerrado' habría dejado a las
    valorizaciones con un estado que ninguna otra consulta reconoce.
    """
    from core import obra_crud as oc
    assert oc.estado_cerrado('requerimientos') == 'cerrado'
    assert oc.estado_cerrado('parte_diario') == 'cerrado'
    assert oc.estado_cerrado('valorizaciones') == 'cerrada'
    assert oc.estado_abierto('requerimientos') == 'abierto'
    assert oc.estado_abierto('parte_diario') == 'abierto'
    assert oc.estado_abierto('valorizaciones') == 'abierta'


def test_cerrar_y_reabrir_escriben_el_estado_de_cada_documento():
    import core.parte_diario as PD
    import core.requerimientos as REQ
    import core.valorizacion as VAL
    pid = _preparar()

    r = REQ.crear_requerimiento(pid, '2026-01-05', 'CEMENTO')
    p = PD.crear_parte(pid, '2026-01-05')
    v = VAL.crear_valorizacion(pid, '2026-01-01', '2026-01-31')

    REQ.cerrar_requerimiento(r); PD.cerrar_parte(p); VAL.cerrar_valorizacion(v)
    assert _estado_crudo('requerimientos', r) == 'cerrado'
    assert _estado_crudo('parte_diario', p) == 'cerrado'
    assert _estado_crudo('valorizaciones', v) == 'cerrada'

    REQ.reabrir_requerimiento(r); PD.reabrir_parte(p); VAL.reabrir_valorizacion(v)
    assert _estado_crudo('requerimientos', r) == 'abierto'
    assert _estado_crudo('parte_diario', p) == 'abierto'
    assert _estado_crudo('valorizaciones', v) == 'abierta'


# ── Lectura ──────────────────────────────────────────────────────────────────

def test_obtener_devuelve_none_si_no_existe():
    from core import obra_crud as oc
    _preparar()
    for doc in ('requerimientos', 'parte_diario', 'valorizaciones'):
        assert oc.obtener(doc, 999999) is None


def test_documento_desconocido_no_llega_al_sql():
    """El nombre de tabla se interpola: solo puede venir de la lista blanca."""
    from core import obra_crud as oc
    for mal in ('proyectos', 'requerimientos; DROP TABLE partidas', ''):
        try:
            oc.obtener(mal, 1)
        except ValueError:
            continue
        raise AssertionError(f"aceptó un documento no permitido: {mal!r}")


def test_orden_invalido_no_llega_al_sql():
    from core import obra_crud as oc
    pid = _preparar()
    try:
        oc.listar('requerimientos', pid, orden='numero; DROP TABLE partidas')
    except ValueError:
        return
    raise AssertionError("aceptó un ORDER BY arbitrario")


# ── Detalle por categoría ────────────────────────────────────────────────────

def test_detalle_ignora_filas_vacias_y_renumera_el_orden():
    import core.requerimientos as REQ
    pid = _preparar()
    r = REQ.crear_requerimiento(pid, '2026-02-01', 'ACERO')
    filas = [
        {'descripcion': 'CEMENTO', 'unidad': 'BOL', 'cantidad': 10},
        {'descripcion': '   ', 'unidad': '', 'cantidad': None},   # se salta
        {'descripcion': '', 'unidad': '', 'cantidad': 0},         # se salta
        {'descripcion': 'ARENA', 'unidad': 'M3', 'cantidad': 2.5},
    ]
    assert REQ.save_detalle(r, 'mat', filas) is True
    det = REQ.get_detalle(r, 'mat')
    assert [x['descripcion'] for x in det] == ['CEMENTO', 'ARENA']
    # el orden se renumera sobre las que entran, sin heredar los huecos.
    # `get_detalle` no devuelve la columna, así que se lee por SQL directo.
    c = sqlite3.connect(_tmpdb)
    ordenes = [x[0] for x in c.execute(
        "SELECT orden FROM requerimiento_detalle WHERE requerimiento_id=? "
        "AND tipo=? ORDER BY orden", (r, 'mat'))]
    c.close()
    assert ordenes == [1, 2], ordenes


def test_detalle_no_se_puede_guardar_con_el_documento_cerrado():
    import core.parte_diario as PD
    import core.requerimientos as REQ
    pid = _preparar()
    filas = [{'descripcion': 'CLAVOS', 'unidad': 'KG', 'cantidad': 3}]

    r = REQ.crear_requerimiento(pid, '2026-03-01', 'VARIOS')
    REQ.cerrar_requerimiento(r)
    assert REQ.save_detalle(r, 'mat', filas) is False

    p = PD.crear_parte(pid, '2026-03-01')
    PD.cerrar_parte(p)
    assert PD.save_recursos_dia(p, 'mat', filas) is False


def test_detalle_reemplaza_entero_la_categoria():
    import core.requerimientos as REQ
    pid = _preparar()
    r = REQ.crear_requerimiento(pid, '2026-04-01', 'PINTURA')
    REQ.save_detalle(r, 'mat', [{'descripcion': 'A', 'unidad': 'u', 'cantidad': 1},
                                {'descripcion': 'B', 'unidad': 'u', 'cantidad': 2}])
    REQ.save_detalle(r, 'mat', [{'descripcion': 'C', 'unidad': 'u', 'cantidad': 3}])
    assert [x['descripcion'] for x in REQ.get_detalle(r, 'mat')] == ['C']
    # …y no toca las otras categorías
    REQ.save_detalle(r, 'eq', [{'descripcion': 'D', 'unidad': 'u', 'cantidad': 4}])
    assert [x['descripcion'] for x in REQ.get_detalle(r, 'mat')] == ['C']
    assert [x['descripcion'] for x in REQ.get_detalle(r, 'eq')] == ['D']


# ── Lo que NO se unificó, a propósito ────────────────────────────────────────

def test_cada_documento_conserva_su_regla_de_borrado():
    """`eliminar_*` NO se unificó: son tres reglas de negocio distintas."""
    import core.valorizacion as VAL
    pid = _preparar()
    v1 = VAL.crear_valorizacion(pid, '2026-05-01', '2026-05-31')
    v2 = VAL.crear_valorizacion(pid, '2026-06-01', '2026-06-30')
    # solo se puede borrar la ÚLTIMA, para no romper la correlatividad
    assert VAL.eliminar_valorizacion(v1) is False
    assert VAL.eliminar_valorizacion(v2) is True
    assert VAL.eliminar_valorizacion(v1) is True


def test_el_parte_es_get_or_create_por_fecha():
    """`crear_parte` tampoco se unificó: es uno por día, no un correlativo."""
    import core.parte_diario as PD
    pid = _preparar()
    a = PD.crear_parte(pid, '2026-07-15')
    b = PD.crear_parte(pid, '2026-07-15')
    assert a == b


def test_el_crud_tiene_un_solo_dueno():
    """Los tres módulos delegan; no volvieron a escribir el cuerpo."""
    import inspect
    import core.parte_diario as PD
    import core.requerimientos as REQ
    import core.valorizacion as VAL
    for mod, fns in ((REQ, ('get_requerimiento', 'listar_requerimientos',
                            'cerrar_requerimiento', 'reabrir_requerimiento',
                            'save_detalle')),
                     (PD, ('get_parte', 'cerrar_parte', 'reabrir_parte',
                           'save_recursos_dia')),
                     (VAL, ('get_valorizacion', 'listar_valorizaciones',
                            'cerrar_valorizacion', 'reabrir_valorizacion'))):
        for nom in fns:
            src = inspect.getsource(getattr(mod, nom))
            assert 'obra_crud.' in src, \
                f"{mod.__name__}.{nom} dejó de delegar en obra_crud"
            assert 'get_db()' not in src, \
                f"{mod.__name__}.{nom} volvió a abrir su propia conexión"


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
    if _tmpdb and os.path.exists(_tmpdb):
        os.unlink(_tmpdb)
    sys.exit(1 if fallos else 0)
