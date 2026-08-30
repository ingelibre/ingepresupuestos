# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Tests del diccionario insumo → índice unificado.

Corre con:  venv/bin/python3 tests/test_diccionario_iu.py

El usuario pidió «implementar el diccionario para la elaboración de las
fórmulas polinómicas». El vínculo ya existía —`recursos.indice_inei`, poblado
al 89%— pero no había forma de verlo como conjunto, arreglarlo en tandas ni
llevárselo a otra instalación.

Lo delicado es la propuesta automática: asignar mal un índice mueve costo de un
monomio a otro de la fórmula. «CEMENTO PORTLAND TIPO V» se parece un 95.7% a
«TIPO I» y son índices distintos (23 y 21); ningún scorer los separa. De ahí el
control de ambigüedad, que es lo que más se prueba acá.

Usa una COPIA temporal de presupuestos_seed.db, nunca la BD activa.
"""
import json
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
    global _tmpdb
    if _tmpdb is None:
        fd, _tmpdb = tempfile.mkstemp(suffix='_dic.db')
        os.close(fd)
        shutil.copy(SEED, _tmpdb)
        d.DB_PATH = _tmpdb
        cfg.DB_PATH = _tmpdb
        d.init_db()
    import core.diccionario_iu as DIC
    return DIC


def _insumo(descripcion, tipo='MAT', inei='', codigo=None):
    """Inserta un insumo y devuelve su id."""
    conn = d.get_db()
    codigo = codigo or f"T{abs(hash(descripcion)) % 100000:05d}"
    cur = conn.execute(
        "INSERT INTO recursos (codigo, descripcion, tipo, unidad, precio, "
        "indice_inei) VALUES (?,?,?,?,?,?)",
        (codigo, descripcion, tipo, 'und', 1.0, inei)
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def _indice_de(rid):
    conn = d.get_db()
    r = conn.execute("SELECT indice_inei FROM recursos WHERE id=?",
                     (rid,)).fetchone()
    conn.close()
    return r['indice_inei'] if r else None


# ── Lo que falta clasificar ──────────────────────────────────────────────────
def test_el_centinela_00_cuenta_como_sin_asignar():
    """'00' no es un índice del INEI: lo pone parte_diario a lo sin clasificar."""
    DIC = _preparar()
    rid = _insumo('INSUMO ZZQX CENTINELA', inei='00')
    assert rid in {i['id'] for i in DIC.insumos_sin_indice()}


def test_los_insumos_con_indice_invalido_tambien_entran():
    """Un insumo con un código que la base vigente no define está tan roto
    como uno sin índice: la fórmula agrupa su costo bajo un índice que nunca
    tendrá valores. El diccionario tiene que poder arreglarlo."""
    DIC = _preparar()
    rid = _insumo('INSUMO ZZQX CON CODIGO MUERTO', inei='22')   # descontinuado
    ids = {i['id'] for i in DIC.insumos_sin_indice()}
    assert rid in ids, "el insumo con índice inválido quedó fuera"
    solo_vacios = {i['id'] for i in
                   DIC.insumos_sin_indice(incluir_invalidos=False)}
    assert rid not in solo_vacios
    assert len(ids) > len(solo_vacios)


def test_asignar_indice_en_tanda():
    DIC = _preparar()
    a = _insumo('INSUMO ZZQX TANDA UNO')
    b = _insumo('INSUMO ZZQX TANDA DOS')
    assert DIC.asignar_indice([a, b], '21') == 2
    assert _indice_de(a) == '21' and _indice_de(b) == '21'


def test_asignar_normaliza_el_codigo():
    DIC = _preparar()
    rid = _insumo('INSUMO ZZQX NORMALIZA')
    DIC.asignar_indice([rid], 7)
    assert _indice_de(rid) == '07'


def test_asignar_sin_ids_no_hace_nada():
    DIC = _preparar()
    assert DIC.asignar_indice([], '21') == 0


# ── Las propuestas ───────────────────────────────────────────────────────────
def test_marca_ambigua_cuando_otro_indice_esta_igual_de_cerca():
    """El caso del cemento, en el camino de la biblioteca.

    Se prueba con `usar_oficial=False` a propósito: el diccionario del INEI
    resuelve el cemento con UN solo código —el 21 de la base 2025 absorbió los
    tipos I, II y V— así que la ambigüedad solo aparece cuando la propuesta se
    apoya en la biblioteca del usuario, que sí conserva la distinción.
    """
    DIC = _preparar()
    _insumo('CEMENTO ZZQX PORTLAND TIPO I', inei='21')
    _insumo('CEMENTO ZZQX PORTLAND TIPO V', inei='23')
    rid = _insumo('CEMENTO ZZQX PORTLAND TIPO II')
    sug = {s['recurso_id']: s
           for s in DIC.sugerencias(umbral=80, usar_oficial=False)}
    assert rid in sug, "no propuso nada para el cemento ambiguo"
    assert sug[rid]['ambiguo'], \
        f"no marcó la ambigüedad: {sug[rid]['codigo']} vs {sug[rid]['rival']}"


def test_el_diccionario_oficial_tiene_prioridad_sobre_la_biblioteca():
    """Es la referencia con autoridad; la biblioteca puede traer errores."""
    DIC = _preparar()
    rid = _insumo('Cemento Portland', inei='')
    sug = {s['recurso_id']: s for s in DIC.sugerencias(umbral=80)}
    assert rid in sug, "el diccionario oficial no lo resolvió"
    assert sug[rid]['fuente'] == 'oficial', sug[rid]
    assert sug[rid]['puntaje'] >= 95, sug[rid]['puntaje']


def test_no_marca_ambigua_cuando_el_ganador_despega():
    DIC = _preparar()
    _insumo('WIDGET ZZQY SUPERESPECIAL DE PRUEBA', inei='26')
    rid = _insumo('WIDGET ZZQY SUPERESPECIAL DE PRUEBA REFORZADO')
    sug = {s['recurso_id']: s for s in DIC.sugerencias(umbral=80)}
    assert rid in sug
    assert not sug[rid]['ambiguo'], sug[rid]['rival']
    assert sug[rid]['codigo'] == '26'


def test_las_propuestas_de_la_biblioteca_no_cruzan_tipos():
    """Un material no se resuelve contra una mano de obra por parecido de texto.

    El guardia es del camino de la biblioteca. El diccionario del INEI mapea
    por NOMBRE del elemento y no conoce el tipo interno de la app, así que ahí
    manda el nombre — que es justamente su criterio.
    """
    DIC = _preparar()
    _insumo('OPERARIO ZZQZ ESPECIALISTA RARO', tipo='MO', inei='47')
    rid = _insumo('OPERARIO ZZQZ ESPECIALISTA RARO', tipo='MAT')
    sug = {s['recurso_id']: s
           for s in DIC.sugerencias(umbral=80, usar_oficial=False)}
    if rid in sug:
        assert sug[rid]['codigo'] != '47', \
            "propuso el índice de mano de obra para un material"


def test_las_propuestas_no_modifican_nada():
    """`sugerencias` solo propone: aplicar es una decisión aparte."""
    DIC = _preparar()
    rid = _insumo('INSUMO ZZQX INTOCABLE')
    antes = len(DIC.insumos_sin_indice())
    DIC.sugerencias(umbral=80)
    assert len(DIC.insumos_sin_indice()) == antes
    assert _indice_de(rid) == ''


def test_aplicar_sugerencias_asigna_lo_que_se_le_pasa():
    DIC = _preparar()
    rid = _insumo('INSUMO ZZQX APLICABLE')
    n = DIC.aplicar_sugerencias([{'recurso_id': rid, 'codigo': '43'}])
    assert n == 1
    assert _indice_de(rid) == '43'


# ── El diccionario como archivo ──────────────────────────────────────────────
def test_exportar_importar_ida_y_vuelta():
    DIC = _preparar()
    rid = _insumo('INSUMO ZZQX EXPORTABLE UNICO', inei='43')
    path = tempfile.mktemp(suffix='.json')
    try:
        n = DIC.exportar(path)
        assert n > 0
        DIC.asignar_indice([rid], '00')          # como si se hubiera perdido
        assert _indice_de(rid) == '00'
        res = DIC.importar(path)
        assert res['asignados'] >= 1, res
        assert _indice_de(rid) == '43', "no lo devolvió a su índice"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_importar_no_pisa_lo_ya_clasificado():
    DIC = _preparar()
    rid = _insumo('INSUMO ZZQX YA CLASIFICADO', inei='43')
    path = tempfile.mktemp(suffix='.json')
    try:
        DIC.exportar(path)
        DIC.asignar_indice([rid], '21')          # el usuario lo corrigió
        DIC.importar(path, solo_sin_indice=True)
        assert _indice_de(rid) == '21', "el archivo pisó la corrección"
        DIC.importar(path, solo_sin_indice=False)
        assert _indice_de(rid) == '43', "no pisó ni pidiéndoselo"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_importar_da_de_alta_los_indices_que_falten():
    """Si no, las asignaciones apuntarían a un código invisible."""
    DIC = _preparar()
    import core.indices_inei as I
    I.eliminar_indice('43')
    assert '43' not in dict(I.catalogo())
    rid = _insumo('INSUMO ZZQX RESUCITA EL INDICE')
    path = tempfile.mktemp(suffix='.json')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({
                'formato': 'ingepresupuestos.diccionario_iu', 'version': 1,
                'catalogo': [{'codigo': '43', 'nombre': 'Madera nacional'}],
                'entradas': {
                    f"MAT|{DIC._normalizar('INSUMO ZZQX RESUCITA EL INDICE')}": '43'},
            }, f)
        res = DIC.importar(path)
        assert res['nuevos'] == 1, res
        assert dict(I.catalogo())['43'] == 'Madera nacional'
        assert _indice_de(rid) == '43'
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_importar_rechaza_un_archivo_ajeno():
    DIC = _preparar()
    path = tempfile.mktemp(suffix='.json')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'algo': 'otra cosa'}, f)
        res = DIC.importar(path)
        assert res['asignados'] == 0
        assert 'no es un diccionario' in res['msg'].lower(), res['msg']
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ── El resumen ───────────────────────────────────────────────────────────────
def test_el_resumen_muestra_los_indices_fuera_del_catalogo():
    """La biblioteca semilla apunta a códigos que el catálogo no definía."""
    DIC = _preparar()
    fuera = [r for r in DIC.resumen()
             if not r['en_catalogo'] and r['codigo'] != '—']
    assert fuera, "el resumen esconde los índices huérfanos"


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
