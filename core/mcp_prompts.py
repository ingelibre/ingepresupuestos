# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Pedidos listos (prompts de MCP): el cliente los ofrece en su menú «/»."""
from __future__ import annotations

_REGLAS = (" Los números los calcula IngePresupuestos: no los inventes. Antes de "
           "escribir, usa dry_run: true, enséñame qué cambia y el total antes y "
           "después, y espera mi visto bueno.")

PROMPTS = {
    "presupuestar_modelo": (
        "Presupuestar el modelo BIM",
        "Arma el presupuesto a partir del modelo abierto en IngeTrazo o de un IFC.",
        (("proyecto", "Proyecto donde va (por nombre)", True),
         ("ifc", "Ruta del .ifc; sin ella, el IngeTrazo abierto", False)),
        "Presupuesta el modelo BIM en el proyecto «{proyecto}». Origen: {ifc}. "
        "Mira qué propone bim_diff sin model_id, agrupa los elementos en "
        "partidas, busca cada una en search_library y dime cuáles no tienen "
        "equivalente. Cuando lo apruebe: bim_apply para registrar el modelo, "
        "add_items y link_elements. Lista los elementos que queden sin medir o "
        "sin vincular, y avisa que los precios de la biblioteca son "
        "referenciales del Perú."),
    "revisar_presupuesto": (
        "Revisar el presupuesto",
        "Busca errores y omisiones sin cambiar nada.",
        (("proyecto", "Proyecto (por nombre)", True),),
        "Revisa el proyecto «{proyecto}» SIN cambiar nada. Usa validate, "
        "list_items, totals, get_footer y get_acu de las partidas de mayor "
        "monto. Ordena lo que encuentres por cuánto afecta al total: metrados o "
        "precios en cero, rendimientos raros, partidas repetidas o que suelen "
        "acompañar a otras y faltan, pie incompleto. Separa lo seguro de lo que "
        "es solo una sospecha."),
    "que_cambio_modelo": (
        "¿Qué cambió en el modelo?",
        "Compara el modelo registrado con el actual y su efecto en el costo.",
        (("proyecto", "Proyecto (por nombre)", True),
         ("ifc", "Ruta del .ifc nuevo; sin ella, el IngeTrazo abierto", False)),
        "En el proyecto «{proyecto}», compara el modelo registrado (bim_models) "
        "con el actual usando bim_diff con su model_id. Origen: {ifc}. Dime qué "
        "elementos se agregaron, cambiaron o faltan, y qué partidas se mueven. "
        "No apliques nada hasta que te lo diga; entonces usa bim_apply solo con "
        "las partidas que apruebe."),
    "presupuesto_desde_descripcion": (
        "Presupuesto desde una descripción",
        "Propone partidas para una obra descrita en palabras.",
        (("obra", "Qué se va a construir, con sus medidas", True),),
        "Arma un presupuesto para: {obra}. Propón títulos y partidas, busca cada "
        "una en search_library y muéstrame la lista. Las medidas que no te di, "
        "pregúntalas: no las supongas. Cuando lo apruebe: create_project, "
        "add_items, set_metrado y set_footer."),
    "redactar_especificaciones": (
        "Redactar especificaciones técnicas",
        "Escribe las especificaciones de las partidas que no las tienen.",
        (("proyecto", "Proyecto (por nombre)", True),),
        "En el proyecto «{proyecto}», mira con get_specs qué partidas no tienen "
        "especificación. Usa project_info, get_memoria y, de cada partida, "
        "get_acu: los materiales, equipos y mano de obra del texto deben ser los "
        "de su análisis. Secciones: descripción, materiales, proceso "
        "constructivo, control de calidad, medición y forma de pago. Cita solo "
        "normas de las que estés seguro y marca las que yo deba verificar. "
        "Enséñame tres primero; tras mi visto bueno, sigue por grupos con "
        "set_specs. No toques las que ya tienen texto."),
    "armar_formula": (
        "Armar la fórmula polinómica",
        "Propone los monomios con sus índices y coeficientes.",
        (("proyecto", "Proyecto (por nombre)", True),),
        "Arma la fórmula polinómica del proyecto «{proyecto}». Mira get_formula, "
        "usa set_formula con preview: true y explícame cada monomio, sus "
        "advertencias y los insumos sin índice. Guárdala solo cuando lo apruebe."),
}


def publicos() -> list[dict]:
    return [{"name": n, "title": t, "description": d,
             "arguments": [{"name": a, "description": x, "required": r}
                           for a, x, r in args]}
            for n, (t, d, args, _txt) in PROMPTS.items()]


def obtener(nombre, argumentos) -> dict:
    if nombre not in PROMPTS:
        raise ValueError(f"pedido desconocido: {nombre!r}")
    _t, desc, args, txt = PROMPTS[nombre]
    dados = argumentos if isinstance(argumentos, dict) else {}
    valores = {}
    for a, _x, req in args:
        v = str(dados.get(a) or '').strip()[:2000]
        if req and not v:
            raise ValueError(f"falta «{a}»")
        valores[a] = v or "el IngeTrazo abierto (source=ingetrazo)"
    return {"description": desc, "messages": [{"role": "user", "content": {
        "type": "text", "text": txt.format(**valores) + (
            "" if nombre == "revisar_presupuesto" else _REGLAS)}}]}
