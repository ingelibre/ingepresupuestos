# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Regresiones de la revisión de la 3.2: números con moneda de coma decimal,
códigos con más de 99 hermanas, planilla BIM editada y sub-partidas."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest                                                       # noqa: E402
from PySide6.QtCore import Qt                                       # noqa: E402
from PySide6.QtWidgets import (QDialog, QLineEdit, QMessageBox,     # noqa: E402
                               QTableWidget, QTableWidgetItem)

import core.database as d                                           # noqa: E402
import views.proyecto_view as pv                                    # noqa: E402
from core import bim_modelo as bim, subpartidas as SP               # noqa: E402
from test_subpartidas import _partida, _pu, _recurso, conn          # noqa: E402,F401
from test_subpartidas_ui import vista                               # noqa: E402,F401

UY = 'Pesos Uruguayos'           # 1.234,56


@pytest.fixture
def uy(vista, conn):                                                # noqa: F811
    conn.execute("UPDATE proyectos SET moneda=? WHERE id=?", (UY, vista.x['pid']))
    conn.commit()
    vista._moneda = UY
    vista.tree.setProperty('moneda', UY)
    return vista


def test_celda_metrado_sin_decimales_abre_sin_miles(uy, monkeypatch):
    monkeypatch.setattr(pv, 'get_decimales_metrado', lambda: 0)
    item = uy._id_to_item[uy.x['a']]
    uy.tree.blockSignals(True)
    item.setText(3, '1.234')
    uy.tree.blockSignals(False)
    dele = pv._MetradoDelegate(uy.tree)
    ed = QLineEdit()
    dele.setEditorData(ed, uy.tree.indexFromItem(item, 3))
    assert ed.text() == '1234'


def test_cantidad_de_subpartida_con_coma_decimal(uy, conn):         # noqa: F811
    from views.subpartidas_tab import SubpartidasTab
    p = _partida(conn, uy.x['pid'], '03', 'ZZ PISO', 'm2', 1)
    conn.commit()
    t = SubpartidasTab(p, uy.x['pid'])
    t.seleccionada = lambda: uy.x['sub']
    t.inp_cant.setText('0,125')
    assert t.agregar() == ''
    assert conn.execute("SELECT cantidad FROM acu_items WHERE partida_id=?",
                        (p,)).fetchone()[0] == pytest.approx(0.125)


def test_agregar_recurso_con_coma_decimal(uy, conn):                # noqa: F811
    from views.recurso_selector_dialog import RecursoSelectorDialog
    p = _partida(conn, uy.x['pid'], '03', 'ZZ PISO', 'm2', 1)
    conn.commit()
    dlg = RecursoSelectorDialog(p, {'id': uy.x['pid']})
    dlg._checked_ids = {uy.x['rec']['lad']}
    dlg.inp_cant_b.setText('0,125')
    dlg._agregar_existentes()
    assert conn.execute("SELECT cantidad FROM acu_items WHERE partida_id=?",
                        (p,)).fetchone()[0] == pytest.approx(0.125)


def test_factor_bim_con_coma_decimal(uy, monkeypatch):
    from views import bim_dialog as bv
    dlg = bv.ModeloBimDialog(uy.x['pid'], uy.x['a'])
    visto = []
    monkeypatch.setattr(bv.bim, 'vincular', lambda *a, **k: (
        visto.append(a[4]) or {'vinculados': 0, 'omitidos': [], 'metrado': 0}))
    dlg.ed_factor.setText('0,125')
    dlg._vincular()
    assert visto == [0.125]


def test_gasto_general_con_coma_decimal(uy, conn):                  # noqa: F811
    gid = conn.execute(
        "INSERT INTO gastos_generales (proyecto_id, rubro, tipo, descripcion, cantidad,"
        " pct_participacion, precio) VALUES (?,'GG','item','x',1,100,10)",
        (uy.x['pid'],)).lastrowid
    conn.commit()
    tbl = QTableWidget(1, 7)
    for c, t in enumerate(('x', 'MES', '100', '0,125', '10', '', '')):
        tbl.setItem(0, c, QTableWidgetItem(t))
    tbl.item(0, 0).setData(Qt.UserRole, gid)
    tbl.item(0, 0).setData(Qt.UserRole + 1, 'item')
    uy._gg_save_cell(tbl, 0, 3)
    assert conn.execute("SELECT cantidad FROM gastos_generales WHERE id=?",
                        (gid,)).fetchone()[0] == 0.125


def test_monto_fijo_del_pie_se_ve_y_se_lee_en_su_moneda(uy, conn, monkeypatch):  # noqa: F811
    pid = uy.x['pid']
    conn.execute("INSERT INTO pie_rubros (proyecto_id, codigo, nombre, tipo, orden)"
                 " VALUES (?,'CUSTOM1','Fijo','rubro',1)", (pid,))
    conn.execute("INSERT INTO gastos_generales (proyecto_id, rubro, tipo, descripcion, precio)"
                 " VALUES (?,'CUSTOM1','manual','x',1234.5)", (pid,))
    conn.commit()

    def campo():
        uy.cargar_pie()
        return [w for w in uy.findChildren(QLineEdit)
                if w.toolTip() == pv.tr("Monto fijo de la línea")][-1]
    assert campo().text() == '1.234,50'
    c = campo()
    c.setText('0,125')
    c.editingFinished.emit()
    assert conn.execute("SELECT precio FROM gastos_generales WHERE proyecto_id=? AND"
                        " tipo='manual'", (pid,)).fetchone()[0] == 0.125
    conn.execute("UPDATE gastos_generales SET precio=1234 WHERE proyecto_id=?", (pid,))
    conn.commit()
    monkeypatch.setattr(pv, 'get_decimales_ppto', lambda: 0)
    c = campo()
    assert c.text() == '1.234'
    c.editingFinished.emit()         # sin tocarlo
    assert conn.execute("SELECT precio FROM gastos_generales WHERE proyecto_id=? AND"
                        " tipo='manual'", (pid,)).fetchone()[0] == 1234


def test_reemplazar_insumo_no_toca_las_lineas_de_subpartida(vista, conn, monkeypatch):  # noqa: F811
    rid = conn.execute("SELECT recurso_id FROM acu_items WHERE sub_partida_id=? LIMIT 1",
                       (vista.x['sub'],)).fetchone()[0]

    class _Dlg:
        selected_id = vista.x['rec']['lad']

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QDialog.Accepted
    monkeypatch.setattr(pv, '_SeleccionarRecursoDialog', _Dlg)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    pu = _pu(conn, vista.x['b'])
    vista._ins_reemplazar_recurso(rid, 'SUB-PARTIDA')
    filas = conn.execute("SELECT recurso_id, cantidad FROM acu_items WHERE sub_partida_id=?",
                         (vista.x['sub'],)).fetchall()
    assert len(filas) == 2 and {f[0] for f in filas} == {rid}
    assert _pu(conn, vista.x['b']) == pu


# ── Más de 99 hermanas ──────────────────────────────────────────────────────

def _modelo(n):
    return bim.ModeloBim(nombre='ZZ', huella='zz', elementos=[
        bim.ElementoBim(f'g{i:03d}', 'IfcWall', tipo=f'T{i:03d}', metrado=(1.0 + i, 'm2'))
        for i in range(n)])


def test_bim_proyecto_nuevo_con_mas_de_99_partidas(conn):           # noqa: F811
    pid = bim.crear_proyecto(_modelo(105))
    f = conn.execute("SELECT item, metrado FROM partidas WHERE proyecto_id=? AND es_titulo=0"
                     " ORDER BY item", (pid,)).fetchall()
    assert [x[1] for x in f] == [1.0 + i for i in range(105)]


def test_bim_anadir_mas_de_99_partidas(vista, conn):                # noqa: F811
    _m, ids = bim.anadir_partidas(vista.x['pid'], _modelo(105))
    orden = [r[0] for r in conn.execute(
        "SELECT id FROM partidas WHERE proyecto_id=? AND id>=? AND es_titulo=0 ORDER BY item",
        (vista.x['pid'], ids[0]))]
    assert orden == ids


def test_mcp_add_items_mas_de_99_hermanas(vista, conn, tmp_path):   # noqa: F811
    from core import mcp_deshacer
    from core.mcp_operaciones import Operaciones
    from models.usuario import Usuario
    conn.execute("UPDATE proyectos SET estado='elaboracion' WHERE id=?", (vista.x['pid'],))
    conn.execute("INSERT OR IGNORE INTO usuarios (id,nombre,username,email,password_hash,rol)"
                 " VALUES (1,'t','t','t@x','h','admin')")
    conn.commit()
    ops = Operaciones(Usuario(id=1, rol='admin'), mcp_deshacer.Pila(tmp_path / 'pila'))
    r = ops.add_items(vista.x['pid'], [{'description': 'ZZ T', 'title': True, 'item': '09'}] + [
        {'description': f'ZZ {i}', 'unit': 'm', 'parent_item': '09'} for i in range(105)])
    hechos = [x for x in r['added'] if not x['title']]
    assert [x['item_id'] for x in sorted(hechos, key=lambda x: x['item'])] == \
        [x['item_id'] for x in hechos]
    assert dict(conn.execute("SELECT id, item FROM partidas WHERE proyecto_id=?",
                             (vista.x['pid'],)).fetchall())[hechos[0]['item_id']] \
        == hechos[0]['item'] == '09.001'


# ── Planilla BIM editada ────────────────────────────────────────────────────

def _fila(valor, factor, **k):
    r = dict.fromkeys(('n_estructuras', 'n_elementos', 'area', 'largo', 'ancho', 'alto'))
    return {**r, 'valor': valor, 'factor': factor, 'parcial': 1.0, **k}


def test_edicion_con_factor_se_detecta():
    assert bim._editada(_fila(1000.0, .2, n_estructuras=.2, largo=1010.0))
    assert bim._editada(_fila(1000.0, 1.5, n_estructuras=1.5, largo=1003.0))
    # Lo que redondea la hoja (2 decimales) no es una edición
    assert not bim._editada(_fila(1000.1234, .155, n_estructuras=.16, largo=1000.12))
    assert not bim._editada(_fila(1000.1234, .155, n_estructuras=.15, largo=1000.12))
    assert not bim._editada(_fila(12.3456, 2.0, n_estructuras=2.0, largo=12.35))
    assert not bim._editada(_fila(7.0, 1.0, largo=7.0))


def test_gasto_general_de_siete_cifras_no_pierde_digitos(uy, conn):  # noqa: F811
    """Con «:g» salía «1.23457e+06», que al duplicar la fila se leía 1.2345706."""
    pid = uy.x['pid']
    conn.execute("INSERT INTO pie_rubros (proyecto_id, codigo, nombre, tipo, orden)"
                 " VALUES (?,'CUSTOM1','Det','rubro',1)", (pid,))
    conn.execute("INSERT INTO gastos_generales (proyecto_id, rubro, tipo, descripcion, cantidad,"
                 " pct_participacion, precio) VALUES (?,'CUSTOM1','item','x',1,100,1234567.89)",
                 (pid,))
    conn.commit()
    uy.cargar_pie()
    textos = [t.item(r, 4).text() for t in uy.findChildren(QTableWidget)
              for r in range(t.rowCount()) if t.item(r, 4) and t.item(r, 0)
              and t.item(r, 0).text() == 'x']
    assert textos and pv.parse_num(textos[-1], UY) == 1234567.89
