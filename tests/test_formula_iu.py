# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Tests de la fórmula polinómica agrupada por índice unificado.

Corre con:  venv/bin/python3 tests/test_formula_iu.py

El mismo usuario que pidió poder editar los índices unificados escribió que
«el esquema para el desarrollo de la fórmula polinómica es simple: no
pudiéndose ver los componentes que conforman cada monomio, ni pudiendo editar
qué componentes corresponderán a cada monomio».

Tenía razón, y la causa era más de fondo de lo que parecía: `calcular_desde_acu`
NO agrupaba por índice unificado. Producía siempre tres monomios fijos —J/M/E
con los índices 47, 39 y 48— desde los totales de MO/MAT/EQ. La columna
`recursos.indice_inei` existía, estaba poblada al 89% y tenía índice en la BD,
pero la fórmula no la leía nunca. No había componentes que mostrar porque no se
calculaban.

Usa una COPIA temporal de presupuestos_seed.db, nunca la BD activa.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import core.config as cfg
import core.database as d

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_tmpdb = None


def _preparar():
    """BD temporal. Devuelve (módulo, pid del proyecto más grande)."""
    global _tmpdb
    if _tmpdb is None:
        fd, _tmpdb = tempfile.mkstemp(suffix='_formula.db')
        os.close(fd)
        shutil.copy(SEED, _tmpdb)
        d.DB_PATH = _tmpdb
        cfg.DB_PATH = _tmpdb
        d.init_db()
    import core.formula_polinomica as F
    conn = d.get_db()
    pid = conn.execute(
        "SELECT proyecto_id FROM partidas WHERE es_titulo=0 "
        "GROUP BY proyecto_id ORDER BY SUM(metrado*precio_unitario) DESC LIMIT 1"
    ).fetchone()[0]
    conn.close()
    return F, pid


def _cd_del_presupuesto(pid):
    """El costo directo tal como lo imprime la app."""
    conn = d.get_db()
    filas = conn.execute(
        "SELECT metrado, precio_unitario FROM partidas "
        "WHERE proyecto_id=? AND es_titulo=0", (pid,)
    ).fetchall()
    conn.close()
    return sum(d.parcial_wysiwyg(f['metrado'], f['precio_unitario'])
               for f in filas)


# ── El reparto por índice ────────────────────────────────────────────────────
def test_las_incidencias_suman_el_costo_directo_del_presupuesto():
    """Sin esto la fórmula reajustaría un monto que no es el de la obra."""
    F, pid = _preparar()
    inc = F.incidencias_por_iu(pid)
    assert inc['ok'], inc['msg']
    assert abs(inc['cd'] - _cd_del_presupuesto(pid)) < 0.01, \
        f"CD fórmula {inc['cd']} vs presupuesto {_cd_del_presupuesto(pid)}"


def test_reparte_entre_varios_indices_no_entre_tres_tipos():
    F, pid = _preparar()
    inc = F.incidencias_por_iu(pid)
    assert len(inc['ius']) > 3, \
        f"solo agrupó en {len(inc['ius'])} índices: sigue siendo por tipo"
    assert {i['codigo'] for i in inc['ius']} - {'47', '39', '48'}, \
        "no salió de los tres índices fijos de siempre"


def test_las_incidencias_estan_ordenadas_de_mayor_a_menor():
    F, pid = _preparar()
    montos = [i['monto'] for i in F.incidencias_por_iu(pid)['ius']]
    assert montos == sorted(montos, reverse=True)


def test_los_insumos_sin_indice_se_reportan_aparte():
    """Caen en el índice de su tipo, pero se dice cuánto costo es un supuesto."""
    F, pid = _preparar()
    inc = F.incidencias_por_iu(pid)
    assert inc['monto_sin_indice'] >= 0
    assert inc['monto_sin_indice'] <= inc['cd']


# ── El armado de los monomios ────────────────────────────────────────────────
def test_los_coeficientes_suman_uno_exacto():
    """Validación del D.S. 011-79-VC que la vista ya exigía a mano."""
    F, pid = _preparar()
    r = F.calcular_por_iu(pid)
    assert r['ok'], r['msg']
    assert abs(sum(m['coeficiente'] for m in r['monomios']) - 1.0) < 1e-9


def test_ningun_monomio_baja_del_cinco_por_ciento():
    F, pid = _preparar()
    r = F.calcular_por_iu(pid)
    bajos = [(m['simbolo'], m['coeficiente'])
             for m in r['monomios'] if m['coeficiente'] < 0.05]
    assert not bajos, f"monomios por debajo del mínimo legal: {bajos}"


def test_no_pasa_de_ocho_monomios():
    F, pid = _preparar()
    assert len(F.calcular_por_iu(pid)['monomios']) <= 8


def test_agrupar_no_pierde_nada_de_la_base():
    """Todo termina en algún monomio: los montos deben cerrar con el subtotal.

    La base NO es el costo directo sino el subtotal del presupuesto —costo
    directo + gastos generales + utilidad—, que es sobre lo que el art. 2 del
    D.S. 011-79-VC calcula las incidencias.
    """
    F, pid = _preparar()
    r = F.calcular_por_iu(pid)
    suma = sum(c['monto'] for m in r['monomios'] for c in m['componentes'])
    assert abs(suma - r['base']) < 0.01, f"se perdieron S/ {r['base'] - suma:,.2f}"
    assert r['base'] > r['cd'], "la base no incluyó gastos generales y utilidad"


def test_cada_indice_esta_en_un_solo_monomio():
    """Salvo el de gastos generales y utilidad, que lleva el índice general y
    puede coincidir con el del monomio de materiales varios."""
    F, pid = _preparar()
    r = F.calcular_por_iu(pid)
    vistos = [c['codigo'] for m in r['monomios'] if m['tipo'] != 'GU'
              for c in m['componentes']]
    assert len(vistos) == len(set(vistos)), "un índice quedó en dos monomios"


def test_gastos_generales_y_utilidad_son_un_monomio_propio():
    """Art. 2: «e·(GU/GUo)». Sin él, ese 13-19% del contrato no se reajusta."""
    F, pid = _preparar()
    r = F.calcular_por_iu(pid)
    gu = [m for m in r['monomios'] if m['tipo'] == 'GU']
    assert len(gu) == 1, f"monomios GU: {len(gu)}"
    assert gu[0]['simbolo'] == 'GU'
    assert gu[0]['coeficiente'] > 0
    esperado = r['gg_utilidad'] / r['base']
    assert abs(gu[0]['coeficiente'] - esperado) < 0.002, (
        gu[0]['coeficiente'], esperado)


def test_los_coeficientes_van_al_milesimo():
    """Art. 2: «cifras decimales con aproximación al milésimo»."""
    F, pid = _preparar()
    for m in F.calcular_por_iu(pid)['monomios']:
        k = m['coeficiente']
        assert abs(k - round(k, 3)) < 1e-9, f"{m['simbolo']} = {k}"


def test_el_indice_del_monomio_sale_de_tres_componentes_como_mucho():
    """Art. 2: «promedio ponderado de los índices hasta de tres elementos».

    El monomio puede agrupar la incidencia de más —descartarlos perdería costo
    directo— pero solo los tres de mayor peso forman su índice.
    """
    F, pid = _preparar()
    import core.indices_inei as I
    comps = [{'codigo': c, 'nombre': f'IU {c}', 'monto': m}
             for c, m in (('21', 50.0), ('43', 30.0), ('05', 15.0), ('04', 5.0))]
    for c in ('21', '43', '05', '04'):
        I.guardar_valor(c, 2020, 1, 100.0)
        I.guardar_valor(c, 2021, 1, 200.0)
    F.guardar_monomios(pid, [{'simbolo': 'M', 'descripcion': 'Agrupado',
                              'indice_inei': '21', 'coeficiente': 1.0,
                              'componentes': comps}])
    fila = F.calcular_reajuste_k(pid, 2020, 1, 2021, 1, '01')['detalle'][0]
    assert len(fila['componentes']) == 3, \
        f"el índice usó {len(fila['componentes'])} componentes"
    assert fila['componentes'][0]['acompanantes'] == 1, \
        "no informó cuántos índices quedaron fuera del promedio"
    assert abs(sum(c['peso'] for c in fila['componentes']) - 1.0) < 1e-9, \
        "los pesos no se renormalizaron sobre los tres"


def test_el_simbolo_de_cada_monomio_es_unico_y_sin_tilde():
    """El símbolo va impreso en la fórmula; «Índice general» daba una «Í»."""
    F, pid = _preparar()
    simbolos = [m['simbolo'] for m in F.calcular_por_iu(pid)['monomios']]
    assert len(simbolos) == len(set(simbolos)), simbolos
    for s in simbolos:
        assert s.isascii() and s[0].isalpha(), f"símbolo inválido: {s!r}"


def test_el_equipo_no_se_funde_en_mano_de_obra():
    """Un índice que no llega al mínimo va al AFÍN, no al mayor a secas.

    Sin el paso del medio en `_destino`, un equipo del 2% terminaba dentro del
    monomio de mano de obra solo porque era el más grande de la fórmula.
    """
    F, pid = _preparar()
    for m in F.calcular_por_iu(pid)['monomios']:
        if m['tipo'] != 'MO':
            continue
        ajenos = [c['codigo'] for c in m['componentes']
                  if c['codigo'] != m['indice_inei']]
        assert not ajenos, \
            f"el monomio de mano de obra absorbió índices de otro tipo: {ajenos}"


# ── La composición: guardar, releer, calcular K ──────────────────────────────
def test_la_composicion_se_guarda_y_se_relee():
    F, pid = _preparar()
    r = F.calcular_por_iu(pid)
    F.guardar_monomios(pid, r['monomios'])
    comps = F.cargar_componentes(pid)
    assert comps, "no se guardó la composición"
    total_guardado = sum(c['monto'] for lista in comps.values() for c in lista)
    assert abs(total_guardado - r['base']) < 0.01
    assert len(comps) == len(r['monomios'])


def test_guardar_reemplaza_la_composicion_anterior():
    F, pid = _preparar()
    r = F.calcular_por_iu(pid)
    F.guardar_monomios(pid, r['monomios'])
    F.guardar_monomios(pid, r['monomios'])
    comps = F.cargar_componentes(pid)
    n = sum(len(v) for v in comps.values())
    esperado = sum(len(m['componentes']) for m in r['monomios'])
    assert n == esperado, f"quedaron {n} componentes, esperaba {esperado}"


def test_k_de_un_monomio_agrupado_pondera_sus_indices():
    """Dos índices al 50%: uno sube 20% y el otro no se mueve → ratio 1.10."""
    F, pid = _preparar()
    import core.indices_inei as I
    for cod in ('21', '43'):
        I.asegurar_codigos([cod])
    I.guardar_valor('21', 2020, 1, 100.0)
    I.guardar_valor('43', 2020, 1, 100.0)
    I.guardar_valor('21', 2021, 1, 120.0)
    I.guardar_valor('43', 2021, 1, 100.0)
    F.guardar_monomios(pid, [{
        'simbolo': 'M', 'descripcion': 'Agrupado', 'indice_inei': '21',
        'coeficiente': 1.0,
        'componentes': [{'codigo': '21', 'nombre': 'Cemento', 'monto': 50.0},
                        {'codigo': '43', 'nombre': 'Madera', 'monto': 50.0}],
    }])
    r = F.calcular_reajuste_k(pid, 2020, 1, 2021, 1, '01')
    fila = r['detalle'][0]
    assert abs(fila['ratio'] - 1.10) < 1e-6, fila['ratio']
    assert len(fila['componentes']) == 2
    assert abs(r['k_total'] - 1.10) < 1e-4, r['k_total']


def test_k_sin_composicion_usa_el_indice_del_monomio():
    """Los proyectos guardados antes de esta versión no cambian de número."""
    F, pid = _preparar()
    import core.indices_inei as I
    I.guardar_valor('21', 2020, 1, 100.0)
    I.guardar_valor('21', 2021, 1, 150.0)
    F.guardar_monomios(pid, [{
        'simbolo': 'C', 'descripcion': 'Cemento', 'indice_inei': '21',
        'coeficiente': 1.0,      # sin 'componentes'
    }])
    r = F.calcular_reajuste_k(pid, 2020, 1, 2021, 1, '01')
    assert abs(r['detalle'][0]['ratio'] - 1.5) < 1e-6
    assert r['detalle'][0]['componentes'] == []


def test_un_componente_sin_datos_no_anula_el_monomio():
    """Se renormaliza sobre los que sí tienen valor, y se avisa cuántos faltan."""
    F, pid = _preparar()
    import core.indices_inei as I
    I.guardar_valor('21', 2020, 1, 100.0)
    I.guardar_valor('21', 2021, 1, 200.0)
    F.guardar_monomios(pid, [{
        'simbolo': 'M', 'descripcion': 'Agrupado', 'indice_inei': '21',
        'coeficiente': 1.0,
        'componentes': [{'codigo': '21', 'nombre': 'Cemento', 'monto': 50.0},
                        {'codigo': '77', 'nombre': 'Sin datos', 'monto': 50.0}],
    }])
    r = F.calcular_reajuste_k(pid, 2020, 1, 2021, 1, '01')
    fila = r['detalle'][0]
    assert not fila['falta_dato'], "anuló el monomio entero"
    assert fila['componentes_sin_dato'] == 1
    assert abs(fila['ratio'] - 2.0) < 1e-6, fila['ratio']


def test_k_se_niega_a_cruzar_el_cambio_de_base():
    """La RJ 016-2026-INEI cambió la base en diciembre de 2025.

    Dividir un índice de la serie nueva entre uno de la vieja da un número sin
    sentido —30 códigos cambiaron de significado—, así que el cálculo se niega
    y lo explica en vez de devolver una cifra falsa.
    """
    F, pid = _preparar()
    F.guardar_monomios(pid, [{
        'simbolo': 'C', 'descripcion': 'Cemento', 'indice_inei': '21',
        'coeficiente': 1.0,
    }])
    r = F.calcular_reajuste_k(pid, 2025, 6, 2026, 3, '01')
    assert not r['ok'], "calculó K a caballo entre las dos bases"
    assert 'empalme' in r['msg'].lower(), r['msg']
    assert r['series'] == ('1992', '2025'), r.get('series')


def test_k_dentro_de_la_misma_base_sigue_calculando():
    F, pid = _preparar()
    import core.indices_inei as I
    I.guardar_valor('21', 2026, 1, 100.0)
    I.guardar_valor('21', 2026, 3, 110.0)
    F.guardar_monomios(pid, [{
        'simbolo': 'C', 'descripcion': 'Cemento', 'indice_inei': '21',
        'coeficiente': 1.0,
    }])
    r = F.calcular_reajuste_k(pid, 2026, 1, 2026, 3, '01')
    assert r['ok'], r.get('msg')
    assert abs(r['k_total'] - 1.10) < 1e-4, r['k_total']


# ── Administración directa: la fórmula no corresponde ────────────────────────
def _set_modalidad(pid, modalidad):
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET modalidad=? WHERE id=?", (modalidad, pid))
    conn.commit()
    conn.close()


def test_no_aplica_en_administracion_directa():
    """El reajuste por fórmula polinómica es de las obras por contrata."""
    F, pid = _preparar()
    _set_modalidad(pid, 'Administración directa')
    try:
        ok, motivo = F.aplica_formula(pid)
        assert not ok
        assert 'contrata' in motivo.lower(), motivo
    finally:
        _set_modalidad(pid, 'Contrata')


def test_si_aplica_por_contrata():
    F, pid = _preparar()
    _set_modalidad(pid, 'Contrata')
    ok, motivo = F.aplica_formula(pid)
    assert ok and motivo == ''


def test_la_valorizacion_no_se_reajusta_en_administracion_directa():
    """La regla tiene que llegar hasta la valorización, no solo a la vista."""
    F, pid = _preparar()
    _set_modalidad(pid, 'Administración directa')
    try:
        r = F.reajuste_de_valorizacion(pid, 2026, 3, 100000.0)
        assert not r['aplica'], r
        assert r['reajuste'] == 0.0
        assert 'contrata' in r['motivo'].lower(), r['motivo']
    finally:
        _set_modalidad(pid, 'Contrata')


def test_la_valorizacion_se_reajusta_por_contrata():
    """R = V·(K−1): es para lo que existe la fórmula polinómica."""
    F, pid = _preparar()
    import core.indices_inei as I
    _set_modalidad(pid, 'Contrata')
    I.guardar_valor('21', 2026, 1, 100.0)
    I.guardar_valor('21', 2026, 3, 120.0)
    F.guardar_monomios(pid, [{'simbolo': 'C', 'descripcion': 'Cemento',
                              'indice_inei': '21', 'coeficiente': 1.0}])
    F.guardar_periodos(pid, 2026, 1, 2026, 3, '01')
    r = F.reajuste_de_valorizacion(pid, 2026, 3, 100000.0)
    assert r['aplica'], r['motivo']
    assert abs(r['k'] - 1.2) < 1e-6, r['k']
    assert abs(r['reajuste'] - 20000.0) < 0.01, r['reajuste']


def test_sin_formula_guardada_no_hay_reajuste():
    F, pid = _preparar()
    _set_modalidad(pid, 'Contrata')
    F.guardar_monomios(pid, [])
    r = F.reajuste_de_valorizacion(pid, 2026, 3, 50000.0)
    assert not r['aplica']
    assert 'fórmula' in r['motivo'].lower(), r['motivo']


# ── Art. 4: varias fórmulas por obra ─────────────────────────────────────────
def _proyecto_con_subs():
    """(módulo, pid, [sub_ids]) de un proyecto con varios subpresupuestos."""
    F, _ = _preparar()
    conn = d.get_db()
    pid = conn.execute("SELECT proyecto_id FROM sub_presupuestos "
                       "GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
    subs = [r[0] for r in conn.execute(
        "SELECT id FROM sub_presupuestos WHERE proyecto_id=? ORDER BY id", (pid,))]
    conn.execute("UPDATE proyectos SET modalidad='Contrata' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    # Los tests comparten la misma BD: dejar una sola fórmula para que el que
    # llena el proyecto hasta el tope no arruine a los siguientes.
    fs = F.listar_formulas(pid)
    for f in fs[1:]:
        F.eliminar_formula(f['id'])
    return F, pid, subs


def test_siempre_hay_al_menos_una_formula():
    F, pid = _preparar()
    fs = F.listar_formulas(pid)
    assert len(fs) >= 1 and fs[0]['numero'] == 1


def test_no_se_pasa_del_maximo_del_articulo_4():
    """«Cada obra podrá tener hasta un máximo de cuatro (4) fórmulas»."""
    F, pid, _ = _proyecto_con_subs()
    while len(F.listar_formulas(pid)) < F.MAX_FORMULAS:
        F.crear_formula(pid)
    try:
        F.crear_formula(pid)
    except ValueError as e:
        assert str(F.MAX_FORMULAS) in str(e), str(e)
        return
    raise AssertionError("dejó pasar del máximo de fórmulas")


def test_la_ultima_formula_no_se_puede_eliminar():
    F, pid = _preparar()
    fid = F.formula_por_defecto(pid)
    for f in F.listar_formulas(pid):
        if f['id'] != fid:
            F.eliminar_formula(f['id'])
    try:
        F.eliminar_formula(fid)
    except ValueError:
        return
    raise AssertionError("borró la única fórmula del proyecto")


def test_cada_formula_cubre_su_subpresupuesto():
    """Art. 4: «el presupuesto se subdividirá en tantas partes como fórmulas»."""
    F, pid, subs = _proyecto_con_subs()
    f1 = F.formula_por_defecto(pid)
    f2 = F.crear_formula(pid, 'ELÉCTRICAS')
    F.asignar_subpresupuestos(f1, [subs[0]])
    F.asignar_subpresupuestos(f2, [subs[1]])
    r1 = F.calcular_por_iu(pid, formula_id=f1)
    r2 = F.calcular_por_iu(pid, formula_id=f2)
    assert r1['ok'] and r2['ok'], (r1.get('msg'), r2.get('msg'))
    assert abs(r1['base'] - r2['base']) > 1, "las dos fórmulas dieron la misma base"
    F.guardar_monomios(pid, r1['monomios'], formula_id=f1)
    F.guardar_monomios(pid, r2['monomios'], formula_id=f2)
    assert len(F.cargar_monomios(pid, f1)) == len(r1['monomios'])
    assert len(F.cargar_monomios(pid, f2)) == len(r2['monomios'])
    assert F.cargar_monomios(pid, f1) != F.cargar_monomios(pid, f2)


def test_el_reajuste_se_reparte_entre_las_formulas():
    """Cada fórmula reajusta lo valorizado de la parte que cubre."""
    F, pid, subs = _proyecto_con_subs()
    import core.indices_inei as I
    f1 = F.formula_por_defecto(pid)
    f2 = F.crear_formula(pid, 'SEGUNDA')
    F.asignar_subpresupuestos(f1, [subs[0]])
    F.asignar_subpresupuestos(f2, [subs[1]])
    I.guardar_valor('21', 2026, 1, 100.0)
    I.guardar_valor('21', 2026, 3, 120.0)   # +20%
    I.guardar_valor('47', 2026, 1, 100.0)
    I.guardar_valor('47', 2026, 3, 110.0)   # +10%
    F.guardar_monomios(pid, [{'simbolo': 'C', 'descripcion': 'Cemento',
                              'indice_inei': '21', 'coeficiente': 1.0}], f1)
    F.guardar_monomios(pid, [{'simbolo': 'J', 'descripcion': 'Mano de obra',
                              'indice_inei': '47', 'coeficiente': 1.0}], f2)
    F.guardar_periodos(pid, 2026, 1, 2026, 3, '01')
    r = F.reajuste_de_valorizacion(pid, 2026, 3, 3000.0,
                                   {subs[0]: 1000.0, subs[1]: 2000.0})
    assert r['aplica'], r['motivo']
    assert len(r['formulas']) == 2, r['formulas']
    por_id = {f['formula_id']: f for f in r['formulas']}
    assert abs(por_id[f1]['reajuste'] - 200.0) < 0.01, por_id[f1]
    assert abs(por_id[f2]['reajuste'] - 200.0) < 0.01, por_id[f2]
    assert abs(r['reajuste'] - 400.0) < 0.01, r['reajuste']


# ── Trazabilidad: del índice hasta la partida ────────────────────────────────
def test_el_desglose_de_un_indice_cuadra_con_su_monto():
    """Sin esto la fórmula no es auditable: dice cuánto pesa cada índice pero
    no de dónde sale. Los montos del desglose tienen que sumar el del índice."""
    F, pid = _preparar()
    r = F.calcular_por_iu(pid)
    iu = r['ius'][0]
    des = F.desglose_de_iu(pid, iu['codigo'])
    assert des['ok'], des['msg']
    assert abs(des['monto'] - iu['monto']) < 0.02, (des['monto'], iu['monto'])
    suma = sum(i['monto'] for i in des['insumos'])
    assert abs(suma - des['monto']) < 0.02, (suma, des['monto'])


def test_el_desglose_llega_hasta_las_partidas():
    F, pid = _preparar()
    r = F.calcular_por_iu(pid)
    des = F.desglose_de_iu(pid, r['ius'][0]['codigo'])
    ins = des['insumos'][0]
    assert ins['partidas'], "el insumo no dice en qué partidas se usa"
    suma = sum(p['monto'] for p in ins['partidas'])
    assert abs(suma - ins['monto']) < 0.05, (suma, ins['monto'])
    assert all(p['item'] for p in ins['partidas']), "hay partidas sin ítem"


def test_el_desglose_marca_los_insumos_sin_indice_propio():
    """Caen en el índice de su tipo; hay que poder ver qué se está asumiendo."""
    F, pid = _preparar()
    from core.config import INEI_DEFAULT
    des = F.desglose_de_iu(pid, INEI_DEFAULT['MAT'])
    if des['ok']:
        assert any('asignado' in i for i in des['insumos'])


def test_el_desglose_de_un_indice_sin_uso_lo_dice():
    F, pid = _preparar()
    des = F.desglose_de_iu(pid, '25')      # hueco de la numeración oficial
    assert not des['ok']
    assert '25' in des['msg']


# ── Navegación: el botón «Cargar valores INEI →» ─────────────────────────────
def test_ir_a_indices_no_se_llama_a_si_mismo():
    """Bug encontrado probando: `RecursionError` al pulsar el botón.

    El recorrido de los widgets padre arrancaba en `self`, y como esta misma
    vista tiene el método buscado, el primer `hasattr` daba positivo sobre ella
    y se llamaba en bucle hasta agotar la pila.
    """
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QMessageBox
    from PySide6.QtCore import Signal
    app = QApplication.instance() or QApplication([])
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    from views.formula_view import FormulaView

    conn = d.get_db()
    pid = conn.execute("SELECT id FROM proyectos LIMIT 1").fetchone()[0]
    conn.close()

    # Sin ningún ancestro que sepa navegar: avisa, no revienta.
    FormulaView(pid, "X")._ir_a_indices_inei()

    # Con el ProyectoView, que expone la señal.
    class FakeProyecto(QWidget):
        ir_a_indices_inei = Signal()
    padre = FakeProyecto()
    lay = QVBoxLayout(padre)
    v = FormulaView(pid, "X")
    lay.addWidget(v)
    recibido = []
    padre.ir_a_indices_inei.connect(lambda: recibido.append(True))
    v._ir_a_indices_inei()
    assert recibido, "no emitió la señal del ProyectoView"

    # Con el MainWindow, que expone el método.
    class FakeMain(QWidget):
        def __init__(self):
            super().__init__()
            self.llamado = False

        def _ir_a_indices_inei(self):
            self.llamado = True
    mw = FakeMain()
    lay2 = QVBoxLayout(mw)
    v2 = FormulaView(pid, "X")
    lay2.addWidget(v2)
    v2._ir_a_indices_inei()
    assert mw.llamado, "no llegó al método de MainWindow"


def test_el_monomio_activo_no_se_mueve_con_el_arrastre():
    """Reportado probando: «selecciono un monomio, me voy a Composición y si
    accidentalmente el mouse pasa por otro, la composición cambia; debería
    quedarse fija en el que yo seleccioné».

    La causa es un micro-arrastre —el botón sigue pulsado una fracción mientras
    el mouse se mueve—, que en una tabla normal mueve la selección. Acá el
    monomio activo solo cambia con un clic deliberado o con el teclado.
    """
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QAbstractItemView
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    from views.formula_view import FormulaView

    F, pid = _preparar()
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET modalidad='Contrata' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    F.guardar_monomios(pid, F.calcular_por_iu(pid)['monomios'])

    v = FormulaView(pid, "X")
    v.resize(1200, 700)
    v.show()
    v.cargar()
    app.processEvents()
    t = v.tbl
    assert t.rowCount() >= 4, "hacen falta al menos cuatro monomios"
    assert t.selectionMode() == QAbstractItemView.SingleSelection

    def centro(f):
        return t.visualItemRect(t.item(f, 2)).center()

    # Clic deliberado: eso SÍ manda.
    QTest.mouseClick(t.viewport(), Qt.LeftButton, Qt.NoModifier, centro(1))
    app.processEvents()
    assert t.currentRow() == 1
    elegido = v.lbl_comp_titulo.text()

    # Micro-arrastre hasta otra fila: no debe mover nada.
    QTest.mousePress(t.viewport(), Qt.LeftButton, Qt.NoModifier, centro(1))
    QTest.mouseMove(t.viewport(), centro(3))
    app.processEvents()
    QTest.mouseRelease(t.viewport(), Qt.LeftButton, Qt.NoModifier, centro(3))
    app.processEvents()
    assert t.currentRow() == 1, f"el arrastre movió la selección a {t.currentRow()}"
    assert v.lbl_comp_titulo.text() == elegido, "la composición saltó de monomio"
    assert len({i.row() for i in t.selectedIndexes()}) == 1

    # Mover el mouse sin botón tampoco.
    QTest.mouseMove(t.viewport(), centro(2))
    app.processEvents()
    assert t.currentRow() == 1
    assert v.lbl_comp_titulo.text() == elegido

    # Pero un clic nuevo y el teclado sí cambian de monomio.
    QTest.mouseClick(t.viewport(), Qt.LeftButton, Qt.NoModifier, centro(3))
    app.processEvents()
    assert t.currentRow() == 3
    assert v.lbl_comp_titulo.text() != elegido, "el clic no cambió la composición"
    QTest.keyClick(t, Qt.Key_Down)
    app.processEvents()
    assert t.currentRow() == 4, "el teclado dejó de mover el monomio activo"


def test_escribir_un_indice_pone_su_nombre_y_avisa_si_ya_esta_en_otro():
    """Dos cosas que se esperan al teclear un código en la columna Índice."""
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    from views.formula_view import FormulaView
    from core.indices_inei import catalogo

    F, pid = _preparar()
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET modalidad='Contrata' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    F.guardar_monomios(pid, F.calcular_por_iu(pid)['monomios'])

    respuesta = {'v': QMessageBox.Yes}
    QMessageBox.question = staticmethod(lambda *a, **k: respuesta['v'])
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)

    v = FormulaView(pid, "X")
    v.resize(1200, 700)
    v.show()
    v.cargar()
    app.processEvents()
    assert len(v._monomios[0].get('componentes') or []) > 1, \
        "hace falta un monomio con varios índices para probarlo"

    # ── un índice libre: solo rellena el nombre
    usados = {c['codigo'] for m in v._monomios
              for c in (m.get('componentes') or [])}
    libre, nombre_libre = next((c, n) for c, n in catalogo() if c not in usados)
    v._agregar_monomio()
    app.processEvents()
    fila = len(v._monomios) - 1
    v.tbl.item(fila, 3).setText(libre)
    app.processEvents()
    assert v._monomios[fila]['descripcion'] == nombre_libre, \
        v._monomios[fila]['descripcion']

    # ── una descripción escrita a mano NO se pisa
    v.tbl.item(fila, 2).setText('Mi texto propio')
    app.processEvents()
    otro = next(c for c, _ in catalogo() if c not in usados and c != libre)
    v.tbl.item(fila, 3).setText(otro)
    app.processEvents()
    assert v._monomios[fila]['descripcion'] == 'Mi texto propio'

    # ── un índice YA agrupado en otro monomio: ofrece moverlo
    cod = v._monomios[0]['componentes'][1]['codigo']
    n_origen = len(v._monomios[0]['componentes'])
    v._agregar_monomio()
    app.processEvents()
    f2 = len(v._monomios) - 1
    v.tbl.item(f2, 3).setText(cod)
    app.processEvents()
    assert len(v._monomios[0]['componentes']) == n_origen - 1, \
        "no lo sacó del monomio de origen"
    assert len(v._monomios[f2]['componentes']) == 1
    assert abs(sum(m['coeficiente'] for m in v._monomios) - 1.0) < 0.002


def test_un_monomio_con_indice_y_sin_incidencia_se_marca():
    """Queda así al crear uno nuevo y no moverle ningún índice."""
    F, pid = _preparar()
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from views.formula_view import FormulaView
    v = FormulaView(pid, "X")
    v._monomios = [
        {'simbolo': 'J', 'descripcion': 'Mano de obra', 'indice_inei': '47',
         'coeficiente': 1.0},
        {'simbolo': 'B', 'descripcion': 'Vacío', 'indice_inei': '21',
         'coeficiente': 0.0},
    ]
    problemas = ' '.join(v._validar_formula())
    assert 'Sin incidencia' in problemas, problemas
    assert 'B' in problemas


def test_la_composicion_no_se_mueve_ni_forzando_la_seleccion():
    """«Debería quedarse fijo al monomio que yo seleccioné.»

    El panel ya no se pinta desde `currentRow()` —eso lo mueve el arrastre, el
    hover en algunos entornos y hasta el foco— sino desde `_monomio_activo`,
    que solo cambia con un clic o con el teclado. Y si algo mueve la selección
    por debajo, se restaura.
    """
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    from views.formula_view import FormulaView

    F, pid = _preparar()
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET modalidad='Contrata' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    F.guardar_monomios(pid, F.calcular_por_iu(pid)['monomios'])

    v = FormulaView(pid, "X")
    v.resize(1200, 700)
    v.show()
    v.cargar()
    app.processEvents()
    t = v.tbl
    assert t.rowCount() >= 5

    QTest.mouseClick(t.viewport(), Qt.LeftButton, Qt.NoModifier,
                     t.visualItemRect(t.item(1, 2)).center())
    app.processEvents()
    assert v._monomio_activo == 1
    elegido = v.lbl_comp_titulo.text()

    # Forzar la selección por debajo, como haría un evento que no controlamos.
    t.selectRow(4)
    app.processEvents()
    app.processEvents()
    assert v._monomio_activo == 1, "el monomio activo se movió solo"
    assert v.lbl_comp_titulo.text() == elegido, "la composición saltó"
    assert t.currentRow() == 1, "no se restauró la fila resaltada"

    # El teclado sí manda.
    QTest.keyClick(t, Qt.Key_Down)
    app.processEvents()
    app.processEvents()
    assert v._monomio_activo == 2, v._monomio_activo


def test_la_vista_de_indices_del_proyecto_los_lista_con_su_monomio():
    """Perspectiva de toda la obra: qué índices hay, cuánto pesan y dónde
    quedaron. El 39 aparece dos veces —materiales y gastos generales— y cada
    uno tiene que mostrar SU monomio, no el del otro."""
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from views.formula_view import IndicesDelProyectoDialog

    F, pid = _preparar()
    r = F.calcular_por_iu(pid)
    dlg = IndicesDelProyectoDialog(pid, r['monomios'], 'Soles')
    assert dlg.tbl.rowCount() == len(r['ius']), (dlg.tbl.rowCount(),
                                                 len(r['ius']))
    simbolos = {m['simbolo'] for m in r['monomios']}
    for fila in range(dlg.tbl.rowCount()):
        assert dlg.tbl.item(fila, 6).text() in simbolos | {'—'}
    # los dos «39» no comparten monomio
    filas39 = [f for f in range(dlg.tbl.rowCount())
               if dlg.tbl.item(f, 0).text() == '39']
    if len(filas39) == 2:
        a, b = (dlg.tbl.item(f, 6).text() for f in filas39)
        assert a != b, f"los dos índices 39 quedaron con el mismo monomio: {a}"


def test_no_se_pierde_la_formula_sin_guardar():
    """Reportado probando: «auto-calculo, me voy a Fórmulas… y se borra».

    Esas acciones releen los monomios de la BASE DE DATOS, y lo auto-calculado
    todavía no estaba guardado. Ahora se pregunta antes: guardar, descartar o
    cancelar.
    """
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    import views.formula_view as FV
    FV.FormulasDialog.exec = lambda self: 0     # que no bloquee el modal

    F, pid = _preparar()
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET modalidad='Contrata' WHERE id=?", (pid,))
    conn.commit()
    conn.close()

    respuesta = {'v': QMessageBox.Save}
    QMessageBox.question = staticmethod(lambda *a, **k: respuesta['v'])
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)

    def recien_calculada():
        F.guardar_monomios(pid, [], F.formula_por_defecto(pid))
        v = FV.FormulaView(pid, "X")
        v.resize(1100, 650)
        v.show()
        v.cargar()
        app.processEvents()
        v._calcular_desde_acu()
        app.processEvents()
        assert v._monomios and v._sucio
        return v

    # Guardar: queda en la BD y en pantalla.
    v = recien_calculada()
    n = len(v._monomios)
    respuesta['v'] = QMessageBox.Save
    v._gestionar_formulas()
    app.processEvents()
    assert len(F.cargar_monomios(pid, v._formula_id)) == n
    assert len(v._monomios) == n
    assert not v._sucio

    # Cancelar: no se abre nada y no se pierde nada.
    v = recien_calculada()
    n = len(v._monomios)
    respuesta['v'] = QMessageBox.Cancel
    v._gestionar_formulas()
    app.processEvents()
    assert len(v._monomios) == n, "canceló y aun así perdió los monomios"

    # Descartar: eso sí los tira, porque se pidió.
    v = recien_calculada()
    respuesta['v'] = QMessageBox.Discard
    v._gestionar_formulas()
    app.processEvents()
    assert v._monomios == [] or not v._sucio

    # Volver al presupuesto: cancelar NO sale; descartar sí.
    salidas = []
    v = recien_calculada()
    v._on_back = lambda: salidas.append(True)
    respuesta['v'] = QMessageBox.Cancel
    v._volver()
    assert not salidas, "salió de la vista pese a cancelar"
    respuesta['v'] = QMessageBox.Discard
    v._volver()
    assert salidas, "no salió al descartar"


def test_mover_un_indice_no_te_saca_del_monomio_que_editas():
    """Reportado probando: al mover un índice, la vista saltaba al monomio de
    DESTINO. Uno está repartiendo los índices del monomio que tiene abierto,
    así que saltar tras cada envío rompe el trabajo."""
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    from views.formula_view import FormulaView

    F, pid = _preparar()
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET modalidad='Contrata' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    F.guardar_monomios(pid, F.calcular_por_iu(pid)['monomios'])

    v = FormulaView(pid, "X")
    v.resize(1100, 650)
    v.show()
    v.cargar()
    app.processEvents()
    v._fijar_monomio(0)
    app.processEvents()
    assert len(v._monomios[0].get('componentes') or []) >= 3, \
        "hace falta un monomio con varios índices"

    n0 = len(v._monomios[0]['componentes'])
    for _ in range(2):
        cod = v.tbl_comp.item(0, 0).text()
        v._mover_componente(cod, 0, 2)
        app.processEvents()
        assert v._monomio_activo == 0, \
            f"la vista saltó al monomio {v._monomio_activo}"
        assert v.lbl_comp_titulo.text().startswith(
            f"Composición de {v._monomios[0]['simbolo']}")
    assert len(v._monomios[0]['componentes']) == n0 - 2
    assert abs(sum(m['coeficiente'] for m in v._monomios) - 1.0) < 0.002


def test_el_decreto_viaja_con_la_app_y_se_abre_desde_la_validacion():
    """El texto «D.S. 011-79-VC» de debajo de la fórmula abre el decreto.

    Va empaquetado en `resources/` para poder consultarlo sin internet, como
    el resto del programa.
    """
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from views.formula_view import FormulaView, DecretoDialog

    ruta = DecretoDialog.ruta_pdf()
    assert ruta.exists(), f"el decreto no está empaquetado: {ruta}"
    assert ruta.stat().st_size > 100_000, "el PDF del decreto parece vacío"

    F, pid = _preparar()
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET modalidad='Contrata' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    F.guardar_monomios(pid, F.calcular_por_iu(pid)['monomios'])

    v = FormulaView(pid, "X")
    v.resize(1100, 650)
    v.show()
    v.cargar()
    app.processEvents()
    assert "href='ds'" in v.lbl_validacion.text(), \
        "el texto de validación no lleva el enlace al decreto"

    dlg = DecretoDialog()
    assert dlg._doc.pageCount() >= 5, dlg._doc.pageCount()


if __name__ == "__main__":
    fallos = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  OK  {name}")
            except AssertionError as e:
                fallos += 1
                print(f"  FAIL {name}: {e}")
            except Exception as e:
                fallos += 1
                print(f"  ERROR {name}: {type(e).__name__}: {e}")
    if _tmpdb and os.path.exists(_tmpdb):
        os.unlink(_tmpdb)
    sys.exit(1 if fallos else 0)
