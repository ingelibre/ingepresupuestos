# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""#51 — los análisis (ACU) del Excel de S10 se importan, y si no, se avisa.

Las hojas son sintéticas pero siguen el reporte «Análisis de precios
unitarios»: cabeceras repetidas por página, columnas corridas, subtotales,
%mo, sub-contratos y sub-partidas. Corre con pytest.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import core.database as bd                       # noqa: E402
from core import importer, s10_acus as s10       # noqa: E402

CAB = ['Código', 'Descripción Recurso', None, 'Unidad', 'Cuadrilla', None, 'Cantidad',
       'Precio S/.', None, 'Parcial S/.']
PAG = [['S10', None, None, None, None, None, None, None, None, 'Página :  1'],
       ['Análisis de precios unitarios'],
       ['Presupuesto', None, '0201001', 'OBRA DE PRUEBA'],
       ['Subpresupuesto', None, '001', 'ESTRUCTURAS', None, None, None,
        'Fecha presupuesto', None, '01/05/2026']]
FILAS = PAG + [
    ['Partida', '01.01', 'CONCRETO f\'c=210 kg/cm2 EN ZAPATAS'],
    ['Rendimiento', 'm3/DIA', None, 'MO. 25.0000', None, 'EQ. 25.0000', None,
     'Costo unitario directo por : m3', None, '389.47'],
    CAB,
    [None, 'Mano de Obra'],
    ['0147010002', 'OPERARIO', None, 'hh', 2, None, 0.64, 25.00, None, 16.00],
    ['0147010004', 'PEON', None, 'hh', '8.0000', None, '2.5600', '18.00', None, '46.08'],
    [None, None, None, None, None, None, None, None, None, 62.08],
    [None, 'Materiales'],
    ['0221000001', 'CEMENTO PORTLAND TIPO I (42.5 kg)', None, 'bol', None, None, 9.73, 25.50,
     None, 248.12],
] + PAG + [CAB,                       # el análisis sigue en la página siguiente
    ['0205000003', 'PIEDRA CHANCADA 1/2"', None, 'm3', None, None, 0.80, 85.00, None, 68.00],
    [None, None, None, None, None, None, None, None, None, 316.12],
    [None, 'Equipos'],
    ['0337010001', 'HERRAMIENTAS MANUALES', None, '%mo', None, None, 3, 62.08, None, 1.86],
    ['0348010007', 'MEZCLADORA DE CONCRETO 11 p3', None, 'hm', 1, None, 0.32, 29.40, None, 9.41],
    [None, None, None, None, None, None, None, None, None, 11.27],
    [],
    ['Partida', '01.02', 'ELIMINACION DE MATERIAL'],
    ['Rendimiento', 'm3/DIA', None, 'MO. 300.0000', None, 'EQ. 250.0000', None,
     'Costo unitario directo por : m3', None, 99.99],       # no cuadra a propósito
    CAB,
    [None, 'Subcontratos'],
    ['0401010001', 'SC ELIMINACION DE MATERIAL', None, 'm3', None, None, 1, 12.5, None, 12.5],
    [],
    ['Partida', '01.09', 'PARTIDA QUE NO ESTA EN EL PRESUPUESTO'],
    ['Rendimiento', 'und/DIA', None, 'MO. 1.0', None, 'EQ. 1.0', None,
     'Costo unitario directo por : und', None, 10],
    CAB,
    [None, 'Materiales'],
    ['0239000001', 'VARIOS', None, 'und', None, None, 1, 10, None, 10],
]


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, 'DB_PATH', str(tmp_path / 's10.db'))
    bd.init_db()
    return tmp_path


def _xlsx(ruta, filas):
    import openpyxl
    wb = openpyxl.Workbook()
    for f in filas:
        wb.active.append(list(f))
    wb.save(ruta)
    return str(ruta)


def _presupuesto(ruta):
    c = [None] * 11
    filas = [c, [None, 'S10 Presupuesto'], [None, 'Presupuesto', None, None, 'OBRA DE PRUEBA'], c]
    filas.append([None, 'Item', None, 'Descripción', None, None, None, 'Und.', 'Metrado', None,
                  'Precio S/.'])
    for it, d, u, m, p in [('01', 'ESTRUCTURAS', None, None, None),
                           ('01.01', "CONCRETO f'c=210 kg/cm2 EN ZAPATAS", 'm3', 12, 389.47),
                           ('01.02', 'ELIMINACION DE MATERIAL', 'm3', 30, 12.5),
                           ('01.03', 'PARTIDA SIN ANALISIS', 'm2', 5, 7)]:
        filas.append([None, it, None, d, None, None, None, u, m, None, p])
    return _xlsx(ruta, filas)


def test_lee_los_analisis(tmp_path):
    acus = s10.leer_s10_acus(_xlsx(tmp_path / 'acu.xlsx', FILAS))
    assert [a['item'] for a in acus] == ['01.01', '01.02', '01.09']
    a = acus[0]
    assert (a['unidad'], a['rendimiento'], a['cu']) == ('m3', 25.0, 389.47)
    assert [(i['codigo'], i['tipo'], i['unidad'], i['cuadrilla'], i['cantidad'], i['precio'])
            for i in a['items']] == [
        ('0147010002', 'MO', 'hh', 2.0, 0.64, 25.0),
        ('0147010004', 'MO', 'hh', 8.0, 2.56, 18.0),
        ('0221000001', 'MAT', 'bol', 0.0, 9.73, 25.5),
        ('0205000003', 'MAT', 'm3', 0.0, 0.8, 85.0),
        ('0337010001', 'EQ', '%mo', 0.0, 3.0, 62.08),
        ('0348010007', 'EQ', 'hm', 1.0, 0.32, 29.4)]
    assert s10.suma_parciales(a) == 389.47
    assert abs(s10.costo_calculado(a) - 389.47) < 0.011


def test_sin_la_palabra_partida_ni_precios(tmp_path):
    """Variante real: sin «Partida», sin código y sin precios."""
    filas = [[], [None, None, None, 'Análisis de precios unitarios'], [],
             [None, '01.02', 'CASETA'], [],
             [None, 'm2/DIA', 20.0, 'EQ.', 20.0, None, 'Costo unitario directo por : m2'], [],
             [None, 'Descripción Recurso', None, None, 'Unidad', 'Cuadrilla', 'Cantidad'],
             [None, None, 'Mano de Obra'],
             [None, 'PEON', None, None, 'hh', 4.0, 1.6], [],
             [None, None, 'Materiales'],
             [None, 'CLAVOS DE 2"', None, None, 'kg', None, 0.15], []]
    a, = s10.leer_s10_acus(_xlsx(tmp_path / 'acu.xlsx', filas))
    assert (a['item'], a['descripcion'], a['rendimiento'], a['cu']) == ('01.02', 'CASETA', 20.0, None)
    assert [(i['tipo'], i['cuadrilla'], i['cantidad'], i['precio']) for i in a['items']] == [
        ('MO', 4.0, 1.6, 0.0), ('MAT', 0.0, 0.15, 0.0)]


def test_un_analisis_auxiliar_no_se_cuela_en_la_partida_anterior(tmp_path):
    filas = FILAS + [['Detalle de sub-partidas'], ['CU0020148', 'CURADO DE CONCRETO'],
                     ['Rendimiento', 'm2/DIA', None, 'MO. 200', None, None, None,
                      'Costo unitario directo por : m2', None, 2.73], CAB,
                     [None, 'Mano de Obra'],
                     ['0147010004', 'PEON', None, 'hh', 1, None, 0.04, 20.31, None, 0.81]]
    acus = s10.leer_s10_acus(_xlsx(tmp_path / 'acu.xlsx', filas))
    assert len(acus) == 3 and len(acus[-1]['items']) == 1


def test_un_excel_que_no_es_de_s10_no_devuelve_analisis_vacios(tmp_path):
    filas = [['Partida', '01.01', None, 'CARTEL', None, None, None, 'Rend:', None, '1.0 UND/DIA'],
             ['Costo Unitario por UND :', 5]]
    assert s10.leer_s10_acus(_xlsx(tmp_path / 'x.xlsx', filas)) == []


def test_importa_reconcilia_y_lista_lo_que_falta(base):
    """El flujo entero por el worker de Importar (sin hilo)."""
    from views.importar_view import _ImportWorker
    w = _ImportWorker('s10', {'presupuesto': _presupuesto(base / 'p.xlsx'),
                              'acus': _xlsx(base / 'a.xlsx', FILAS)})
    ok, mal = [], []
    w.finished_ok.connect(lambda pid, r: ok.append((pid, r)))
    w.failed.connect(mal.append)
    w.run()
    assert not mal, mal
    pid, resumen = ok[0]
    assert '2 ACUs' in resumen
    assert '01.02' in resumen and '99.99' in resumen             # no cuadra
    assert 'PARTIDA SIN ANALISIS' in resumen
    assert 'PARTIDA QUE NO ESTA EN EL PRESUPUESTO' in resumen
    assert 'MO 300, EQ 250' in resumen
    conn = bd.get_db()
    p = conn.execute("SELECT * FROM partidas WHERE proyecto_id=? AND item='01.01'", (pid,)).fetchone()
    assert p['rendimiento'] == 25
    items, tot = bd.get_acu_items(conn, p['id'])
    assert len(items) == 6 and abs(sum(tot.values()) - 389.47) < 0.011
    # Código clásico: 01·47·010002 → el índice unificado es 47
    iu = {i['descripcion']: i['indice_inei'] for i in items}
    assert iu['OPERARIO'] == '47' and iu['CEMENTO PORTLAND TIPO I (42.5 kg)'] == '21'
    # La biblioteca apunta a SU recurso: los códigos S10 recortados a 7
    # dígitos coinciden entre operario y peón.
    bib = conn.execute(
        "SELECT r.descripcion FROM biblioteca_acu_items b JOIN recursos r ON r.id=b.recurso_id "
        "JOIN biblioteca_cu c ON c.id=b.cu_id WHERE c.descripcion LIKE 'CONCRETO%'").fetchall()
    assert len({r[0] for r in bib}) == 6
    conn.close()


def test_avisa_cuando_no_hay_acu(base):
    from views.importar_view import _ImportWorker
    for extra, texto in (({}, 'no elegiste el Excel'),
                         ({'acus': _xlsx(base / 'otro.xlsx', [['hola', 1]])}, 'No se importó ningún')):
        w = _ImportWorker('s10', {'presupuesto': _presupuesto(base / 'p.xlsx'), **extra})
        ok = []
        w.finished_ok.connect(lambda pid, r: ok.append(r))
        w.run()
        assert ok and texto in ok[0], ok


def test_items_repetidos_entre_subpresupuestos_se_emparejan_por_descripcion():
    part = [{'item': '01.01', 'descripcion': d, 'unidad': 'm2', 'es_titulo': 0} for d in ('MURO', 'PISO')]
    acu = [{'item': '1.01', 'descripcion': d, 'unidad': 'm2', 'items': []} for d in ('PISO', 'MURO')]
    datos, sp, sa = s10.emparejar(part, acu)
    assert not sp and not sa
    assert {p['descripcion']: datos[p['item_origen']]['descripcion'] for p in part} == {
        'MURO': 'MURO', 'PISO': 'PISO'}


def test_guardar_importacion_no_cruza_recursos_en_la_biblioteca(base):
    """Dos insumos cuyo código se recorta al mismo de 7 dígitos: la
    biblioteca buscaba por código y ponía dos veces el primero."""
    part = [{'item': '01', 'descripcion': 'P', 'unidad': 'm2', 'metrado': 1, 'precio_unitario': 1,
             'nivel': 1, 'es_titulo': 0}]
    it = lambda c, d: {'codigo': c, 'descripcion': d, 'tipo': 'MO', 'unidad': 'hh',
                       'cuadrilla': 1, 'cantidad': 1, 'precio': 1}
    importer.guardar_importacion({'nombre': 'X'}, part, {'01': {'rendimiento': 1, 'items': [
        it('0101010003', 'OPERARIO'), it('0101010005', 'PEON')]}})
    conn = bd.get_db()
    d = {r[0] for r in conn.execute("SELECT r.descripcion FROM biblioteca_acu_items b "
                                    "JOIN recursos r ON r.id=b.recurso_id")}
    conn.close()
    assert d == {'OPERARIO', 'PEON'}
