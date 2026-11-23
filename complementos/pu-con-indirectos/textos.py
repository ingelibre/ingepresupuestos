# SPDX-License-Identifier: GPL-3.0-or-later
"""Textos en inglés y portugués; el español es la clave."""
from ingepresupuestos import api

TEXTOS = {
    "en": {
        "No cambia el total del presupuesto": "Does not change the budget total",
        "Descripción": "Description",
        "Und.": "Unit",
        "Ítem": "Item",
        "Parcial": "Amount",
        "P. unitario": "Unit price",
        "Subtotal": "Subtotal",
        "Ajuste por redondeo de los precios": "Price rounding adjustment",
        "Aparte: {que}.": "Separately: {que}.",
        "Cada precio unitario lleva su parte de todas las líneas del pie. El impuesto puede quedar aparte, al final.": "Each unit price carries its share of every footer line. The tax can be left separate, at the end.",
        "El presupuesto no tiene costo directo.": "The budget has no direct cost.",
        "Este reporte no cambia el presupuesto: el total es el mismo.": "This report does not change the budget: the total is the same.",
        "Incluir también el impuesto en los precios": "Include the tax in the prices as well",
        "Los precios unitarios incluyen: {que}.": "Unit prices include: {que}.",
        "Metrado": "Quantity",
        "PRESUPUESTO TOTAL": "TOTAL BUDGET",
        "Precios con indirectos": "Prices with overhead",
        "Precios con indirectos: opciones…": "Prices with overhead: options…",
        "Presupuesto": "Budget",
        "Presupuesto con indirectos en los precios": "Budget with overhead in the prices",
        "solo el costo directo": "direct cost only"
    },
    "pt_BR": {
        "No cambia el total del presupuesto": "Não muda o total do orçamento",
        "Descripción": "Descrição",
        "Und.": "Un.",
        "Ítem": "Item",
        "Parcial": "Parcial",
        "P. unitario": "P. unitário",
        "Subtotal": "Subtotal",
        "Ajuste por redondeo de los precios": "Ajuste de arredondamento dos preços",
        "Aparte: {que}.": "À parte: {que}.",
        "Cada precio unitario lleva su parte de todas las líneas del pie. El impuesto puede quedar aparte, al final.": "Cada preço unitário leva sua parte de todas as linhas do fechamento. O imposto pode ficar à parte, no final.",
        "El presupuesto no tiene costo directo.": "O orçamento não tem custo direto.",
        "Este reporte no cambia el presupuesto: el total es el mismo.": "Este relatório não muda o orçamento: o total é o mesmo.",
        "Incluir también el impuesto en los precios": "Incluir também o imposto nos preços",
        "Los precios unitarios incluyen: {que}.": "Os preços unitários incluem: {que}.",
        "Metrado": "Quantidade",
        "PRESUPUESTO TOTAL": "ORÇAMENTO TOTAL",
        "Precios con indirectos": "Preços com indiretos",
        "Precios con indirectos: opciones…": "Preços com indiretos: opções…",
        "Presupuesto": "Orçamento",
        "Presupuesto con indirectos en los precios": "Orçamento com indiretos nos preços",
        "solo el costo directo": "só o custo direto"
    }
}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
