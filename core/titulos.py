# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Lista de títulos que ofrece «Agregar título» (issue #20).

La lista de fábrica no es una tabla: son los títulos distintos de todos los
proyectos, y por eso un título nuevo entra solo. Lo que el usuario cambia se
guarda aparte, en `titulos_lista`, como una capa por encima: nunca se escribe
en `partidas`, y restaurar es borrar la capa.

`clave` es el texto tal como está en los proyectos (o el de un título propio),
`descripcion` el que se muestra, `oculto` los borrados y `orden` los movidos a
mano (los demás van después, por orden alfabético, como siempre).
"""

TABLA_SQL = """
CREATE TABLE IF NOT EXISTS titulos_lista (
    clave TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL,
    orden INTEGER,
    oculto INTEGER NOT NULL DEFAULT 0,
    propia INTEGER NOT NULL DEFAULT 0
);
"""


def _de_proyectos(conn) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT descripcion FROM partidas"
        " WHERE es_titulo=1 AND COALESCE(descripcion, '')<>''")}


def filas(conn) -> list[dict]:
    """La lista en su orden: [{'descripcion', 'claves', 'propia'}]. Dos claves
    con el mismo texto (un título renombrado como otro) son una sola fila."""
    base = _de_proyectos(conn)
    capa = {r['clave']: r for r in conn.execute("SELECT * FROM titulos_lista")}
    por_desc: dict[str, dict] = {}

    def _poner(clave, desc, orden, propia):
        f = por_desc.setdefault(desc, {'descripcion': desc, 'claves': [],
                                       'propia': False, 'orden': None})
        f['claves'].append(clave)
        f['propia'] = f['propia'] or propia
        if orden is not None and (f['orden'] is None or orden < f['orden']):
            f['orden'] = orden

    for clave in base - capa.keys():
        _poner(clave, clave, None, False)
    for clave, r in capa.items():
        # Sin proyecto que lo use, un título de fábrica solo movido
        # desaparece, como siempre; uno corregido a mano se conserva.
        if not r['oculto'] and (clave in base or r['propia']
                                or r['descripcion'] != clave):
            _poner(clave, r['descripcion'], r['orden'], bool(r['propia']))
    out = sorted(por_desc.values(), key=lambda f: f['descripcion'])
    out.sort(key=lambda f: (f['orden'] is None, f['orden'] or 0))
    return [{'descripcion': f['descripcion'], 'claves': f['claves'],
             'propia': f['propia']} for f in out]


def lista(conn) -> list[str]:
    return [f['descripcion'] for f in filas(conn)]


def guardar(conn, nuevas: list[dict]) -> None:
    """Guarda la lista entera como quedó en el gestor: lo que falta se oculta,
    el orden es el de `nuevas`. Una fila nueva lleva `claves` vacío."""
    previas = filas(conn)
    ocultas = [r['clave'] for r in conn.execute(
        "SELECT clave FROM titulos_lista WHERE oculto=1")]
    base = _de_proyectos(conn)

    # Se numera solo hasta la última fila fuera de su sitio: el resto ya va en
    # orden alfabético y los títulos nuevos se intercalan ahí.
    descs = [f['descripcion'] for f in nuevas]
    tramo = max(0, len(descs) - 1)
    while tramo and descs[tramo - 1] <= descs[tramo]:
        tramo -= 1

    # Si una fila nueva usa el texto que otra tenía antes de renombrarse, la
    # clave pasa a la nueva y la renombrada queda como título propio.
    textos = set(descs)
    nuevas = [dict(f, claves=[c for c in f['claves']
                              if c == f['descripcion'] or c not in textos])
              for f in nuevas]

    capa: dict[str, tuple] = {c: (c, 1, None, 0) for c in ocultas}
    vivas = {c for f in nuevas for c in f['claves']}
    for f in previas:
        for c in f['claves']:
            if c not in vivas and c in base:
                capa[c] = (c, 1, None, 0)
    for pos, f in enumerate(nuevas):
        desc = f['descripcion']
        orden = pos + 1 if pos < tramo else None
        propia = int(bool(f['propia'] or not f['claves']))
        claves = f['claves'] or [desc]
        for c in claves:
            if c not in base and propia:
                c = desc                    # un título propio: su clave es él
            if c != desc or orden is not None or propia:
                capa[c] = (desc, 0, orden, propia)
    with conn:
        conn.execute("DELETE FROM titulos_lista")
        conn.executemany(
            "INSERT INTO titulos_lista (clave, descripcion, oculto, orden, propia)"
            " VALUES (?,?,?,?,?)", [(c, *v) for c, v in capa.items()])


def restaurar(conn) -> None:
    """Vuelve a la lista de fábrica: deshace lo borrado, lo corregido y el
    orden. Los títulos que el usuario agregó se conservan."""
    propias = {f['descripcion'] for f in filas(conn) if f['propia']}
    with conn:
        conn.execute("DELETE FROM titulos_lista")
        conn.executemany(
            "INSERT INTO titulos_lista (clave, descripcion, propia) VALUES (?,?,1)",
            [(d, d) for d in sorted(propias)])
