# SPDX-License-Identifier: GPL-3.0-or-later
"""Textos en inglés y portugués; el español es la clave."""
from ingepresupuestos import api

TEXTOS = {
    "en": {
        "No altera precios ni totales": "Does not change prices or totals",
        "El presupuesto no tiene partidas.": "The budget has no items.",
        "Reporte informativo: no altera los precios ni el total del presupuesto.": "Informative report: it does not change the prices or the budget total.",
        "Cantidad": "Quantity",
        "Parcial": "Amount",
        "Importe": "Amount",
        "Administrador / dirigido a": "Manager / addressed to",
        "Alto": "Height",
        "Ancho": "Width",
        "Base imponible": "Taxable base",
        "Capítulo": "Chapter",
        "Condiciones generales": "General conditions",
        "Código": "Code",
        "El total del presupuesto en el programa es {v}: su pie lleva otro impuesto o ninguno.": "The budget total in the program is {v}: its footer has another tax or none.",
        "Escribe antes el texto en Complementos → Presupuesto y mediciones: datos e IVA.": "First write the text in Add-ons → Bill of quantities: data and VAT.",
        "Fecha": "Date",
        "IVA": "VAT",
        "Largo": "Length",
        "Por ejemplo, 10 o 21": "For example, 10 or 21",
        "Precio": "Price",
        "Presupuesto y mediciones": "Bill of quantities",
        "Presupuesto y mediciones: datos e IVA…": "Bill of quantities: data and VAT…",
        "Proyecto": "Project",
        "Resumen": "Summary",
        "Resumen por capítulos": "Summary by chapter",
        "Si la situación queda vacía se usa la ubicación del proyecto.": "If the location is left empty, the project location is used.",
        "Situación": "Location",
        "TOTAL CON IVA": "TOTAL WITH VAT",
        "Total de capítulos": "Chapters total",
        "Uds.": "No."
    },
    "pt_BR": {
        "No altera precios ni totales": "Não altera preços nem totais",
        "El presupuesto no tiene partidas.": "O orçamento não tem itens.",
        "Reporte informativo: no altera los precios ni el total del presupuesto.": "Relatório informativo: não altera os preços nem o total do orçamento.",
        "Cantidad": "Quantidade",
        "Parcial": "Parcial",
        "Importe": "Valor",
        "Administrador / dirigido a": "Administrador / dirigido a",
        "Alto": "Altura",
        "Ancho": "Largura",
        "Base imponible": "Base tributável",
        "Capítulo": "Capítulo",
        "Condiciones generales": "Condições gerais",
        "Código": "Código",
        "El total del presupuesto en el programa es {v}: su pie lleva otro impuesto o ninguno.": "O total do orçamento no programa é {v}: seu fechamento leva outro imposto ou nenhum.",
        "Escribe antes el texto en Complementos → Presupuesto y mediciones: datos e IVA.": "Escreva antes o texto em Complementos → Orçamento e medições: dados e IVA.",
        "Fecha": "Data",
        "IVA": "IVA",
        "Largo": "Comprimento",
        "Por ejemplo, 10 o 21": "Por exemplo, 10 ou 21",
        "Precio": "Preço",
        "Presupuesto y mediciones": "Orçamento e medições",
        "Presupuesto y mediciones: datos e IVA…": "Orçamento e medições: dados e IVA…",
        "Proyecto": "Projeto",
        "Resumen": "Resumo",
        "Resumen por capítulos": "Resumo por capítulos",
        "Si la situación queda vacía se usa la ubicación del proyecto.": "Se a localização ficar vazia, usa-se a do projeto.",
        "Situación": "Localização",
        "TOTAL CON IVA": "TOTAL COM IVA",
        "Total de capítulos": "Total dos capítulos",
        "Uds.": "Un."
    }
}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
