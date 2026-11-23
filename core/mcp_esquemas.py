# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Las herramientas MCP: nombre, descripción y esquema (solo stdlib).

Un solo sitio: el proceso `--mcp` los publica en `tools/list` y la app los
vuelve a comprobar con `validar()` antes de ejecutar nada. Los esquemas son
estrictos: un argumento que no está aquí se rechaza, no se ignora.
"""
from __future__ import annotations

import math


def _obj(props: dict, req: tuple = ()) -> dict:
    return {"type": "object", "properties": props, "required": list(req),
            "additionalProperties": False}


_ID = {"type": "integer", "minimum": 1}
_PID = dict(_ID, description="Id del proyecto (list_projects).")
_PART = dict(_ID, description="Id de la partida (list_items).")
_NUM = {"type": "number"}
_POS = {"type": "number", "minimum": 0}
_TXT = {"type": "string", "maxLength": 500}
_BOOL = {"type": "boolean"}
_LIMITE = {"type": "integer", "minimum": 1, "maximum": 500}
_DESDE = {"type": "integer", "minimum": 0}
_MODELO = dict(_ID, description="Id del modelo BIM (bim_models).")
_GLOBALES = {"type": "array", "minItems": 1, "maxItems": 5000,
             "items": {"type": "string", "minLength": 1, "maxLength": 64},
             "description": "GlobalId IFC."}
_FUENTE = {
    "source": {"type": "string", "enum": ["ingetrazo", "ifc"],
               "description": "De dónde sale el modelo nuevo: el IngeTrazo "
                              "abierto o un archivo IFC."},
    "path": {"type": "string", "maxLength": 4096,
             "description": "Ruta absoluta del .ifc (solo con source=ifc)."},
    "document_id": {"type": "string", "maxLength": 200,
                    "description": "Documento de IngeTrazo, si hay varios "
                                   "abiertos."},
}

REPORTES = ("presupuesto", "resumen", "gastos_generales", "insumos",
            "insumos_sub", "acus", "metrados", "especificaciones",
            "memoria_descriptiva", "presupuesto_cerrado", "cronograma",
            "cronograma_valorizado", "cronograma_adquisiciones",
            "cronograma_curva_s", "completo")
REPORTES_XLSX = ("presupuesto", "insumos", "insumos_sub", "acus", "metrados",
                 "gastos_generales", "completo")

HERRAMIENTAS: list[dict] = [
    # ── Lectura ──────────────────────────────────────────────────────────
    {"name": "list_projects", "lee": True,
     "description": "Proyectos que el usuario de la app puede ver: id, "
                    "nombre, cliente, estado, moneda. Empieza por aquí.",
     "inputSchema": _obj({"query": _TXT, "limit": _LIMITE})},
    {"name": "project_info", "lee": True,
     "description": "Datos de un proyecto, sus sub-presupuestos y qué se "
                    "puede editar en su estado actual.",
     "inputSchema": _obj({"project_id": _PID}, ("project_id",))},
    {"name": "list_items", "lee": True,
     "description": "Títulos y partidas en orden: id, ítem, descripción, "
                    "unidad, metrado, precio unitario y parcial. `gantt_row` "
                    "es su número de fila en el cronograma.",
     "inputSchema": _obj({"project_id": _PID, "query": _TXT,
                          "sub_budget_id": dict(_DESDE, description=
                              "0 = principal; sin él, todos."),
                          "offset": _DESDE, "limit": _LIMITE},
                         ("project_id",))},
    {"name": "get_acu", "lee": True,
     "description": "Análisis de costo unitario de una partida: rendimiento, "
                    "insumos con cuadrilla, cantidad, precio y parcial.",
     "inputSchema": _obj({"item_id": _PART}, ("item_id",))},
    {"name": "search_library", "lee": True,
     "description": "Busca en la biblioteca de costos unitarios (partidas "
                    "tipo con su ACU). Los `library_id` sirven para add_items "
                    "y set_acu.",
     "inputSchema": _obj({"query": dict(_TXT, minLength=2), "group": _TXT,
                          "limit": _LIMITE}, ("query",))},
    {"name": "search_resources", "lee": True,
     "description": "Busca insumos del catálogo: mano de obra (MO), "
                    "materiales (MAT), equipos (EQ), subcontratos (SC).",
     "inputSchema": _obj({"query": dict(_TXT, minLength=2),
                          "type": {"type": "string",
                                   "enum": ["MO", "MAT", "EQ", "SC"]},
                          "limit": _LIMITE}, ("query",))},
    {"name": "totals", "lee": True,
     "description": "Costo directo, pie completo y total del presupuesto, y "
                    "el total de cada título.",
     "inputSchema": _obj({"project_id": _PID}, ("project_id",))},
    {"name": "get_metrados", "lee": True,
     "description": "Planilla de metrados de una partida (normal o de acero) "
                    "y qué filas vienen de un modelo BIM.",
     "inputSchema": _obj({"item_id": _PART}, ("item_id",))},
    {"name": "validate", "lee": True,
     "description": "Revisa un proyecto sin cambiarlo: partidas sin metrado, "
                    "sin ACU o sin precio, ítems repetidos, PU que no cuadra "
                    "con su ACU, un insumo con varios precios.",
     "inputSchema": _obj({"project_id": _PID}, ("project_id",))},
    # ── Escritura ────────────────────────────────────────────────────────
    {"name": "create_project", "lee": False,
     "description": "Crea un proyecto vacío y lo abre. Lo que no se indique "
                    "toma los valores por defecto del usuario (moneda, "
                    "jornada, impuesto del país).",
     "inputSchema": _obj({
         "name": dict(_TXT, minLength=1), "client": _TXT, "location": _TXT,
         "sub_budget": _TXT, "cost_date": dict(_TXT, description="dd/mm/aaaa"),
         "term_days": {"type": "integer", "minimum": 1, "maximum": 10000},
         "currency": _TXT,
         "workday_hours": {"type": "integer", "minimum": 1, "maximum": 24},
     }, ("name",))},
    {"name": "add_items", "lee": False,
     "description": "Agrega títulos y partidas, en orden. Cada elemento lleva "
                    "`library_id` (entra con su ACU), o `title: true` con "
                    "`description`, o `description` + `unit` (partida sin "
                    "ACU). `item` fija el código («01.02»); sin él se toma el "
                    "siguiente libre bajo `parent_item`. En un proyecto que "
                    "no está en soles hay que elegir `library_prices`.",
     "inputSchema": _obj({
         "project_id": _PID,
         "sub_budget_id": dict(_DESDE, description="0 o nada = principal."),
         "library_prices": {"type": "string",
                            "enum": ["library", "structure_only"],
                            "description": "Los precios de la biblioteca son "
                                           "del Perú, en soles."},
         "items": {"type": "array", "minItems": 1, "maxItems": 300,
                   "items": _obj({
                       "library_id": _ID, "title": _BOOL,
                       "description": dict(_TXT, minLength=1),
                       "unit": {"type": "string", "maxLength": 20},
                       "item": {"type": "string", "maxLength": 60,
                                "pattern": r"^\d{2,3}(\.\d{2,3})*$"},
                       "parent_item": {"type": "string", "maxLength": 60,
                                       "pattern": r"^\d{2,3}(\.\d{2,3})*$"},
                       "quantity": _POS})},
     }, ("project_id", "items"))},
    {"name": "set_metrado", "lee": False,
     "description": "Pone el metrado de una partida: con `rows` escribe la "
                    "planilla (parcial = producto de las dimensiones "
                    "presentes) o con `quantity` un número directo. Si ya hay "
                    "planilla hace falta `replace: true`. No toca filas que "
                    "vienen de un modelo BIM.",
     "inputSchema": _obj({
         "item_id": _PART, "quantity": _POS, "replace": _BOOL,
         "rows": {"type": "array", "minItems": 1, "maxItems": 2000,
                  "items": _obj({
                      "description": _TXT, "structures": _NUM,
                      "elements": _NUM, "area": _NUM, "length": _NUM,
                      "width": _NUM, "height": _NUM})},
     }, ("item_id",))},
    {"name": "set_acu", "lee": False,
     "description": "Cambia el ACU de una partida: rendimiento, insumos del "
                    "catálogo (`resource_id`), o copia el de `library_id`. "
                    "Con cuadrilla la cantidad se deriva. Si ya hay insumos, "
                    "`mode` dice si se agregan o se reemplazan.",
     "inputSchema": _obj({
         "item_id": _PART,
         "performance": dict(_POS, description="Producción por día; 0 = no "
                                               "aplica."),
         "library_id": _ID,
         "library_prices": {"type": "string",
                            "enum": ["library", "structure_only"]},
         "mode": {"type": "string", "enum": ["append", "replace"]},
         "resources": {"type": "array", "minItems": 1, "maxItems": 200,
                       "items": _obj({
                           "resource_id": _ID, "crew": _POS,
                           "quantity": _POS}, ("resource_id",))},
     }, ("item_id",))},
    {"name": "set_price", "lee": False,
     "description": "Fija el precio de un insumo EN EL PROYECTO (en todas sus "
                    "partidas: un insumo, un precio por proyecto). No cambia "
                    "el catálogo.",
     "inputSchema": _obj({"project_id": _PID, "resource_id": _ID,
                          "price": _POS},
                         ("project_id", "resource_id", "price"))},
    {"name": "set_schedule", "lee": False,
     "description": "Duración (días), inicio y predecesoras de partidas en el "
                    "cronograma. `durations_from_quantities` calcula las "
                    "duraciones como ⌈metrado / rendimiento⌉.",
     "inputSchema": _obj({
         "project_id": _PID, "durations_from_quantities": _BOOL,
         "tasks": {"type": "array", "minItems": 1, "maxItems": 2000,
                   "items": _obj({
                       "item_id": _PART,
                       "duration": {"type": "integer", "minimum": 0,
                                    "maximum": 10000},
                       "start_day": {"type": "integer", "minimum": 1,
                                     "maximum": 100000},
                       "milestone": _BOOL,
                       "predecessors": {
                           "type": "array", "maxItems": 50,
                           "items": _obj({
                               "item_id": _PART,
                               "type": {"type": "string",
                                        "enum": ["FC", "CC", "FF", "CF"]},
                               "lag": {"type": "integer", "minimum": -1000,
                                       "maximum": 1000}}, ("item_id",))}},
                       ("item_id",))},
     }, ("project_id",))},
    {"name": "undo_last", "lee": False,
     "description": "Deshace la última escritura hecha por la IA. Si el "
                    "usuario editó ese proyecto después, se niega: "
                    "en ese caso solo él puede deshacer, desde la app.",
     "inputSchema": _obj({})},
    # ── Salida ───────────────────────────────────────────────────────────
    {"name": "export_report", "lee": True,
     "description": "Genera un reporte en PDF o Excel en la ruta absoluta "
                    "dada. No pisa un archivo existente sin "
                    "`overwrite: true`.",
     "inputSchema": _obj({
         "project_id": _PID,
         "report": {"type": "string", "enum": list(REPORTES)},
         "path": {"type": "string", "minLength": 1, "maxLength": 4096,
                  "description": "Ruta absoluta terminada en .pdf o .xlsx."},
         "overwrite": _BOOL, "cover": _BOOL},
         ("project_id", "report", "path"))},
    {"name": "screenshot", "lee": True,
     "description": "Imagen de lo que se ve en la app (o de la pestaña de un "
                    "proyecto abierto). Las pantallas de configuración y de "
                    "claves no se capturan.",
     "inputSchema": _obj({"project_id": _PID})},
    # ── Puente BIM ───────────────────────────────────────────────────────
    {"name": "bim_models", "lee": True,
     "description": "Modelos BIM registrados en el proyecto.",
     "inputSchema": _obj({"project_id": _PID}, ("project_id",))},
    {"name": "bim_diff", "lee": True,
     "description": "Compara un modelo registrado con el actual (IngeTrazo "
                    "abierto o IFC) sin escribir nada. Sin `model_id` propone "
                    "las partidas del modelo nuevo con sus GlobalId.",
     "inputSchema": _obj(dict(_FUENTE, project_id=_PID, model_id=_MODELO),
                         ("project_id", "source"))},
    {"name": "bim_apply", "lee": False,
     "description": "Con `model_id` aplica los cambios del modelo a las "
                    "partidas vinculadas (`item_ids` las limita). Sin "
                    "`model_id` registra el modelo en el proyecto. Los "
                    "metrados escritos a mano no se tocan.",
     "inputSchema": _obj(dict(_FUENTE, project_id=_PID, model_id=_MODELO,
                              item_ids={"type": "array", "minItems": 1,
                                        "maxItems": 2000, "items": _ID}),
                         ("project_id", "source"))},
    {"name": "link_elements", "lee": False,
     "description": "Vincula elementos del modelo a una partida: cada uno es "
                    "una fila de su planilla. `measure` elige la cantidad "
                    "(NetSideArea…); sin ella, el metrado del elemento. "
                    "`unlink: true` los desvincula. Los que no se pudieron "
                    "vincular salen en `skipped` con el motivo. Un metrado "
                    "escrito a mano solo se reemplaza con replace_manual.",
     "inputSchema": _obj({"item_id": _PART, "model_id": _MODELO,
                          "global_ids": _GLOBALES, "measure": _TXT,
                          "factor": {"type": "number"}, "unlink": _BOOL,
                          "replace_manual": _BOOL},
                         ("item_id", "model_id", "global_ids"))},
    {"name": "show_in_model", "lee": True,
     "description": "Selecciona en el IngeTrazo abierto los elementos de una "
                    "partida o los GlobalId dados.",
     "inputSchema": _obj({"item_id": _PART, "global_ids": _GLOBALES,
                          "document_id": _FUENTE["document_id"]})},
]

POR_NOMBRE = {h["name"]: h for h in HERRAMIENTAS}

#: Las que necesitan hablar con IngeTrazo: se piden fuera del hilo de Qt.
CON_INGETRAZO = ("bim_diff", "bim_apply", "show_in_model")


def publicas() -> list[dict]:
    """Las herramientas como las pide MCP, con `instance_id` opcional."""
    out = []
    for h in HERRAMIENTAS:
        esquema = dict(h["inputSchema"])
        esquema["properties"] = dict(
            esquema["properties"],
            instance_id={"type": "string", "maxLength": 64,
                         "description": "Solo si hay varias ventanas de "
                                        "IngePresupuestos abiertas."})
        out.append({"name": h["name"], "description": h["description"],
                    "inputSchema": esquema,
                    "annotations": {"readOnlyHint": h["lee"],
                                    "openWorldHint": False}})
    return out


class ErrorDeArgumentos(ValueError):
    pass


def validar(nombre: str, args) -> dict:
    h = POR_NOMBRE.get(nombre)
    if h is None:
        raise ErrorDeArgumentos(f"herramienta desconocida: {nombre!r}")
    _validar(args, h["inputSchema"], "argumentos")
    return args


_TIPOS = {"object": dict, "array": list, "string": str, "boolean": bool}


def _validar(v, esquema: dict, donde: str) -> None:
    tipo = esquema.get("type")
    if tipo in _TIPOS and not isinstance(v, _TIPOS[tipo]):
        raise ErrorDeArgumentos(f"{donde}: se esperaba {tipo}")
    if tipo == "integer" and type(v) is not int:
        raise ErrorDeArgumentos(f"{donde}: se esperaba un entero")
    if tipo == "number":
        if type(v) not in (int, float) or not math.isfinite(v):
            raise ErrorDeArgumentos(f"{donde}: se esperaba un número finito")
        if abs(v) > 1e15:
            raise ErrorDeArgumentos(f"{donde}: número fuera de rango")
    if tipo == "integer" and abs(v) > 2 ** 62:
        raise ErrorDeArgumentos(f"{donde}: número fuera de rango")
    if "enum" in esquema and v not in esquema["enum"]:
        raise ErrorDeArgumentos(
            f"{donde}: debe ser uno de {', '.join(map(str, esquema['enum']))}")
    if "minimum" in esquema and v < esquema["minimum"]:
        raise ErrorDeArgumentos(f"{donde}: el mínimo es {esquema['minimum']}")
    if "maximum" in esquema and v > esquema["maximum"]:
        raise ErrorDeArgumentos(f"{donde}: el máximo es {esquema['maximum']}")
    if tipo == "string":
        if len(v) < esquema.get("minLength", 0) or (
                esquema.get("minLength") and not v.strip()):
            raise ErrorDeArgumentos(f"{donde}: texto vacío o muy corto")
        if len(v) > esquema.get("maxLength", 10 ** 6):
            raise ErrorDeArgumentos(f"{donde}: texto demasiado largo")
        if "pattern" in esquema:
            import re
            if not re.fullmatch(esquema["pattern"], v):
                raise ErrorDeArgumentos(f"{donde}: formato no válido")
    if tipo == "array":
        if len(v) < esquema.get("minItems", 0):
            raise ErrorDeArgumentos(f"{donde}: lista vacía")
        if len(v) > esquema.get("maxItems", 10 ** 6):
            raise ErrorDeArgumentos(
                f"{donde}: máximo {esquema['maxItems']} elementos")
        for i, x in enumerate(v):
            _validar(x, esquema["items"], f"{donde}[{i}]")
    if tipo == "object":
        props = esquema["properties"]
        for k in v:
            if k not in props:
                raise ErrorDeArgumentos(f"{donde}: «{k}» no existe; admite "
                                        + (", ".join(props) or "nada"))
        for k in esquema["required"]:
            if k not in v:
                raise ErrorDeArgumentos(f"{donde}: falta «{k}»")
        for k, x in v.items():
            _validar(x, props[k], f"{donde}.{k}" if donde != "argumentos" else k)
