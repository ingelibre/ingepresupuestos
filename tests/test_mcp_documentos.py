# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""MCP 3.2.2: especificaciones, memoria, detalle de gastos, fórmula
polinómica, cronograma, curva S, valorizaciones y Word."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_mcp_operaciones import (PID, huella, ops, partida, puente,  # noqa: E402,F401
                                  sql)
from test_mcp_editar import obra                           # noqa: E402,F401

from core import formula_polinomica as fp                  # noqa: E402
from core.mcp_operaciones import ErrorMCP                  # noqa: E402
from core.textos_spec import a_html, a_texto               # noqa: E402

TXT = "1. DESCRIPCIÓN\nVaciado con f'c < 210 & curado.\n\n2. MATERIALES\n- Cemento"


def estado(pid, e):
    sql("UPDATE proyectos SET estado=? WHERE id=?", e, pid)


def test_texto_a_html_y_vuelta():
    assert a_texto(a_html(TXT)) == (TXT, 0)
    qt = ('<!DOCTYPE HTML><html><head><style>p{x:1}</style></head><body>'
          '<p>uno<br/>dos</p><img src="data:a"/></body></html>')
    assert a_texto(qt) == ("uno\ndos\n[imagen]", 1)
    assert a_texto(None) == ("", 0) and a_texto(" plano ") == ("plano", 0)


def test_especificaciones_escribir_leer_y_deshacer(obra):
    i, pid = obra.i, obra.pid
    h = obra.get_specs(pid)
    assert (h["total"], h["without_spec"]) == (3, 3) and "text" not in h["items"][0]
    obra.set_specs(pid, [{"item_id": i["x"], "text": TXT}])
    assert obra.get_specs(pid, [i["x"]])["items"][0]["text"] == TXT
    assert obra.get_specs(pid)["without_spec"] == 2
    with pytest.raises(ErrorMCP, match="replace"):
        obra.set_specs(pid, [{"item_id": i["y"], "text": "a"},
                             {"item_id": i["x"], "text": "b"}])
    assert obra.get_specs(pid)["without_spec"] == 2        # nada a medias
    with pytest.raises(ErrorMCP, match="título"):
        obra.set_specs(pid, [{"item_id": i["A"], "text": "a"}])
    with pytest.raises(ErrorMCP, match="no es"):
        obra.set_specs(pid, [{"item_id": partida(), "text": "a"}])
    obra.undo_last()
    assert obra.get_specs(pid)["without_spec"] == 3


def test_una_especificacion_con_imagenes_no_se_pierde(obra):
    i, pid = obra.i["x"], obra.pid
    sql("UPDATE partidas SET especificaciones='<p>a<img src=\"x\"/></p>' WHERE id=?", i)
    with pytest.raises(ErrorMCP, match="discard_images"):
        obra.set_specs(pid, [{"item_id": i, "text": "b"}], replace=True)
    obra.set_specs(pid, [{"item_id": i, "text": "b"}], replace=True, discard_images=True)
    assert obra.get_specs(pid, [i])["items"][0]["text"] == "b"


def test_especificaciones_y_memoria_siguen_el_estado(obra):
    pid, i = obra.pid, obra.i
    estado(pid, 'revision')
    obra.set_specs(pid, [{"item_id": i["x"], "text": TXT}])
    obra.set_memoria(pid, TXT)
    assert obra.get_memoria(pid)["text"] == TXT
    with pytest.raises(ErrorMCP, match="replace"):
        obra.set_memoria(pid, "otra")
    with pytest.raises(ErrorMCP):
        obra.set_overhead(pid, [{"description": "a", "quantity": 1, "price": 1}])
    obra.undo_last()                       # en revisión también se deshace
    obra.undo_last()
    assert not obra.get_memoria(pid)["text"] and obra.get_specs(pid)["without_spec"] == 3
    estado(pid, 'aprobado')
    with pytest.raises(ErrorMCP, match="specs"):
        obra.set_specs(pid, [{"item_id": i["x"], "text": TXT}])


def test_detalle_de_gastos_generales(obra):
    pid = obra.pid
    filas = [{"group": True, "description": "Personal"},
             {"description": "Residente", "unit": "mes", "quantity": 3, "price": 100},
             {"description": "Maestro", "quantity": 2, "price": 50,
              "participation_pct": 50}]
    sql("DELETE FROM pie_rubros WHERE proyecto_id=?", pid)
    with pytest.raises(ErrorMCP, match="set_footer"):
        obra.set_overhead(pid, filas)
    obra.set_footer(pid, [{"code": "GG", "name": "GG", "kind": "rubro", "pct": 10},
                          {"code": "UTIL", "name": "U", "kind": "pct_cd", "pct": 5}])
    r = obra.set_overhead(pid, filas)
    assert r["amount"] == 350 and r["total"] == obra.totals(pid)["total"]
    g = obra.get_overhead(pid)
    assert g["amount"] == 350 and len(g["rows"]) == 3 and g["rows"][0]["group"]
    with pytest.raises(ErrorMCP, match="detalle"):
        obra.set_overhead(pid, filas)
    obra.set_overhead(pid, filas[:2], replace=True)
    assert obra.get_overhead(pid)["amount"] == 300
    with pytest.raises(ErrorMCP, match="porcentaje"):
        obra.set_overhead(pid, filas, code="UTIL")
    with pytest.raises(ErrorMCP, match="quantity"):
        obra.set_overhead(pid, [{"description": "x"}], replace=True)


def con_costos(ops):
    sql("UPDATE proyectos SET modalidad='Contrata' WHERE id=?", PID)
    sql("DELETE FROM formula_monomios WHERE proyecto_id=?", PID)
    sql("DELETE FROM formula_monomio_iu WHERE proyecto_id=?", PID)
    return ops.get_formula(PID)["incidences"]


def test_formula_automatica_previa_guardada_y_deshecha(ops):
    con_costos(ops)
    h = huella()
    p = ops.set_formula(PID, preview=True)
    assert not p["saved"] and p["sum"] == 1.0 and huella() == h
    s = ops.set_formula(PID)
    assert s["monomials"] == p["monomials"]
    g = ops.get_formula(PID)
    assert [m["coefficient"] for m in g["monomials"]] == [
        m["coefficient"] for m in s["monomials"]]
    with pytest.raises(ErrorMCP, match="replace"):
        ops.set_formula(PID)
    ops.undo_last()
    assert huella() == h


def test_formula_con_monomios_dados(ops):
    inc = [x["code"] for x in con_costos(ops) if x["code"] != "GU"]
    mitad = len(inc) // 2 or 1
    grupos = [{"index_codes": inc[:mitad], "symbol": "Z"}]
    with pytest.raises(ErrorMCP, match="faltan"):
        ops.set_formula(PID, monomials=grupos)
    grupos.append({"index_codes": inc[mitad:] + ["99x"]})
    with pytest.raises(ErrorMCP, match="99x"):
        ops.set_formula(PID, monomials=grupos)
    grupos[1]["index_codes"].pop()
    r = ops.set_formula(PID, monomials=grupos, periods={"base_month": 3})
    assert r["sum"] == 1.0 and r["monomials"][0]["symbol"] == "Z"
    assert fp.cargar_periodos(PID)["oferta_mes"] == 3


def test_formula_no_aplica_en_administracion_directa(ops):
    con_costos(ops)
    sql("UPDATE proyectos SET modalidad='Administración Directa' WHERE id=?", PID)
    with pytest.raises(ErrorMCP, match="directa|Directa"):
        ops.set_formula(PID)
    assert ops.get_formula(PID)["applies"] is False


def test_leer_la_formula_no_escribe(ops):
    sql("DELETE FROM formulas WHERE proyecto_id=?", PID)
    h = huella()
    ops.get_formula(PID)
    assert huella() == h


def test_cronograma_y_curva(ops):
    r = ops.get_schedule(PID, limit=5)
    assert len(r["tasks"]) == 5 < r["total"]
    for per in ("month", "week", "calendar_month"):
        assert ops.s_curve(PID, per)["rows"], per


def test_valorizaciones(obra):
    pid, i = obra.pid, obra.i
    with pytest.raises(ErrorMCP, match="ejecuci"):
        obra.create_valuation(pid, "2026-01-01", "2026-01-31")
    estado(pid, 'ejecutado')
    v = obra.create_valuation(pid, "2026-01-01", "2026-01-31")["valuation_id"]
    with pytest.raises(ErrorMCP, match="cruza"):
        obra.create_valuation(pid, "2026-01-31", "2026-02-28")
    for a, b in (("2026-02-30", "2026-03-01"), ("2026-03-02", "2026-03-01")):
        with pytest.raises(ErrorMCP):
            obra.create_valuation(pid, a, b)
    r = obra.set_valuation_progress(v, [{"item_id": i["x"], "quantity": 4}])
    assert r["current"] == 400 and not r["over_contract"]
    r = obra.set_valuation_progress(v, [{"item_id": i["y"], "quantity": 6}])
    assert r["over_contract"][0]["item_id"] == i["y"]
    g = obra.get_valuation(v, only_executed=True)
    assert [x["item_id"] for x in g["items"]] == [i["x"], i["y"]]
    obra.undo_last()
    assert obra.list_valuations(pid)["valuations"][0]["current"] == 400
    sql("UPDATE valorizaciones SET estado='cerrada' WHERE id=?", v)
    with pytest.raises(ErrorMCP, match="cerrada"):
        obra.set_valuation_progress(v, [{"item_id": i["x"], "quantity": 1}])
    sql("UPDATE valorizaciones SET estado='abierta' WHERE id=?", v)
    sql("UPDATE valorizacion_detalle SET origen='diario' WHERE valorizacion_id=?", v)
    with pytest.raises(ErrorMCP, match="cuaderno"):
        obra.set_valuation_progress(v, [{"item_id": i["x"], "quantity": 1}])


def test_no_se_ven_valorizaciones_de_otro(obra):
    estado(obra.pid, 'ejecutado')
    v = obra.create_valuation(obra.pid, "2026-01-01", "2026-01-31")["valuation_id"]
    from core.mcp_operaciones import Operaciones
    from models.usuario import Usuario
    otro = Operaciones(Usuario(id=2, rol='usuario'), obra.pila)
    sql("UPDATE proyectos SET usuario_id=1 WHERE id=?", obra.pid)
    for f in (lambda: otro.get_valuation(v), lambda: otro.get_specs(obra.pid),
              lambda: otro.get_memoria(obra.pid), lambda: otro.get_formula(obra.pid),
              lambda: otro.get_overhead(obra.pid), lambda: otro.s_curve(obra.pid),
              lambda: otro.get_schedule(obra.pid),
              lambda: otro.list_valuations(obra.pid),
              lambda: otro.set_valuation_progress(v, [])):
        with pytest.raises(ErrorMCP, match="no existe"):
            f()


def test_word(obra, tmp_path):
    from docx import Document
    obra.set_specs(obra.pid, [{"item_id": obra.i["x"], "text": TXT}])
    f = tmp_path / "e.docx"
    obra.export_report(obra.pid, "especificaciones", str(f))
    assert any("curado" in p.text for p in Document(f).paragraphs)
    with pytest.raises(ErrorMCP, match="Word"):
        obra.export_report(obra.pid, "acus", str(tmp_path / "a.docx"))
