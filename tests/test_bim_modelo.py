# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Núcleo BIM: lectura IFC/takeoff, vínculos con partidas y actualización.

`fixtures/bim/*.ifc` son sintéticos (IfcOpenShell e IngeTrazo);
`ifcopenshell.json` es lo que IfcOpenShell lee de ellos, ya en SI.
Corre con pytest.
"""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import core.database as bd                       # noqa: E402
from core import bim_modelo as bim               # noqa: E402
from core import ifc_lector as step              # noqa: E402
from core.ifc_importer import parse_ifc          # noqa: E402

FX = os.path.join(os.path.dirname(__file__), 'fixtures', 'bim')
VERDAD = json.load(open(os.path.join(FX, 'ifcopenshell.json'), encoding='utf-8'))
TAKEOFF = json.load(open(os.path.join(FX, 'takeoff-ejemplo.json'), encoding='utf-8'))
IFC_IT = os.path.join(FX, 'takeoff-ejemplo.ifc')


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, 'DB_PATH', str(tmp_path / 'bim.db'))
    bd.init_db()
    bd.init_db()          # idempotente
    return tmp_path


def _q(sql, *a):
    c = bd.get_db()
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def _x(sql, *a):
    c = bd.get_db()
    try:
        r = c.execute(sql, a).lastrowid
        c.commit()
        return r
    finally:
        c.close()


def _proyecto():
    return _x("INSERT INTO proyectos (nombre) VALUES ('P')")


def _partida(pid, unidad, desc='X', item='01.01', metrado=0):
    return _x("INSERT INTO partidas (proyecto_id, item, descripcion, unidad, metrado, nivel, "
              "es_titulo) VALUES (?,?,?,?,?,2,0)", pid, item, desc, unidad, metrado)


def _met(part):
    return _q("SELECT metrado FROM partidas WHERE id=?", part)[0][0]


def _muros(m):
    return [e.global_id for e in m.elementos if e.clase == 'IfcWall']


# ── Sintaxis STEP ────────────────────────────────────────────────────────────

def test_step_varias_por_linea_punto_y_coma_y_comentarios():
    d = (b"ISO-10303-21;\nHEADER;\nFILE_NAME('#9=IFCWALL(x);');\nENDSEC;\nDATA;\n"
         b"/* #7=IFCWALL('no'); 'abierta */ #1=IFCWALL('a;b',$,'it''s #5 (x, y)',(#2,#3)); #2 = ifcslab('z');\n"
         b"#3=IFCBEAM('multi',\n  $,\r\n 'l');\nENDSEC;\nEND-ISO-10303-21;")
    r = list(step.sentencias(d))
    assert [(a, b) for a, b, _ in r] == [(1, 'IFCWALL'), (2, 'IFCSLAB'), (3, 'IFCBEAM')]
    a = step.argumentos(r[0][2])
    assert step.texto(a[0]) == 'a;b' and step.texto(a[2]) == "it's #5 (x, y)"
    assert step.refs(a[3]) == [2, 3] and step.refs_crudas(r[0][2]) == [2, 3]


@pytest.mark.parametrize('crudo,esperado', [
    (rb"'Pe\X2\00F1\X0\\X2\00F3\X0\n'", 'Peñón'), (rb"'\X\F1'", 'ñ'), (rb"'\S\q'", 'ñ'),
    (rb"'\X4\0001F600\X0\'", '\U0001F600'), (rb"'\PE\\S\T'", 'д'), (rb"'a\\b'", 'a\\b'),
    ("'Muro ñ'".encode(), 'Muro ñ'), ("'Muro ñ'".encode('latin-1'), 'Muro ñ'), (b'$', ''),
    (rb"'\X2\6771\X0\'", '東')])
def test_textos_codificados(crudo, esperado):
    assert step.texto(crudo) == esperado


# ── Lectura frente a IfcOpenShell ────────────────────────────────────────────

@pytest.mark.parametrize('nombre', sorted(VERDAD))
def test_lee_lo_mismo_que_ifcopenshell(nombre):
    m = bim.leer_ifc(os.path.join(FX, nombre + '.ifc'))
    v = VERDAD[nombre]
    assert m.nombre == v['proyecto']
    els = {e.global_id: e for e in m.elementos}
    assert set(els) == set(v['elementos'])
    for g, x in v['elementos'].items():
        e = els[g]
        assert (e.clase, e.nombre, e.tipo, e.piso) == (x['clase'], x['nombre'], x['tipo'], x['piso'])
        assert set(e.cantidades) == set(x['q'])
        for k, val in x['q'].items():
            assert abs(e.cantidades[k][0] - val) < 1e-9, (e.nombre, k)


def test_reglas_de_metrado():
    m = bim.leer_ifc(os.path.join(FX, 'IFC2X3_ft.ifc'))
    n = {e.nombre: e for e in m.elementos}
    assert n['Muro ñ 0'].medida == 'NetSideArea' and abs(n['Muro ñ 0'].metrado[0] - 8) < 1e-9
    assert n['Muro ñ 0'].material == 'Ladrillo + Tarrajeo'
    assert n['Solo bruto'].avisos == [bim.BRUTA]          # con vano y sin neta
    assert abs(n['C0'].metrado[0] - .25) < 1e-9            # del tipo
    assert abs(n['C1'].metrado[0] - .30) < 1e-9            # lo suyo manda
    assert n['Viga sin nada'].metrado is None and n['Viga sin nada'].avisos == [bim.SIN_CANTIDAD]
    assert n['Techo'].conjunto and n['Faldón'].metrado[1] == 'm2'
    assert n['P'].parte_de == n['CW'].global_id            # no se cuenta dos veces
    assert n['P-1'].metrado == (1.0, 'und')


def test_no_se_suman_unidades_distintas_ni_se_inventa_el_uno():
    """El importador viejo sumaba m3 + m2 de la viga y ponía 1.0 a la que no
    traía cantidad."""
    ruta = os.path.join(FX, 'IFC4_mm.ifc')
    vigas = [p for p in bim.proponer_partidas(bim.leer_ifc(ruta)) if p['clase'] == 'IfcBeam']
    assert sorted((p['unidad'], p['metrado'], len(p['sin_cantidad'])) for p in vigas) == [
        ('m2', 7.0, 0), ('m3', 0.5, 1)]
    info, partidas = parse_ifc(ruta)
    muro = next(p for p in partidas if 'Ladrillo KK' in p['descripcion'])
    assert (muro['unidad'], muro['metrado']) == ('m2', 31.5)     # neta, en m2 y no mm2
    assert info['nombre'].startswith('Edificio Peñón')
    assert not any(p['metrado'] == 1 and p['unidad'] != 'und' for p in partidas)


def test_modelo_sin_unidades_avisa(tmp_path):
    f = tmp_path / 'x.ifc'
    f.write_text("ISO-10303-21;\nDATA;\n#1=IFCWALL('g',$,'M',$,$,$,$,$);"
                 "#2=IFCQUANTITYAREA('NetSideArea',$,$,5.);"
                 "#3=IFCELEMENTQUANTITY('q',$,'BaseQuantities',$,$,(#2));"
                 "#4=IFCRELDEFINESBYPROPERTIES('r',$,$,$,(#1),#3);\nENDSEC;\n")
    m = bim.leer_ifc(f)
    assert m.elementos[0].metrado == (5.0, 'm2') and 'AREAUNIT' in m.avisos[0]
    with pytest.raises(ValueError):
        (tmp_path / 'n.ifc').write_text('hola')
        bim.leer_ifc(tmp_path / 'n.ifc')


def test_el_takeoff_y_el_ifc_de_ingetrazo_dicen_lo_mismo():
    a, b = bim.leer_ifc(IFC_IT), bim.leer_takeoff(TAKEOFF)
    ea, eb = ({e.global_id: e for e in m.elementos} for m in (a, b))
    assert len(ea) == 15 and set(ea) == set(eb)
    for g in ea:
        assert ea[g].clase == eb[g].clase and set(ea[g].cantidades) == set(eb[g].cantidades)
        assert (ea[g].metrado is None) == (eb[g].metrado is None)
    for malo in ({}, {'schema': 'inge-takeoff', 'version': 2}):
        with pytest.raises(ValueError):
            bim.leer_takeoff(malo)


def test_takeoff_nunca_inventa():
    d = {'schema': 'inge-takeoff', 'version': 1, 'elements': [
        {'global_id': 'a', 'ifc_class': 'IfcWall', 'metrado': None,
         'quantities': {'NetSideArea': {'value': 0, 'unit': 'm2'}, 'X': {'value': None, 'unit': 'm'}}},
        {'global_id': 'a', 'ifc_class': 'IfcWall'}, {'ifc_class': 'IfcWall'}]}
    m = bim.leer_takeoff(d)
    assert len(m.elementos) == 1 and m.elementos[0].cantidades == {} and m.elementos[0].metrado is None
    assert len(m.avisos) == 3


# ── Vínculos ─────────────────────────────────────────────────────────────────

def test_vincular_una_fila_por_elemento_y_desvincular(base):
    pid = _proyecto()
    m = bim.leer_takeoff(TAKEOFF)
    mid = bim.registrar_modelo(pid, m, 'a.igz')
    assert bim.registrar_modelo(pid, m) == mid                 # misma huella
    assert len(bim.elementos(mid)) == 15
    part = _partida(pid, 'm²')
    r = bim.vincular(part, mid, _muros(m))
    assert r['vinculados'] == 2 and r['omitidos'] == [] and _met(part) == 25.38
    assert len(_q("SELECT 1 FROM metrados_detalle WHERE partida_id=?", part)) == 2
    assert [m_ for _g, m_ in bim.vincular(part, mid, _muros(m) + ['nada'])['omitidos']]
    assert bim.partidas_de(mid, _muros(m)[0]) == [part]
    v = bim.vinculos_partida(part)
    assert v[0]['elemento'].clase == 'IfcWall' and not v[0]['editada']
    _x("INSERT INTO metrados_detalle (partida_id, orden, descripcion, n_elementos, parcial) "
       "VALUES (?,9,'a mano',5,5)", part)
    assert bim.desvincular(part, mid, _muros(m)[:1]) == 1
    assert _met(part) == 17.69
    assert [x[0] for x in _q("SELECT descripcion FROM metrados_detalle WHERE partida_id=? ORDER BY orden",
                             part)][-1] == 'a mano'


def test_vincular_respeta_unidades_factor_y_lo_escrito_a_mano(base):
    pid = _proyecto()
    m = bim.leer_takeoff(TAKEOFF)
    mid = bim.registrar_modelo(pid, m)
    z = [e.global_id for e in m.elementos if e.clase == 'IfcFooting']
    m2 = _partida(pid, 'm2')
    assert bim.vincular(m2, mid, z, 'GrossVolume')['vinculados'] == 0        # m3 en m2
    assert bim.vincular(m2, mid, z, 'GrossVolume', 0.5)['metrado'] == 1.2    # con factor sí
    kg = _partida(pid, 'bol', item='01.02')
    assert bim.vincular(kg, mid, z)['vinculados'] == 0                       # ¿qué medida?
    assert bim.vincular(kg, mid, z, 'GrossVolume', 7.5)['metrado'] == 18
    abierta = [e.global_id for e in m.elementos if 'abierta' in e.nombre]
    m3 = _partida(pid, 'm3', item='01.03')
    assert bim.vincular(m3, mid, abierta)['omitidos'][0][0] == abierta[0]
    amano = _partida(pid, 'm2', item='01.04', metrado=99)
    with pytest.raises(bim.MetradoManual):
        bim.vincular(amano, mid, _muros(m))
    assert _met(amano) == 99 and not _q("SELECT 1 FROM bim_vinculos WHERE partida_id=?", amano)
    assert bim.vincular(amano, mid, _muros(m), reemplazar_manual=True)['metrado'] == 25.38
    with pytest.raises(ValueError):
        bim.vincular(amano, mid, z, factor=0)


def test_borrar_la_fila_deshace_el_vinculo_y_guardar_la_planilla_no(base):
    pid = _proyecto()
    m = bim.leer_takeoff(TAKEOFF)
    mid = bim.registrar_modelo(pid, m)
    part = _partida(pid, 'm2')
    bim.vincular(part, mid, _muros(m))
    filas = [(r['id'], r['orden'], r['descripcion'] + ' retocada', None, None, r['area'], None, None,
              None, r['parcial']) for r in _q("SELECT * FROM metrados_detalle WHERE partida_id=?", part)]
    c = bd.get_db()
    bd.guardar_filas_metrado(c, part, filas[:1] + [(None, 7, 'nueva', None, 2, None, None, None, None, 2)])
    c.commit()
    c.close()
    assert len(bim.vinculos_partida(part)) == 1
    assert len(_q("SELECT 1 FROM metrados_detalle WHERE partida_id=?", part)) == 2


def test_la_planilla_de_la_vista_conserva_los_vinculos(base):
    """El panel de metrados borraba y reinsertaba todas las filas al guardar:
    cualquier tecla deshacía los vínculos."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    pid = _proyecto()
    m = bim.leer_takeoff(TAKEOFF)
    mid = bim.registrar_modelo(pid, m)
    part = _partida(pid, 'm2')
    bim.vincular(part, mid, _muros(m))
    from views.proyecto_view import ProyectoView
    from models.usuario import Usuario
    v = ProyectoView(pid, Usuario(id=1, nombre='t', rol='admin'))
    try:
        for _ in range(60):
            app.processEvents()
            if hasattr(v, '_id_to_item'):
                break
            import time
            time.sleep(.02)
        v._met_modo = 'met'
        v.cargar_metrados(part)
        v._metrado_guardar_silencioso()
        assert len(bim.vinculos_partida(part)) == 2
        v._met_insertar_fila(0)
        v.tbl_met.item(0, 0).setText('a mano')
        v.tbl_met.item(0, 2).setText('3')
        v._metrado_guardar_silencioso()
        assert len(bim.vinculos_partida(part)) == 2 and round(_met(part), 2) == 28.38
        v.tbl_met.removeRow(1)
        v._metrado_guardar_silencioso()
        assert len(bim.vinculos_partida(part)) == 1
    finally:
        v.deleteLater()
        app.processEvents()


# ── Actualizar ───────────────────────────────────────────────────────────────

def _v2():
    d = copy.deepcopy(TAKEOFF)
    els = d['elements']
    muros = [e for e in els if e['ifc_class'] == 'IfcWall']
    for k in ('NetSideArea',):
        muros[0]['quantities'][k]['value'] = 10.0
    muros[0]['metrado']['value'] = 10.0
    els.remove(muros[1])
    n = copy.deepcopy(muros[0])
    n['global_id'] = 'N' * 22
    n['metrado']['value'] = n['quantities']['NetSideArea']['value'] = 3.0
    els.append(n)
    return d, muros[0]['global_id'], muros[1]['global_id']


def test_diferencias_y_aplicar(base):
    pid = _proyecto()
    m = bim.leer_takeoff(TAKEOFF)
    mid = bim.registrar_modelo(pid, m)
    part, otra = _partida(pid, 'm2'), _partida(pid, 'm2', item='01.02')
    bim.vincular(part, mid, _muros(m))
    bim.vincular(otra, mid, _muros(m), None, 2.0)               # tarrajeo 2 caras
    _x("INSERT INTO metrados_detalle (partida_id, orden, descripcion, n_elementos, parcial) "
       "VALUES (?,9,'a mano',5,5)", part)
    _x("UPDATE partidas SET metrado=30.38 WHERE id=?", part)
    d, cambiado, borrado = _v2()
    nuevo = bim.leer_takeoff(d)
    dif = bim.diferencias(mid, nuevo)
    assert [e.global_id for e in dif['nuevos']] == ['N' * 22]
    assert [e.global_id for e in dif['borrados']] == [borrado]
    assert [(c['global_id'], c['campos']) for c in dif['cambiados']] == [
        (cambiado, ['NetSideArea', 'metrado'])]
    assert len(dif['iguales']) == 13
    assert [(p['partida_id'], p['antes'], p['despues']) for p in dif['partidas']] == [
        (part, 30.38, 15.0), (otra, 50.76, 20.0)]
    assert dif['sugerencias'] == {}                # ambiguo: está en dos partidas
    assert _met(part) == 30.38                     # no escribió nada
    r = bim.aplicar(mid, nuevo, [part], nuevos={'N' * 22: part})
    assert (r['actualizadas'], r['borradas'], r['vinculados']) == (1, 1, 1)
    assert _met(part) == 18.0 and _met(otra) == 50.76
    assert 'a mano' in [x[0] for x in _q("SELECT descripcion FROM metrados_detalle WHERE partida_id=?", part)]
    # La no elegida sigue pendiente y se puede aplicar después.
    dif = bim.diferencias(mid, nuevo)
    assert dif['cambiados'] == [] and [p['partida_id'] for p in dif['partidas']] == [otra]
    bim.aplicar(mid, nuevo)
    assert _met(otra) == 20.0 and bim.diferencias(mid, nuevo)['partidas'] == []


def test_lo_editado_a_mano_no_se_pisa(base):
    pid = _proyecto()
    m = bim.leer_takeoff(TAKEOFF)
    mid = bim.registrar_modelo(pid, m)
    part = _partida(pid, 'm2')
    bim.vincular(part, mid, _muros(m))
    d, cambiado, borrado = _v2()
    for g, val in ((cambiado, 77), (borrado, 88)):
        _x("UPDATE metrados_detalle SET area=?, parcial=? WHERE id=(SELECT metrado_detalle_id "
           "FROM bim_vinculos WHERE global_id=?)", val, val, g)
    nuevo = bim.leer_takeoff(d)
    assert bim.diferencias(mid, nuevo)['partidas'][0]['editadas'] == 2
    assert bim.aplicar(mid, nuevo)['editadas'] == 2
    assert sorted(x[0] for x in _q("SELECT area FROM metrados_detalle WHERE partida_id=?", part)) == [77, 88]


def test_ifc_frente_a_takeoff_no_es_un_cambio(base):
    """Piso, tipo, capa y material dependen de la vía: no cuentan."""
    pid = _proyecto()
    mid = bim.registrar_modelo(pid, bim.leer_takeoff(TAKEOFF))
    part = _partida(pid, 'm2')
    bim.vincular(part, mid, _muros(bim.leer_takeoff(TAKEOFF)))
    ifc = bim.leer_ifc(IFC_IT)
    dif = bim.diferencias(mid, ifc)
    assert not (dif['nuevos'] or dif['borrados'] or dif['cambiados'] or dif['partidas'])
    bim.aplicar(mid, ifc)
    e = next(x for x in bim.elementos(mid) if x.clase == 'IfcWall')
    assert e.piso == 'Storey' and e.capa == 'Muros' and e.material == 'Ladrillo'


def test_sugerencia_para_los_nuevos_y_medida_que_desaparece(base):
    pid = _proyecto()
    m = bim.leer_takeoff(TAKEOFF)
    mid = bim.registrar_modelo(pid, m)
    part = _partida(pid, 'm2')
    bim.vincular(part, mid, _muros(m), 'NetSideArea')
    d, _c, _b = _v2()
    for e in d['elements']:
        if e['ifc_class'] == 'IfcWall' and e['global_id'] != 'N' * 22:
            del e['quantities']['NetSideArea']
    dif = bim.diferencias(mid, bim.leer_takeoff(d))
    assert dif['sugerencias'] == {'N' * 22: part}
    p, = dif['partidas']
    assert (p['sin_medida'], p['borrar'], p['despues']) == (1, 1, 12.69)    # no se inventa


def test_aplicar_es_todo_o_nada(base, monkeypatch):
    pid = _proyecto()
    m = bim.leer_takeoff(TAKEOFF)
    mid = bim.registrar_modelo(pid, m)
    part = _partida(pid, 'm2')
    bim.vincular(part, mid, _muros(m))
    d, _c, _b = _v2()
    monkeypatch.setattr(bim, '_guardar_elementos', lambda *a: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        bim.aplicar(mid, bim.leer_takeoff(d))
    assert _met(part) == 25.38 and len(bim.vinculos_partida(part)) == 2 and len(bim.elementos(mid)) == 15


# ── Crear y copiar ───────────────────────────────────────────────────────────

def test_crear_proyecto_y_anadir(base):
    m = bim.leer_ifc(IFC_IT)
    pid = bim.crear_proyecto(m, IFC_IT)
    hojas = _q("SELECT * FROM partidas WHERE proyecto_id=? AND es_titulo=0", pid)
    assert len(hojas) == 7 and len(_q("SELECT 1 FROM bim_vinculos")) == 14
    col = next(h for h in hojas if h['descripcion'].startswith('COLUMNA'))
    assert col['unidad'] == 'm3' and abs(col['metrado'] - 1.12) < 1e-9      # planilla a 2 decimales
    mid, ids = bim.anadir_partidas(pid, m)
    assert bim.modelos(pid)[0]['id'] == mid and len(ids) == 7
    items = [r[0] for r in _q("SELECT item FROM partidas WHERE proyecto_id=?", pid)]
    assert len(items) == len(set(items))
    assert len(bim.modelos(pid)) == 1


def test_sugerir_y_poner_acu(base):
    cu = _x("INSERT INTO biblioteca_cu (descripcion, unidad, rendimiento, costo_unitario, grupo) "
            "VALUES ('MURO DE LADRILLO KK SOGA','m2',9,50,'')")
    _x("INSERT INTO biblioteca_cu (descripcion, unidad, grupo) VALUES ('MURO DE LADRILLO','m3','')")
    rec = _x("INSERT INTO recursos (codigo, descripcion, tipo, unidad, precio) "
             "VALUES ('1700001','LADRILLO','MAT','und',1.5)")
    _x("INSERT INTO biblioteca_acu_items (cu_id, recurso_id, cantidad, precio) VALUES (?,?,40,1.5)", cu, rec)
    s = bim.sugerir_biblioteca('MURO — Muro de ladrillo', 'm²')
    assert [x['descripcion'] for x in s] == ['MURO DE LADRILLO KK SOGA']
    part = _partida(_proyecto(), 'm2')
    assert bim.poner_acu(part, s[0]['origen'], s[0]['ref_id'])
    assert not bim.poner_acu(part, s[0]['origen'], s[0]['ref_id'])          # ya tiene ACU
    assert _q("SELECT precio_unitario, rendimiento FROM partidas WHERE id=?", part)[0][0] == 60


def _con_vinculos():
    pid = _proyecto()
    m = bim.leer_takeoff(TAKEOFF)
    mid = bim.registrar_modelo(pid, m, 'x.igz')
    part = _partida(pid, 'm2')
    bim.vincular(part, mid, _muros(m))
    return pid, mid, part


def _verificar_copia(pid2, mid_viejo=None):
    (m,) = bim.modelos(pid2)
    assert m['id'] != mid_viejo and m['n_elementos'] == 15 and m['n_vinculos'] == 2
    part = _q("SELECT id FROM partidas WHERE proyecto_id=? AND es_titulo=0", pid2)[0][0]
    v = bim.vinculos_partida(part)
    assert all(x['elemento'] and not x['editada'] and x['parcial'] == 12.69 for x in v)


def test_exportar_e_importar_db(base):
    from core.exporter import exportar_proyecto_db
    from core.ingepresupuestos_db_importer import importar_proyecto_db_directo
    pid, mid, _p = _con_vinculos()
    _x("INSERT INTO metrados_detalle (id, partida_id, parcial) VALUES (500, ?, 0)",
       _partida(_proyecto(), 'm2'))         # los ids de fila se corren
    ruta = str(base / 'exp.db')
    exportar_proyecto_db(pid, ruta)
    _verificar_copia(importar_proyecto_db_directo(ruta, pid), mid)


def test_importar_un_db_de_antes_del_bim(base):
    import sqlite3
    from core.exporter import exportar_proyecto_db
    from core.ingepresupuestos_db_importer import importar_proyecto_db_directo
    pid, _m, _p = _con_vinculos()
    ruta = str(base / 'viejo.db')
    exportar_proyecto_db(pid, ruta)
    c = sqlite3.connect(ruta)
    for t in ('bim_vinculos', 'bim_elementos', 'bim_modelos'):
        c.execute(f"DROP TABLE {t}")
    c.commit()
    c.close()
    nuevo = importar_proyecto_db_directo(ruta, pid)
    assert bim.modelos(nuevo) == [] and len(_q(
        "SELECT 1 FROM metrados_detalle md JOIN partidas p ON p.id=md.partida_id "
        "WHERE p.proyecto_id=?", nuevo)) == 2


def test_duplicar_proyecto(base):
    from views import dashboard_view as dv
    pid, mid, _p = _con_vinculos()
    c = bd.get_db()
    nuevo = dv._clonar_proyecto(c, pid, {'metrados'})
    c.commit()
    c.close()
    _verificar_copia(nuevo, mid)


def test_copiar_y_pegar(base):
    from utils import partidas_clipboard as pc
    pid, mid, part = _con_vinculos()
    c = bd.get_db()
    pc.copiar(c, [part], pid)
    otro = c.execute("INSERT INTO proyectos (nombre) VALUES ('otro')").lastrowid
    pc.pegar(c, otro, None, None)
    pc.pegar(c, pid, None, None)
    c.commit()
    c.close()
    _verificar_copia(otro, mid)
    assert len(bim.modelos(pid)) == 1 and bim.modelos(pid)[0]['n_vinculos'] == 4
    # Copiar no arrastra los cambios: borrar el modelo conserva los metrados.
    bim.eliminar_modelo(mid)
    assert _met(part) == 25.38 and len(_q("SELECT 1 FROM metrados_detalle WHERE partida_id=?", part)) == 2
