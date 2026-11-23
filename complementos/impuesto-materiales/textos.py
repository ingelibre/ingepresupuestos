# SPDX-License-Identifier: GPL-3.0-or-later
"""Textos en inglés y portugués; el español es la clave."""
from ingepresupuestos import api

TEXTOS = {'en': {'Tasa del impuesto sobre materiales…': 'Materials tax rate…',
        'Impuesto sobre materiales': 'Tax on materials',
        'No altera precios ni totales': 'Does not change prices or totals',
        'Nombre': 'Name',
        'Tasa': 'Rate',
        'El presupuesto no tiene partidas.': 'The budget has no items.',
        'TOTAL': 'TOTAL',
        'Reporte informativo: no altera los precios ni el total del presupuesto.': 'For '
                                                                                   'information '
                                                                                   'only: '
                                                                                   'it '
                                                                                   'does '
                                                                                   'not '
                                                                                   'change '
                                                                                   'prices '
                                                                                   'or '
                                                                                   'the '
                                                                                   'budget '
                                                                                   'total.',
        'Ítem': 'Item',
        'Descripción': 'Description',
        'Und.': 'Unit',
        'Metrado': 'Quantity',
        'P. unitario': 'Unit price',
        'Materiales por und.': 'Materials per unit',
        'Impuesto por und.': 'Tax per unit',
        'P. unitario con impuesto': 'Unit price with tax',
        'Impuesto total': 'Total tax',
        'Materiales': 'Materials',
        'Costo directo': 'Direct cost',
        'Costo directo con el impuesto': 'Direct cost with the tax',
        'Atención: el pie del presupuesto ya cobra {que}. Sumar además este impuesto lo cobraría dos veces sobre los materiales.': 'Note: '
                                                                                                                                   'the '
                                                                                                                                   'budget '
                                                                                                                                   'footer '
                                                                                                                                   'already '
                                                                                                                                   'charges '
                                                                                                                                   '{que}. '
                                                                                                                                   'Adding '
                                                                                                                                   'this '
                                                                                                                                   'tax '
                                                                                                                                   'too '
                                                                                                                                   'would '
                                                                                                                                   'charge '
                                                                                                                                   'materials '
                                                                                                                                   'twice.'},
 'pt_BR': {'Tasa del impuesto sobre materiales…': 'Alíquota do imposto sobre '
                                                  'materiais…',
           'Impuesto sobre materiales': 'Imposto sobre materiais',
           'No altera precios ni totales': 'Não altera preços nem totais',
           'Nombre': 'Nome',
           'Tasa': 'Alíquota',
           'El presupuesto no tiene partidas.': 'O orçamento não tem itens.',
           'TOTAL': 'TOTAL',
           'Reporte informativo: no altera los precios ni el total del presupuesto.': 'Relatório '
                                                                                      'informativo: '
                                                                                      'não '
                                                                                      'altera '
                                                                                      'os '
                                                                                      'preços '
                                                                                      'nem '
                                                                                      'o '
                                                                                      'total '
                                                                                      'do '
                                                                                      'orçamento.',
           'Ítem': 'Item',
           'Descripción': 'Descrição',
           'Und.': 'Un.',
           'Metrado': 'Quantidade',
           'P. unitario': 'P. unitário',
           'Materiales por und.': 'Materiais por un.',
           'Impuesto por und.': 'Imposto por un.',
           'P. unitario con impuesto': 'P. unitário com imposto',
           'Impuesto total': 'Imposto total',
           'Materiales': 'Materiais',
           'Costo directo': 'Custo direto',
           'Costo directo con el impuesto': 'Custo direto com o imposto',
           'Atención: el pie del presupuesto ya cobra {que}. Sumar además este impuesto lo cobraría dos veces sobre los materiales.': 'Atenção: '
                                                                                                                                      'o '
                                                                                                                                      'rodapé '
                                                                                                                                      'do '
                                                                                                                                      'orçamento '
                                                                                                                                      'já '
                                                                                                                                      'cobra '
                                                                                                                                      '{que}. '
                                                                                                                                      'Somar '
                                                                                                                                      'também '
                                                                                                                                      'este '
                                                                                                                                      'imposto '
                                                                                                                                      'o '
                                                                                                                                      'cobraria '
                                                                                                                                      'duas '
                                                                                                                                      'vezes '
                                                                                                                                      'sobre '
                                                                                                                                      'os '
                                                                                                                                      'materiais.'}}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
