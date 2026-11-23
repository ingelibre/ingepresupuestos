# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Deshacer/Rehacer: núcleo, predecesoras, vista y menú Editar."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_mcp_operaciones import (PID, _app, _girar, _vista, huella,  # noqa: E402,F401
                                  ops, partida, puente, sql)

from PySide6.QtCore import Qt                              # noqa: E402
from PySide6.QtWidgets import QMessageBox                  # noqa: E402

from core import mcp_deshacer as md                        # noqa: E402
from core.historial import Conflicto, Historial            # noqa: E402


def limpio():
    """Huella sin el estado (que el historial no toca)."""
    return huella()


# ── Núcleo ──────────────────────────────────────────────────────────────────

def test_deshacer_y_rehacer_varios_pasos(ops):              # noqa: F811
    p = partida()
    h = Historial(PID)
    fotos = [limpio()]
    for q in ("UPDATE partidas SET descripcion='UNO' WHERE id=?",
              "UPDATE partidas SET metrado=7 WHERE id=?",
              "DELETE FROM acu_items WHERE partida_id=?",
              "DELETE FROM partidas WHERE id=?"):
        sql(q, p)
        assert h.revisar()
        fotos.append(limpio())
    assert [n for n, _ in h.hechos] == ["editar partida", "metrado",
                                        "análisis de costo unitario", "eliminar partida"]
    for f in reversed(fotos[:-1]):
        h.deshacer()
        assert limpio() == f
    assert h.deshacer() is None
    for f in fotos[1:]:
        h.rehacer()
        assert limpio() == f
    assert h.rehacer() is None


def test_un_cambio_nuevo_borra_el_rehacer(ops):             # noqa: F811
    p = partida()
    h = Historial(PID)
    sql("UPDATE partidas SET metrado=7 WHERE id=?", p)
    h.revisar()
    h.deshacer()
    sql("UPDATE partidas SET metrado=8 WHERE id=?", p)
    h.revisar()
    assert not h.rehechos and len(h.hechos) == 1


def test_no_pisa_lo_que_cambio_por_fuera(ops):              # noqa: F811
    p = partida()
    h = Historial(PID)
    sql("UPDATE partidas SET metrado=7 WHERE id=?", p)
    h.revisar()
    sql("UPDATE partidas SET metrado=99 WHERE id=?", p)
    f = limpio()
    with pytest.raises(Conflicto):
        h.deshacer()
    assert limpio() == f


def test_lo_no_anotado_no_estorba_a_pasos_anteriores(ops):  # noqa: F811
    p = partida()
    h = Historial(PID)
    sql("UPDATE partidas SET metrado=7 WHERE id=?", p)
    h.revisar()
    sql("INSERT INTO pie_rubros (proyecto_id, codigo, nombre) VALUES (?,'Q','q')", PID)
    h.revisar(anotar=False)
    h.deshacer()
    assert sql("SELECT COUNT(*) FROM pie_rubros WHERE codigo='Q'") == [(1,)]


def test_deshacer_no_cambia_el_estado_del_proyecto(ops):    # noqa: F811
    h = Historial(PID)
    sql("UPDATE proyectos SET cliente='NUEVO' WHERE id=?", PID)
    h.revisar()
    sql("UPDATE proyectos SET estado='aprobado' WHERE id=?", PID)
    assert not h.revisar() and len(h.hechos) == 1
    h.deshacer()
    assert sql("SELECT estado, cliente<>'NUEVO' FROM proyectos WHERE id=?",
               PID) == [('aprobado', 1)]


def test_tope_de_pasos(ops):                                # noqa: F811
    p = partida()
    h = Historial(PID, maximo=3)
    for k in range(6):
        sql("UPDATE partidas SET metrado=? WHERE id=?", 1000 + k, p)
        h.revisar()
    assert len(h.hechos) == 3


def test_predecesoras_siguen_a_su_partida_y_se_deshacen(ops):  # noqa: F811
    from core.estructura_ops import foto_filas
    import core.database as d

    def fila(i):
        c = d.get_db()
        f = foto_filas(c, PID)[0]
        c.close()
        return next(n for n, k in f.items() if k == i)
    ps = [r[0] for r in sql("SELECT id FROM partidas_ppto WHERE proyecto_id=? AND "
                            "es_titulo=0 AND sub_presupuesto_id IS NULL ORDER BY item", PID)]
    a, b, borrada = ps[-1], ps[-2], ps[0]
    sql("DELETE FROM cronograma_partidas WHERE partida_id IN "
        "(SELECT id FROM partidas WHERE proyecto_id=?)", PID)
    sql("INSERT INTO cronograma_partidas (partida_id, predecesoras) VALUES (?,?)",
        a, f"{fila(b)}CC+2")
    h = Historial(PID)
    f0 = limpio()
    n0 = fila(b)
    sql("DELETE FROM partidas WHERE id=?", borrada)
    h.revisar()
    pred = sql("SELECT predecesoras FROM cronograma_partidas WHERE partida_id=?", a)[0][0]
    assert fila(b) == n0 - 1 and pred == f"{n0 - 1}CC+2"
    assert len(h.hechos) == 1
    h.deshacer()
    assert limpio() == f0
    h.rehacer()
    assert sql("SELECT predecesoras FROM cronograma_partidas WHERE partida_id=?",
               a) == [(pred,)]


# ── En la ventana ───────────────────────────────────────────────────────────

def girar(s=.4):
    fin = time.time() + s
    while time.time() < fin:
        _app.processEvents()
        time.sleep(.005)


@pytest.fixture
def vista(puente):                                          # noqa: F811
    v = _vista(puente._ventana)
    _girar(lambda: v._historial._h is not None)
    girar()
    v._puente = puente
    return v


def pasos(v):
    v._historial.al_dia()
    return [n for n, _ in v._historial._h.hechos]


def test_abrir_y_recorrer_las_vistas_no_crea_pasos(vista, monkeypatch):
    monkeypatch.setattr(QMessageBox, 'information', staticmethod(lambda *a, **k: None))
    assert pasos(vista) == []
    for ir in (vista._ir_metrados, vista._ir_pie, vista._ir_formula,
               vista._abrir_centro_reportes):
        ir()
        girar()
        assert pasos(vista) == [], ir.__name__
    from PySide6.QtGui import QAction
    for m in (vista._build_cronograma_menu(), vista._build_control_obra_menu()):
        for a in m.actions():
            if isinstance(a, QAction) and not a.isSeparator() and not a.menu():
                a.trigger()
                girar(.2)
                assert pasos(vista) == [], a.text()


def test_borrar_con_la_vista_deshacer_y_rehacer(vista, monkeypatch):
    v = vista
    p = partida()
    f = limpio()
    item = v._id_to_item[p].text(0)
    import core.adjuntos as adj
    from core.config import UPLOADS_DIR
    d = UPLOADS_DIR / 'especificaciones' / str(p)
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: 0)
    monkeypatch.setattr(QMessageBox, 'clickedButton', lambda self: self.buttons()[0])
    v._eliminar_partida(p, 'x')
    girar()
    assert p not in v._id_to_item and pasos(v) == ["eliminar partida"]
    assert d.exists()                       # el adjunto sigue para deshacer
    v._historial.deshacer()
    girar()
    assert v._id_to_item[p].text(0) == item and limpio() == f
    assert v._historial.nombre() is None and v._historial.nombre(True)
    v._historial.rehacer()
    girar()
    assert p not in v._id_to_item
    v._historial.deshacer()
    girar()
    assert limpio() == f and adj.limpiar_huerfanos() == 0
    d.rmdir()


def test_mover_un_nivel_es_un_paso(vista):
    v = vista
    f = limpio()
    p = next(i for i, it in v._id_to_item.items() if it.parent() is not None
             and not it.data(0, Qt.UserRole + 1))
    v.tree.setCurrentItem(v._id_to_item[p])
    v._subir_nivel()
    girar()
    assert len(pasos(v)) == 1
    v._historial.deshacer()
    girar()
    assert limpio() == f and pasos(v) == []


def test_el_menu_dice_que_se_deshace(vista):
    v = vista
    m = v._build_editar_menu()
    textos = [a.text().split('\t')[0] for a in m.actions()]
    assert 'Datos del proyecto…' in textos and 'Buscar y reemplazar…' in textos
    m.aboutToShow.emit()
    assert not m.actions()[0].isEnabled()
    sql("UPDATE partidas SET metrado=12 WHERE id=?", partida())
    m.aboutToShow.emit()
    assert m.actions()[0].text().startswith('Deshacer: ') and m.actions()[0].isEnabled()


def test_proyecto_aprobado_no_se_deshace(vista, monkeypatch):
    v = vista
    sql("UPDATE partidas SET metrado=12 WHERE id=?", partida())
    pasos(v)
    sql("UPDATE proyectos SET estado='aprobado' WHERE id=?", PID)
    f = limpio()
    avisos = []
    monkeypatch.setattr(QMessageBox, 'information',
                        staticmethod(lambda *a, **k: avisos.append(a)))
    v._historial.deshacer()
    assert limpio() == f and avisos


def test_lo_que_hace_la_ia_tambien_se_deshace_con_ctrl_z(vista):
    v = vista
    f = limpio()
    p = partida()
    v._puente.ejecutar('set_metrado', {"item_id": p, "quantity": 3, "replace": True})
    girar()
    assert len(pasos(v)) == 1
    v._historial.deshacer()
    girar()
    assert limpio() == f


def test_guardar_desde_otro_hilo_se_anota(vista):
    import threading
    p = partida()
    t = threading.Thread(target=sql, args=(
        "UPDATE partidas SET metrado=12.5 WHERE id=?", p))
    t.start()
    t.join()
    girar()
    assert len(vista._historial._h.hechos) == 1


# ── Buscar y reemplazar ─────────────────────────────────────────────────────

def test_reemplazos():
    from views.reemplazar_dialog import reemplazos as r
    fs = [{'id': 1, 'item': '01', 'descripcion': 'Muro (1.5) muro', 'unidad': 'm'},
          {'id': 2, 'item': '02', 'descripcion': 'Muros', 'unidad': 'm2'}]
    assert [x[3] for x in r(fs, 'descripcion', 'muro', r'\1')] == [r'\1 (1.5) \1', r'\1s']
    assert [x[0] for x in r(fs, 'descripcion', 'Muro', 'X', entera=True)] == [1]
    assert r(fs, 'descripcion', 'Muro', 'X', mayus=True)[0][3] == 'X (1.5) muro'
    assert [x[0] for x in r(fs, 'unidad', 'm', 'ml')] == [1]
    assert r(fs, 'descripcion', 'Muros', '') == [] and r(fs, 'unidad', '', 'x') == []
    assert r(fs, 'descripcion', '(1.5) ', '')[0][3] == 'Muro muro'


def test_reemplazar_aplica_solo_lo_marcado_y_es_un_paso(vista):
    from views.reemplazar_dialog import ReemplazarDialog
    f = limpio()
    dlg = ReemplazarDialog(PID, vista)
    dlg.ed_buscar.setText('a')
    dlg.ed_poner.setText('@')
    n = dlg.lista.topLevelItemCount()
    assert n > 2
    dlg.lista.topLevelItem(0).setCheckState(0, Qt.Unchecked)
    dlg._aplicar()
    girar()
    assert len(pasos(vista)) == 1
    assert sql("SELECT COUNT(*) FROM partidas WHERE proyecto_id=? AND descripcion "
               "LIKE '%@%'", PID) == [(n - 1,)]
    vista._historial.deshacer()
    assert limpio() == f


def test_menu_complementos_se_llena_al_abrir(vista, monkeypatch):
    import views.complementos_menu as cm
    from PySide6.QtWidgets import QMenu
    m = vista._build_complementos_menu()
    m.aboutToShow.emit()
    assert [a.text() for a in m.actions()] == ['Administrar complementos…']
    hecho = []
    monkeypatch.setattr(cm, 'ejecutar_accion',
                        lambda p, v, c, r, pid: hecho.append((c.nombre, pid)))

    class C:
        registros = [1]

        def __init__(self, nombre):
            self.nombre = nombre

        def de(self, tipo):
            from types import SimpleNamespace as N
            return [N(titulo='Hola', extra={'ayuda': ''})] if tipo == 'accion' else []
    monkeypatch.setattr(cm.cargador, 'cargados', lambda: [C('Uno'), C('Dos')])
    for _ in range(3):
        m.aboutToShow.emit()
        girar(.05)
    import gc
    from PySide6.QtCore import QEvent
    _app.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()
    assert [a.text() for a in m.actions() if not a.isSeparator()] == [
        'Uno', 'Dos', 'Administrar complementos…']
    subs = m.findChildren(QMenu)
    assert len(subs) == 2
    subs[1].actions()[0].trigger()
    assert hecho == [('Dos', PID)]
    monkeypatch.setattr(cm.cargador, 'cargados', lambda: [C('Uno')])
    m.aboutToShow.emit()
    girar(.05)
    m.actions()[0].trigger()
    assert hecho[-1] == ('Uno', PID)


def test_tema_del_proyecto_se_deshace(ops):                 # noqa: F811
    h = Historial(PID)
    sql("UPDATE proyectos SET tema_reporte='z' WHERE id=?", PID)
    assert h.revisar()
    h.deshacer()
    assert (sql("SELECT tema_reporte FROM proyectos WHERE id=?", PID)[0][0] or '') != 'z'
