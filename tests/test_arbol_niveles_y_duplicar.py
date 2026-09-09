# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Dos pedidos de David Ramos del 9 sep 2026 sobre el árbol del presupuesto.

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_arbol_niveles_y_duplicar.py

1. «Mostrar hasta el nivel N» (botón «≡» junto a recalcular): abre el árbol
   hasta ese nivel y lo deja cerrado de ahí para abajo, para ver los montos
   agrupados sin plegar rama por rama. El nivel elegido sobrevive a la recarga.
2. Duplicar una partida abre su ficha para renombrarla; si se CANCELA, la
   copia se descarta (antes quedaba insertada igual).

Usa una COPIA temporal del seed y una ProyectoView real en `offscreen`; el
diálogo de la ficha se sustituye por uno que acepta o cancela sin abrirse.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem

import core.database as d

_app = QApplication.instance() or QApplication([])

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_arbol_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)


def _usar_bd_temporal():
    """Apunta `get_db()` a la copia. Se llama en cada prueba, no al importar:
    en la suite completa otros módulos también fijan `DB_PATH` al importarse
    y el último en cargarse ganaría."""
    if d.DB_PATH != _tmpdb:
        d.DB_PATH = _tmpdb
        d.init_db()      # migraciones sobre la copia, como hace la app al arrancar


_usar_bd_temporal()

import views.proyecto_view as PV                    # noqa: E402
from views.proyecto_view import (                   # noqa: E402
    expandir_hasta_nivel, profundidad_titulos, ProyectoView)
from models.usuario import Usuario                  # noqa: E402

PID = 186  # RESERVORIOS DE 600 M3: en elaboración, 62 filas, títulos a 2 niveles


def _vista() -> ProyectoView:
    """ProyectoView real con el árbol ya cargado (la app lo difiere con
    QTimer al abrir la pestaña)."""
    _usar_bd_temporal()
    v = ProyectoView(PID, Usuario(id=1, nombre="t", rol="admin"))
    v._completar_panel_tabs()      # panel ACU/insumos (segunda etapa)
    v._cargar_datos_inicial()      # partidas + total
    return v


# ── 1. Expandir hasta un nivel ───────────────────────────────────────────────

def _arbol_de_prueba():
    """01 (t1) → 01.01 (t2) → 01.01.01 (t3) → partida ; 02 (t1) → partida."""
    tw = QTreeWidget()
    t1 = QTreeWidgetItem(tw, ["01"])
    t2 = QTreeWidgetItem(t1, ["01.01"])
    t3 = QTreeWidgetItem(t2, ["01.01.01"])
    QTreeWidgetItem(t3, ["01.01.01.01"])
    t1b = QTreeWidgetItem(tw, ["02"])
    QTreeWidgetItem(t1b, ["02.01"])
    tw.expandAll()
    return tw, (t1, t2, t3, t1b)


def test_profundidad_cuenta_solo_los_titulos():
    tw, _ = _arbol_de_prueba()
    assert profundidad_titulos(tw.invisibleRootItem()) == 3
    assert profundidad_titulos(QTreeWidget().invisibleRootItem()) == 0


def test_nivel_1_deja_solo_los_capitulos_cerrados():
    tw, (t1, t2, t3, t1b) = _arbol_de_prueba()
    expandir_hasta_nivel(tw.invisibleRootItem(), 1)
    assert not t1.isExpanded() and not t1b.isExpanded()
    # Los de abajo también quedan cerrados: al abrir el capítulo a mano no
    # debe aparecer todo el sub-árbol de golpe.
    assert not t2.isExpanded() and not t3.isExpanded()


def test_nivel_2_abre_los_capitulos_y_cierra_los_subcapitulos():
    tw, (t1, t2, t3, t1b) = _arbol_de_prueba()
    expandir_hasta_nivel(tw.invisibleRootItem(), 2)
    assert t1.isExpanded() and t1b.isExpanded()
    assert not t2.isExpanded()
    assert not t3.isExpanded()


def test_todos_abre_el_arbol_entero():
    tw, nodos = _arbol_de_prueba()
    expandir_hasta_nivel(tw.invisibleRootItem(), 1)
    expandir_hasta_nivel(tw.invisibleRootItem(), None)
    assert all(n.isExpanded() for n in nodos)


def test_el_nivel_elegido_sobrevive_a_la_recarga():
    v = _vista()
    root = v.tree.invisibleRootItem()
    n_max = profundidad_titulos(root)
    assert n_max >= 2, "el proyecto de prueba necesita al menos 2 niveles"
    v.mostrar_hasta_nivel(1)
    assert all(not root.child(i).isExpanded() for i in range(root.childCount()))
    v.recargar_partidas()               # lo que hace recalcular, editar, etc.
    assert all(not root.child(i).isExpanded() for i in range(root.childCount()))
    v.mostrar_hasta_nivel(None)
    v.recargar_partidas()
    assert all(root.child(i).isExpanded() for i in range(root.childCount()))


def test_el_menu_ofrece_tantos_niveles_como_hay():
    v = _vista()
    n_max = profundidad_titulos(v.tree.invisibleRootItem())
    v._armar_menu_niveles()
    textos = [a.text() for a in v._menu_niveles.actions() if not a.isSeparator()]
    assert textos == ["Todos"] + [f"Nivel {n}" for n in range(1, n_max + 1)]
    assert v._menu_niveles.actions()[0].isChecked()   # «Todos» es el activo


# ── 2. Duplicar y cancelar ───────────────────────────────────────────────────

class _FichaFalsa:
    """Sustituto de PartidaFormDialog: no abre nada, solo acepta o cancela."""
    resultado = 0
    abiertas: list = []

    def __init__(self, pid, part_id, usuario, parent=None, **kw):
        _FichaFalsa.abiertas.append(part_id)

    def exec(self):
        return _FichaFalsa.resultado


def _partidas(pid):
    conn = d.get_db()
    rows = conn.execute(
        "SELECT id, item, descripcion FROM partidas WHERE proyecto_id=? "
        "AND es_titulo=0 ORDER BY item", (pid,)).fetchall()
    conn.close()
    return [tuple(r) for r in rows]


def _con_ficha_falsa(fn):
    import views.partida_form_dialog as PFD
    real = PFD.PartidaFormDialog
    PFD.PartidaFormDialog = _FichaFalsa
    try:
        return fn()
    finally:
        PFD.PartidaFormDialog = real


def test_cancelar_la_ficha_descarta_la_copia():
    v = _vista()
    antes = _partidas(PID)
    orig_id = antes[0][0]
    _FichaFalsa.resultado = 0
    _FichaFalsa.abiertas = []
    _con_ficha_falsa(lambda: v._duplicar_partida(orig_id))
    despues = _partidas(PID)
    assert despues == antes, "al cancelar no debe quedar ninguna partida nueva"
    assert len(_FichaFalsa.abiertas) == 1 and _FichaFalsa.abiertas[0] != orig_id
    # La ficha se abrió sobre la copia, y esa copia ya no existe.
    conn = d.get_db()
    assert conn.execute("SELECT COUNT(*) FROM partidas WHERE id=?",
                        (_FichaFalsa.abiertas[0],)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM acu_items WHERE partida_id=?",
                        (_FichaFalsa.abiertas[0],)).fetchone()[0] == 0
    conn.close()
    # Y el árbol vuelve a la original.
    cur = v.tree.currentItem()
    assert cur is not None and cur.data(0, 0x0100) == orig_id


def test_aceptar_la_ficha_conserva_la_copia_como_hermana():
    v = _vista()
    antes = _partidas(PID)
    orig_id, orig_item, orig_desc = antes[0]
    _FichaFalsa.resultado = 1
    _FichaFalsa.abiertas = []
    _con_ficha_falsa(lambda: v._duplicar_partida(orig_id))
    despues = _partidas(PID)
    assert len(despues) == len(antes) + 1
    nuevo = [r for r in despues if r[0] == _FichaFalsa.abiertas[0]][0]
    assert nuevo[2] == orig_desc
    # Hermana justo debajo: mismo prefijo, correlativo siguiente.
    pref, n = orig_item.rsplit('.', 1)
    assert nuevo[1] == f"{pref}.{int(n) + 1:02d}"
    # La copia trae los insumos del ACU.
    conn = d.get_db()
    n_orig = conn.execute("SELECT COUNT(*) FROM acu_items WHERE partida_id=?",
                          (orig_id,)).fetchone()[0]
    n_new = conn.execute("SELECT COUNT(*) FROM acu_items WHERE partida_id=?",
                         (nuevo[0],)).fetchone()[0]
    conn.close()
    assert n_new == n_orig


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-q']))
