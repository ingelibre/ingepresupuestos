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
        from core.indices_inei import SERIE_ACTUAL, asegurar_seed
        asegurar_seed(conn)
        rows = conn.execute(
            """SELECT COALESCE(NULLIF(r.indice_inei,''), '—') AS codigo,
                      COALESCE(i.nombre, '') AS nombre,
                      COUNT(*) AS n_insumos,
                      SUM(COALESCE(r.precio, 0)) AS valor,
                      (i.codigo IS NOT NULL) AS en_catalogo
                 FROM recursos r
                 LEFT JOIN indices_inei i
                        ON i.codigo = r.indice_inei AND i.serie = ?
                GROUP BY 1, 2, 5
                ORDER BY n_insumos DESC""", (SERIE_ACTUAL,)
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


def _mejor(objetivo: str, claves: list[str], umbral: int,
           codigo_de) -> tuple[str, float, bool, str] | None:
    """(clave, puntaje, ambiguo, rival) del mejor candidato, o None.

    El riesgo del dominio: «CEMENTO PORTLAND TIPO V» se parece un 95.7% a
    «TIPO I» y son índices distintos (23 y 21). Ningún scorer los separa, así
    que si el mejor candidato de OTRO índice queda a menos de `MARGEN_AMBIGUO`
    puntos, la propuesta se marca para que la decida el usuario.
    """
    if not claves:
        return None
    try:
        from rapidfuzz import fuzz, process
        hits = process.extract(objetivo, claves, scorer=fuzz.token_set_ratio,
                               limit=8, score_cutoff=umbral)
        hits = [(h[1], h[2]) for h in hits]
    except ImportError:
        import difflib
        cerca = difflib.get_close_matches(objetivo, claves, n=8,
                                          cutoff=umbral / 100)
        hits = sorted(((difflib.SequenceMatcher(None, objetivo, t).ratio() * 100,
                        claves.index(t)) for t in cerca), key=lambda h: -h[0])
    if not hits:
        return None
    puntaje, idx = hits[0]
    cod = codigo_de(claves[idx])
    rival = next(((p, codigo_de(claves[i])) for p, i in hits[1:]
                  if codigo_de(claves[i]) != cod), None)
    ambiguo = bool(rival and (puntaje - rival[0]) < MARGEN_AMBIGUO)
    return claves[idx], puntaje, ambiguo, (f"{rival[1]} ({rival[0]:.0f})"
                                           if rival else '')


def sugerencias(umbral: int = 85, limite: int | None = None,
                conn=None, usar_oficial: bool = True) -> list[dict]:
    """Propone un índice unificado para cada insumo sin clasificar.

    Dos fuentes, en este orden:

    1. **El Diccionario de Elementos de la Construcción del INEI** (Anexo 2 de
       la RJ 016-2026-INEI, ~1930 entradas). Es la referencia con autoridad:
       primero por coincidencia exacta del nombre normalizado y después por
       parecido. Resuelve algo más de la mitad de lo que falta y, a diferencia
       de la biblioteca propia, no propaga errores de clasificación previos.
    2. **La propia biblioteca**, por parecido con los insumos que YA tienen
       índice. Cubre lo que el diccionario no nombra —marcas, formatos y
       descripciones locales.

    No inventa índices ni toca nada: devuelve las propuestas con su puntaje, su
    fuente y el elemento en que se apoya, para que el usuario acepte o
    descarte. Las que tienen un rival cercano de OTRO índice salen marcadas
    `ambiguo`.

    Devuelve [{'recurso_id','descripcion','tipo','codigo','nombre','puntaje',
               'parecido_a','ambiguo','rival','fuente'}].
    """
    own = conn is None
    if own:
        conn = get_db()
    try:
        from core.indices_inei import SERIE_ACTUAL, asegurar_seed
        asegurar_seed(conn)
        clasificados = conn.execute(
            "SELECT descripcion, tipo, indice_inei FROM recursos "
            "WHERE COALESCE(indice_inei,'') NOT IN ('', '00') "
            "  AND COALESCE(descripcion,'') <> ''"
        ).fetchall()
        pendientes = insumos_sin_indice(limite, conn)
        nombres = dict(conn.execute(
            "SELECT codigo, nombre FROM indices_inei WHERE serie=?",
            (SERIE_ACTUAL,)).fetchall())
    finally:
        if own:
            conn.close()

    if not pendientes:
        return []

    # ── Fuente 1: el diccionario oficial ──
    oficial: dict[str, str] = {}
    if usar_oficial:
        from core.indices_inei import diccionario_oficial
        for elemento, cod in diccionario_oficial().items():
            n = _normalizar(elemento)
            if n:
                oficial[n] = cod
    claves_of = list(oficial)

    # ── Fuente 2: la biblioteca, por tipo ──
    banco: dict[str, list[tuple[str, str, str]]] = {}
    for r in clasificados:
        norm = _normalizar(r['descripcion'])
        if norm:
            banco.setdefault(r['tipo'] or 'MAT', []).append(
                (norm, r['indice_inei'], r['descripcion']))

    out = []
    for ins in pendientes:
        objetivo = _normalizar(ins['descripcion'])
        if not objetivo:
            continue

        # 1a. El diccionario oficial, palabra por palabra.
        if objetivo in oficial:
            cod = oficial[objetivo]
            out.append({
                'recurso_id': ins['id'], 'descripcion': ins['descripcion'],
                'tipo': ins['tipo'], 'codigo': cod,
                'nombre': nombres.get(cod, f"Índice {cod}"),
                'puntaje': 100.0, 'parecido_a': ins['descripcion'],
                'ambiguo': False, 'rival': '', 'fuente': 'oficial',
            })
            continue

        # 1b. El diccionario oficial, por parecido.
        m = _mejor(objetivo, claves_of, umbral, lambda k: oficial[k])
        if m:
            clave, puntaje, ambiguo, rival = m
            cod = oficial[clave]
            out.append({
                'recurso_id': ins['id'], 'descripcion': ins['descripcion'],
                'tipo': ins['tipo'], 'codigo': cod,
                'nombre': nombres.get(cod, f"Índice {cod}"),
                'puntaje': round(puntaje, 1), 'parecido_a': clave,
                'ambiguo': ambiguo, 'rival': rival, 'fuente': 'oficial',
            })
            continue

        # 2. La biblioteca propia, dentro del mismo tipo de insumo.
        cand = banco.get(ins['tipo'] or 'MAT') or []
        if not cand:
            continue
        textos = [c[0] for c in cand]
        idx_por_texto = {t: i for i, t in enumerate(textos)}
        m = _mejor(objetivo, textos, umbral,
                   lambda t: cand[idx_por_texto[t]][1])
        if not m:
            continue
        clave, puntaje, ambiguo, rival = m
        _, cod, desc_origen = cand[idx_por_texto[clave]]
        out.append({
            'recurso_id': ins['id'], 'descripcion': ins['descripcion'],
            'tipo': ins['tipo'], 'codigo': cod,
            'nombre': nombres.get(cod, f"Índice {cod}"),
            'puntaje': round(puntaje, 1), 'parecido_a': desc_origen,
            'ambiguo': ambiguo, 'rival': rival, 'fuente': 'biblioteca',
        })

    out.sort(key=lambda x: (x['fuente'] != 'oficial', -x['puntaje']))
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
        from core.indices_inei import SERIE_ACTUAL
        catalogo = [dict(r) for r in conn.execute(
            "SELECT codigo, nombre FROM indices_inei WHERE serie=? "
            "ORDER BY codigo", (SERIE_ACTUAL,))]
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
