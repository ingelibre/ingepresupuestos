# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Sub-partidas (issue #23): núcleo, sin interfaz.

El proyecto de prueba tiene una sub-partida «Mortero» usada por dos partidas,
y un gemelo con el mismo análisis pero sin sub-partidas (insumos directos).

Usa una copia temporal del seed, nunca la BD activa.
"""
import os
import re
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import core.database as d                                           # noqa: E402
from core import subpartidas as SP                                  # noqa: E402

RAIZ = os.path.join(os.path.dirname(__file__), '..')
SEED = os.path.join(RAIZ, 'presupuestos_seed.db')


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """Cada prueba con su copia limpia: nada se cuela de una a otra."""
    db = str(tmp_path / 'p.db')
    shutil.copy(SEED, db)
    monkeypatch.setattr(d, 'DB_PATH', db)
    d.init_db()
    c = d.get_db()
    yield c
    c.close()


def _recurso(c, desc, tipo, unidad, precio, iu='39'):
    return c.execute(
        "INSERT INTO recursos (codigo, descripcion, tipo, unidad, precio, indice_inei)"
        " VALUES (?,?,?,?,?,?)", ('T' + desc[:6], desc, tipo, unidad, precio, iu)).lastrowid


def _partida(c, pid, item, desc, unidad, metrado):
    return c.execute(
        "INSERT INTO partidas (proyecto_id, item, descripcion, unidad, metrado, nivel,"
        " es_titulo, rendimiento) VALUES (?,?,?,?,?,1,0,10)",
        (pid, item, desc, unidad, metrado)).lastrowid


def _linea(c, part, rec, cant, cuad=0):
    c.execute("INSERT INTO acu_items (partida_id, recurso_id, cuadrilla, cantidad, precio)"
              " VALUES (?,?,?,?,(SELECT precio FROM recursos WHERE id=?))",
              (part, rec, cuad, cant, rec))


def _proyecto(c, nombre='ZZ sub-partidas'):
    """{pid, sub, a, b, rec}: «a» y «b» usan la sub-partida Mortero."""
    pid = c.execute("INSERT INTO proyectos (nombre, jornada_laboral, plazo) VALUES (?,8,60)",
                    (nombre,)).lastrowid
    rec = {
        'peon': _recurso(c, 'ZZ PEON', 'MO', 'hh', 17.35, '47'),
        'cem': _recurso(c, 'ZZ CEMENTO', 'MAT', 'bol', 23.17, '21'),
        'are': _recurso(c, 'ZZ ARENA', 'MAT', 'm3', 61.9, '04'),
        'mez': _recurso(c, 'ZZ MEZCLADORA', 'EQ', 'hm', 18.33, '48'),
        'her': _recurso(c, 'ZZ HERRAMIENTAS', 'EQ', '%mo', 0, '37'),
        'lad': _recurso(c, 'ZZ LADRILLO', 'MAT', 'und', 1.37, '17'),
    }
    sub = SP.crear(c, pid, 'ZZ MORTERO 1:4', 'm3', 8)
    for k, q in (('peon', 2.3333), ('cem', 8.91), ('are', 1.07), ('mez', 0.4444), ('her', 5)):
        _linea(c, sub, rec[k], q, 1 if k == 'peon' else 0)
    d._recalcular_pu(c, sub)
    a = _partida(c, pid, '01', 'ZZ MURO', 'm2', 137.43)
    b = _partida(c, pid, '02', 'ZZ TARRAJEO', 'm2', 211.07)
    for p, q in ((a, 0.0357), (b, 0.0171)):
        _linea(c, p, rec['peon'], 0.8, 1)
        _linea(c, p, rec['her'], 3)
        SP.enlazar(c, p, sub, q)
    _linea(c, a, rec['lad'], 39)
    for p in (a, b):
        d._recalcular_pu(c, p)
    c.commit()
    return {'pid': pid, 'sub': sub, 'a': a, 'b': b, 'rec': rec}


def _pu(c, part):
    return c.execute("SELECT precio_unitario FROM partidas WHERE id=?", (part,)).fetchone()[0]


def _cd(pid):
    return d.calcular_totales(pid)[1]['cd']


# ── Núcleo ──────────────────────────────────────────────────────────────────

def test_migracion_idempotente_y_proyectos_viejos_intactos(conn):
    antes = [tuple(r) for r in conn.execute("SELECT * FROM partidas ORDER BY id")]
    d.init_db()
    assert [tuple(r) for r in conn.execute("SELECT * FROM partidas ORDER BY id")] == antes
    assert conn.execute("SELECT COUNT(*) FROM partidas").fetchone()[0] \
        == conn.execute("SELECT COUNT(*) FROM partidas_ppto").fetchone()[0]


def test_la_vista_ve_las_columnas_que_se_agregan_despues(conn):
    conn.execute("ALTER TABLE partidas ADD COLUMN zz_nueva TEXT")
    assert 'zz_nueva' in conn.execute("SELECT * FROM partidas_ppto LIMIT 1").fetchone().keys()


def test_suma_de_insumos_es_el_cd_con_sub_partidas(conn):
    x = _proyecto(conn)
    ins = d.get_insumos_proyecto(conn, x['pid'])
    assert round(sum(i['parcial_total'] for i in ins), 2) == round(_cd(x['pid']), 2) > 0
    nombres = {i['descripcion'] for i in ins}
    assert 'ZZ CEMENTO' in nombres and SP.DESC_RECURSO not in nombres
    assert 'ZZ MORTERO 1:4' not in nombres


def test_cantidad_explotada_es_hoja_por_sub_por_metrado(conn):
    x = _proyecto(conn)
    ins = {i['descripcion']: i for i in d.get_insumos_proyecto(conn, x['pid'])}
    assert ins['ZZ CEMENTO']['cantidad_total'] == pytest.approx(
        8.91 * (0.0357 * 137.43 + 0.0171 * 211.07), abs=0.011)
    # La misma cantidad aparece en los directos y en la sub-partida: se suman.
    assert ins['ZZ PEON']['cantidad_total'] == pytest.approx(
        0.8 * (137.43 + 211.07)
        + d.cantidad_acu(2.3333, 'MO') * (0.0357 * 137.43 + 0.0171 * 211.07), abs=0.011)


def test_por_partida_cuadra_con_el_detalle(conn):
    x = _proyecto(conn)
    ins = d.get_insumos_para_partidas(conn, [x['a'], x['b']], detallar_partidas=True)
    for i in ins:
        assert sum(p['monto'] for p in i['por_partida'].values()) == pytest.approx(
            i['parcial_total'], abs=0.03)
        assert x['sub'] not in i['por_partida']


def test_no_hay_doble_conteo_en_el_costo_directo(conn):
    x = _proyecto(conn)
    esperado = sum(d.parcial_wysiwyg(m, _pu(conn, p))
                   for p, m in ((x['a'], 137.43), (x['b'], 211.07)))
    assert _cd(x['pid']) == pytest.approx(esperado)
    items, _ = d.calcular_totales(x['pid'])
    assert x['sub'] not in {i['partida']['id'] for i in items}


def test_la_sub_partida_no_cuenta_aunque_alguien_le_ponga_metrado(conn):
    x = _proyecto(conn)
    cd = _cd(x['pid'])
    conn.execute("UPDATE partidas SET metrado=99 WHERE id=?", (x['sub'],))
    conn.commit()
    assert _cd(x['pid']) == cd
    ins = d.get_insumos_proyecto(conn, x['pid'])
    assert round(sum(i['parcial_total'] for i in ins), 2) == round(cd, 2)


def test_entra_como_bloque_sc_y_no_en_la_base_de_mo(conn):
    x = _proyecto(conn)
    items, tt = d.get_acu_items(conn, x['a'])
    linea = next(i for i in items if i['sub_partida_id'])
    assert linea['tipo'] == 'SC' and linea['descripcion'] == 'ZZ MORTERO 1:4'
    assert linea['unidad'] == 'm3' and linea['precio'] == _pu(conn, x['sub'])
    assert tt['SC'] == linea['parcial'] > 0
    her = next(i for i in items if i['unidad'] == '%mo')
    assert her['precio'] == d._rn(0.8 * 17.35, 2)      # solo la MO propia
    assert sum(tt.values()) == pytest.approx(_pu(conn, x['a']))


def test_cascada_al_cambiar_un_insumo_de_la_sub_partida(conn):
    x = _proyecto(conn)
    antes = _pu(conn, x['a']), _pu(conn, x['b'])
    d.unificar_precio_recurso(conn, x['pid'], x['rec']['cem'], 40.0)
    conn.commit()
    assert _pu(conn, x['a']) > antes[0] and _pu(conn, x['b']) > antes[1]
    linea = next(i for i in d.get_acu_items(conn, x['a'])[0] if i['sub_partida_id'])
    assert linea['precio'] == _pu(conn, x['sub'])
    assert d.partidas_pu_inconsistente(conn, x['pid']) == []
    ins = d.get_insumos_proyecto(conn, x['pid'])
    assert round(sum(i['parcial_total'] for i in ins), 2) == round(_cd(x['pid']), 2)


def test_un_ciclo_en_la_base_no_cuelga_el_recalculo(conn):
    x = _proyecto(conn)
    s2 = SP.crear(conn, x['pid'], 'ZZ OTRA', 'm3')
    rid = SP.recurso_subpartida(conn)
    for padre, hijo in ((x['sub'], s2), (s2, x['sub'])):
        conn.execute("INSERT INTO acu_items (partida_id, recurso_id, cantidad, precio,"
                     " sub_partida_id) VALUES (?,?,1,1,?)", (padre, rid, hijo))
    assert d._recalcular_pu(conn, x['sub']) > 0
    d.get_insumos_proyecto(conn, x['pid'])
    d.partidas_pu_inconsistente(conn, x['pid'])


def test_un_solo_nivel_y_sin_autorreferencia(conn):
    x = _proyecto(conn)
    s2 = SP.crear(conn, x['pid'], 'ZZ OTRA', 'm3')
    with pytest.raises(ValueError, match='no puede contener otra'):
        SP.enlazar(conn, s2, x['sub'])
    with pytest.raises(ValueError, match='sí misma'):
        SP.enlazar(conn, x['sub'], x['sub'])
    with pytest.raises(ValueError, match='no puede contener otra'):
        SP.crear_desde_partida(conn, x['pid'], x['a'])
    with pytest.raises(ValueError):
        SP.enlazar(conn, x['a'], x['b'])            # no es sub-partida
    y = _proyecto(conn, 'ZZ otro')
    with pytest.raises(ValueError, match='otro proyecto'):
        SP.enlazar(conn, x['a'], y['sub'])


def test_validacion_de_la_ficha(conn):
    x = _proyecto(conn)
    for desc, und in (('', 'm3'), ('ZZ mortero 1:4 ', 'm3'), ('ZZ X', '%mo')):
        with pytest.raises(ValueError):
            SP.crear(conn, x['pid'], desc, und)


def test_pu_inconsistente_mira_el_costo_del_hijo(conn):
    x = _proyecto(conn)
    assert d.partidas_pu_inconsistente(conn, x['pid']) == []
    # Precio de la línea desfasado: manda el hijo, no marca a los padres.
    conn.execute("UPDATE acu_items SET precio=0 WHERE sub_partida_id=?", (x['sub'],))
    assert d.partidas_pu_inconsistente(conn, x['pid']) == []


def test_las_herramientas_de_precio_no_tocan_la_linea(conn):
    x = _proyecto(conn)
    s2 = SP.crear(conn, x['pid'], 'ZZ OTRA', 'm3')
    _linea(conn, s2, x['rec']['cem'], 1)
    d._recalcular_pu(conn, s2)
    SP.enlazar(conn, x['a'], s2, 1)
    rid = SP.recurso_subpartida(conn)
    assert rid not in d.precios_inconsistentes(conn, x['pid'])
    antes = [r[0] for r in conn.execute("SELECT precio FROM acu_items WHERE sub_partida_id"
                                        " IS NOT NULL ORDER BY id")]
    d.unificar_precio_recurso(conn, x['pid'], rid, 1.0)
    assert antes == [r[0] for r in conn.execute("SELECT precio FROM acu_items WHERE"
                                                " sub_partida_id IS NOT NULL ORDER BY id")]


def test_sub_partida_sin_analisis_no_pierde_monto(conn):
    x = _proyecto(conn)
    conn.execute("DELETE FROM acu_items WHERE partida_id=?", (x['sub'],))
    ins = d.get_insumos_para_partidas(conn, [x['a']])
    assert 'ZZ MORTERO 1:4' in {i['descripcion'] for i in ins}
    assert round(sum(i['parcial_total'] for i in ins), 2) \
        == d.parcial_wysiwyg(137.43, _pu(conn, x['a']))


def test_eliminar_en_uso_avisa_y_forzar_recalcula(conn):
    x = _proyecto(conn)
    with pytest.raises(ValueError, match='01, 02'):
        SP.eliminar(conn, x['sub'])
    antes = _pu(conn, x['a'])
    assert set(SP.eliminar(conn, x['sub'], forzar=True)) == {x['a'], x['b']}
    assert _pu(conn, x['a']) < antes
    assert SP.listar(conn, x['pid']) == []
    with pytest.raises(ValueError):
        SP.eliminar(conn, x['a'], forzar=True)      # una partida normal, jamás


# ── Copias ──────────────────────────────────────────────────────────────────

def _insumos(c, pid):
    return [(i['descripcion'], i['cantidad_total'], i['parcial_total'])
            for i in d.get_insumos_proyecto(c, pid)]


def test_copiar_y_pegar_entre_proyectos(conn):
    from utils import partidas_clipboard as K
    x = _proyecto(conn)
    dst = conn.execute("INSERT INTO proyectos (nombre) VALUES ('ZZ destino')").lastrowid
    assert K.copiar(conn, [x['a'], x['b']], x['pid']) == 2
    K.pegar(conn, dst, None)
    conn.commit()
    assert len(SP.listar(conn, dst)) == 1           # una sola, compartida
    assert _cd(dst) == _cd(x['pid'])
    assert _insumos(conn, dst) == _insumos(conn, x['pid'])
    # Pegar otra vez no duplica la sub-partida.
    K.pegar(conn, dst, None)
    assert len(SP.listar(conn, dst)) == 1
    # Y el original no se entera de los cambios de la copia.
    d.unificar_precio_recurso(conn, dst, x['rec']['cem'], 99)
    assert d.partidas_pu_inconsistente(conn, x['pid']) == []


def test_pegar_en_el_mismo_proyecto_reusa_la_sub_partida(conn):
    from utils import partidas_clipboard as K
    x = _proyecto(conn)
    K.copiar(conn, [x['a']], x['pid'])
    K.pegar(conn, x['pid'], None)
    assert [s['n_usos'] for s in SP.listar(conn, x['pid'])] == [3]


def test_pegar_con_gemela_distinta_crea_otra(conn):
    from utils import partidas_clipboard as K
    x = _proyecto(conn)
    y = _proyecto(conn, 'ZZ destino')
    conn.execute("UPDATE acu_items SET cantidad=cantidad*2 WHERE partida_id=?", (y['sub'],))
    K.copiar(conn, [x['a']], x['pid'])
    K.pegar(conn, y['pid'], None)
    assert {s['descripcion'] for s in SP.listar(conn, y['pid'])} \
        == {'ZZ MORTERO 1:4', 'ZZ MORTERO 1:4 (2)'}


def test_copiar_sub_presupuesto_no_arrastra_las_sub_partidas_como_partidas(conn):
    from utils import partidas_clipboard as K
    x = _proyecto(conn)
    dst = conn.execute("INSERT INTO proyectos (nombre) VALUES ('ZZ destino')").lastrowid
    assert K.copiar_subppto(conn, x['pid'], None, 'Principal') == 2
    K.pegar_subppto(conn, dst, None)
    conn.commit()
    assert _cd(dst) == _cd(x['pid'])
    assert len(SP.listar(conn, dst)) == 1


def test_duplicar_proyecto(conn):
    from views.dashboard_view import _clonar_proyecto as dup
    x = _proyecto(conn)
    nuevo = dup(conn, x['pid'], set())
    conn.commit()
    assert _cd(nuevo) == _cd(x['pid'])
    assert _insumos(conn, nuevo) == _insumos(conn, x['pid'])
    subs = {s['id'] for s in SP.listar(conn, nuevo)}
    usadas = {r[0] for r in conn.execute(
        "SELECT ai.sub_partida_id FROM acu_items ai JOIN partidas p ON p.id=ai.partida_id"
        " WHERE p.proyecto_id=? AND ai.sub_partida_id IS NOT NULL", (nuevo,))}
    assert usadas == subs and x['sub'] not in subs
    # Borrar el original no deja nada colgando ni toca la copia.
    conn.execute("DELETE FROM proyectos WHERE id=?", (x['pid'],))
    conn.commit()
    assert conn.execute("PRAGMA foreign_key_check(acu_items)").fetchall() == []
    assert len(SP.listar(conn, nuevo)) == 1


def test_exportar_e_importar_db(conn, tmp_path):
    from core.exporter import exportar_proyecto_db
    from core import ingepresupuestos_db_importer as imp
    x = _proyecto(conn)
    f = str(tmp_path / 'x.db')
    exportar_proyecto_db(x['pid'], f)
    info = [i for i in imp.listar_proyectos_db(f) if i['id_ppto'] == x['pid']]
    assert len(info) == 1 and info[0]['n_partidas'] == 2
    nuevo = imp.importar_proyecto_db_directo(f, x['pid'])
    nuevo = nuevo['proyecto_id'] if isinstance(nuevo, dict) else nuevo
    assert _cd(nuevo) == _cd(x['pid'])
    assert _insumos(conn, nuevo) == _insumos(conn, x['pid'])
    sub = SP.listar(conn, nuevo)
    assert len(sub) == 1 and sub[0]['id'] != x['sub'] and sub[0]['n_usos'] == 2
    # La biblioteca recibe la línea aplanada con el nombre de la sub-partida.
    assert conn.execute(
        "SELECT COUNT(*) FROM biblioteca_acu_items b JOIN recursos r ON r.id=b.recurso_id"
        " WHERE r.codigo=?", (SP.CODIGO_RECURSO,)).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM biblioteca_acu_items b JOIN recursos r ON r.id=b.recurso_id"
        " WHERE r.descripcion='ZZ MORTERO 1:4' AND r.tipo='SC'").fetchone()[0] == 2


def test_importar_db_de_una_version_sin_sub_partidas(conn, tmp_path):
    """El seed no tiene las columnas nuevas: importa igual."""
    from core import ingepresupuestos_db_importer as imp
    f = str(tmp_path / 'viejo.db')
    shutil.copy(SEED, f)
    assert imp.listar_proyectos_db(f)
    r = imp.importar_proyecto_db_directo(f, 397)
    r = r['proyecto_id'] if isinstance(r, dict) else r
    assert _cd(r) == _cd(397)


def test_copiar_acu_desde_el_pool(conn):
    x = _proyecto(conn)
    dst = conn.execute("INSERT INTO proyectos (nombre) VALUES ('ZZ destino')").lastrowid
    p = _partida(conn, dst, '01', 'ZZ MURO', 'm2', 1)
    acu = d.acu_de_pool(conn, 'proj', x['a'])
    d.copiar_items_acu(conn, p, acu['items'], proyecto_id=dst)
    assert d._recalcular_pu(conn, p) == _pu(conn, x['a'])
    assert len(SP.listar(conn, dst)) == 1


def test_crear_desde_partida_y_desde_biblioteca(conn):
    pid = conn.execute("INSERT INTO proyectos (nombre) VALUES ('ZZ destino')").lastrowid
    p = conn.execute("SELECT p.* FROM partidas p WHERE p.proyecto_id=397 AND p.es_titulo=0"
                     " AND EXISTS (SELECT 1 FROM acu_items a WHERE a.partida_id=p.id)"
                     " LIMIT 1").fetchone()
    s = SP.crear_desde_partida(conn, pid, p['id'])
    assert len(d.get_acu_items(conn, s)[0]) == len(d.get_acu_items(conn, p['id'])[0])
    cu = conn.execute("SELECT cu_id FROM biblioteca_acu_items LIMIT 1").fetchone()
    if cu:
        assert SP.crear_desde_biblioteca(conn, pid, cu[0])
    conn.commit()
    assert _cd(pid) == 0


# ── Periféricos ─────────────────────────────────────────────────────────────

def test_requerimientos_piden_insumos_no_la_sub_partida(conn):
    from core import requerimientos as R
    x = _proyecto(conn)
    filas = {f['descripcion']: f for f in R._insumos_presupuesto_filas(x['pid'])}
    assert 'ZZ CEMENTO' in filas and SP.DESC_RECURSO not in filas
    assert filas['ZZ CEMENTO']['cantidad'] == pytest.approx(
        8.91 * (0.0357 * 137.43 + 0.0171 * 211.07), abs=0.011)


def test_formula_polinomica_ve_la_mano_de_obra_interna(conn):
    from core import formula_polinomica as F
    x = _proyecto(conn)
    ins = d.get_insumos_proyecto(conn, x['pid'])
    mo = sum(i['parcial_total'] for i in ins if i['tipo'] == 'MO')
    eq = sum(i['parcial_total'] for i in ins if i['tipo'] == 'EQ')
    F.incidencias_por_iu(x['pid'])
    assert F.desglose_de_iu(x['pid'], '47')['monto'] == pytest.approx(mo, abs=0.05)
    r = F.calcular_desde_acu(x['pid'])
    assert r['ok'] and r['totales']['MO'] == pytest.approx(mo, rel=0.005)
    # El % de herramientas de dentro va sobre la MO de dentro, no del padre.
    assert r['totales']['EQ'] == pytest.approx(eq, rel=0.02)


def test_cronograma_valorizacion_y_curva_s_no_la_listan(conn):
    from core import curva_s, valorizacion
    x = _proyecto(conn)
    val = valorizacion.crear_valorizacion(x['pid'], '2026-01-01', '2026-01-31')
    val = val['id'] if isinstance(val, dict) else val
    filas, _ = valorizacion.get_valorizacion_detalle(val)
    assert x['sub'] not in {f.get('partida_id', f.get('id')) for f in filas}
    curva_s.curva_s_comparada(x['pid'])


def test_parte_diario_estima_con_los_insumos_de_dentro(conn):
    from core import parte_diario as PD
    x = _proyecto(conn)
    conn.execute("INSERT INTO parte_diario (id, proyecto_id, fecha) VALUES (9001,?,'2026-01-01')",
                 (x['pid'],))
    conn.execute("INSERT INTO parte_diario_metrado (parte_id, partida_id, metrado_dia)"
                 " VALUES (9001,?,10)", (x['a'],))
    conn.commit()
    est = PD.estimar_consumo_dia(9001)
    mat = {i['descripcion']: i['cantidad'] for i in est['mat']}
    assert mat['ZZ CEMENTO'] == pytest.approx(8.91 * 0.0357 * 10, abs=0.011)
    assert est['sc'] == []


def test_reportes_de_acu_salen_con_el_desglose(conn):
    import openpyxl
    from core import exporter as X
    x = _proyecto(conn)
    for fn in (X.exportar_acus, X.exportar_reporte_completo, X.exportar_insumos):
        wb = openpyxl.load_workbook(fn(x['pid']))
        txt = '\n'.join(str(v) for ws in wb for row in ws.iter_rows(values_only=True)
                        for v in row if v is not None)
        assert SP.DESC_RECURSO not in txt
        assert 'ZZ CEMENTO' in txt
    from PySide6.QtWidgets import QApplication
    _ = QApplication.instance() or QApplication([])
    from core import pdf_reports as P
    html = P._build_html_for('acus', x['pid'], None)[1]
    assert html.count('ZZ MORTERO 1:4') >= 3         # en a, en b y su propio análisis
    assert 'ZZ CEMENTO' in html
    pres = P._build_html_for('presupuesto', x['pid'], None)[1]
    assert 'ZZ MORTERO' not in pres
    adq = P._build_html_for('cronograma_adquisiciones', x['pid'], None)[1]
    assert 'ZZ CEMENTO' in adq and 'ZZ MORTERO' not in adq


# ── Guardia: ningún listado por proyecto lee `partidas` a secas ─────────────

def test_los_listados_por_proyecto_usan_la_vista():
    # Consultas que quedan fuera: recién importado o recálculo de precios
    # (core/importer, core/database), que no listan el presupuesto, y las
    # propias sub-partidas. `database` lista solo con la vista.
    FUERA = ('core/subpartidas.py', 'core/importer.py')
    patron = re.compile(r"FROM partidas\b(?! WHERE id)")
    sospechosos = []
    for base in ('core', 'views', 'utils', 'widgets'):
        for nombre in sorted(os.listdir(os.path.join(RAIZ, base))):
            if not nombre.endswith('.py'):
                continue
            ruta = f'{base}/{nombre}'
            lineas = open(os.path.join(RAIZ, ruta), encoding='utf-8').read().split('\n')
            for n, l in enumerate(lineas):
                if ruta in FUERA or not patron.search(l) or 'DELETE' in l \
                        or 'partida_id IN (SELECT id' in l:
                    continue
                if 'sub-partidas: incluidas' in '\n'.join(lineas[max(0, n - 4):n + 1]):
                    continue
                if 'FROM partidas WHERE proyecto_id=p.id' in l:
                    continue        # archivo ajeno: ahí no está la vista
                if 'proyecto_id' in '\n'.join(lineas[n:n + 4]):
                    sospechosos.append(f'{ruta}:{n + 1}: {l.strip()}')
    assert sospechosos == [], (
        'Usa `partidas_ppto`, o marca la consulta con un comentario '
        '«sub-partidas: incluidas» si debe verlas:\n' + '\n'.join(sospechosos))
