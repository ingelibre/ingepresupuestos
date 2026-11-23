# SPDX-License-Identifier: GPL-3.0-or-later
"""Textos en inglés y portugués; el español es la clave."""
from ingepresupuestos import api

TEXTOS = {'en': {'Presupuesto n.º': 'Budget No.',
        'Fecha': 'Date',
        'Contacto': 'Contact',
        'Descripción': 'Description',
        'Datos de la primera página…': 'First-page data…',
        'Datos de la primera página': 'First-page data',
        'Presupuesto con datos del proyecto': 'Budget with project data',
        'El cliente, la ubicación y el plazo salen de los datos del proyecto. Lo que dejes vacío no se imprime.': 'Client, '
                                                                                                                  'location '
                                                                                                                  'and '
                                                                                                                  'duration '
                                                                                                                  'come '
                                                                                                                  'from '
                                                                                                                  'the '
                                                                                                                  'project '
                                                                                                                  'data. '
                                                                                                                  'Anything '
                                                                                                                  'left '
                                                                                                                  'empty '
                                                                                                                  'is '
                                                                                                                  'not '
                                                                                                                  'printed.',
        'Proyecto': 'Project',
        'Cliente': 'Client',
        'Ubicación': 'Location',
        'Costos al': 'Costs as of',
        'Plazo': 'Duration',
        '{n} días': '{n} days',
        'Moneda': 'Currency',
        'El presupuesto no tiene partidas.': 'The budget has no items.',
        'Presupuesto': 'Budget',
        'PRESUPUESTO TOTAL': 'TOTAL BUDGET',
        'COSTO DIRECTO': 'DIRECT COST',
        'Datos del proyecto': 'Project data',
        'Ítem': 'Item',
        'Und.': 'Unit',
        'Metrado': 'Quantity',
        'P. unitario': 'Unit price',
        'Parcial': 'Amount'},
 'pt_BR': {'Presupuesto n.º': 'Orçamento n.º',
           'Fecha': 'Data',
           'Contacto': 'Contato',
           'Descripción': 'Descrição',
           'Datos de la primera página…': 'Dados da primeira página…',
           'Datos de la primera página': 'Dados da primeira página',
           'Presupuesto con datos del proyecto': 'Orçamento com dados do projeto',
           'El cliente, la ubicación y el plazo salen de los datos del proyecto. Lo que dejes vacío no se imprime.': 'O '
                                                                                                                     'cliente, '
                                                                                                                     'a '
                                                                                                                     'localização '
                                                                                                                     'e '
                                                                                                                     'o '
                                                                                                                     'prazo '
                                                                                                                     'vêm '
                                                                                                                     'dos '
                                                                                                                     'dados '
                                                                                                                     'do '
                                                                                                                     'projeto. '
                                                                                                                     'O '
                                                                                                                     'que '
                                                                                                                     'ficar '
                                                                                                                     'vazio '
                                                                                                                     'não '
                                                                                                                     'é '
                                                                                                                     'impresso.',
           'Proyecto': 'Projeto',
           'Cliente': 'Cliente',
           'Ubicación': 'Localização',
           'Costos al': 'Custos em',
           'Plazo': 'Prazo',
           '{n} días': '{n} dias',
           'Moneda': 'Moeda',
           'El presupuesto no tiene partidas.': 'O orçamento não tem itens.',
           'Presupuesto': 'Orçamento',
           'PRESUPUESTO TOTAL': 'ORÇAMENTO TOTAL',
           'COSTO DIRECTO': 'CUSTO DIRETO',
           'Datos del proyecto': 'Dados do projeto',
           'Ítem': 'Item',
           'Und.': 'Un.',
           'Metrado': 'Quantidade',
           'P. unitario': 'P. unitário',
           'Parcial': 'Parcial'}}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
