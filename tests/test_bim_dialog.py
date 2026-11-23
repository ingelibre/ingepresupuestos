# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Diálogos BIM: vista previa, vínculos y actualización. Corre con pytest."""
import copy
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt                                        # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox     # noqa: E402

import core.database as bd                                           # noqa: E402
from core import bim_modelo as bim                                   # noqa: E402
from views import bim_dialog as bv                                   # noqa: E402

app = QApplication.instance() or QApplication([])
FX = os.path.join(os.path.dirname(__file__), 'fixtures', 'bim')
TAKEOFF = json.load(open(os.path.join(FX, 'takeoff-ejemplo.json'), encoding='utf-8'))


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, 'DB_PATH', str(tmp_path / 'bim.db'))
    bd.init_db()
    # Ningún cuadro modal debe quedarse esperando a nadie.
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes)
    for n in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, n, lambda *a, _n=n, **k: MSG.append((_n, a[2])))
    MSG.clear()


MSG: list = []


def _x(sql, *a):
    c = bd.get_db()
    r = c.execute(sql, a)
    fila, rid = r.fetchone() if r.description else None, r.lastrowid
    c.commit()
    c.close()
    return fila[0] if fila else rid


def _proyecto():
    pid = _x("INSERT INTO proyectos (nombre) VALUES ('P')")
    return pid, _x("INSERT INTO partidas (proyecto_id,item,descripcion,unidad,metrado,nivel,es_titulo) "
                   "VALUES (?,'01.01','Muro','m2',0,2,0)", pid)


def _esperar(cond):
    t = time.time()
    while not cond() and time.time() - t < 10:
        app.processEvents()
        time.sleep(.01)
    assert cond()


def _rama(arbol, texto):
    return next(arbol.topLevelItem(i) for i in range(arbol.topLevelItemCount())
                if texto in arbol.topLevelItem(i).text(0))


def test_arbol_marca_por_rama_y_por_elemento():
    m = bim.leer_takeoff(TAKEOFF)
    a = bv.ArbolElementos()
    a.cargar(m.elementos)
    assert a.marcados() == []
    muro = _rama(a, 'IfcWall')
    muro.setCheckState(0, Qt.Checked)
    assert len(a.marcados()) == 2
    piso = muro.child(0).child(0)
    piso.setExpanded(True)
    assert piso.childCount() == len(a._grupos[piso.data(0, Qt.UserRole)]['els']) > 0
    piso.child(0).setCheckState(0, Qt.Unchecked)
    assert len(a.marcados()) == 1 and muro.checkState(0) == Qt.PartiallyChecked
    a.marcar_todo(True)
    assert len(a.marcados()) == 15 and muro.checkState(0) == Qt.Checked


def test_vista_previa_avisa_y_crea_o_anade(base):
    m = bim.leer_takeoff(TAKEOFF)
    d = bv.ImportarBimDialog(m, 'x.ifc')
    avisos = [_rama(d.arbol, c).text(3) for c in ('IfcWall', 'IfcSlab')]
    assert any('sin cantidad' in (d.arbol.topLevelItem(i).text(3)) for i in range(d.arbol.topLevelItemCount())), avisos
    _rama(d.arbol, 'IfcWall').setCheckState(0, Qt.Unchecked)
    d._aceptar()
    pid = d.proyecto_id
    assert pid and not _x("SELECT COUNT(*) FROM partidas WHERE proyecto_id=? AND descripcion LIKE 'MURO%' "
                          "AND es_titulo=0", pid)
    assert bim.modelos(pid)[0]['n_elementos'] == 15      # el modelo entra completo
    n = _x("SELECT COUNT(*) FROM partidas WHERE proyecto_id=?", pid)
    d2 = bv.ImportarBimDialog(m, 'x.ifc')
    d2.cmb.setCurrentIndex(d2.cmb.findData(pid))
    d2._aceptar()
    assert d2.proyecto_id == pid and _x("SELECT COUNT(*) FROM partidas WHERE proyecto_id=?", pid) > n
    # Un proyecto que no se puede editar no se ofrece.
    _x("UPDATE proyectos SET estado='aprobado' WHERE id=?", pid)
    from core.config import puede_editar
    if not puede_editar('aprobado', 'presupuesto'):
        assert bv.ImportarBimDialog(m, 'x').cmb.findData(pid) < 0


def test_vincular_actualizar_y_desvincular(base, monkeypatch, tmp_path):
    pid, part = _proyecto()
    d = bv.ModeloBimDialog(pid, part)
    d.recibir_takeoff(TAKEOFF, 'Casa.igz')
    assert d.cambio and len(d._els) == 15 and d.partida_id == part
    _rama(d.arbol, 'IfcWall').setCheckState(0, Qt.Checked)
    d._vincular()
    assert d.tv.topLevelItemCount() == 2
    assert _x("SELECT metrado FROM partidas WHERE id=?", part) == 25.38
    d.chk_sueltos.setChecked(True)
    assert not any('IfcWall' in d.arbol.topLevelItem(i).text(0) for i in range(d.arbol.topLevelItemCount()))
    d.chk_sueltos.setChecked(False)

    # Un takeoff del mismo modelo se compara con el que ya está.
    nuevo = copy.deepcopy(TAKEOFF)
    muro = next(e for e in nuevo['elements'] if e['ifc_class'] == 'IfcWall')
    muro['metrado']['value'] = muro['quantities']['NetSideArea']['value'] = 10
    vistos = []

    def _exec(dlg):
        vistos.append(dlg)
        if len(vistos) == 1:                  # no marcar nada: no cambia nada
            dlg.it_partidas[0].setCheckState(0, Qt.Unchecked)
        dlg._aplicar()
        return dlg.result()
    monkeypatch.setattr(bv.DiferenciasDialog, 'exec', _exec)
    d.recibir_takeoff(nuevo)
    assert _x("SELECT metrado FROM partidas WHERE id=?", part) == 25.38
    ruta = tmp_path / 't.json'
    ruta.write_text(json.dumps(nuevo), encoding='utf-8')
    monkeypatch.setattr(d, '_pedir_archivo', lambda: str(ruta))
    d._actualizar()                           # por el hilo de lectura
    _esperar(lambda: len(vistos) == 2 and d._lector is None)
    assert _x("SELECT metrado FROM partidas WHERE id=?", part) == 22.69
    assert len(bim.modelos(pid)) == 1
    d.tv.selectAll()
    d._desvincular()
    assert d.tv.topLevelItemCount() == 0 and _x("SELECT metrado FROM partidas WHERE id=?", part) == 0
    d._quitar()
    assert bim.modelos(pid) == []


def test_metrado_a_mano_y_solo_lectura(base, monkeypatch):
    pid, part = _proyecto()
    _x("UPDATE partidas SET metrado=9 WHERE id=?", part)
    d = bv.ModeloBimDialog(pid, part)
    d.recibir_takeoff(TAKEOFF)
    _rama(d.arbol, 'IfcWall').setCheckState(0, Qt.Checked)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.No)
    d._vincular()
    assert _x("SELECT metrado FROM partidas WHERE id=?", part) == 9
    d._crear()
    assert _x("SELECT COUNT(*) FROM bim_vinculos") == 2 and len(bim.modelos(pid)) == 1
    lectura = bv.ModeloBimDialog(pid, part, editable=False)
    lectura.arbol.marcar_todo(True)
    assert not any(b.isEnabled() for b in (lectura.b_vincular, lectura.b_crear, lectura.b_agregar,
                                           lectura.b_actualizar, lectura.b_quitar, lectura.b_acu))


def test_archivo_malo_avisa(base, monkeypatch, tmp_path):
    pid, part = _proyecto()
    f = tmp_path / 'roto.json'
    f.write_text('{')
    d = bv.ModeloBimDialog(pid, part)
    monkeypatch.setattr(d, '_pedir_archivo', lambda: str(f))
    d._agregar()
    _esperar(lambda: d._lector is None)
    assert MSG and MSG[0][0] == 'critical' and bim.modelos(pid) == []


def test_importar_vista_abre_la_vista_previa(base, monkeypatch):
    from views.importar_view import ImportarView
    v = ImportarView()
    v._formato_id = 'ifc'
    v._archivos = {'ifc': os.path.join(FX, 'takeoff-ejemplo.ifc')}
    monkeypatch.setattr(bv.ImportarBimDialog, 'exec', lambda dlg: (dlg._aceptar(), dlg.result())[1])
    pids = []
    v.proyecto_importado.connect(pids.append)
    v._leer_bim(v._archivos['ifc'])
    _esperar(lambda: bool(pids))
    assert bim.modelos(pids[0])[0]['n_vinculos'] == 14


def test_los_dialogos_son_de_la_ventana(base):
    pid, part = _proyecto()
    for d in (bv.ModeloBimDialog(pid, part), bv.ImportarBimDialog(bim.leer_takeoff(TAKEOFF))):
        assert d.windowModality() == Qt.WindowModal and isinstance(d, QDialog)
