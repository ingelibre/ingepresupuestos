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
