# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""MCP: editar lo existente, pie, simulación (dry_run) y prompts."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_mcp_operaciones import (PID, huella, ops, puente, partida,  # noqa: E402,F401
                                  sql)

import core.database as d                                  # noqa: E402
from core import mcp_esquemas, mcp_prompts, mcp_stdio      # noqa: E402
from core.mcp_operaciones import ErrorMCP                  # noqa: E402


@pytest.fixture
def obra(ops):                                             # noqa: F811
    """Proyecto nuevo: 01 A (01.01 x, 01.02 y), 02 B (02.01 z)."""
    pid = ops.create_project("obra", currency="Soles")["project_id"]
    r = ops.add_items(pid, [
        {"title": True, "description": "A", "item": "01"},
        {"description": "x", "unit": "m2", "item": "01.01", "quantity": 10},
        {"description": "y", "unit": "m3", "item": "01.02", "quantity": 5},
        {"title": True, "description": "B", "item": "02"},
        {"description": "z", "unit": "und", "item": "02.01", "quantity": 2},
    ])["added"]
    sql("UPDATE partidas SET precio_unitario=100 WHERE proyecto_id=? AND es_titulo=0", pid)
    ops.pid = pid
    ops.i = {x["description"]: x["item_id"] for x in r}
    return ops


def arbol(pid):
    return sql("SELECT item, descripcion, nivel FROM partidas WHERE proyecto_id=?"
               " ORDER BY item", pid)


def pred(i):
    r = sql("SELECT predecesoras FROM cronograma_partidas WHERE partida_id=?", i)
    return r[0][0] if r else ''


def test_editar_descripcion_y_unidad(obra):
    obra.edit_items(obra.pid, [{"item_id": obra.i["x"], "description": "X2", "unit": "ml"},
                               {"item_id": obra.i["A"], "description": "AA"}])
    assert sql("SELECT descripcion, unidad FROM partidas WHERE id=?",
               obra.i["x"]) == [("X2", "ml")]
    with pytest.raises(ErrorMCP, match="título"):
        obra.edit_items(obra.pid, [{"item_id": obra.i["A"], "unit": "m"}])
    ajena = partida()
    with pytest.raises(ErrorMCP, match="no es de este proyecto"):
        obra.edit_items(obra.pid, [{"item_id": ajena, "description": "q"}])


def test_mover_renumera_y_las_predecesoras_siguen_a_su_partida(obra):
    i = obra.i
    obra.set_schedule(obra.pid, tasks=[
        {"item_id": i["z"], "duration": 2, "predecessors": [
            {"item_id": i["x"], "type": "CC", "lag": 2}, {"item_id": i["y"]}]}])
    obra.move_item(obra.pid, i["x"], after_item_id=i["z"])
    assert arbol(obra.pid) == [("01", "A", 1), ("01.01", "y", 2), ("02", "B", 1),
                               ("02.01", "z", 2), ("02.02", "x", 2)]
    filas = {x["item_id"]: x["gantt_row"] for x in obra.list_items(obra.pid)["items"]}
    assert pred(i["z"]) == f"{filas[i['x']]}CC+2,{filas[i['y']]}"
    with pytest.raises(ErrorMCP, match="dentro de sí"):
        obra.move_item(obra.pid, i["A"], parent_item_id=i["A"])
    with pytest.raises(ErrorMCP, match="título"):
        obra.move_item(obra.pid, i["x"], parent_item_id=i["y"])
    obra.move_item(obra.pid, i["B"], parent_item_id=i["A"])
    assert [a[:2] for a in arbol(obra.pid)] == [
        ("01", "A"), ("01.01", "y"), ("01.02", "B"), ("01.02.01", "z"), ("01.02.02", "x")]
    obra.undo_last()
    obra.undo_last()
    assert [a[1] for a in arbol(obra.pid)] == list("AxyBz")


def test_agregar_en_medio_no_cambia_a_quien_apunta_una_predecesora(obra):
    i = obra.i
    obra.set_schedule(obra.pid, tasks=[{"item_id": i["x"], "duration": 1, "predecessors": [
        {"item_id": i["z"]}]}])
    obra.add_items(obra.pid, [{"description": "w", "unit": "m", "parent_item": "01"}])
    filas = {x["item_id"]: x["gantt_row"] for x in obra.list_items(obra.pid)["items"]}
    assert pred(i["x"]) == str(filas[i["z"]])


def test_copiar_un_titulo_con_lo_suyo(obra):
    i = obra.i
    obra.copy_item(obra.pid, i["A"], after_item_id=i["A"])
    assert [a[:2] for a in arbol(obra.pid)] == [
        ("01", "A"), ("01.01", "x"), ("01.02", "y"), ("02", "A"), ("02.01", "x"),
        ("02.02", "y"), ("03", "B"), ("03.01", "z")]
    assert obra.totals(obra.pid)["direct_cost"] == 1700 + 1500
    obra.copy_item(obra.pid, i["z"], parent_item_id=i["A"])
    assert ("01.03", "z", 2) in arbol(obra.pid)


def test_copiar_no_toca_el_portapapeles_del_usuario(obra):
    from utils import partidas_clipboard as pc
    antes = pc._CLIPBOARD
    obra.copy_item(obra.pid, obra.i["z"], parent_item_id=0)
    assert pc._CLIPBOARD is antes


def test_borrar(obra):
    i = obra.i
    obra.set_schedule(obra.pid, tasks=[{"item_id": i["z"], "duration": 1, "predecessors": [
        {"item_id": i["x"]}, {"item_id": i["y"]}]}])
    with pytest.raises(ErrorMCP, match="with_children"):
        obra.delete_items(obra.pid, [i["A"]])
    obra.delete_items(obra.pid, [i["x"]])
    assert [a[:2] for a in arbol(obra.pid)][:2] == [("01", "A"), ("01.01", "y")]
    filas = {x["item_id"]: x["gantt_row"] for x in obra.list_items(obra.pid)["items"]}
    assert pred(i["z"]) == str(filas[i["y"]])
    obra.undo_last()
    obra.delete_items(obra.pid, [i["A"]], with_children=True)
    assert arbol(obra.pid) == [("01", "B", 1), ("01.01", "z", 2)]
    obra.undo_last()
    assert len(arbol(obra.pid)) == 5


def test_no_borra_lo_que_ya_tiene_avance_de_obra(obra):
    sql("INSERT INTO valorizaciones (id, proyecto_id, numero) VALUES (88,?,1)", obra.pid)
    sql("INSERT INTO valorizacion_detalle (valorizacion_id, partida_id, "
        "metrado_periodo) VALUES (88,?,3)", obra.i["x"])
    with pytest.raises(ErrorMCP, match="avance de obra"):
        obra.delete_items(obra.pid, [obra.i["A"]], with_children=True)
    assert len(arbol(obra.pid)) == 5


def test_editar_y_quitar_insumos_del_acu(ops):              # noqa: F811
    p = partida()
    acu = ops.get_acu(p)["resources"]
    r = next(x for x in acu if x["type"] == "MAT" and not x["subitem_id"]
             and not x["unit"].startswith('%'))
    ops.edit_acu(p, changes=[{"resource_id": r["resource_id"], "quantity": 7}])
    n = next(x for x in ops.get_acu(p)["resources"]
             if x["resource_id"] == r["resource_id"])
    assert n["quantity"] == 7
    pu = ops.get_acu(p)["unit_price"]
    ops.edit_acu(p, remove=[{"resource_id": r["resource_id"]}])
    assert len(ops.get_acu(p)["resources"]) == len(acu) - 1
    assert ops.get_acu(p)["unit_price"] < pu
    with pytest.raises(ErrorMCP, match="no está en este ACU"):
        ops.edit_acu(p, remove=[{"resource_id": r["resource_id"]}])
    with pytest.raises(ErrorMCP, match="cuadrilla"):
        m = next(x for x in ops.get_acu(p)["resources"] if x["type"] == "MAT")
        ops.edit_acu(p, changes=[{"resource_id": m["resource_id"], "crew": 1}])


def test_cuadrilla_deriva_la_cantidad(ops):                 # noqa: F811
    p = sql("SELECT p.id FROM partidas p JOIN acu_items a ON a.partida_id=p.id JOIN"
            " recursos r ON r.id=a.recurso_id WHERE p.proyecto_id=? AND r.tipo='MO' AND"
            " lower(r.unidad)='hh' AND p.unidad NOT LIKE 'gl%' AND p.rendimiento>0"
            " AND a.cuadrilla>0 LIMIT 1", PID)[0][0]
    acu = ops.get_acu(p)
    r = next(x for x in acu["resources"] if x["type"] == "MO" and x["crew"] > 0)
    ops.edit_acu(p, changes=[{"resource_id": r["resource_id"], "crew": 3}])
    n = next(x for x in ops.get_acu(p)["resources"]
             if x["resource_id"] == r["resource_id"])
    assert n["crew"] == 3
    assert n["quantity"] == pytest.approx(
        3 / acu["performance"] * acu["workday_hours"], abs=1e-3)


def test_datos_del_proyecto(obra):
    obra.update_project(obra.pid, client="C", term_days=90)
    p = obra.project_info(obra.pid)
    assert (p["client"], p["term_days"]) == ("C", 90)
    with pytest.raises(ErrorMCP, match="dd/mm"):
        obra.update_project(obra.pid, cost_date="2026-01-01")


def test_pie_se_lee_se_cambia_y_se_deshace(obra):
    f = obra.get_footer(obra.pid)
    assert not f["configured"]
    lineas = [{k: x[k] for k in ("code", "name", "kind", "pct", "active")}
              for x in f["lines"]]
    for x in lineas:
        if x["code"] == "GG":
            x["pct"] = 20
    lineas.append({"name": "Contingencia", "kind": "rubro", "amount": 1000})
    r = obra.set_footer(obra.pid, lineas)
    cd = 1700
    sub = cd + cd * .20 + cd * .05
    igv = next(x["pct"] for x in f["lines"] if x["code"] == "IGV")
    assert r["total"] == pytest.approx(sub * (1 + igv / 100) + 1000, abs=.02)
    assert r["total"] == obra.totals(obra.pid)["total"]
    g = obra.get_footer(obra.pid)
    assert g["configured"] and g["lines"][-1]["amount"] == 1000
    # Un monto del usuario no se pierde por olvidarlo.
    with pytest.raises(ErrorMCP, match="monto o detalle"):
        obra.set_footer(obra.pid, [{"name": "GG", "kind": "pct_cd", "pct": 5, "code": "GG"}])
    obra.undo_last()
    assert not obra.get_footer(obra.pid)["configured"]


def test_el_detalle_de_gastos_del_usuario_no_se_pisa(obra):
    sql("INSERT INTO gastos_generales (proyecto_id, rubro, tipo, descripcion, cantidad,"
        " precio) VALUES (?,'GG','item','Residente',1,500)", obra.pid)
    with pytest.raises(ErrorMCP, match="detalle"):
        obra.set_footer(obra.pid, [{"code": "GG", "name": "GG", "kind": "rubro",
                                    "amount": 9}])
    with pytest.raises(ErrorMCP, match="no tendría efecto"):
        obra.set_footer(obra.pid, [{"code": "GG", "name": "GG", "kind": "rubro",
                                    "pct": 33}])


# ── Simulación ──────────────────────────────────────────────────────────────

def test_dry_run_mide_y_no_guarda_nada(puente):              # noqa: F811
    p = partida()
    h = huella()
    t = puente.ejecutar('totals', {"project_id": PID})
    n = len(list(puente.pila._archivos()))
    avisos = []
    puente.actividad.connect(avisos.append)
    sim = puente.ejecutar('set_metrado', {"item_id": p, "quantity": 12345,
                                          "replace": True, "dry_run": True})
    assert sim["dry_run"] and not sim["saved"]
    assert sim["total"]["before"] == t["total"] != sim["total"]["after"]
    assert huella() == h and len(list(puente.pila._archivos())) == n and not avisos
    real = puente.ejecutar('set_metrado', {"item_id": p, "quantity": 12345,
                                           "replace": True, "dry_run": False})
    assert real["quantity"] == 12345
    assert puente.ejecutar('totals', {"project_id": PID})["total"] == sim["total"]["after"]


def test_dry_run_de_cada_escritura_no_deja_rastro(obra):
    i = obra.i
    pid = obra.pid
    rid = sql("SELECT id FROM recursos WHERE tipo='MAT' LIMIT 1")[0][0]
    obra.set_acu(i["x"], resources=[{"resource_id": rid, "quantity": 2}])
    llamadas = {
        "add_items": (pid, [{"title": True, "description": "Q"}]),
        "set_metrado": (i["x"], None, 9), "set_acu": (i["x"], 5),
        "set_price": (pid, rid, 3.5), "set_schedule": (pid, None, True),
        "edit_items": (pid, [{"item_id": i["x"], "description": "o"}]),
        "move_item": (pid, i["x"], 0), "copy_item": (pid, i["x"], 0),
        "delete_items": (pid, [i["x"]]),
        "edit_acu": (i["x"], [{"resource_id": rid, "quantity": 1}]),
        "update_project": None,
        "set_footer": (pid, [{"name": "n", "kind": "pct_cd", "pct": 1}])}
    assert set(llamadas) == set(mcp_esquemas.SIMULABLES)

    def foto():
        conn = d.get_db()
        out = {t: [tuple(r) for r in conn.execute(f'SELECT * FROM "{t}"')]
               for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE "
                                        "type='table' AND name NOT LIKE '%fts%'")}
        conn.close()
        return out
    antes = foto()
    obra.simular = True
    for nombre, a in llamadas.items():
        r = (obra.update_project(pid, client="x") if a is None
             else getattr(obra, nombre)(*a))
        assert r["dry_run"], nombre
        assert foto() == antes, nombre


def test_dry_run_solo_donde_se_ofrece():
    mcp_esquemas.validar('set_price', {"project_id": 1, "resource_id": 1,
                                       "price": 1, "dry_run": True})
    for n in ('create_project', 'bim_apply', 'link_elements', 'undo_last'):
        assert 'dry_run' not in mcp_esquemas.POR_NOMBRE[n]["inputSchema"]["properties"]


def test_un_fallo_en_simulacion_tampoco_guarda(obra):
    antes = arbol(obra.pid)
    obra.simular = True
    with pytest.raises(ErrorMCP):
        obra.delete_items(obra.pid, [obra.i["A"]])
    assert arbol(obra.pid) == antes


def test_invitado_no_edita(obra):
    from models.usuario import Usuario
    obra.usuario = Usuario(id=1, rol='invitado')
    with pytest.raises(ErrorMCP, match="invitado"):
        obra.delete_items(obra.pid, [obra.i["x"]])


# ── Vista y prompts ─────────────────────────────────────────────────────────

def test_borrar_y_mover_refrescan_la_vista(puente):          # noqa: F811
    from test_mcp_operaciones import _vista
    v = _vista(puente._ventana)
    p = partida()
    v.cargar_acu(p)
    puente.ejecutar('edit_items', {"project_id": PID, "changes": [
        {"item_id": p, "description": "NUEVA DESCRIPCIÓN"}]})
    assert v._id_to_item[p].text(1) == "NUEVA DESCRIPCIÓN"
    puente.ejecutar('move_item', {"project_id": PID, "item_id": p, "parent_item_id": 0})
    assert v._id_to_item[p].parent() is None
    puente.ejecutar('delete_items', {"project_id": PID, "item_ids": [p]})
    assert p not in v._id_to_item and v._partida_actual_id is None


def test_prompts():
    r = mcp_stdio.atender({"id": 1, "method": "prompts/list"})["result"]["prompts"]
    assert {p["name"] for p in r} == set(mcp_prompts.PROMPTS)
    g = mcp_stdio.atender({"id": 2, "method": "prompts/get", "params": {
        "name": "que_cambio_modelo", "arguments": {"proyecto": "Casa {x}"}}})
    t = g["result"]["messages"][0]["content"]["text"]
    assert "Casa {x}" in t and "IngeTrazo" in t
    e = mcp_stdio.atender({"id": 3, "method": "prompts/get",
                           "params": {"name": "revisar_presupuesto"}})
    assert e["error"]["code"] == -32602
    nombres = {h["name"] for h in mcp_esquemas.HERRAMIENTAS}
    import re
    for _t, _d, _a, txt in mcp_prompts.PROMPTS.values():
        for w in re.findall(r"\b[a-z]+_[a-z_]+\b", txt):
            assert w in nombres | {"model_id", "dry_run"}, w
