# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Mover, borrar y renumerar partidas sin la interfaz (las usa el MCP).

Misma numeración que el árbol (`PresupuestoTree._renumerar`). No hacen commit.
"""
from __future__ import annotations

import re

from core import partidas_ops as ops


class Arbol:
    """El árbol de un sub-presupuesto: `hijos[id]` en orden (None = raíz)."""

    def __init__(self, conn, pid: int, sub):
        filas = conn.execute(
            "SELECT id, item, es_titulo FROM partidas_ppto WHERE proyecto_id=?"
            " AND sub_presupuesto_id IS ? ORDER BY item, id", (pid, sub)).fetchall()
        self.pid, self.sub = pid, sub
        self.hijos: dict = {None: []}
        self.padre: dict = {}
        self.titulo = {f['id']: bool(f['es_titulo']) for f in filas}
        por_item = {}
        for f in filas:
            por_item.setdefault(f['item'], f['id'])
        for f in filas:
            arriba, padre = f['item'], None
            while '.' in arriba:
                arriba = arriba.rpartition('.')[0]
                if por_item.get(arriba, f['id']) != f['id']:
                    padre = por_item[arriba]
                    break
            self.padre[f['id']] = padre
            self.hijos.setdefault(padre, []).append(f['id'])

    def descendientes(self, i) -> list:
        out = []
        for h in self.hijos.get(i, []):
            out += [h, *self.descendientes(h)]
        return out

    def quitar(self, i) -> None:
        self.hijos[self.padre[i]].remove(i)

    def poner(self, i, padre, pos: int | None = None) -> None:
        lista = self.hijos.setdefault(padre, [])
        lista.insert(len(lista) if pos is None else pos, i)
        self.padre[i] = padre

    def renumerar(self, conn) -> None:
        inicio = 0
        if self.sub is not None:
            inicio = conn.execute(
                """SELECT COUNT(*) FROM partidas_ppto WHERE proyecto_id=? AND nivel=1
                   AND (sub_presupuesto_id IS NULL OR sub_presupuesto_id IN (
                     SELECT id FROM sub_presupuestos WHERE proyecto_id=? AND orden <
                       (SELECT orden FROM sub_presupuestos WHERE id=?)))""",
                (self.pid, self.pid, self.sub)).fetchone()[0]

        def nivel(padre, prefijo, n, desde):
            ids = self.hijos.get(padre, [])
            ancho = max(2, len(str(len(ids) + desde)))
            for k, i in enumerate(ids, start=1 + desde):
                cod = f"{prefijo}{k:0{ancho}d}"
                conn.execute("UPDATE partidas SET item=?, nivel=? WHERE id=?",
                             (cod, n, i))
                nivel(i, cod + '.', n + 1, 0)
        nivel(None, '', 1, inicio)


# ── Predecesoras ─────────────────────────────────────────────────────────────

def foto_filas(conn, pid: int) -> tuple[dict, dict]:
    """(nº de fila del Gantt → clave, ítem → id) de ahora."""
    from core.cronograma import numerar_filas
    partidas = ops.partidas_en_orden(conn, pid)
    return ({v: k for k, v in numerar_filas(partidas).items()},
            {p['item']: p['id'] for p in partidas})


def conservar_predecesoras(conn, pid: int, antes: tuple[dict, dict]) -> int:
    """Las predecesoras se guardan como número de fila («5FC+2»): al insertar,
    mover o borrar partidas apuntarían a otra. Las reescribe para que sigan en
    la misma; la de una partida borrada se quita. Devuelve cuántas se quitaron."""
    filas0, items0 = antes
    filas1, items1 = foto_filas(conn, pid)
    if filas0 == filas1 and items0 == items1:
        return 0
    num = {k: n for n, k in filas1.items()}
    cod = {i: c for c, i in items1.items()}
    quitadas = 0
    for r in conn.execute(
            """SELECT c.partida_id, c.predecesoras FROM cronograma_partidas c
               JOIN partidas p ON p.id=c.partida_id
               WHERE p.proyecto_id=? AND COALESCE(c.predecesoras,'')<>''""",
            (pid,)).fetchall():
        nuevas = []
        for ref in re.split(r'[,;]+', r['predecesoras']):
            ref = ref.strip()
            m = re.match(r'[\d.]+', ref)
            base = m.group(0) if m else ''
            if base.isdecimal() and str(int(base)) == base and int(base) in filas0:
                clave, destino = filas0[int(base)], num
            elif base in items0:
                clave, destino = items0[base], cod
            else:
                if ref:
                    nuevas.append(ref)
                continue
            if clave in destino:
                nuevas.append(f"{destino[clave]}{ref[len(base):]}")
            else:
                quitadas += 1
        txt = ','.join(nuevas)
        if txt != r['predecesoras']:
            conn.execute("UPDATE cronograma_partidas SET predecesoras=? WHERE"
                         " partida_id=?", (txt, r['partida_id']))
    return quitadas


def con_obra_registrada(conn, ids) -> list[int]:
    """De esas partidas, las que ya tienen avance o adquisiciones de obra:
    borrarlas se llevaría valorizaciones y partes diarios en cascada."""
    ids = list(ids)
    out = set()
    for (t,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND"
            " (name LIKE 'valorizacion%' OR name LIKE 'parte_diario%')").fetchall():
        if 'partida_id' not in {c['name'] for c in conn.execute(
                f'PRAGMA table_info("{t}")')}:
            continue
        for k in range(0, len(ids), 500):
            trozo = ids[k:k + 500]
            out |= {r[0] for r in conn.execute(
                f'SELECT DISTINCT partida_id FROM "{t}" WHERE partida_id IN '
                f"({','.join('?' * len(trozo))})", trozo)}
    return sorted(out)
