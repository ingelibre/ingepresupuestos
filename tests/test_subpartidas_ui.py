# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Sub-partidas (issue #23): panel ACU y pestaña del selector.

Usa una copia temporal del seed, nunca la BD activa.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest                                                       # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox  # noqa: E402

_app = QApplication.instance() or QApplication([])

import core.database as d                                           # noqa: E402
from core import subpartidas as SP                                  # noqa: E402
from test_subpartidas import _linea, _partida, _proyecto, _pu, conn  # noqa: E402,F401

_VIVAS = []


@pytest.fixture
def vista(conn):                                                    # noqa: F811
    from models.usuario import Usuario
    from views.proyecto_view import ProyectoView
    x = _proyecto(conn)
    win = QMainWindow()
    v = ProyectoView(x['pid'], Usuario(id=1, nombre='t', rol='admin'))
    win.setCentralWidget(v)
    _VIVAS.append(win)
    v._completar_panel_tabs()
    v._cargar_datos_inicial()
    _app.processEvents()
    v.x = x
    v.cargar_acu(x['a'])
    return v


def _fila_sub(v):
    return next(iter(v._acu_subs))


def test_el_arbol_no_la_muestra_y_el_total_no_la_cuenta(vista):
    assert set(vista._id_to_item) == {vista.x['a'], vista.x['b']}
    assert vista._total_proyecto(all_subs=True) == pytest.approx(
        d.calcular_totales(vista.x['pid'])[1]['cd'])


def test_fila_expandible(vista):
    r = _fila_sub(vista)
    hojas = list(vista._acu_hojas_sub)
    assert len(hojas) == 5 and all(vista._acu_row_ids[h] == -1 for h in hojas)
    assert all(vista.tbl_acu.isRowHidden(h) for h in hojas)
    vista._on_acu_cell_clicked(r, 1)
    assert not any(vista.tbl_acu.isRowHidden(h) for h in hojas)
    assert vista.tbl_acu.item(r, 1).text().startswith('▾')
    vista.cargar_acu(vista.x['a'])      # la recarga la deja abierta
    assert not any(vista.tbl_acu.isRowHidden(h) for h in vista._acu_hojas_sub)
    vista._on_acu_cell_clicked(_fila_sub(vista), 1)
    assert all(vista.tbl_acu.isRowHidden(h) for h in vista._acu_hojas_sub)
    assert len(vista._acu_row_ids) == vista.tbl_acu.rowCount()


def test_precio_derivado_solo_lectura_y_cantidad_editable(vista, conn):  # noqa: F811
    r = _fila_sub(vista)
    m = vista.tbl_acu.model()
    deleg = vista.tbl_acu.itemDelegateForColumn(5)
    assert not deleg._editable(m.index(r, 5)) and deleg._editable(m.index(r, 4))
    assert not any(deleg._editable(m.index(h, c))
                   for h in vista._acu_hojas_sub for c in (3, 4, 5))
    acu_id, antes = vista._acu_row_ids[r], _pu(conn, vista.x['a'])
    vista._aplicar_cambio_acu(acu_id, 5, 9999.0)
    assert _pu(conn, vista.x['a']) == antes
    vista._aplicar_cambio_acu(acu_id, 4, 1.0)
    assert _pu(conn, vista.x['a']) > antes


def test_abrir_editar_y_volver(vista, conn):                        # noqa: F811
    r = _fila_sub(vista)
    vista._editar_celda_acu(vista.tbl_acu.model().index(r, 1))
    assert vista._partida_actual_id == vista.x['sub']
    assert not vista._btn_volver_sub.isHidden() and vista._acu_subs == {}
    # Editar un insumo de dentro llega a las partidas y al árbol.
    antes = _pu(conn, vista.x['b'])
    fila = next(i for i, a in enumerate(vista._acu_row_ids) if a != -1
                and vista.tbl_acu.item(i, 1).text() == 'ZZ CEMENTO')
    vista._aplicar_cambio_acu(vista._acu_row_ids[fila], 4, 20.0)
    assert _pu(conn, vista.x['b']) > antes
    nodo = vista._id_to_item[vista.x['b']]
    assert nodo.text(4).replace(',', '') == f"{_pu(conn, vista.x['b']):.2f}"
    vista._volver_de_subpartida()
    assert vista._partida_actual_id == vista.x['a'] and vista._btn_volver_sub.isHidden()


def test_metrados_vuelve_a_la_partida(vista):
    vista._abrir_subpartida(vista.x['sub'])
    vista.tabs.setCurrentIndex(2)
    assert vista._partida_actual_id == vista.x['a']


def test_duplicar_partida_conserva_el_vinculo(vista, conn, monkeypatch):  # noqa: F811
    import views.partida_form_dialog as F

    class _Dlg:
        def __init__(self, *a, **k): pass
        def exec(self): return 1
    monkeypatch.setattr(F, 'PartidaFormDialog', _Dlg)
    vista._duplicar_partida(vista.x['a'])
    assert SP.listar(conn, vista.x['pid'])[0]['n_usos'] == 3
    nuevo = vista._partida_actual_id
    assert nuevo not in (vista.x['a'], vista.x['b'])
    assert d._recalcular_pu(conn, nuevo) == _pu(conn, vista.x['a'])


def test_copiar_y_pegar_insumos_del_acu(vista, conn, monkeypatch):  # noqa: F811
    vista.tbl_acu.selectAll()
    vista._copiar_acu_seleccionados()
    p = _partida(conn, vista.x['pid'], '03', 'ZZ NUEVA', 'm2', 1)
    conn.commit()
    vista.recargar_partidas()
    vista.cargar_acu(p)
    vista._pegar_acu()
    assert len(vista._acu_subs) == 1
    assert _pu(conn, p) == _pu(conn, vista.x['a'])
    # Dentro de otra sub-partida no entra, y se avisa.
    avisos = []
    monkeypatch.setattr(QMessageBox, 'information',
                        staticmethod(lambda *a, **k: avisos.append(a[2])))
    s2 = SP.crear(conn, vista.x['pid'], 'ZZ OTRA', 'm3')
    conn.commit()
    vista.cargar_acu(s2)
    vista._pegar_acu()
    assert avisos and vista._acu_subs == {}
    assert not SP.contiene_subpartidas(conn, s2)


def test_guardar_en_biblioteca_la_aplana(vista, conn, monkeypatch):  # noqa: F811
    import views.guardar_biblioteca_dialog as G

    class _Dlg:
        modo, grupo = 'nuevo', 'ZZ'
        def __init__(self, *a, **k): pass
        def exec(self):
            from PySide6.QtWidgets import QDialog
            return QDialog.Accepted
    monkeypatch.setattr(G, 'GuardarBibliotecaDialog', _Dlg)
    monkeypatch.setattr(QMessageBox, 'information', staticmethod(lambda *a, **k: None))
    vista._guardar_en_biblioteca()
    filas = conn.execute(
        "SELECT r.descripcion, r.tipo, b.precio FROM biblioteca_acu_items b"
        " JOIN recursos r ON r.id=b.recurso_id JOIN biblioteca_cu c ON c.id=b.cu_id"
        " WHERE c.grupo='ZZ'").fetchall()
    assert ('ZZ MORTERO 1:4', 'SC', _pu(conn, vista.x['sub'])) in [tuple(f) for f in filas]


def test_pestana_crear_agregar_y_un_nivel(vista, conn):             # noqa: F811
    from views.recurso_selector_dialog import RecursoSelectorDialog
    from views.subpartidas_tab import FichaSubpartidaDialog
    f = FichaSubpartidaDialog(vista.x['pid'])
    f.inp_desc.setText('ZZ Mortero 1:4')
    f.inp_und.setText('m3')
    f._guardar()
    assert f.lbl_error.text() and f.sub_id is None      # repetida
    f.inp_desc.setText('ZZ CONCRETO')
    f._guardar()
    assert SP.es_subpartida(conn, f.sub_id)
    dlg = RecursoSelectorDialog(vista.x['b'], {}, parent=vista)
    _VIVAS.append(dlg)
    assert not any(dlg.tbl.item(r, 1).text() == SP.CODIGO_RECURSO
                   for r in range(dlg.tbl.rowCount()))
    t = dlg.tab_subs
    dlg.tabs.setCurrentWidget(t)
    t.tbl.clearSelection()
    t.tbl.setCurrentCell(-1, -1)
    assert t.agregar()                                  # nada elegido
    t.cargar(f.sub_id)
    t.inp_cant.setText('0,5')
    dlg._agregar()
    assert conn.execute("SELECT cantidad FROM acu_items WHERE partida_id=? AND"
                        " sub_partida_id=?", (vista.x['b'], f.sub_id)).fetchone()[0] == 0.5
    # En el ACU de una sub-partida la pestaña queda apagada.
    otra = RecursoSelectorDialog(f.sub_id, {}, parent=vista)
    _VIVAS.append(otra)
    assert not otra.tab_subs.btn_nueva.isEnabled()
    otra.tab_subs.cargar(vista.x['sub'])
    assert 'no puede contener otra' in otra.tab_subs.agregar()


def test_eliminar_en_uso_pregunta(vista, conn, monkeypatch):        # noqa: F811
    from views.subpartidas_tab import SubpartidasTab
    preguntas, resp = [], [QMessageBox.No]
    monkeypatch.setattr(QMessageBox, 'warning', staticmethod(
        lambda *a, **k: preguntas.append(a[2]) or resp[0]))
    t = SubpartidasTab(vista.x['a'], vista.x['pid'])
    t.cargar(vista.x['sub'])
    t._eliminar()
    assert '01' in preguntas[0] and '02' in preguntas[0]
    assert SP.es_subpartida(conn, vista.x['sub'])
    resp[0] = QMessageBox.Yes
    antes = _pu(conn, vista.x['a'])
    t._eliminar()
    assert not SP.listar(conn, vista.x['pid']) and _pu(conn, vista.x['a']) < antes


def test_copiar_de_biblioteca_o_partida(vista, conn):               # noqa: F811
    from views.subpartidas_tab import CopiarSubpartidaDialog
    p = _partida(conn, vista.x['pid'], '03', 'ZZ SIMPLE', 'm2', 1)
    _linea(conn, p, vista.x['rec']['cem'], 1)
    conn.commit()
    dlg = CopiarSubpartidaDialog(vista.x['pid'])
    textos = [dlg.lst.item(i).text() for i in range(dlg.lst.count())]
    assert not any('MORTERO' in t for t in textos)
    dlg.inp.setText('simple')
    assert dlg.lst.count() == 1
    dlg.lst.setCurrentRow(0)
    dlg._copiar()
    assert SP.es_subpartida(conn, dlg.sub_id) and _pu(conn, dlg.sub_id) == 23.17
    dlg.cmb.setCurrentIndex(1)


def test_adquisiciones_y_gantt_bajan_a_los_insumos(vista):
    from views.cronograma_view import CronogramaView
    c = CronogramaView(vista.x['pid'], vista._proy, lambda: None)
    _VIVAS.append(c)
    c.cargar()
    assert {p['id'] for p in c._partidas} == {vista.x['a'], vista.x['b']}
