# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""core.diccionario_iu — el diccionario insumo → índice unificado.

La fórmula polinómica agrupa el costo directo por el índice unificado de cada
insumo (`recursos.indice_inei`). Ese vínculo es el «diccionario» que pidió el
usuario: *«implementar el diccionario para la elaboración de las fórmulas
polinómicas, mismas que son actualizadas y publicadas por el INEI»*.

El dato ya existía y estaba bastante completo —89% de la biblioteca semilla—
pero no había forma de verlo como conjunto, de arreglarlo en tandas ni de
llevárselo a otra instalación. Y el 11% sin clasificar no es menor: en el
proyecto de agua potable de la semilla son el 37.5% del costo directo, que la
fórmula reparte por el índice del TIPO del insumo, un supuesto que conviene
poder corregir.

Funciones:
    - ``resumen()``            → cuántos insumos y cuánto valor por índice
    - ``insumos_sin_indice()`` → los que faltan clasificar
    - ``asignar_indice()``     → asignación en tanda
    - ``sugerencias()``        → propone índice por parecido de descripción
    - ``exportar()`` / ``importar()`` → el diccionario como archivo JSON
"""
from __future__ import annotations

import json
import re

from core.database import get_db


# Distancia mínima, en puntos de parecido, entre el índice propuesto y el
# mejor candidato de OTRO índice. Por debajo, la propuesta se marca ambigua.
MARGEN_AMBIGUO = 3.0


def _normalizar(texto: str) -> str:
    """Descripción comparable: sin marcas, sin dobles espacios, en minúscula."""
    s = (texto or '').lower()
    s = re.sub(r'[^\w\s]', ' ', s, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', s).strip()


def resumen(conn=None) -> list[dict]:
    """Por índice unificado: cuántos insumos lo usan y cuánto valen.

    Incluye los índices que NO están en el catálogo, para que se vean: la
    biblioteca semilla trae insumos apuntando a códigos que el catálogo no
    definía.
    """
    own = conn is None
    if own:
        conn = get_db()
    try:
        rows = conn.execute(
            """SELECT COALESCE(NULLIF(r.indice_inei,''), '—') AS codigo,
                      COALESCE(i.nombre, '') AS nombre,
                      COUNT(*) AS n_insumos,
                      SUM(COALESCE(r.precio, 0)) AS valor,
                      (i.codigo IS NOT NULL) AS en_catalogo
                 FROM recursos r
                 LEFT JOIN indices_inei i ON i.codigo = r.indice_inei
                GROUP BY 1, 2, 5
                ORDER BY n_insumos DESC"""
        ).fetchall()
    finally:
        if own:
            conn.close()
    return [dict(r) for r in rows]


def insumos_sin_indice(limite: int | None = None, conn=None) -> list[dict]:
    """Los insumos que no tienen índice unificado asignado.

    El '00' cuenta como sin asignar: no es un índice del INEI sino el centinela
    que usa `core.parte_diario` para los recursos sin clasificar.
    """
    own = conn is None
    if own:
        conn = get_db()
    try:
        sql = ("SELECT id, codigo, descripcion, tipo, unidad, "
               "COALESCE(precio,0) AS precio FROM recursos "
               "WHERE COALESCE(indice_inei,'') IN ('', '00') "
               "ORDER BY tipo, descripcion")
        if limite:
            sql += f" LIMIT {int(limite)}"
        rows = conn.execute(sql).fetchall()
    finally:
        if own:
            conn.close()
    return [dict(r) for r in rows]


def asignar_indice(recurso_ids, codigo: str, conn=None) -> int:
    """Asigna un índice a varios insumos de una vez. Devuelve cuántos cambió."""
    from core.indices_inei import _norm_codigo
    codigo = _norm_codigo(codigo)
    ids = [int(i) for i in recurso_ids]
    if not ids:
        return 0
    own = conn is None
    if own:
        conn = get_db()
    try:
        marcas = ','.join('?' * len(ids))
        cur = conn.execute(
            f"UPDATE recursos SET indice_inei=? WHERE id IN ({marcas})",
            [codigo, *ids]
        )
        conn.commit()
        return cur.rowcount
    finally:
        if own:
            conn.close()


def sugerencias(umbral: int = 85, limite: int | None = None,
                conn=None) -> list[dict]:
    """Propone un índice para cada insumo sin clasificar.

    El criterio es el parecido de la descripción con los insumos que SÍ están
    clasificados: si «CEMENTO PORTLAND TIPO I 42.5KG» ya está en el 21, es muy
    probable que «CEMENTO PORTLAND TIPO I (BOLSA 42.5 KG)» también.

    No inventa índices nuevos ni toca nada: devuelve las propuestas con su
    puntaje y el insumo en que se apoya, para que el usuario acepte o descarte.
    Las que tienen un rival cercano de OTRO índice salen marcadas `ambiguo`:
    «CEMENTO PORTLAND TIPO V» se parece un 95.7% a «TIPO I» y son índices
    distintos (23 y 21), así que un puntaje alto no basta.
    Sin `rapidfuzz` instalado usa `difflib`, que es más lento pero está en la
    biblioteca estándar.

    Devuelve [{'recurso_id','descripcion','tipo','codigo','nombre','puntaje',
               'parecido_a'}].
    """
    own = conn is None
    if own:
        conn = get_db()
    try:
        clasificados = conn.execute(
            "SELECT descripcion, tipo, indice_inei FROM recursos "
            "WHERE COALESCE(indice_inei,'') NOT IN ('', '00') "
            "  AND COALESCE(descripcion,'') <> ''"
        ).fetchall()
        pendientes = insumos_sin_indice(limite, conn)
        nombres = dict(conn.execute(
            "SELECT codigo, nombre FROM indices_inei").fetchall())
    finally:
        if own:
            conn.close()

    if not clasificados or not pendientes:
        return []

    # Un banco por tipo: un material no debería resolverse contra una mano de
    # obra por mucho que se parezcan los textos.
    banco: dict[str, list[tuple[str, str, str]]] = {}
    for r in clasificados:
        norm = _normalizar(r['descripcion'])
        if norm:
            banco.setdefault(r['tipo'] or 'MAT', []).append(
                (norm, r['indice_inei'], r['descripcion']))

    try:
        from rapidfuzz import fuzz, process
        _fuzz = True
    except ImportError:
        import difflib
        _fuzz = False

    out = []
    for ins in pendientes:
        cand = banco.get(ins['tipo'] or 'MAT') or []
        if not cand:
            continue
        objetivo = _normalizar(ins['descripcion'])
        if not objetivo:
            continue
        textos = [c[0] for c in cand]

        if _fuzz:
            # Varios candidatos, no uno: hace falta ver si el segundo apunta a
            # OTRO índice con casi el mismo puntaje.
            hits = process.extract(objetivo, textos,
                                   scorer=fuzz.token_set_ratio,
                                   limit=8, score_cutoff=umbral)
            if not hits:
                continue
            hits = [(h[1], h[2]) for h in hits]          # (puntaje, idx)
        else:
            import difflib
            cerca = difflib.get_close_matches(objetivo, textos, n=8,
                                              cutoff=umbral / 100)
            if not cerca:
                continue
            hits = [(difflib.SequenceMatcher(None, objetivo, t).ratio() * 100,
                     textos.index(t)) for t in cerca]
            hits.sort(key=lambda h: -h[0])

        puntaje, idx = hits[0]
        _, cod, desc_origen = cand[idx]

        # El riesgo del dominio: «CEMENTO PORTLAND TIPO V» se parece un 95.7% a
        # «TIPO I», y son índices distintos (23 y 21). Ningún scorer distingue
        # eso. Si el mejor candidato de OTRO índice queda a menos de `MARGEN`
        # puntos, la propuesta es ambigua y se marca para que el usuario decida:
        # asignar mal un índice desplaza plata de un monomio a otro.
        rival = next(((p, cand[i][1]) for p, i in hits[1:]
                      if cand[i][1] != cod), None)
        ambiguo = bool(rival and (puntaje - rival[0]) < MARGEN_AMBIGUO)

        out.append({
            'recurso_id':  ins['id'],
            'descripcion': ins['descripcion'],
            'tipo':        ins['tipo'],
            'codigo':      cod,
            'nombre':      nombres.get(cod, f"Índice {cod}"),
            'puntaje':     round(puntaje, 1),
            'parecido_a':  desc_origen,
            'ambiguo':     ambiguo,
            'rival':       (f"{rival[1]} ({rival[0]:.0f})" if rival else ''),
        })
    out.sort(key=lambda x: -x['puntaje'])
    return out


def aplicar_sugerencias(sugs) -> int:
    """Aplica las propuestas aceptadas. Devuelve cuántos insumos se asignaron."""
    por_codigo: dict[str, list[int]] = {}
    for s in sugs:
        por_codigo.setdefault(s['codigo'], []).append(s['recurso_id'])
    conn = get_db()
    try:
        n = 0
        for codigo, ids in por_codigo.items():
            n += asignar_indice(ids, codigo, conn)
        return n
    finally:
        conn.close()


def exportar(filepath: str) -> int:
    """Guarda el diccionario como JSON. Devuelve cuántas entradas escribió.

    Se exporta por descripción normalizada y no por id: el archivo sirve para
    llevarlo a otra instalación, donde los ids son otros.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT descripcion, tipo, indice_inei FROM recursos "
            "WHERE COALESCE(indice_inei,'') NOT IN ('', '00') "
            "  AND COALESCE(descripcion,'') <> ''"
        ).fetchall()
        catalogo = [dict(r) for r in conn.execute(
            "SELECT codigo, nombre FROM indices_inei ORDER BY codigo")]
    finally:
        conn.close()

    entradas = {}
    for r in rows:
        entradas[f"{r['tipo']}|{_normalizar(r['descripcion'])}"] = r['indice_inei']
    data = {
        'formato': 'ingepresupuestos.diccionario_iu',
        'version': 1,
        'catalogo': catalogo,
        'entradas': entradas,
    }
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return len(entradas)


def importar(filepath: str, solo_sin_indice: bool = True) -> dict:
    """Aplica un diccionario exportado. Devuelve {'asignados','nuevos','msg'}.

    Con `solo_sin_indice` (lo predeterminado) no pisa las asignaciones que el
    usuario ya tenga: el archivo completa, no reemplaza. Los índices del
    archivo que falten en el catálogo se dan de alta, porque si no las
    asignaciones apuntarían a un código invisible.
    """
    try:
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return {'asignados': 0, 'nuevos': 0, 'msg': f"No se pudo leer: {e}"}

    if data.get('formato') != 'ingepresupuestos.diccionario_iu':
        return {'asignados': 0, 'nuevos': 0,
                'msg': "El archivo no es un diccionario de índices unificados."}

    entradas = data.get('entradas') or {}
    if not entradas:
        return {'asignados': 0, 'nuevos': 0, 'msg': "El archivo está vacío."}

    from core.indices_inei import asegurar_codigos
    nombres = {c['codigo']: c.get('nombre', '')
               for c in (data.get('catalogo') or [])}
    nuevos = asegurar_codigos(set(entradas.values()), nombres)

    conn = get_db()
    try:
        sql = ("SELECT id, descripcion, tipo FROM recursos "
               "WHERE COALESCE(descripcion,'') <> ''")
        if solo_sin_indice:
            sql += " AND COALESCE(indice_inei,'') IN ('', '00')"
        pendientes = conn.execute(sql).fetchall()
        asignados = 0
        for r in pendientes:
            cod = entradas.get(f"{r['tipo']}|{_normalizar(r['descripcion'])}")
            if not cod:
                continue
            conn.execute("UPDATE recursos SET indice_inei=? WHERE id=?",
                         (cod, r['id']))
            asignados += 1
        conn.commit()
    finally:
        conn.close()

    return {'asignados': asignados, 'nuevos': nuevos,
            'msg': f"{asignados} insumo(s) clasificados"
                   + (f", {nuevos} índice(s) dados de alta." if nuevos else ".")}
