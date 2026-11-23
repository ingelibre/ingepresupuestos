# SPDX-License-Identifier: GPL-3.0-or-later
"""Textos en inglés y portugués; el español es la clave."""
from ingepresupuestos import api

TEXTOS = {'en': {'Mano de obra': 'Labor',
        'Materiales': 'Materials',
        'Equipos': 'Equipment',
        'Subcontratos': 'Subcontracts',
        'Ajustar a un total…': 'Adjust to a total…',
        'Ajustar a un total': 'Adjust to a total',
        'Escala los precios de este proyecto, con vista previa': 'Scales this '
                                                                 "project's prices, "
                                                                 'with a preview',
        'Con esos insumos solo se puede llegar a un total entre {a} y {b} sin bajar ningún precio de la mitad ni pasar del doble.': 'With '
                                                                                                                                    'those '
                                                                                                                                    'resources '
                                                                                                                                    'the '
                                                                                                                                    'total '
                                                                                                                                    'can '
                                                                                                                                    'only '
                                                                                                                                    'be '
                                                                                                                                    'between '
                                                                                                                                    '{a} '
                                                                                                                                    'and '
                                                                                                                                    '{b} '
                                                                                                                                    'without '
                                                                                                                                    'any '
                                                                                                                                    'price '
                                                                                                                                    'below '
                                                                                                                                    'half '
                                                                                                                                    'or '
                                                                                                                                    'above '
                                                                                                                                    'double.',
        'Total objetivo': 'Target total',
        'Total actual: {v}. Marca los insumos cuyos precios se pueden escalar.': 'Current '
                                                                                 'total: '
                                                                                 '{v}. '
                                                                                 'Check '
                                                                                 'the '
                                                                                 'resources '
                                                                                 'whose '
                                                                                 'prices '
                                                                                 'may '
                                                                                 'be '
                                                                                 'scaled.',
        'Marca al menos un tipo de insumo.': 'Check at least one resource type.',
        'El presupuesto ya tiene ese total.': 'The budget already has that total.',
        'No hay insumos con precio de esos tipos.': 'There are no priced resources of '
                                                    'those types.',
        'Ningún cambio de precio acerca más el total al objetivo.': 'No price change '
                                                                    'brings the total '
                                                                    'closer to the '
                                                                    'target.',
        'Total actual: {v}': 'Current total: {v}',
        'Objetivo: {v}': 'Target: {v}',
        'Alcanzado: {v}': 'Reached: {v}',
        'Diferencia con el objetivo: {v}': 'Difference from target: {v}',
        'El redondeo no permite llegar exacto.': 'Rounding does not allow an exact '
                                                 'match.',
        'No se encontró una combinación exacta.': 'No exact combination was found.',
        'Cambian {n} precios de este proyecto; la biblioteca no se toca.': '{n} prices '
                                                                           'change in '
                                                                           'this '
                                                                           'project; '
                                                                           'the '
                                                                           'library is '
                                                                           'untouched.',
        'Algún insumo tenía precios distintos según la partida: quedará con uno solo.': 'Some '
                                                                                        'resource '
                                                                                        'had '
                                                                                        'different '
                                                                                        'prices '
                                                                                        'across '
                                                                                        'items: '
                                                                                        'it '
                                                                                        'will '
                                                                                        'have '
                                                                                        'a '
                                                                                        'single '
                                                                                        'one.',
        '… y {n} más.': '… and {n} more.',
        '¿Aplicar?': 'Apply?',
        'El presupuesto cambió; vuelve a intentarlo.': 'The budget changed; try '
                                                       'again.'},
 'pt_BR': {'Mano de obra': 'Mão de obra',
           'Materiales': 'Materiais',
           'Equipos': 'Equipamentos',
           'Subcontratos': 'Subcontratos',
           'Ajustar a un total…': 'Ajustar a um total…',
           'Ajustar a un total': 'Ajustar a um total',
           'Escala los precios de este proyecto, con vista previa': 'Escala os preços '
                                                                    'deste projeto, '
                                                                    'com prévia',
           'Con esos insumos solo se puede llegar a un total entre {a} y {b} sin bajar ningún precio de la mitad ni pasar del doble.': 'Com '
                                                                                                                                       'esses '
                                                                                                                                       'insumos '
                                                                                                                                       'só '
                                                                                                                                       'é '
                                                                                                                                       'possível '
                                                                                                                                       'um '
                                                                                                                                       'total '
                                                                                                                                       'entre '
                                                                                                                                       '{a} '
                                                                                                                                       'e '
                                                                                                                                       '{b} '
                                                                                                                                       'sem '
                                                                                                                                       'baixar '
                                                                                                                                       'nenhum '
                                                                                                                                       'preço '
                                                                                                                                       'da '
                                                                                                                                       'metade '
                                                                                                                                       'nem '
                                                                                                                                       'passar '
                                                                                                                                       'do '
                                                                                                                                       'dobro.',
           'Total objetivo': 'Total desejado',
           'Total actual: {v}. Marca los insumos cuyos precios se pueden escalar.': 'Total '
                                                                                    'atual: '
                                                                                    '{v}. '
                                                                                    'Marque '
                                                                                    'os '
                                                                                    'insumos '
                                                                                    'cujos '
                                                                                    'preços '
                                                                                    'podem '
                                                                                    'ser '
                                                                                    'escalados.',
           'Marca al menos un tipo de insumo.': 'Marque pelo menos um tipo de insumo.',
           'El presupuesto ya tiene ese total.': 'O orçamento já tem esse total.',
           'No hay insumos con precio de esos tipos.': 'Não há insumos com preço '
                                                       'desses tipos.',
           'Ningún cambio de precio acerca más el total al objetivo.': 'Nenhuma '
                                                                       'mudança de '
                                                                       'preço aproxima '
                                                                       'mais o total '
                                                                       'do desejado.',
           'Total actual: {v}': 'Total atual: {v}',
           'Objetivo: {v}': 'Desejado: {v}',
           'Alcanzado: {v}': 'Alcançado: {v}',
           'Diferencia con el objetivo: {v}': 'Diferença para o desejado: {v}',
           'El redondeo no permite llegar exacto.': 'O arredondamento não permite '
                                                    'chegar ao valor exato.',
           'No se encontró una combinación exacta.': 'Não foi encontrada uma '
                                                     'combinação exata.',
           'Cambian {n} precios de este proyecto; la biblioteca no se toca.': 'Mudam '
                                                                              '{n} '
                                                                              'preços '
                                                                              'deste '
                                                                              'projeto; '
                                                                              'a '
                                                                              'biblioteca '
                                                                              'não é '
                                                                              'alterada.',
           'Algún insumo tenía precios distintos según la partida: quedará con uno solo.': 'Algum '
                                                                                           'insumo '
                                                                                           'tinha '
                                                                                           'preços '
                                                                                           'diferentes '
                                                                                           'por '
                                                                                           'item: '
                                                                                           'ficará '
                                                                                           'com '
                                                                                           'um '
                                                                                           'só.',
           '… y {n} más.': '… e mais {n}.',
           '¿Aplicar?': 'Aplicar?',
           'El presupuesto cambió; vuelve a intentarlo.': 'O orçamento mudou; tente '
                                                          'novamente.'}}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
