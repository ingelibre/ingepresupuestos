# SPDX-License-Identifier: GPL-3.0-or-later
"""Textos en inglés y portugués; el español es la clave."""
from ingepresupuestos import api

TEXTOS = {'en': {'Agregar zapatas…': 'Add footings…',
        'Metrado por dimensiones, sin precios': 'Quantities from dimensions, without '
                                                'prices',
        'Nombre': 'Name',
        'Cantidad de zapatas': 'Number of footings',
        'Largo': 'Length',
        'Ancho': 'Width',
        'Alto': 'Height',
        'Profundidad de excavación': 'Excavation depth',
        '0 = el alto de la zapata': '0 = the footing height',
        'Sobreancho de excavación por lado': 'Extra excavation per side',
        'Recubrimiento': 'Cover',
        'Varillas paralelas al largo': 'Bars parallel to the length',
        'Diámetro de esas varillas': 'Diameter of those bars',
        'Varillas paralelas al ancho': 'Bars parallel to the width',
        'Diámetro de esas varillas (ancho)': 'Diameter of those bars (width)',
        'Desperdicio de acero': 'Steel waste',
        'La profundidad de excavación es menor que el alto de la zapata.': 'The '
                                                                           'excavation '
                                                                           'depth is '
                                                                           'less than '
                                                                           'the '
                                                                           'footing '
                                                                           'height.',
        'El recubrimiento no cabe en esas dimensiones.': 'The cover does not fit those '
                                                         'dimensions.',
        'Indica al menos una varilla.': 'Enter at least one bar.',
        'Excavación': 'Excavation',
        'Concreto': 'Concrete',
        'Encofrado': 'Formwork',
        'Acero': 'Steel',
        'Peso por metro: π/4 × diámetro² × 7850 kg/m³. Largo de varilla: lado − 2 × recubrimiento.': 'Weight '
                                                                                                     'per '
                                                                                                     'meter: '
                                                                                                     'π/4 '
                                                                                                     '× '
                                                                                                     'diameter² '
                                                                                                     '× '
                                                                                                     '7850 '
                                                                                                     'kg/m³. '
                                                                                                     'Bar '
                                                                                                     'length: '
                                                                                                     'side '
                                                                                                     '− '
                                                                                                     '2 '
                                                                                                     '× '
                                                                                                     'cover.',
        'Zapatas': 'Footings',
        'ZAPATAS': 'FOOTINGS',
        'EXCAVACIÓN PARA ZAPATA': 'EXCAVATION FOR FOOTING',
        'CONCRETO EN ZAPATA': 'CONCRETE IN FOOTING',
        'ENCOFRADO Y DESENCOFRADO DE ZAPATA': 'FOOTING FORMWORK',
        'ACERO DE REFUERZO EN ZAPATA': 'REINFORCING STEEL IN FOOTING',
        'Se agregará el título {item} «{titulo}» con 4 partidas sin precio.': 'Title '
                                                                              '{item} '
                                                                              '“{titulo}” '
                                                                              'will be '
                                                                              'added '
                                                                              'with 4 '
                                                                              'unpriced '
                                                                              'items.',
        '¿Agregar?': 'Add?',
        'Solo mide zapatas rectangulares: no diseña ni verifica la estructura. No calcula ganchos, traslapes, arranques de columna, solado, relleno ni eliminación. El desperdicio se aplica solo al acero.': 'It '
                                                                                                                                                                                                              'only '
                                                                                                                                                                                                              'measures '
                                                                                                                                                                                                              'rectangular '
                                                                                                                                                                                                              'footings: '
                                                                                                                                                                                                              'it '
                                                                                                                                                                                                              'does '
                                                                                                                                                                                                              'not '
                                                                                                                                                                                                              'design '
                                                                                                                                                                                                              'or '
                                                                                                                                                                                                              'check '
                                                                                                                                                                                                              'the '
                                                                                                                                                                                                              'structure. '
                                                                                                                                                                                                              'It '
                                                                                                                                                                                                              'does '
                                                                                                                                                                                                              'not '
                                                                                                                                                                                                              'compute '
                                                                                                                                                                                                              'hooks, '
                                                                                                                                                                                                              'laps, '
                                                                                                                                                                                                              'column '
                                                                                                                                                                                                              'starters, '
                                                                                                                                                                                                              'blinding, '
                                                                                                                                                                                                              'backfill '
                                                                                                                                                                                                              'or '
                                                                                                                                                                                                              'disposal. '
                                                                                                                                                                                                              'Waste '
                                                                                                                                                                                                              'applies '
                                                                                                                                                                                                              'to '
                                                                                                                                                                                                              'steel '
                                                                                                                                                                                                              'only.'},
 'pt_BR': {'Agregar zapatas…': 'Adicionar sapatas…',
           'Metrado por dimensiones, sin precios': 'Quantidades por dimensões, sem '
                                                   'preços',
           'Nombre': 'Nome',
           'Cantidad de zapatas': 'Quantidade de sapatas',
           'Largo': 'Comprimento',
           'Ancho': 'Largura',
           'Alto': 'Altura',
           'Profundidad de excavación': 'Profundidade de escavação',
           '0 = el alto de la zapata': '0 = a altura da sapata',
           'Sobreancho de excavación por lado': 'Folga de escavação por lado',
           'Recubrimiento': 'Cobrimento',
           'Varillas paralelas al largo': 'Barras paralelas ao comprimento',
           'Diámetro de esas varillas': 'Diâmetro dessas barras',
           'Varillas paralelas al ancho': 'Barras paralelas à largura',
           'Diámetro de esas varillas (ancho)': 'Diâmetro dessas barras (largura)',
           'Desperdicio de acero': 'Perda de aço',
           'La profundidad de excavación es menor que el alto de la zapata.': 'A '
                                                                              'profundidade '
                                                                              'de '
                                                                              'escavação '
                                                                              'é menor '
                                                                              'que a '
                                                                              'altura '
                                                                              'da '
                                                                              'sapata.',
           'El recubrimiento no cabe en esas dimensiones.': 'O cobrimento não cabe '
                                                            'nessas dimensões.',
           'Indica al menos una varilla.': 'Informe pelo menos uma barra.',
           'Excavación': 'Escavação',
           'Concreto': 'Concreto',
           'Encofrado': 'Fôrma',
           'Acero': 'Aço',
           'Peso por metro: π/4 × diámetro² × 7850 kg/m³. Largo de varilla: lado − 2 × recubrimiento.': 'Peso '
                                                                                                        'por '
                                                                                                        'metro: '
                                                                                                        'π/4 '
                                                                                                        '× '
                                                                                                        'diâmetro² '
                                                                                                        '× '
                                                                                                        '7850 '
                                                                                                        'kg/m³. '
                                                                                                        'Comprimento '
                                                                                                        'da '
                                                                                                        'barra: '
                                                                                                        'lado '
                                                                                                        '− '
                                                                                                        '2 '
                                                                                                        '× '
                                                                                                        'cobrimento.',
           'Zapatas': 'Sapatas',
           'ZAPATAS': 'SAPATAS',
           'EXCAVACIÓN PARA ZAPATA': 'ESCAVAÇÃO PARA SAPATA',
           'CONCRETO EN ZAPATA': 'CONCRETO EM SAPATA',
           'ENCOFRADO Y DESENCOFRADO DE ZAPATA': 'FÔRMA E DESFÔRMA DE SAPATA',
           'ACERO DE REFUERZO EN ZAPATA': 'ARMADURA DE AÇO EM SAPATA',
           'Se agregará el título {item} «{titulo}» con 4 partidas sin precio.': 'Será '
                                                                                 'adicionado '
                                                                                 'o '
                                                                                 'título '
                                                                                 '{item} '
                                                                                 '«{titulo}» '
                                                                                 'com '
                                                                                 '4 '
                                                                                 'itens '
                                                                                 'sem '
                                                                                 'preço.',
           '¿Agregar?': 'Adicionar?',
           'Solo mide zapatas rectangulares: no diseña ni verifica la estructura. No calcula ganchos, traslapes, arranques de columna, solado, relleno ni eliminación. El desperdicio se aplica solo al acero.': 'Só '
                                                                                                                                                                                                                 'mede '
                                                                                                                                                                                                                 'sapatas '
                                                                                                                                                                                                                 'retangulares: '
                                                                                                                                                                                                                 'não '
                                                                                                                                                                                                                 'dimensiona '
                                                                                                                                                                                                                 'nem '
                                                                                                                                                                                                                 'verifica '
                                                                                                                                                                                                                 'a '
                                                                                                                                                                                                                 'estrutura. '
                                                                                                                                                                                                                 'Não '
                                                                                                                                                                                                                 'calcula '
                                                                                                                                                                                                                 'ganchos, '
                                                                                                                                                                                                                 'traspasses, '
                                                                                                                                                                                                                 'arranques '
                                                                                                                                                                                                                 'de '
                                                                                                                                                                                                                 'pilar, '
                                                                                                                                                                                                                 'lastro, '
                                                                                                                                                                                                                 'reaterro '
                                                                                                                                                                                                                 'nem '
                                                                                                                                                                                                                 'bota-fora. '
                                                                                                                                                                                                                 'A '
                                                                                                                                                                                                                 'perda '
                                                                                                                                                                                                                 'se '
                                                                                                                                                                                                                 'aplica '
                                                                                                                                                                                                                 'só '
                                                                                                                                                                                                                 'ao '
                                                                                                                                                                                                                 'aço.'}}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
