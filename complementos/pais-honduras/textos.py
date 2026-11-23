# SPDX-License-Identifier: GPL-3.0-or-later
"""Textos en inglés y portugués; el español es la clave."""
from ingepresupuestos import api

TEXTOS = {
    "en": {
        "No altera precios ni totales": "Does not change prices or totals",
        "El presupuesto no tiene partidas.": "The budget has no items.",
        "Reporte informativo: no altera los precios ni el total del presupuesto.": "Informative report: it does not change the prices or the budget total.",
        "Descripción": "Description",
        "Und.": "Unit",
        "Cantidad": "Quantity",
        "P. unitario": "Unit price",
        "Importe": "Amount",
        "Subtotal": "Subtotal",
        "MATERIALES": "MATERIALS",
        "MANO DE OBRA": "LABOR",
        "HERRAMIENTA Y EQUIPO": "TOOLS AND EQUIPMENT",
        "SUBCONTRATOS Y OTROS": "SUBCONTRACTS AND OTHER",
        "Ajuste de redondeo": "Rounding adjustment",
        "Análisis de precios": "Price analysis",
        "Análisis de precios sin cuadrilla": "Price analysis without crew",
        "COSTO UNITARIO": "UNIT COST",
        "Horas por jornada": "Hours per workday",
        "Mano de obra en horas o jornales": "Labor in hours or workdays",
        "Mano de obra en horas o jornales…": "Labor in hours or workdays…",
        "Mano de obra en jornales de {h} horas.": "Labor in workdays of {h} hours.",
        "Mostrar la mano de obra en jornales": "Show labor in workdays",
        "jornal": "workday"
    },
    "pt_BR": {
        "No altera precios ni totales": "Não altera preços nem totais",
        "El presupuesto no tiene partidas.": "O orçamento não tem itens.",
        "Reporte informativo: no altera los precios ni el total del presupuesto.": "Relatório informativo: não altera os preços nem o total do orçamento.",
        "Descripción": "Descrição",
        "Und.": "Un.",
        "Cantidad": "Quantidade",
        "P. unitario": "P. unitário",
        "Importe": "Valor",
        "Subtotal": "Subtotal",
        "MATERIALES": "MATERIAIS",
        "MANO DE OBRA": "MÃO DE OBRA",
        "HERRAMIENTA Y EQUIPO": "FERRAMENTAS E EQUIPAMENTOS",
        "SUBCONTRATOS Y OTROS": "SUBCONTRATOS E OUTROS",
        "Ajuste de redondeo": "Ajuste de arredondamento",
        "Análisis de precios": "Composição de preços",
        "Análisis de precios sin cuadrilla": "Composição de preços sem equipe",
        "COSTO UNITARIO": "CUSTO UNITÁRIO",
        "Horas por jornada": "Horas por jornada",
        "Mano de obra en horas o jornales": "Mão de obra em horas ou diárias",
        "Mano de obra en horas o jornales…": "Mão de obra em horas ou diárias…",
        "Mano de obra en jornales de {h} horas.": "Mão de obra em diárias de {h} horas.",
        "Mostrar la mano de obra en jornales": "Mostrar a mão de obra em diárias",
        "jornal": "diária"
    }
}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
