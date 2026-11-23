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
        "Ítem": "Item",
        "Cantidad": "Quantity",
        "Parcial": "Amount",
        "COSTO DIRECTO": "DIRECT COST",
        "El resto del subcontrato va a mano de obra. Sin repartir, quedan en su propia columna.": "The rest of the subcontract goes to labor. If not split, they keep their own column.",
        "Los subcontratos y las partidas sin análisis no se reparten.": "Subcontracts and items without analysis are not split.",
        "Mano de obra": "Labor",
        "Materiales": "Materials",
        "Materiales y mano de obra": "Materials and labor",
        "Parcial = materiales + mano de obra. La mano de obra incluye los equipos.": "Amount = materials + labor. Labor includes equipment.",
        "Repartir los subcontratos": "Split the subcontracts",
        "Reparto de subcontratos": "Subcontract split",
        "Reparto de subcontratos…": "Subcontract split…",
        "Subcontratos repartidos: {a} materiales y {b} mano de obra.": "Subcontracts split: {a} materials and {b} labor.",
        "Subcontratos y otros": "Subcontracts and other",
        "Total": "Total",
        "Parte de materiales (general)": "Materials share (general)",
        "Porcentaje propio de un subcontrato": "A subcontract's own percentage",
        "Subcontrato": "Subcontract",
        "% materiales": "% materials",
        "Vacío = el general": "Empty = the general one",
        "«{x}» no es un porcentaje de 0 a 100.": "«{x}» is not a percentage from 0 to 100.",
        "«{x}» está dos veces.": "«{x}» appears twice.",
        "Subcontratos repartidos con más de un porcentaje de materiales (el resto es mano de obra): {que}.": "Subcontracts split with more than one materials percentage (the rest is labor): {que}."
    },
    "pt_BR": {
        "No altera precios ni totales": "Não altera preços nem totais",
        "El presupuesto no tiene partidas.": "O orçamento não tem itens.",
        "Reporte informativo: no altera los precios ni el total del presupuesto.": "Relatório informativo: não altera os preços nem o total do orçamento.",
        "Descripción": "Descrição",
        "Und.": "Un.",
        "Ítem": "Item",
        "Cantidad": "Quantidade",
        "Parcial": "Parcial",
        "COSTO DIRECTO": "CUSTO DIRETO",
        "El resto del subcontrato va a mano de obra. Sin repartir, quedan en su propia columna.": "O restante do subcontrato vai para mão de obra. Sem dividir, ficam em sua própria coluna.",
        "Los subcontratos y las partidas sin análisis no se reparten.": "Os subcontratos e os itens sem composição não são divididos.",
        "Mano de obra": "Mão de obra",
        "Materiales": "Materiais",
        "Materiales y mano de obra": "Materiais e mão de obra",
        "Parcial = materiales + mano de obra. La mano de obra incluye los equipos.": "Parcial = materiais + mão de obra. A mão de obra inclui os equipamentos.",
        "Repartir los subcontratos": "Dividir os subcontratos",
        "Reparto de subcontratos": "Divisão de subcontratos",
        "Reparto de subcontratos…": "Divisão de subcontratos…",
        "Subcontratos repartidos: {a} materiales y {b} mano de obra.": "Subcontratos divididos: {a} materiais e {b} mão de obra.",
        "Subcontratos y otros": "Subcontratos e outros",
        "Total": "Total",
        "Parte de materiales (general)": "Parte de materiais (geral)",
        "Porcentaje propio de un subcontrato": "Percentual próprio de um subcontrato",
        "Subcontrato": "Subcontrato",
        "% materiales": "% materiais",
        "Vacío = el general": "Vazio = o geral",
        "«{x}» no es un porcentaje de 0 a 100.": "«{x}» não é um percentual de 0 a 100.",
        "«{x}» está dos veces.": "«{x}» está duas vezes.",
        "Subcontratos repartidos con más de un porcentaje de materiales (el resto es mano de obra): {que}.": "Subcontratos divididos com mais de um percentual de materiais (o resto é mão de obra): {que}."
    }
}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
