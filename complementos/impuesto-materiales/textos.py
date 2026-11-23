# SPDX-License-Identifier: GPL-3.0-or-later
"""Textos en inglés y portugués; el español es la clave."""
from ingepresupuestos import api

TEXTOS = {'en': {'Tasa del impuesto sobre materiales…': 'Materials tax rate…',
        'Impuesto sobre materiales': 'Tax on materials',
        'No altera precios ni totales': 'Does not change prices or totals',
        'Nombre': 'Name',
        'Tasa': 'Rate'},
 'pt_BR': {'Tasa del impuesto sobre materiales…': 'Alíquota do imposto sobre '
                                                  'materiais…',
           'Impuesto sobre materiales': 'Imposto sobre materiais',
           'No altera precios ni totales': 'Não altera preços nem totais',
           'Nombre': 'Nome',
           'Tasa': 'Alíquota'}}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
