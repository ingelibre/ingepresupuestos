# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Tests de las reglas críticas de negocio (sin GUI).

Corre con:  venv/bin/python3 tests/test_reglas_negocio.py

Usa una COPIA temporal de presupuestos_seed.db (nunca la BD activa).
Protege las reglas de «Reglas críticas de negocio» de CLAUDE.md:
redondeo comercial, parcial WYSIWYG, decimales por ámbito, suma del ACU
(incl. overhead %MO/%MAT), recálculo de PU, detector PU≠ACU y coherencia
de calcular_totales.
"""
import sys, os, shutil, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import core.database as d

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')

_tmpdb = None

def _db_seed():
    """Copia temporal del seed; get_db() queda apuntando a ella."""
    global _tmpdb
    if _tmpdb is None:
        fd, _tmpdb = tempfile.mkstemp(suffix='_test.db')
        os.close(fd)
        shutil.copy(SEED, _tmpdb)
        d.DB_PATH = _tmpdb
    return d.get_db()


# ── Redondeo comercial (half-up, criterio S10/Delphin) ──────────────────────

def test_redondeo_half_up():
    assert d._r2(2.675) == 2.68          # float binario 2.674999… debe subir
    assert d._r2(0.125) == 0.13
    assert d._r2(1.004) == 1.00
    assert d._rn(2.67449, 3) == 2.674
    assert d._rn(None) == 0.0
    assert d._rn(0.00005, 4) == 0.0001


# ── parcial_wysiwyg: metrado y monto con decimales propios ──────────────────

def test_parcial_wysiwyg_separa_ambitos():
    dm, dp = d._DECIMALES_METRADO, d._DECIMALES_PPTO
    try:
        d.set_decimales_metrado(2); d.set_decimales_ppto(2)
        # metrado visible 12.35 × 10.555 = 130.35385 → 130.35
        assert d.parcial_wysiwyg(12.34567, 10.555) == 130.35
        d.set_decimales_metrado(4)
        # metrado visible 12.3457 × 10.555 → 130.31
        assert d.parcial_wysiwyg(12.34567, 10.555) == 130.31
        # None / 0 no rompen
        assert d.parcial_wysiwyg(None, 10) == 0.0
        assert d.parcial_wysiwyg(10, None) == 0.0
    finally:
        d.set_decimales_metrado(dm); d.set_decimales_ppto(dp)


# ── Derivación de cantidad ACU: cuadrilla / rendimiento (× jornada) ─────────

def test_cantidad_derivada_cuadrilla():
    dc = d._DECIMALES_CANT_ACU
    try:
        d.set_decimales_cant_acu(4)
        n = d.get_decimales_cant_acu()
        # MO/EQ por hora: cant = cuadrilla / rendimiento × jornada
        assert d._rn(2 / 25 * 8, n) == 0.64
        assert d._rn(1 / 3.5 * 8, n) == 2.2857
        # MO/EQ por día: sin jornada
        assert d._rn(1 / 3.5, n) == 0.2857
    finally:
        d.set_decimales_cant_acu(dc)


# ── Clasificación canónica de insumos derivados de la cuadrilla ─────────────

def test_clasificacion_cantidad_cuadrilla():
    # MO y equipo por hora (hh/hm) → cantidad derivada de la cuadrilla.
    assert d.recurso_por_hora('MO', 'hh')
    assert d.recurso_por_hora('EQ', 'hm')          # ← el bug: hm DEBE contar
    assert d.recurso_por_hora('MO', 'día')         # MO siempre, cualquier unidad
    assert not d.recurso_por_hora('MAT', 'm3')
    assert not d.recurso_por_hora('EQ', 'día')     # equipo-día NO es por hora
    # Por día (día/jor) → derivado SIN jornada.
    assert d.recurso_por_dia('EQ', 'día')
    assert d.recurso_por_dia('MO', 'jor')
    assert not d.recurso_por_dia('MAT', 'día')     # material nunca se deriva
    # Partida global (glb/est/serv) → cantidad directa.
    assert d.partida_global('glb') and d.partida_global('EST')
    assert not d.partida_global('m3')


# ── Recálculo al cambiar rendimiento / jornada (incluye equipo por hora) ────

def _recalc_item(it, rend, jornada):
    """Réplica de la regla canónica de los handlers de rendimiento/jornada
    (proyecto_view._guardar_rendimiento, nuevo_proyecto_view, proyecto_form_dialog):
    devuelve la nueva cantidad, o la original si el insumo es de cantidad directa."""
    cuad = it['cuadrilla'] or 0
    if cuad <= 0:
        return it['cantidad']
    por_dia = d.recurso_por_dia(it['tipo'], it['unidad'])
    if not (por_dia or d.recurso_por_hora(it['tipo'], it['unidad'])):
        return it['cantidad']
    factor = 1 if por_dia else jornada
    return d._rn(cuad / rend * factor, d.get_decimales_cant_acu())


def test_recalculo_incluye_equipo_por_hora():
    """Regresión del bug hm: al cambiar rendimiento/jornada se recalculan MO Y
    equipo por hora (hm); MAT, equipo-día sin cuadrilla y overhead conservan su
    cantidad; la MO/EQ por día se recalcula SIN multiplicar por la jornada."""
    dc = d._DECIMALES_CANT_ACU
    try:
        d.set_decimales_cant_acu(4)
        items = [
            {'tipo': 'MO',  'unidad': 'hh',  'cuadrilla': 1.0, 'cantidad': 0.0267},  # quedó en rend 300
            {'tipo': 'EQ',  'unidad': 'hm',  'cuadrilla': 1.0, 'cantidad': 0.0267},  # ← el caso del bug
            {'tipo': 'MAT', 'unidad': 'gln', 'cuadrilla': 0.0, 'cantidad': 0.1202},  # directo
            {'tipo': 'EQ',  'unidad': 'día', 'cuadrilla': 0.0, 'cantidad': 5.0},     # equipo-día directo
            {'tipo': 'MO',  'unidad': 'día', 'cuadrilla': 1.0, 'cantidad': 99.0},    # MO-día (sin jornada)
            {'tipo': 'EQ',  'unidad': '%MO', 'cuadrilla': 0.0, 'cantidad': 3.0},     # overhead
        ]
        out = [_recalc_item(it, 200.0, 8) for it in items]
        assert out[0] == 0.04                  # MO hh:  1/200×8
        assert out[1] == 0.04                  # EQ hm:  recalculado igual que MO  ← clave
        assert out[2] == 0.1202                # MAT:    intacto
        assert out[3] == 5.0                   # EQ-día sin cuadrilla: intacto
        assert out[4] == d._rn(1 / 200, 4)     # MO-día: cuad/rend SIN jornada
        assert out[5] == 3.0                   # overhead %: intacto
    finally:
        d.set_decimales_cant_acu(dc)


# ── Suma del ACU: parciales redondeados + overhead %MO/%MAT al final ────────

def test_pu_desde_items_overhead():
    items = [
        {'cantidad': 2.0,  'precio': 10.0, 'unidad': 'hh',  'tipo': 'MO'},   # 20.00
        {'cantidad': 1.0,  'precio': 50.0, 'unidad': 'kg',  'tipo': 'MAT'},  # 50.00
        {'cantidad': 5.0,  'precio': 0.0,  'unidad': '%MO', 'tipo': 'EQ'},   # 5% de MO = 1.00
    ]
    assert d._pu_desde_items(items) == 71.0
    # %MAT usa la base de materiales
    items[2]['unidad'] = '%MAT'
    assert d._pu_desde_items(items) == 72.5
    # cada parcial se redondea ANTES de sumar (0.333×3 = 1.00, no 0.999→1.0)
    items3 = [{'cantidad': 0.333, 'precio': 1.0, 'unidad': 'u', 'tipo': 'MAT'}] * 3
    assert d._pu_desde_items(items3) == 0.99
    # tipo desconocido cae a MAT, no se pierde
    assert d._pu_desde_items([{'cantidad': 1, 'precio': 7, 'unidad': 'u', 'tipo': 'XX'}]) == 7.0


# ── _recalcular_pu y detector PU≠ACU sobre datos reales del seed ────────────

def _proyecto_sano(conn):
    """Primer proyecto del seed sin inconsistencias PU↔ACU."""
    for (prid,) in conn.execute("SELECT id FROM proyectos ORDER BY id"):
        if not d.partidas_pu_inconsistente(conn, prid):
            n = conn.execute(
                """SELECT COUNT(*) FROM partidas p WHERE p.proyecto_id=? AND p.es_titulo=0
                   AND EXISTS (SELECT 1 FROM acu_items ai WHERE ai.partida_id=p.id)""",
                (prid,)).fetchone()[0]
            if n > 5:
                return prid
    raise AssertionError("el seed no tiene ningún proyecto consistente PU↔ACU")

def test_detector_y_recalculo_pu():
    conn = _db_seed()
    try:
        prid = _proyecto_sano(conn)
        part = conn.execute(
            """SELECT p.id, p.precio_unitario FROM partidas p
               WHERE p.proyecto_id=? AND p.es_titulo=0
               AND EXISTS (SELECT 1 FROM acu_items ai WHERE ai.partida_id=p.id)
               AND p.precio_unitario > 1 LIMIT 1""", (prid,)).fetchone()
        pu_bueno = part['precio_unitario']

        # 1. romper el PU → el detector lo encuentra
        conn.execute("UPDATE partidas SET precio_unitario=? WHERE id=?",
                     (pu_bueno + 100, part['id']))
        inc = d.partidas_pu_inconsistente(conn, prid)
        assert any(x['partida_id'] == part['id'] for x in inc), "detector no vio el PU roto"
        roto = next(x for x in inc if x['partida_id'] == part['id'])
        assert roto['pu_acu'] == pu_bueno

        # 2. _recalcular_pu lo repara y el detector vuelve a 0
        nuevo = d._recalcular_pu(conn, part['id'])
        assert nuevo == pu_bueno
        assert not any(x['partida_id'] == part['id']
                       for x in d.partidas_pu_inconsistente(conn, prid))

        # 3. partida sin ACU (PU manual) nunca aparece en el detector
        conn.execute("UPDATE partidas SET precio_unitario=? WHERE id=?",
                     (pu_bueno + 100, part['id']))
        conn.execute("DELETE FROM acu_items WHERE partida_id=?", (part['id'],))
        assert not any(x['partida_id'] == part['id']
                       for x in d.partidas_pu_inconsistente(conn, prid))
        conn.rollback()
    finally:
        conn.close()


# ── calcular_totales: coherencia CD / total ─────────────────────────────────

def test_calcular_totales_coherente():
    conn = _db_seed()
    try:
        prid = _proyecto_sano(conn)
    finally:
        conn.close()
    items, t = d.calcular_totales(prid)
    assert t['cd'] > 0
    # CD = suma de parciales WYSIWYG de las partidas hoja
    cd_manual = sum(d.parcial_wysiwyg(e['partida']['metrado'],
                                      e['partida']['precio_unitario'])
                    for e in items if not e['partida']['es_titulo'])
    assert abs(t['cd'] - cd_manual) < 0.01, (t['cd'], cd_manual)
    # Presupuesto Total = CD + GG + utilidad + IGV — nunca menor que el CD
    assert t['total'] >= t['cd'] - 0.01
    assert t['igv'] >= 0 and t['subtotal'] >= t['cd'] - 0.01


# ── Precios por proyecto: COALESCE(ai.precio, r.precio, 0) ──────────────────

def test_precio_coalesce():
    conn = _db_seed()
    try:
        prid = _proyecto_sano(conn)
        row = conn.execute(
            """SELECT ai.id, ai.partida_id, ai.precio, r.precio AS cat
               FROM acu_items ai
                 JOIN partidas p ON p.id=ai.partida_id
                 JOIN recursos r ON r.id=ai.recurso_id
               WHERE p.proyecto_id=? AND r.precio > 0
                 AND SUBSTR(COALESCE(r.unidad,''),1,1) != '%' LIMIT 1""",
            (prid,)).fetchone()
        # ai.precio NULL → rige el precio del catálogo
        conn.execute("UPDATE acu_items SET precio=NULL WHERE id=?", (row['id'],))
        eff = conn.execute(
            """SELECT COALESCE(ai.precio, r.precio, 0) e FROM acu_items ai
               JOIN recursos r ON r.id=ai.recurso_id WHERE ai.id=?""",
            (row['id'],)).fetchone()['e']
        assert eff == row['cat']
        # ai.precio puesto → rige el del proyecto aunque difiera del catálogo
        conn.execute("UPDATE acu_items SET precio=? WHERE id=?",
                     (row['cat'] + 7, row['id']))
        eff = conn.execute(
            """SELECT COALESCE(ai.precio, r.precio, 0) e FROM acu_items ai
               JOIN recursos r ON r.id=ai.recurso_id WHERE ai.id=?""",
            (row['id'],)).fetchone()['e']
        assert eff == row['cat'] + 7
        conn.rollback()
    finally:
        conn.close()


# ── Estados: matriz de bloqueo por nivel ────────────────────────────────────

def test_estados_bloqueo():
    from core.config import puede_editar
    # Solo «elaboracion» permite editar el presupuesto (partidas/ACU/PU);
    # el detector PU≠ACU y «unificar precios» dependen de esta matriz.
    for estado in ('revision', 'aprobado', 'ejecutado'):
        assert not puede_editar(estado, 'presupuesto'), estado
        assert not puede_editar(estado, 'pie'), estado
    assert puede_editar('elaboracion', 'presupuesto')
    assert puede_editar('revision', 'specs')        # specs editable en revisión
    assert puede_editar('aprobado', 'cronograma')   # cronograma hasta ejecutado
    assert not puede_editar('ejecutado', 'cronograma')
    assert puede_editar(None, 'presupuesto')        # sin estado = elaboración


# ── Importador .prs: ACU completo y CD fiel (solo si hay archivos reales) ───

def test_importador_prs_reconcilia():
    import shutil as _sh
    archivos = [p for p in (
        os.path.expanduser('~/Descargas/TROCHA CHICHAS.prs'),
        os.path.expanduser('~/Documentos/ET Plaza Yanque/Base de datos Plaza Yanque.prs'),
    ) if os.path.isfile(p)]
    if not archivos or not _sh.which('mdb-export'):
        print("      (saltado: sin archivos .prs de prueba o sin mdbtools)")
        return
    from core.powercost_prs_importer import import_powercost_prs
    for prs in archivos:
        info, partidas, acus, recursos, metrados = import_powercost_prs(prs)
        for p in partidas:
            # acus_data se indexa por item_origen (clave única por sub).
            key = p.get('item_origen') or p['item']
            if p.get('es_titulo') or key not in acus:
                continue
            cu = d._pu_desde_items(acus[key]['items'])
            dif = abs(cu - (p['precio_unitario'] or 0))
            # ≤ 2 céntimos: criterio de redondeo PowerCost vs app (tolerado
            # por el detector). Más que eso = desglose incompleto (regresión).
            assert dif <= 0.0205, \
                f"{os.path.basename(prs)} {p['item']}: PU={p['precio_unitario']} vs ACU={cu}"


def test_importador_prs_pie_de_presupuesto():
    """El pie del .prs (PiePpto + EstGGs) se importa FIEL: rubros con sus
    porcentajes, desagregado de costos indirectos y total al céntimo.

    Antes se sembraba un pie genérico inactivo y el total no cuadraba con
    PowerCost. Contrastado con «Desagregado CI.xlsx» del propio PowerCost.
    """
    import shutil as _sh
    prs = os.path.expanduser('~/Descargas/yanque/Plaza Yanque.prs')
    if not os.path.isfile(prs) or not _sh.which('mdb-export'):
        print("      (saltado: sin el .prs de prueba o sin mdbtools)")
        return
    from core.powercost_prs_importer import import_powercost_prs
    from core.exporter import _calcular_rubros_pie
    from core import importer

    info, partidas, acus, rec, met = import_powercost_prs(prs)
    assert info.get('pie_rubros'), "no se leyó el pie del .prs"

    conn = _db_seed()
    d.init_db()
    pid = importer.guardar_importacion(info, partidas, acus, rec, met)
    _items, tot = d.calcular_totales(pid)
    conn = d.get_db()
    rubros, total = _calcular_rubros_pie(conn, pid, tot['cd'])
    conn.close()

    # Valores del reporte «Desagregado de Costo Indirecto» de PowerCost.
    esperado = {
        'Gastos Generales':          58590.00,
        'Utilidad':                  15098.33,
        'Sub Total':                451146.60,
        'IGV':                       81206.39,
        'Valor Referencial De Obra':532352.99,
        'Supervision De Obra':       25560.00,
        'Expediente Tecnico':        35000.00,
        'Liquidación De Obra':        6000.00,
    }
    assert abs(tot['cd'] - 377458.27) <= 0.02, f"CD={tot['cd']}"
    vistos = {}
    for r in rubros or []:
        vistos[r['nombre']] = r['valor']
    for nombre, val in esperado.items():
        assert nombre in vistos, f"falta el rubro «{nombre}» en el pie"
        assert abs(vistos[nombre] - val) <= 0.02, \
            f"{nombre}: app={vistos[nombre]:.2f} vs PowerCost={val:.2f}"
    assert abs(total - 598912.99) <= 0.02, f"total={total:.2f}"
    # El renglón del GRAN TOTAL (EsTotal=1 en PiePpto) NO debe importarse:
    # la app cierra el pie con su propia línea y saldría el monto dos veces.
    assert not any('COSTO TOTAL' in n.upper() for n in vistos), \
        f"el gran total se importó como rubro y saldrá duplicado: {list(vistos)}"

    # El desagregado también, no solo los totales.
    conn = d.get_db()
    gg = sum((g['cantidad'] or 0) * (g['precio'] or 0) for g in conn.execute(
        "SELECT * FROM gastos_generales WHERE proyecto_id=? AND rubro='GG'"
        " AND tipo='item'", (pid,)))
    n_tit = conn.execute(
        "SELECT COUNT(*) FROM gastos_generales WHERE proyecto_id=? AND tipo='titulo'",
        (pid,)).fetchone()[0]
    conn.close()
    assert abs(gg - 58590.00) <= 0.02, f"desagregado GG = {gg:.2f}"
    assert n_tit > 0, "no se importaron los títulos del desagregado"

    # ── Segundo archivo: los rubros se llaman DISTINTO ────────────────────
    # «GASTOS DE EXP. TEC.» no contiene «EXPEDIENTE»: clasificar por nombre
    # lo tomaba por un subtotal y perdía sus 6 500. El tipo debe salir de la
    # ESTRUCTURA (si tiene desagregado en EstGGs → es un rubro).
    prs2 = os.path.expanduser('~/Descargas/yara/yarah.prs')
    if not os.path.isfile(prs2):
        return
    info2, part2, acus2, rec2, met2 = import_powercost_prs(prs2)
    pid2 = importer.guardar_importacion(info2, part2, acus2, rec2, met2)
    _i2, tot2 = d.calcular_totales(pid2)
    conn = d.get_db()
    rubros2, total2 = _calcular_rubros_pie(conn, pid2, tot2['cd'])
    conn.close()
    esperado2 = {
        'Gastos Generales':      27750.00,
        'Gastos De Supervision': 12000.00,
        'Gastos De Liquidacion':  4500.00,
        'Gastos De Exp. Tec.':    6500.00,
    }
    vistos2 = {r['nombre']: r['valor'] for r in (rubros2 or [])}
    for nombre, val in esperado2.items():
        assert nombre in vistos2, f"falta «{nombre}» (¿clasificado como subtotal?)"
        assert abs(vistos2[nombre] - val) <= 0.02, \
            f"{nombre}: app={vistos2[nombre]:.2f} vs PowerCost={val:.2f}"
    assert abs(total2 - 213396.74) <= 0.02, f"total yarah = {total2:.2f}"
    assert not any('COSTO TOTAL' in n.upper() for n in vistos2), \
        f"el gran total se importó como rubro: {list(vistos2)}"


def test_importador_prs_subpresupuestos_dentro_del_proyecto():
    """Un proyecto .prs con varios sub-presupuestos se importa COMPLETO como
    UN solo proyecto: el primer sub es el Principal y los demás viajan en
    `sub_ref`; al guardar quedan como filas de `sub_presupuestos` con sus
    partidas colgadas. El CD de cada sub cuadra con la tabla SubPptos.

    Regresión: antes se importaba en silencio solo el primer sub
    (`IdSubPpto>0`), así que una base con 7 sub-presupuestos traía 1 de 7.
    """
    import shutil as _sh
    prs = os.path.expanduser('~/Descargas/p/base de datos mantenimiento.prs')
    if not os.path.isfile(prs) or not _sh.which('mdb-export'):
        print("      (saltado: sin archivo .prs de prueba o sin mdbtools)")
        return
    from core.powercost_prs_importer import import_powercost_prs, _query, _int, _num
    from core import importer

    # CD por sub según la tabla SubPptos del archivo (IdSubPpto=0 es el total)
    subs_tabla = {r['NomSubPpto'].strip(): _num(r['CD'])
                  for r in _query(prs, 'SubPptos') if _int(r['IdSubPpto']) > 0}
    if len(subs_tabla) < 2:
        print("      (saltado: el .prs de prueba no tiene varios subs)")
        return

    info, partidas, acus, recursos, metrados = import_powercost_prs(prs)

    # 1) Las claves item_origen son únicas aunque cada sub numere desde 01
    origenes = [p['item_origen'] for p in partidas]
    assert len(origenes) == len(set(origenes)), "item_origen duplicado"

    # 1b) Y los ÍTEMS VISIBLES también son únicos en todo el proyecto: la
    #     numeración de títulos raíz es continua entre subs (01, 04, 08…),
    #     como en PowerCost. Es un requisito duro: `calcular_totales` indexa
    #     los parciales en un dict por `item` (database.py:885) y con ítems
    #     repetidos solo sobrevivía el último → el CD salía truncado, y
    #     `subtotal_de(prefijo)` mezclaba títulos de subs distintos.
    items_vis = [p['item'] for p in partidas]
    assert len(items_vis) == len(set(items_vis)), \
        "ítems visibles duplicados entre sub-presupuestos"

    # 2) Aparecen TODOS los subs: Principal (sub_ref None) + N-1 con nombre
    refs = {p.get('sub_ref') for p in partidas}
    assert None in refs, "falta el sub Principal"
    assert len(refs) == len(subs_tabla), \
        f"esperados {len(subs_tabla)} subs, importados {len(refs)}"

    # 3) CD por sub cuadra con SubPptos (1 sol de tolerancia de redondeo)
    def _cd(pred):
        return sum((p['metrado'] or 0) * (p['precio_unitario'] or 0)
                   for p in partidas
                   if not p.get('es_titulo') and pred(p))
    for nombre, cd_tabla in subs_tabla.items():
        es_principal = (nombre == info['sub_presupuesto'])
        cd_imp = _cd(lambda p, n=nombre, ep=es_principal:
                     (p.get('sub_ref') is None) if ep else (p.get('sub_ref') == n))
        assert abs(cd_imp - cd_tabla) <= 1.0, \
            f"{nombre}: CD archivo={cd_tabla:.2f} vs importado={cd_imp:.2f}"

    # 4) Persistencia: guardar crea las filas de sub_presupuestos y cuelga
    #    las partidas; los ACU no se cruzan entre subs.
    conn = _db_seed()
    d.init_db()
    pid = importer.guardar_importacion(info, partidas, acus, recursos, metrados)
    conn = d.get_db()
    n_subs_bd = conn.execute(
        "SELECT COUNT(*) FROM sub_presupuestos WHERE proyecto_id=?", (pid,)
    ).fetchone()[0]
    assert n_subs_bd == len(subs_tabla) - 1, \
        f"sub_presupuestos en BD: {n_subs_bd}, esperados {len(subs_tabla)-1}"
    # CD por sub en la BD = CD por sub del archivo
    for row in conn.execute(
        """SELECT COALESCE(s.nombre, ?) AS nom,
                  SUM(p.metrado * p.precio_unitario) AS cd
           FROM partidas p
           LEFT JOIN sub_presupuestos s ON s.id = p.sub_presupuesto_id
           WHERE p.proyecto_id=? AND p.es_titulo=0
           GROUP BY p.sub_presupuesto_id""",
        (info['sub_presupuesto'], pid)
    ).fetchall():
        cd_tabla = subs_tabla.get(row['nom'])
        assert cd_tabla is not None, f"sub inesperado en BD: {row['nom']}"
        assert abs(row['cd'] - cd_tabla) <= 1.0, \
            f"{row['nom']}: BD={row['cd']:.2f} vs archivo={cd_tabla:.2f}"

    # 5) El CD del proyecto = suma de TODOS los subs. Con ítems duplicados
    #    el dict de parciales de calcular_totales se comía los repetidos.
    _items, tot = d.calcular_totales(pid)
    cd_archivo = sum(subs_tabla.values())
    assert abs(tot['cd'] - cd_archivo) <= 1.0, \
        f"CD proyecto: calcular_totales={tot['cd']:.2f} vs archivo={cd_archivo:.2f}"
    conn.close()



# ── Importador Delphin — sub-partidas aplanadas, sin doble conteo ────────────

def test_importador_delphin_subpartidas_no_duplican():
    """Una sub-partida de Delphin entra como UNA línea SC con su costo, y su
    desglose interno NO se suma además al ACU del padre.

    Delphin anida la sub-partida colgando subtotales de una composición padre
    (`subtotal_*.id_composicionpadre`, que en la raíz viene como cadena VACÍA,
    no NULL). El importador los traía todos, así que la partida se quedaba con
    la línea de la sub-partida —que ya trae su costo completo— y encima con la
    mano de obra, materiales y equipo internos de esa sub-partida.

    El síntoma que reportó el usuario: el costo unitario se ve bien al importar
    porque se guarda el de Delphin, pero al editar cualquier dato
    `_recalcular_pu` recalcula desde los ítems duplicados y salta.

    Contrasta los 194 ACU de la biblioteca contra `analisis_costo.costo_unitario`
    del propio Delphin. Antes del arreglo discrepaban 13 (todas «Muro de
    ladrillo…», las que llevan sub-partida).
    """
    import shutil as _sh, sqlite3 as _sq, tempfile as _tf
    fuente = os.path.join(os.path.dirname(__file__), '..', '..',
                          'datos', 'SQLDelphin_basica.sqlite')
    if not os.path.isfile(fuente):
        print("      (saltado: sin la base Delphin de prueba)")
        return

    # BD limpia: el importador escribe, no debe tocar la de los otros tests
    fd, dbtmp = _tf.mkstemp(suffix='_delphin.db'); os.close(fd)
    _sh.copy(SEED, dbtmp)
    db_previa = d.DB_PATH
    d.DB_PATH = dbtmp
    try:
        import core.config as _cfg
        cfg_previa = _cfg.DB_PATH
        _cfg.DB_PATH = dbtmp
        d.init_db()

        conn = d.get_db()
        previos = {r[0] for r in conn.execute("SELECT id FROM biblioteca_cu")}
        conn.close()

        from core.delphin_sqlite_importer import import_biblioteca_delphin_sqlite
        res = import_biblioteca_delphin_sqlite(fuente)
        assert res.get('ok'), f"la importación falló: {res}"

        # Costo unitario de referencia: el que trae el propio Delphin
        src = _sq.connect(fuente); src.row_factory = _sq.Row
        ref = {str(r['descripcion_costo']).strip().upper(): r['costo_unitario']
               for r in src.execute(
                   "SELECT descripcion_costo, costo_unitario FROM analisis_costo")
               if r['descripcion_costo']}
        src.close()

        conn = d.get_db()
        nuevos = [r for r in conn.execute(
            "SELECT id, descripcion FROM biblioteca_cu") if r['id'] not in previos]
        assert len(nuevos) >= 190, f"se importaron solo {len(nuevos)} ACU"

        malos = []
        con_sub = 0
        for f in nuevos:
            clave = (f['descripcion'] or '').strip().upper()
            if clave not in ref:
                continue
            items = [dict(x) for x in conn.execute(
                """SELECT i.cantidad, COALESCE(i.precio, r.precio, 0) AS precio,
                          r.unidad, r.tipo
                   FROM biblioteca_acu_items i
                   JOIN recursos r ON r.id = i.recurso_id
                   WHERE i.cu_id=?""", (f['id'],))]
            if any(x['tipo'] == 'SC' for x in items):
                con_sub += 1
            calc = d._pu_desde_items(items)
            if abs(calc - (ref[clave] or 0)) > 0.02:
                malos.append(f"{f['descripcion'][:44]}: app={calc:.2f} delphin={ref[clave]:.2f}")
        conn.close()

        assert con_sub > 0, "la biblioteca de prueba ya no trae sub-partidas"
        assert not malos, ("ACU que no cuadran con Delphin (doble conteo de "
                           f"sub-partida): {malos[:5]}")
    finally:
        d.DB_PATH = db_previa
        import core.config as _cfg
        _cfg.DB_PATH = cfg_previa
        if os.path.exists(dbtmp):
            os.unlink(dbtmp)



# ── Unidades «porcentaje»: sobre qué subtotal se aplica cada una ─────────────

def test_base_overhead_reconoce_las_grafias_reales():
    """`%mt` es «% de materiales» en S10 y en PowerCost, no «% de MO».

    El estándar peruano usa cinco unidades porcentaje (ver
    ingeconverter/docs/s10_schema_notes.md). La app resuelve las tres que son
    subtotales del propio ACU; `%pu` y `%cd` conservan la base MO histórica
    porque su base no vive dentro del ACU.

    Antes sólo se reconocían `%mo` y `%mat` —esta última una grafía propia de
    la app que NO usa ningún archivo real— y todo lo demás caía en MO.
    """
    b = d.base_overhead
    # mano de obra
    assert b('%mo') == 'MO' and b('%MO') == 'MO'
    # materiales: la grafía real del mercado y la propia de la app
    assert b('%mt') == 'MAT' and b('%MT') == 'MAT'
    assert b('%mat') == 'MAT' and b('%MAT') == 'MAT'
    # equipos
    assert b('%eq') == 'EQ' and b('%EQ') == 'EQ'
    # sin resolver: se quedan en la base histórica, no se inventa semántica
    assert b('%pu') == 'MO', "«% del precio unitario» es recursivo, no se resuelve"
    assert b('%cd') == 'MO', "«% del costo directo» es de presupuesto, no de ACU"
    assert b('%') == 'MO'
    # entradas degeneradas
    assert b(None) == 'MO' and b('') == 'MO' and b('kg') == 'MO'


def test_overhead_porcentaje_de_materiales_usa_los_materiales():
    """Un insumo `%MT` se calcula sobre el subtotal de MATERIALES."""
    items = [
        {'cantidad': 2.0,  'precio': 50.0, 'unidad': 'hh',  'tipo': 'MO'},   # MO  = 100
        {'cantidad': 4.0,  'precio': 25.0, 'unidad': 'kg',  'tipo': 'MAT'},  # MAT = 100... 
        {'cantidad': 10.0, 'precio': 40.0, 'unidad': 'kg',  'tipo': 'MAT'},  # +400 → MAT = 500
        {'cantidad': 3.0,  'precio': 0.0,  'unidad': '%MT', 'tipo': 'MAT'},  # 3% de MAT
    ]
    # MO=100 · MAT=500 · 3% de 500 = 15  →  100 + 500 + 15 = 615
    assert d._pu_desde_items(items) == 615.0
    # con la regla vieja habría dado 100+500+3 = 603 (3% de la MO)

    # y el mismo ACU con %MO sí se calcula sobre la mano de obra
    items[-1] = {'cantidad': 3.0, 'precio': 0.0, 'unidad': '%MO', 'tipo': 'EQ'}
    assert d._pu_desde_items(items) == 603.0   # 3% de 100 = 3


def test_la_regla_de_overhead_tiene_un_solo_dueno():
    """Los tres sitios que resolvían la base usan el helper, no una copia.

    Estaba escrita tres veces —`_pu_desde_items`, `get_acu_items` y el diálogo
    de agregar partida— con el mismo ternario. Arreglar dos de tres dejaba la
    vista previa del diálogo mostrando otro número que el ACU real.
    """
    import inspect
    import views.agregar_partida_dialog as apd
    fuentes = {
        'core.database': inspect.getsource(d),
        'views.agregar_partida_dialog': inspect.getsource(apd),
    }
    for nombre, src in fuentes.items():
        assert "'%mo' in" not in src, \
            f"{nombre} volvió a resolver la base a mano en vez de base_overhead()"



# ── La regla de la cuadrilla tiene un solo dueño ─────────────────────────────

def test_la_regla_de_la_cuadrilla_no_esta_duplicada():
    """`cant = (cuadrilla/rendimiento) × jornada` decide la MO de TODO el
    presupuesto, y hasta 2026-08-29 estaba escrita tres veces: en
    `core.database`, en `proyecto_view` y en `recurso_selector_dialog`, con un
    comentario que pedía «mantener en sync» a mano.

    Las vistas ahora la importan. Se comprueba por IDENTIDAD (`is`), no por
    igualdad de resultados: mientras sean el mismo objeto función es imposible
    que diverjan, que es justamente lo que un comentario no garantiza.
    """
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    import views.proyecto_view as PV
    import views.recurso_selector_dialog as RS

    assert PV._recurso_por_hora is d.recurso_por_hora
    assert PV._recurso_por_dia is d.recurso_por_dia
    assert PV._partida_global is d.partida_global
    assert RS._es_por_hora is d.recurso_por_hora
    assert RS._es_por_dia is d.recurso_por_dia
    assert RS._es_partida_global is d.partida_global


def test_unidades_que_derivan_la_cantidad_de_la_cuadrilla():
    """Fija el vocabulario de unidades de la regla, que es lo que de verdad
    decide si un insumo deriva su cantidad o la lleva directa."""
    # por HORA: toda la MO, y el equipo con unidad de hora
    for t, u in (('MO', 'kg'), ('MO', None), ('EQ', 'hh'), ('EQ', 'hm'),
                 ('EQ', 'h-h'), ('EQ', 'jph'), ('MAT', 'hora'), ('EQ', 'HORA')):
        assert d.recurso_por_hora(t, u), (t, u)
    for t, u in (('MAT', 'kg'), ('EQ', 'und'), ('SC', 'glb'), ('MAT', None)):
        assert not d.recurso_por_hora(t, u), (t, u)

    # por DÍA: MO/EQ con unidad día o jornada — el rendimiento ya es por día
    for t, u in (('MO', 'día'), ('MO', 'dia'), ('EQ', 'jor'), ('EQ', 'JOR.'),
                 ('MO', 'jornada'), ('EQ', 'dias')):
        assert d.recurso_por_dia(t, u), (t, u)
    for t, u in (('MAT', 'día'), ('SC', 'jor'), ('MO', 'hh')):
        assert not d.recurso_por_dia(t, u), (t, u)

    # partida GLOBAL: sin cuadrilla, cantidad directa en todos los insumos
    for u in ('glb', 'GLB.', 'gbl', 'est', 'serv'):
        assert d.partida_global(u), u
    for u in ('m3', 'und', 'día', '', None):
        assert not d.partida_global(u), u


def test_el_dialogo_de_recursos_graba_cuadrilla_solo_donde_aplica():
    """«Crear nuevo recurso» grababa la cuadrilla tal cual para cualquier tipo:
    un material entraba al ACU con cuadrilla 1.0 (el valor por defecto del
    campo) mientras «Buscar en catálogo» le ponía 0. Reporte de David Ramos,
    2 sep 2026.

    Ahora las dos pestañas pasan por `_cuadrilla_y_cantidad`, y el formulario
    habilita cuadrilla O cantidad con la misma regla que la tabla del ACU.
    """
    import os, inspect
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import views.recurso_selector_dialog as RS

    # Las dos pestañas usan la función única, ninguna resuelve la regla a mano
    for fn in (RS.RecursoSelectorDialog._agregar_existentes,
               RS.RecursoSelectorDialog._agregar_nuevo):
        fuente = inspect.getsource(fn)
        assert '_cuadrilla_y_cantidad(' in fuente, fn.__name__
        assert '_es_por_hora(' not in fuente, \
            f"{fn.__name__} volvió a decidir la cuadrilla por su cuenta"

    conn = _db_seed()
    p = conn.execute(
        "SELECT p.id, p.rendimiento, pr.jornada_laboral FROM partidas p "
        "JOIN proyectos pr ON pr.id = p.proyecto_id "
        "WHERE p.rendimiento > 0 "
        "  AND lower(p.unidad) NOT IN ('glb','gbl','est','serv') LIMIT 1"
    ).fetchone()
    conn.close()
    part_id, rend = p['id'], p['rendimiento']
    jornada = p['jornada_laboral'] or 8

    dlg = RS.RecursoSelectorDialog(part_id, {})
    def _tipo(t):
        dlg.cmb_n_tipo.setCurrentIndex(dlg.cmb_n_tipo.findData(t))
    def _campos():
        return dlg.inp_n_cuad.isEnabled(), dlg.inp_n_cant.isEnabled()

    # Formulario: cuadrilla O cantidad, según tipo y unidad
    _tipo('MAT'); dlg.inp_n_unidad.setText('kg')
    assert _campos() == (False, True), 'material: solo cantidad'
    _tipo('SC'); dlg.inp_n_unidad.setText('glb')
    assert _campos() == (False, True), 'subcontrato: solo cantidad'
    _tipo('MO'); dlg.inp_n_unidad.setText('hh')
    assert _campos() == (True, False), 'mano de obra: solo cuadrilla'
    _tipo('EQ'); dlg.inp_n_unidad.setText('hm')
    assert _campos() == (True, False), 'equipo por hora: solo cuadrilla'
    dlg.inp_n_unidad.setText('und')
    assert _campos() == (False, True), 'equipo por unidad: solo cantidad'

    # Grabación: el material entra con cuadrilla 0 aunque el campo traiga 1.000
    _tipo('MAT'); dlg.inp_n_unidad.setText('kg')
    dlg.inp_n_desc.setText('TEST material sin cuadrilla')
    dlg.inp_n_precio.setText('10')
    dlg.inp_n_cant.setText('2.5')
    dlg.inp_n_cuad.setText('1.000')          # como quedaba antes del arreglo
    dlg._agregar_nuevo()
    conn = _db_seed()
    fila = conn.execute(
        "SELECT ai.cuadrilla, ai.cantidad FROM acu_items ai "
        "JOIN recursos r ON r.id = ai.recurso_id "
        "WHERE ai.partida_id=? AND r.descripcion=?",
        (part_id, 'TEST material sin cuadrilla')).fetchone()
    conn.close()
    assert (fila['cuadrilla'], fila['cantidad']) == (0, 2.5), dict(fila)

    # …y la MO deriva su cantidad de la cuadrilla, como en la tabla del ACU
    _tipo('MO'); dlg.inp_n_unidad.setText('hh')
    dlg.inp_n_desc.setText('TEST peon con cuadrilla')
    dlg.inp_n_precio.setText('20')
    dlg.inp_n_cuad.setText('2')
    dlg._agregar_nuevo()
    conn = _db_seed()
    fila = conn.execute(
        "SELECT ai.cuadrilla, ai.cantidad FROM acu_items ai "
        "JOIN recursos r ON r.id = ai.recurso_id "
        "WHERE ai.partida_id=? AND r.descripcion=?",
        (part_id, 'TEST peon con cuadrilla')).fetchone()
    conn.close()
    assert fila['cuadrilla'] == 2, dict(fila)
    assert fila['cantidad'] == d._rn(2 / rend * jornada,
                                     d.get_decimales_cant_acu()), dict(fila)


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
    if _tmpdb and os.path.exists(_tmpdb):
        os.unlink(_tmpdb)
    sys.exit(1 if fallos else 0)
