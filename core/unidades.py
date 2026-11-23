# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Unidades de medida (issue #55): lista para elegir y unión de variantes.

Unir solo cambia cómo está ESCRITA la unidad («M2», «m2», «m²»). La unidad
decide cálculos (hh, hm, día, glb, kg de acero, bolsas enteras…), así que dos
grafías solo se juntan si la app las trata exactamente igual en todas esas
reglas (`_firma`); los «%mo», «%mt»… no se tocan nunca.
"""
from __future__ import annotations

from core.database import (
    es_partida_acero, get_db, partida_global, recurso_por_dia, recurso_por_hora,
)

# Las de siempre, en el orden en que se ofrecen.
COMUNES = [
    "m²", "m³", "m", "ml", "km", "cm", "mm",
    "und", "pza", "pzas", "jgo", "glb", "gbl", "est",
    "kg", "tn", "ton", "lb",
    "hh", "hm", "he", "h", "hr", "día", "sem", "mes",
    "l", "lt", "gal", "bls", "bol",
    "pto", "cjt", "ha", "pie²", "pie³", "p2", "p3", "vj", "rll",
]

# Dónde hay unidades vivas. Los documentos de obra ya emitidos (partes,
# requerimientos, almacén) guardan su propia copia y no se reescriben.
_TABLAS = ('recursos', 'biblioteca_cu', 'partidas', 'gastos_generales')
_PLANO = str.maketrans('²³áéíóú', '23aeiou')


def clave(unidad) -> str:
    """Forma común de las grafías de una misma unidad."""
    return (unidad or '').strip().rstrip('.').lower().translate(_PLANO)


def _firma(unidad) -> tuple:
    """Todo lo que la app decide mirando la unidad."""
    from core.requerimientos import redondear_para_pedido
    return (
        tuple(recurso_por_hora(t, unidad) for t in ('MO', 'MAT', 'EQ', 'SC')),
        tuple(recurso_por_dia(t, unidad) for t in ('MO', 'MAT', 'EQ', 'SC')),
        partida_global(unidad),
        es_partida_acero('ACERO', unidad),
        redondear_para_pedido(1.5, unidad),
    )


def misma_unidad(a, b) -> bool:
    return ('%' not in f'{a}{b}' and clave(a) == clave(b) != ''
            and _firma(a) == _firma(b))


def _filtro(tabla: str) -> str:
    """Los presupuestos cerrados (revisión, aprobado, ejecutado) no se tocan."""
    if tabla not in ('partidas', 'gastos_generales'):
        return ''
    from core.config import ESTADOS_BLOQUEADOS
    nivel = 'presupuesto' if tabla == 'partidas' else 'pie'
    est = ','.join(f"'{e}'" for e in ESTADOS_BLOQUEADOS[nivel])
    return (" AND proyecto_id IN (SELECT id FROM proyectos"
            f" WHERE COALESCE(estado,'elaboracion') NOT IN ({est}))")


def en_uso(conn) -> dict:
    """{unidad: {tabla: nº de filas}} de lo que se puede cambiar."""
    usos = {}
    for t in _TABLAS:
        for u, n in conn.execute(
                f"SELECT unidad, COUNT(*) FROM {t}"
                f" WHERE TRIM(COALESCE(unidad,''))<>''{_filtro(t)} GROUP BY unidad"):
            usos.setdefault(u, {})[t] = n
    return usos


def variantes(conn) -> list:
    """Grupos con más de una grafía: [{'sugerida', 'grafias': {u: n}, 'usos'}]."""
    grupos = {}
    usos = en_uso(conn)
    for u, por_tabla in usos.items():
        if '%' not in u and clave(u):
            grupos.setdefault((clave(u), _firma(u)), {})[u] = sum(por_tabla.values())
    out = []
    for (cl, _f), grafias in grupos.items():
        if len(grafias) < 2:
            continue
        # La grafía de la lista de siempre («m²») si vale exactamente igual;
        # si no, la más usada.
        normal = next((c for c in COMUNES if misma_unidad(c, next(iter(grafias)))), None)
        sugerida = normal or max(grafias, key=lambda u: (grafias[u], u))
        tablas = {t: sum(usos[u].get(t, 0) for u in grafias) for t in _TABLAS}
        out.append({'clave': cl, 'sugerida': sugerida,
                    'grafias': dict(sorted(grafias.items(), key=lambda x: -x[1])),
                    'tablas': tablas})
    out.sort(key=lambda g: -sum(g['grafias'].values()))
    return out


def unir(conn, cambios: dict) -> int:
    """Aplica {grafía vieja: grafía nueva} en UNA transacción y devuelve cuántas
    filas cambió. Rechaza cualquier par que no sea la misma unidad."""
    cambios = {a: b.strip() for a, b in cambios.items() if a != b.strip()}
    for a, b in cambios.items():
        if not misma_unidad(a, b):
            raise ValueError(f'«{a}» y «{b}» no son la misma unidad')
    n = 0
    with conn:
        for t in _TABLAS:
            for a, b in cambios.items():
                n += conn.execute(
                    f"UPDATE {t} SET unidad=? WHERE unidad=?{_filtro(t)}",
                    (b, a)).rowcount
    if n:
        _olvidar_indices()
    return n


def _olvidar_indices():
    """El pool de partidas parecidas guarda la unidad y su firma no la mira."""
    import core.database as d
    d._POOL_RAG_CACHE = None
    try:
        from core import biblioteca_embeddings as be
        be._INDEX = None
        be._INDEX_META.unlink(missing_ok=True)
    except Exception:
        pass            # sin numpy/model2vec no hay índice que olvidar


def lista(conn=None) -> list:
    """Unidades para elegir: las comunes —con la grafía de casa si solo se usa
    una— y después las demás que ya están en uso."""
    propia = conn is None
    if propia:
        conn = get_db()
    usos = {}
    for t in _TABLAS:
        for (u,) in conn.execute(f"SELECT DISTINCT unidad FROM {t}"):
            u = (u or '').strip()
            if u:
                usos.setdefault(clave(u), set()).add(u)
    if propia:
        conn.close()
    out, vistas = [], set()
    for c in COMUNES:
        k = clave(c)
        g = usos.get(k, set())
        out.append(next(iter(g)) if len(g) == 1 else c)
        vistas.add(k)
    out += sorted((u for k, g in usos.items() if k not in vistas for u in g),
                  key=str.lower)
    return out
