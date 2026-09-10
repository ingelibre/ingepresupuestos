# SPDX-License-Identifier: GPL-3.0-or-later
"""Elegir QUÉ presupuesto se importa de una base de Delphin.

Un amigo de Marco le pasó su base y ingePresupuestos respondía «el archivo no
contiene partidas reconocibles». El archivo estaba perfecto: 8 especialidades
con sus ACU e insumos. Lo que fallaba era que el importador hacía

    SELECT * FROM proyecto LIMIT 1

sin orden ni filtro, y el primer registro de esa base es la plantilla vacía
«Nuevo Proyecto» que Delphin crea al instalarse — costo directo 0, cero
partidas. `listar_proyectos_delphin()` ya existía desde el principio; no la
llamaba nadie.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

pytest.importorskip("PySide6")


def _base_delphin(tmp_path):
    """Una base mínima con la plantilla vacía PRIMERO, como la real."""
    ruta = tmp_path / "obra.sqlite"
    con = sqlite3.connect(ruta)
    con.executescript(
        """
        CREATE TABLE proyecto (id_proyecto TEXT PRIMARY KEY,
                               nombre_proyecto TEXT, fecha_proyecto TEXT);
        CREATE TABLE presupuesto (id_presupuesto TEXT PRIMARY KEY,
                                  nombre_presupuesto TEXT, id_proyecto TEXT,
                                  costo_directo REAL, total_presupuesto REAL);
        INSERT INTO proyecto VALUES ('PR0000000006','Nuevo Proyecto','12/06/2017');
        INSERT INTO proyecto VALUES ('PR0000000009','MEJORAMIENTO…','30/01/2026');
        INSERT INTO presupuesto VALUES ('PP0000000046','PRESUPUESTO',
                                        'PR0000000006', 0, 0);
        INSERT INTO presupuesto VALUES ('PP0000000077','ESTRUCTURAS',
                                        'PR0000000009', 2892587.87, 4298513.25);
        INSERT INTO presupuesto VALUES ('PP0000000078','ARQUITECTURA',
                                        'PR0000000009', 1607517.05, 2388841.29);
        """
    )
    con.commit()
    con.close()
    return str(ruta)


def test_la_plantilla_vacia_no_se_ofrece(tmp_path, monkeypatch):
    """Los presupuestos sin importe son restos: si hay alguno con dinero,
    los vacíos no llegan a la lista."""
    from views import importar_view

    ruta = _base_delphin(tmp_path)
    vistas = []

    class _DlgFalso:
        def __init__(self, filas, parent=None, **kw):
            vistas.append((filas, kw))
            self.ids_seleccionados = [1]

        def exec(self):
            return importar_view.QDialog.Accepted

    monkeypatch.setattr(importar_view, "_SelectPptoDialog", _DlgFalso)
    vista = importar_view.ImportarView.__new__(importar_view.ImportarView)
    vista._archivos = {"db": ruta}
    elegido = importar_view.ImportarView._elegir_presupuesto_delphin(vista)

    filas, kw = vistas[0]
    assert kw.get("seleccion_unica") is True, "aquí solo se importa uno"
    nombres = " ".join(f["nombre"] for f in filas)
    assert "ESTRUCTURAS" in nombres and "ARQUITECTURA" in nombres
    assert "Nuevo Proyecto" not in nombres, "ofreció la plantilla vacía"
    assert elegido == ("PR0000000009", "PP0000000077")


def test_cancelar_no_importa_nada(tmp_path, monkeypatch):
    from views import importar_view

    class _DlgFalso:
        def __init__(self, *a, **kw):
            self.ids_seleccionados = []

        def exec(self):
            return 0            # rechazado

    monkeypatch.setattr(importar_view, "_SelectPptoDialog", _DlgFalso)
    vista = importar_view.ImportarView.__new__(importar_view.ImportarView)
    vista._archivos = {"db": _base_delphin(tmp_path)}
    assert importar_view.ImportarView._elegir_presupuesto_delphin(vista) is None


def test_con_un_solo_presupuesto_no_pregunta(tmp_path, monkeypatch):
    from views import importar_view

    ruta = tmp_path / "una.sqlite"
    con = sqlite3.connect(ruta)
    con.executescript(
        """
        CREATE TABLE proyecto (id_proyecto TEXT PRIMARY KEY,
                               nombre_proyecto TEXT, fecha_proyecto TEXT);
        CREATE TABLE presupuesto (id_presupuesto TEXT PRIMARY KEY,
                                  nombre_presupuesto TEXT, id_proyecto TEXT,
                                  costo_directo REAL, total_presupuesto REAL);
        INSERT INTO proyecto VALUES ('PR1','Obra','01/01/2026');
        INSERT INTO presupuesto VALUES ('PP1','ÚNICO','PR1', 100.0, 118.0);
        """
    )
    con.commit(); con.close()

    def _no_llamar(*a, **kw):
        raise AssertionError("preguntó con un solo presupuesto")

    monkeypatch.setattr(importar_view, "_SelectPptoDialog", _no_llamar)
    vista = importar_view.ImportarView.__new__(importar_view.ImportarView)
    vista._archivos = {"db": str(ruta)}
    assert (importar_view.ImportarView._elegir_presupuesto_delphin(vista)
            == ("PR1", "PP1"))


REAL = "/home/sumaritux/Descargas/CHOQUEHUANCA CONTRATA 2026QQQ.sqlite"


@pytest.mark.skipif(not os.path.isfile(REAL), reason="base real no disponible")
def test_la_base_real_importa_cuando_se_le_dice_cual():
    """El caso reportado, de punta a punta."""
    from core.delphin_sqlite_importer import (import_delphin_sqlite,
                                              listar_proyectos_delphin)

    # Sin elegir: cae en la plantilla vacía y no encuentra nada.
    _info, partidas, *_ = import_delphin_sqlite(REAL)
    assert partidas == [], "la base ya no empieza por la plantilla vacía"

    proys = listar_proyectos_delphin(REAL)
    estructuras = next(p for p in proys
                       if p["nombre_presupuesto"] == "ESTRUCTURAS")
    _info, partidas, acus, recursos, _m = import_delphin_sqlite(
        REAL, estructuras["id_proyecto"], estructuras["id_presupuesto"])
    reales = [p for p in partidas if not p.get("es_titulo")]
    assert len(reales) == 95
    assert len(acus) == 95
    assert recursos


# ---- el diálogo compartido no cambia para quien ya lo usaba -----------------

def _filas():
    return [
        {"id_ppto": 1, "nombre": "OBRA A", "fecha": "01/01/2026",
         "cd": 100.0, "localidad": "PUNO"},
        {"id_ppto": 2, "nombre": "OBRA B", "fecha": "02/01/2026",
         "cd": 200.0, "localidad": ""},
    ]


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_el_modo_multiple_sigue_siendo_el_de_por_defecto(qapp):
    """PowerCost (.prs) y las bases .db importan varios a la vez."""
    from PySide6.QtWidgets import QAbstractItemView
    from views.importar_view import _SelectPptoDialog

    dlg = _SelectPptoDialog(_filas(), None, origen_texto="PowerCost (.prs)")
    try:
        assert dlg.lst.selectionMode() == QAbstractItemView.ExtendedSelection
        assert dlg.btn_all.isVisibleTo(dlg), "el botón de todos debe seguir"
        assert dlg.lst.count() == 2
    finally:
        dlg.deleteLater()


def test_el_modo_unico_restringe_y_esconde_seleccionar_todos(qapp):
    from PySide6.QtWidgets import QAbstractItemView
    from views.importar_view import _SelectPptoDialog

    dlg = _SelectPptoDialog(_filas(), None, origen_texto="Delphin (.sqlite)",
                            seleccion_unica=True)
    try:
        assert dlg.lst.selectionMode() == QAbstractItemView.SingleSelection
        assert not dlg.btn_all.isVisibleTo(dlg)
        assert dlg.lst.count() == 2
    finally:
        dlg.deleteLater()
