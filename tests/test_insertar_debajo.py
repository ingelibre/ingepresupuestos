# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Insertar una partida DEBAJO de la selección (David Ramos, 15 sep 2026).

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_insertar_debajo.py

- Título seleccionado → la partida nueva es su PRIMER hijo (02.05.01) y las
  que había bajan un número.
- Partida seleccionada → hermana inmediatamente debajo (02.05.03) y las
  siguientes bajan.
- Sin selección → como siempre: cuelga del último título con el primer
  código libre, sin renumerar nada.
- Pegar (Ctrl+V) sigue el mismo criterio.

Los diálogos graban la fila con el primer código libre; aquí se simula esa
grabación y se llama al mismo manejador que dispara su señal.
Usa una COPIA temporal del seed y una ProyectoView real en `offscreen`.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt                               # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

import core.database as d                                   # noqa: E402

_app = QApplication.instance() or QApplication([])

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_insertar_test.db')
os.close(_fd)


def _bd_fresca():
    """Copia NUEVA del seed en cada prueba: todas parten del mismo árbol."""
    shutil.copy(SEED, _tmpdb)
    d.DB_PATH = _tmpdb
    d.init_db()


_bd_fresca()

from views.proyecto_view import ProyectoView               # noqa: E402
from models.usuario import Usuario                         # noqa: E402
import utils.partidas_clipboard as _pclip                  # noqa: E402

PID = 186  # RESERVORIOS DE 600 M3: 01 OBRAS PROVISIONALES → 01.01, 01.02, 01.03; 02 → 02.01, 02.02


def _vista() -> ProyectoView:
    _bd_fresca()
    v = ProyectoView(PID, Usuario(id=1, nombre="t", rol="admin"))
    v._completar_panel_tabs()
    v._cargar_datos_inicial()
    return v


def _items(pid=PID) -> dict[int, str]:
    conn = d.get_db()
    out = {r[0]: r[1] for r in conn.execute(
        "SELECT id, item FROM partidas WHERE proyecto_id=?", (pid,)).fetchall()}
    conn.close()
    return out


def _id_de(item: str) -> int:
    conn = d.get_db()
    row = conn.execute("SELECT id FROM partidas WHERE proyecto_id=? AND item=?",
                       (PID, item)).fetchone()
    conn.close()
    assert row, item
    return row[0]


def _seleccionar(v: ProyectoView, part_id: int):
    nodo = v._id_to_item[part_id]
    v.tree.clearSelection()
    v.tree.setCurrentItem(nodo)
    nodo.setSelected(True)
    assert v.tree.selectedItems()[0] is nodo


def _grabar_como_el_dialogo(v: ProyectoView, ctx_item, ctx_es_titulo, desc) -> int:
    """La misma grabación que `AgregarPartidaDialog._agregar_manual`: el
    código lo decide `_siguiente_item` (primer libre de su nivel)."""
    from views.agregar_partida_dialog import AgregarPartidaDialog
    dlg = AgregarPartidaDialog(PID, v.usuario, tab_inicial=1,
                               contexto_item=ctx_item,
                               contexto_es_titulo=ctx_es_titulo,
                               sub_presupuesto_id=v._sub_ppto_id, parent=v)
    conn = d.get_db()
    codigo = dlg._siguiente_item(conn)
    cur = conn.execute(
        "INSERT INTO partidas (proyecto_id,item,descripcion,unidad,metrado,"
        "precio_unitario,nivel,es_titulo,rendimiento,sub_presupuesto_id)"
        " VALUES (?,?,?,?,0,0,?,0,1,?)",
        (PID, codigo, desc, 'm2', len(codigo.split('.')), v._sub_ppto_id))
    conn.commit()
    conn.close()
    dlg.deleteLater()
    return cur.lastrowid


def _agregar_con_seleccion(v: ProyectoView, part_id: int, desc="NUEVA") -> int:
    """Lo que hace `_nueva_partida` + el diálogo + la señal, sin abrir nada."""
    _seleccionar(v, part_id)
    ctx_item, ctx_es_titulo = v._contexto_seleccion()
    v._ancla_insercion = v._nueva_ancla_insercion()
    nuevo = _grabar_como_el_dialogo(v, ctx_item, ctx_es_titulo, desc)
    v._on_partidas_agregadas()
    v._ancla_insercion = None
    return nuevo


# ── Caso 2 de David: partida seleccionada → hermana justo debajo ─────────────

def test_con_una_partida_seleccionada_la_nueva_entra_justo_debajo():
    v = _vista()
    antes = _items()
    id_0101, id_0102, id_0103 = _id_de('01.01'), _id_de('01.02'), _id_de('01.03')
    nuevo = _agregar_con_seleccion(v, id_0102)
    despues = _items()
    assert despues[nuevo] == '01.03', despues[nuevo]
    assert despues[id_0101] == '01.01'
    assert despues[id_0102] == '01.02'
    assert despues[id_0103] == '01.04', "la que seguía baja un número"
    # Nada más se movió.
    for i, it in antes.items():
        if i not in (id_0103,):
            assert despues[i] == it, (i, it, despues[i])
    # El árbol refleja el orden: 01 → 01.01, 01.02, NUEVA, 01.04.
    t01 = v._id_to_item[_id_de('01')]
    assert [t01.child(k).data(0, Qt.UserRole) for k in range(t01.childCount())] == \
        [id_0101, id_0102, nuevo, id_0103]
    conn = d.get_db()
    assert conn.execute("SELECT nivel FROM partidas WHERE id=?", (nuevo,)).fetchone()[0] == 2
    conn.close()


# ── Caso 1 de David: título seleccionado → primer hijo ───────────────────────

def test_con_un_titulo_seleccionado_la_nueva_es_su_primer_hijo():
    v = _vista()
    id_02, id_0201, id_0202 = _id_de('02'), _id_de('02.01'), _id_de('02.02')
    id_0301 = _id_de('03.01')
    nuevo = _agregar_con_seleccion(v, id_02)
    despues = _items()
    assert despues[nuevo] == '02.01'
    assert despues[id_0201] == '02.02'
    assert despues[id_0202] == '02.03'
    assert despues[id_02] == '02' and despues[id_0301] == '03.01'
    t02 = v._id_to_item[id_02]
    assert t02.isExpanded()
    assert t02.child(0).data(0, Qt.UserRole) == nuevo


# ── Sin selección: como siempre ──────────────────────────────────────────────

def test_sin_seleccion_cuelga_del_ultimo_titulo_sin_renumerar():
    v = _vista()
    antes = _items()
    v.tree.clearSelection()
    v.tree.setCurrentItem(None)
    assert v._nueva_ancla_insercion() is None
    v._ancla_insercion = None
    nuevo = _grabar_como_el_dialogo(v, None, False, "AL FINAL")
    v._on_partidas_agregadas()
    despues = _items()
    codigo = despues.pop(nuevo)
    assert despues == antes, "sin ancla no se renumera nada"
    conn = d.get_db()
    ultimo = conn.execute(
        "SELECT item FROM partidas WHERE proyecto_id=? AND es_titulo=1 "
        "ORDER BY CAST(item AS INTEGER) DESC LIMIT 1", (PID,)).fetchone()[0]
    conn.close()
    assert codigo.startswith(ultimo + '.'), (codigo, ultimo)


# ── Dos seguidas del mismo diálogo quedan en orden ───────────────────────────

def test_dos_partidas_seguidas_entran_una_debajo_de_otra():
    v = _vista()
    id_0101 = _id_de('01.01')
    _seleccionar(v, id_0101)
    v._ancla_insercion = v._nueva_ancla_insercion()
    a = _grabar_como_el_dialogo(v, '01.01', False, "A")
    v._on_partidas_agregadas()
    # el diálogo sigue abierto y agrega otra: el ancla ya es «A»
    ctx = v._ancla_insercion
    assert ctx and ctx['id'] == a
    b = _grabar_como_el_dialogo(v, _items()[a], False, "B")
    v._on_partidas_agregadas()
    v._ancla_insercion = None
    despues = _items()
    assert (despues[id_0101], despues[a], despues[b]) == ('01.01', '01.02', '01.03')


# ── Pegar sigue el mismo criterio ────────────────────────────────────────────

def test_pegar_coloca_lo_pegado_justo_debajo_de_la_seleccion():
    v = _vista()
    id_0101, id_0102 = _id_de('01.01'), _id_de('01.02')
    origen = _id_de('03.01')
    conn = d.get_db()
    _pclip.copiar(conn, [origen], PID)
    conn.close()
    _seleccionar(v, id_0101)
    v._pegar_partidas_clipboard()
    despues = _items()
    pegada = [i for i in despues if i not in (id_0101, id_0102) and despues[i] == '01.02']
    assert len(pegada) == 1, sorted(despues.values())[:6]
    assert despues[id_0101] == '01.01' and despues[id_0102] == '01.03'
    conn = d.get_db()
    assert conn.execute("SELECT descripcion FROM partidas WHERE id=?", (pegada[0],)).fetchone()[0] == \
        conn.execute("SELECT descripcion FROM partidas WHERE id=?", (origen,)).fetchone()[0]
    conn.close()


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
            except Exception as e:                        # noqa: BLE001
                fallos += 1
                import traceback; traceback.print_exc()
                print(f"  ERROR {name}: {e}")
    if os.path.exists(_tmpdb):
        os.unlink(_tmpdb)
    sys.exit(1 if fallos else 0)
