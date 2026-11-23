# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""MCP + core.bim_modelo DE VERDAD: modelo de IngeTrazo → partidas → vínculo →
cambia el modelo → actualizar → deshacer."""
import copy

import pytest

from tests.test_mcp_operaciones import PID, ops, sql  # noqa: F401  (fixture)
from core.mcp_operaciones import ErrorMCP


def _muro(gid, m2):
    return {"global_id": gid, "ifc_class": "IfcWall", "name": "Muro", "type": "",
            "storey": "", "layer": "", "material": "",
            "quantities": {"NetSideArea": {"value": m2, "unit": "m2"}},
            "metrado": {"value": m2, "unit": "m2"}}


TAKE = {"schema": "inge-takeoff", "version": 1,
        "source": {"app": "IngeTrazo", "document": "Casa.igz", "namespace": "ab"},
        "elements": [_muro("1zrN7iXkLPrf0agvfmQtFO", 12.69),
                     _muro("1$yFsOwEzHS8vrvf1KYqvz", 10.0)]}
IDS = [e["global_id"] for e in TAKE["elements"]]


def _partida(ops, unidad="m2"):
    return ops.add_items(PID, [{"description": "MURO DE LADRILLO",
                                "unit": unidad}])["added"][0]["item_id"]


def test_del_modelo_al_presupuesto_y_vuelta(ops):  # noqa: F811
    prop = ops.bim_diff(PID, 'ingetrazo', _takeoff=TAKE)["proposals"]
    assert prop[0]["metrado"] == pytest.approx(22.69)
    part = _partida(ops)
    mid = ops.bim_apply(PID, 'ingetrazo', _takeoff=TAKE)["model_id"]
    r = ops.link_elements(part, mid, IDS)
    assert r["links"] == 2 and r["quantity"] == pytest.approx(22.69)
    assert r["skipped"] == []
    with pytest.raises(ErrorMCP):
        ops.set_metrado(part, quantity=1, replace=True)

    nuevo = copy.deepcopy(TAKE)
    for k in (nuevo["elements"][1]["quantities"]["NetSideArea"],
              nuevo["elements"][1]["metrado"]):
        k["value"] = 20.0
    d = ops.bim_diff(PID, 'ingetrazo', model_id=mid, _takeoff=nuevo)
    assert d["counts"]["cambiados"] == 1
    assert [p["partida_id"] for p in d["partidas"]] == [part]
    ops.bim_apply(PID, 'ingetrazo', model_id=mid, _takeoff=nuevo)
    met = lambda: sql("SELECT metrado FROM partidas WHERE id=?", part)[0][0]
    assert met() == pytest.approx(32.69)
    ops.undo_last()
    assert met() == pytest.approx(22.69)
    assert len(sql("SELECT 1 FROM bim_vinculos WHERE partida_id=?", part)) == 2
    assert ops.bim_diff(PID, 'ingetrazo', model_id=mid,
                        _takeoff=nuevo)["counts"]["cambiados"] == 1


def test_lo_que_no_encaja_se_dice(ops):  # noqa: F811
    part = _partida(ops, "m3")
    mid = ops.bim_apply(PID, 'ingetrazo', _takeoff=TAKE)["model_id"]
    r = ops.link_elements(part, mid, IDS)
    assert r["links"] == 0 and len(r["skipped"]) == 2


def test_una_subpartida_no_se_vincula_ni_lleva_metrado(ops):  # noqa: F811
    part = _partida(ops)
    sql("UPDATE partidas SET es_subanalisis=1 WHERE id=?", part)
    mid = ops.bim_apply(PID, 'ingetrazo', _takeoff=TAKE)["model_id"]
    with pytest.raises(ErrorMCP):
        ops.link_elements(part, mid, IDS)
    with pytest.raises(ErrorMCP):
        ops.set_metrado(part, quantity=1)
