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
    with pytest.raises(ErrorMCP, match="especificaciones"):
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


# ── Hallazgos de la revisión ─────────────────────────────────────────────────
def test_leer_valorizaciones_no_escribe_y_se_deshace(obra):
    pid = obra.pid
    sql("UPDATE proyectos SET modalidad='Contrata', estado='ejecutado' WHERE id=?", pid)
    sql("DELETE FROM formulas WHERE proyecto_id=?", pid)
    v = obra.create_valuation(pid, "2026-01-01", "2026-01-31")["valuation_id"]
    obra.list_valuations(pid), obra.get_valuation(v), obra.s_curve(pid)
    obra.set_valuation_progress(v, [{"item_id": obra.i["x"], "quantity": 1}])
    obra.undo_last()
    obra.undo_last()
    assert not obra.list_valuations(pid)["valuations"]
    assert not sql("SELECT 1 FROM formulas WHERE proyecto_id=?", pid)


def test_las_valorizaciones_van_en_orden(obra):
    estado(obra.pid, 'ejecutado')
    obra.create_valuation(obra.pid, "2026-02-01", "2026-02-28")
    with pytest.raises(ErrorMCP, match="anterior"):
        obra.create_valuation(obra.pid, "2025-12-01", "2025-12-31")


def test_forzar_deshacer_pide_lo_que_de_verdad_cambia(obra):
    pid, i = obra.pid, obra.i
    estado(pid, 'revision')
    obra.set_specs(pid, [{"item_id": i["x"], "text": "a"}])
    sql("UPDATE partidas SET especificaciones='b' WHERE id=?", i["y"])
    with pytest.raises(ErrorMCP, match="editó después"):
        obra.undo_last()
    obra.undo_last(force=True)
    obra.set_specs(pid, [{"item_id": i["x"], "text": "a"}])
    sql("UPDATE partidas SET metrado=metrado+1 WHERE id=?", i["y"])
    with pytest.raises(ErrorMCP, match="presupuesto"):
        obra.undo_last(force=True)
    sql("UPDATE partidas SET metrado=metrado-1 WHERE id=?", i["y"])
    estado(pid, 'ejecutado')                  # no se vuelve el estado atrás
    with pytest.raises(ErrorMCP):
        obra.undo_last(force=True)


def test_forzar_no_devuelve_el_estado_del_proyecto(obra):
    obra.set_specs(obra.pid, [{"item_id": obra.i["x"], "text": "a"}])
    estado(obra.pid, 'revision')
    with pytest.raises(ErrorMCP, match="revisión|Revisión"):
        obra.undo_last(force=True)


def test_forzar_deshacer_una_valorizacion(obra):
    estado(obra.pid, 'ejecutado')
    v = obra.create_valuation(obra.pid, "2026-01-01", "2026-01-31")["valuation_id"]
    sql("UPDATE valorizaciones SET periodo_hasta='2026-01-30' WHERE id=?", v)
    obra.undo_last(force=True)
    assert not obra.list_valuations(obra.pid)["valuations"]


def test_cambiar_solo_los_periodos_respeta_los_monomios(ops):
    inc = [x["code"] for x in con_costos(ops) if x["code"] != "GU"]
    ops.set_formula(PID, monomials=[{"index_codes": inc, "symbol": "Z"}])
    g = ops.get_formula(PID)["monomials"]
    r = ops.set_formula(PID, periods={"adjust_year": 2090, "adjust_month": 9})
    assert r["periods_only"] and ops.get_formula(PID)["monomials"] == g
    assert ops.get_formula(PID)["periods"]["adjust_month"] == 9
    with pytest.raises(ErrorMCP, match="área"):
        ops.set_formula(PID, periods={"area": "99"})
    with pytest.raises(ErrorMCP, match="anterior"):
        ops.set_formula(PID, periods={"adjust_year": 1990})


@pytest.mark.parametrize("fid", [None, 999999])
def test_monomios_sin_formula_no_se_pisan_ni_se_duplican(ops, fid):
    con_costos(ops)
    sql("DELETE FROM formulas WHERE proyecto_id=?", PID)
    sql("INSERT INTO formula_monomios (proyecto_id, formula_id, orden, simbolo, "
        "descripcion, indice_inei, coeficiente) VALUES (?,?,0,'V','v','47',1)", PID, fid)
    assert ops.get_formula(PID)["monomials"][0]["symbol"] == "V"
    with pytest.raises(ErrorMCP, match="replace"):
        ops.set_formula(PID)
    ops.set_formula(PID, replace=True)
    assert abs(sql("SELECT SUM(coeficiente) FROM formula_monomios WHERE "
                   "proyecto_id=?", PID)[0][0] - 1) < 1e-9


def test_insumos_sin_indice(ops):
    con_costos(ops)
    sql("UPDATE recursos SET indice_inei='' WHERE tipo='MAT'")
    r = ops.get_formula(PID)["resources_without_index"]
    assert r and r[0]["amount"] >= r[-1]["amount"]


def test_textos_raros(obra, tmp_path):
    pid, i = obra.pid, obra.i["x"]
    obra.set_specs(pid, [{"item_id": i, "text": "a\x0bb\x00c"}])
    obra.export_report(pid, "especificaciones", str(tmp_path / "e.docx"))
    for guardado in ("<html><head><meta charset='x'><body><p>hola</p>",
                     "<style>p{}<p>hola</p>", "Resistencia <p 5 MPa"):
        sql("UPDATE partidas SET especificaciones=? WHERE id=?", guardado, i)
        with pytest.raises(ErrorMCP, match="replace"):
            obra.set_specs(pid, [{"item_id": i, "text": "b"}])
    assert a_texto("Resistencia <p 5 MPa") == ("Resistencia <p 5 MPa", 0)
    assert obra.get_specs(pid, only_missing=True)["total"] == 2


def test_participacion_cero(obra):
    obra.set_footer(obra.pid, [
        {"code": "GG", "name": "GG", "kind": "rubro", "pct": 10}])
    with pytest.raises(ErrorMCP, match="participation"):
        obra.set_overhead(obra.pid, [{"description": "a", "quantity": 2, "price": 1,
                                      "participation_pct": 0}])


def test_exportar_la_formula(ops, tmp_path):
    con_costos(ops)
    ops.set_formula(PID)
    for ext in ("pdf", "xlsx"):
        ops.export_report(PID, "formula_polinomica", str(tmp_path / f"f.{ext}"))


def test_la_vista_de_la_formula(ops):
    """Abrirla no escribe; editar una celda la marca sin guardar."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views.formula_view import FormulaView
    con_costos(ops)
    sql("DELETE FROM formula_periodos WHERE proyecto_id=?", PID)
    ops.set_formula(PID)
    h = huella()
    v = FormulaView(PID)
    v.cargar()
    assert huella() == h and not v._sucio
    v.tbl.item(0, 2).setText("MI TEXTO")
    assert v._sucio
    v.deleteLater()
