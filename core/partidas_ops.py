# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Operaciones de edición del presupuesto sin Qt ni diálogos.

Las reglas de número (PU, overhead, precio único por proyecto, decimales)
son las de `core.database`; aquí está el PASO que antes solo existía dentro
de un diálogo. Todas reciben `conn` y NO hacen commit: la transacción es del
que llama.
"""
from __future__ import annotations

from core.database import (_recalcular_pu, _rn, copiar_items_acu,
                           get_decimales_cant_acu, get_decimales_metrado,
                           partida_global, precio_recurso_en_proyecto,
                           recurso_por_dia, recurso_por_hora)


def siguiente_item(conn, pid: int, contexto: str | None,
                   es_titulo: bool) -> str:
    """Primer código libre: hijo del título `contexto`, hermano de la partida
    `contexto`, o raíz. Se mira el proyecto entero, no el sub-presupuesto."""
    existing = {r[0] for r in conn.execute(
        "SELECT item FROM partidas_ppto WHERE proyecto_id=?", (pid,))}
    if contexto and es_titulo:
        prefijo = contexto + '.'
    elif contexto and '.' in contexto:
        prefijo = contexto.rsplit('.', 1)[0] + '.'
    else:
        prefijo = ''
    for n in range(1, 1000):
        codigo = f"{prefijo}{n:02d}"
        if codigo not in existing:
            return codigo
    return "99"


def insertar_titulo(conn, pid: int, item: str, descripcion: str,
                    sub_id: int | None) -> int:
    return conn.execute(
        """INSERT INTO partidas
           (proyecto_id, item, descripcion, unidad, metrado, precio_unitario,
            nivel, es_titulo, rendimiento, sub_presupuesto_id)
           VALUES (?,?,?,'',0,0,?,1,1,?)""",
        (pid, item, descripcion, len(item.split('.')), sub_id)).lastrowid


def insertar_partida(conn, pid: int, item: str, descripcion: str, unidad: str,
                     sub_id: int | None) -> int:
    return conn.execute(
        """INSERT INTO partidas
           (proyecto_id, item, descripcion, unidad, metrado, precio_unitario,
            nivel, es_titulo, rendimiento, grupo, sub_presupuesto_id)
           VALUES (?,?,?,?,0,0,?,0,1,'',?)""",
        (pid, item, descripcion, unidad, len(item.split('.')), sub_id)).lastrowid


def insertar_desde_biblioteca(conn, pid: int, cu_id: int, item: str,
                              sub_id: int | None,
                              solo_estructura: bool = False) -> int | None:
    """Partida nueva con el ACU de un costo unitario de la biblioteca.
    None si ese costo unitario no existe."""
    cu = conn.execute("SELECT * FROM biblioteca_cu WHERE id=?",
                      (cu_id,)).fetchone()
    if not cu:
        return None
    nuevo = conn.execute(
        """INSERT INTO partidas
           (proyecto_id, item, descripcion, unidad, metrado, precio_unitario,
            nivel, es_titulo, rendimiento, sub_presupuesto_id)
           VALUES (?,?,?,?,0,?,?,0,?,?)""",
        (pid, item, cu['descripcion'], cu['unidad'] or '',
         cu['costo_unitario'] or 0, len(item.split('.')),
         cu['rendimiento'] or 1, sub_id)).lastrowid
    copiar_acu_biblioteca(conn, pid, nuevo, cu_id, solo_estructura)
    return nuevo


def copiar_acu_biblioteca(conn, pid: int, partida_id: int, cu_id: int,
                          solo_estructura: bool = False) -> int:
    filas = conn.execute("SELECT * FROM biblioteca_acu_items WHERE cu_id=?",
                         (cu_id,)).fetchall()
    n = copiar_items_acu(conn, partida_id, filas, proyecto_id=pid,
                         solo_estructura=solo_estructura)
    if filas:
        _recalcular_pu(conn, partida_id)
    return n


# ── ACU ──────────────────────────────────────────────────────────────────────

def cuadrilla_y_cantidad(tipo, unidad, *, cuad, cant, rend, jornada,
                         es_global) -> tuple[float, float]:
    """Qué se graba en `acu_items` para un insumo que entra al ACU.

    Devuelve `(cuadrilla, cantidad)`. La regla es la del ACU (helpers de
    `core.database`): en MO y equipo por hora o por día la cantidad se DERIVA
    de la cuadrilla; en todo lo demás —y en toda partida global— la cuadrilla
    no aplica y se graba 0, nunca el «1.000» que trae el campo por defecto.

    Las DOS pestañas del diálogo «Agregar recursos» pasan por aquí, y el MCP.
    Hasta la 3.0.4 «Crear nuevo recurso» grababa la cuadrilla tal cual para
    cualquier tipo, así que un material nuevo entraba con cuadrilla 1.0
    mientras «Buscar en catálogo» le ponía 0 (reporte de David Ramos,
    2 sep 2026).
    """
    por_dia = recurso_por_dia(tipo, unidad)
    if es_global or not (por_dia or recurso_por_hora(tipo, unidad)):
        return 0.0, cant
    if cuad <= 0:
        return 0.0, cant
    factor = 1 if por_dia else jornada
    return cuad, _rn(cuad / (rend or 1) * factor, get_decimales_cant_acu(tipo))


def jornada_de(conn, pid: int) -> float:
    r = conn.execute("SELECT jornada_laboral FROM proyectos WHERE id=?",
                     (pid,)).fetchone()
    return (r['jornada_laboral'] if r else None) or 8


def insertar_insumo(conn, partida_id: int, recurso_id: int, *,
                    cuadrilla: float = 0.0, cantidad: float = 0.0) -> int:
    """Agrega un recurso del catálogo al ACU, con el precio que ya tiene en
    el proyecto o, si es nuevo, el del catálogo. No recalcula el PU."""
    p = conn.execute("SELECT * FROM partidas WHERE id=?", (partida_id,)).fetchone()
    r = conn.execute("SELECT tipo, unidad, precio FROM recursos WHERE id=?",
                     (recurso_id,)).fetchone()
    cuad, cant = cuadrilla_y_cantidad(
        r['tipo'], r['unidad'], cuad=cuadrilla, cant=cantidad,
        rend=p['rendimiento'], jornada=jornada_de(conn, p['proyecto_id']),
        es_global=partida_global(p['unidad']))
    precio = precio_recurso_en_proyecto(conn, p['proyecto_id'], recurso_id)
    if precio is None:
        precio = r['precio'] or 0
    return conn.execute(
        "INSERT INTO acu_items (partida_id, recurso_id, cuadrilla, cantidad, precio)"
        " VALUES (?,?,?,?,?)",
        (partida_id, recurso_id, cuad, cant, precio)).lastrowid


def aplicar_rendimiento(conn, partida_id: int, rend: float) -> None:
    """Graba el rendimiento y re-deriva las cantidades que salen de una
    cuadrilla. 0 = «no aplica»: se conservan las cantidades. Recalcula el PU."""
    p = conn.execute("SELECT proyecto_id, unidad FROM partidas WHERE id=?",
                     (partida_id,)).fetchone()
    conn.execute("UPDATE partidas SET rendimiento=? WHERE id=?",
                 (rend, partida_id))
    if rend > 0 and not partida_global(p['unidad']):
        jornada = jornada_de(conn, p['proyecto_id'])
        for it in conn.execute(
                """SELECT ai.id, ai.cuadrilla, r.tipo, r.unidad
                   FROM acu_items ai JOIN recursos r ON r.id=ai.recurso_id
                   WHERE ai.partida_id=?""", (partida_id,)).fetchall():
            cuad, cant = cuadrilla_y_cantidad(
                it['tipo'], it['unidad'], cuad=it['cuadrilla'] or 0,
                cant=None, rend=rend, jornada=jornada, es_global=False)
            if cuad > 0 and cant is not None:
                conn.execute("UPDATE acu_items SET cantidad=? WHERE id=?",
                             (cant, it['id']))
    _recalcular_pu(conn, partida_id)


# ── Metrados ─────────────────────────────────────────────────────────────────

CAMPOS_PLANILLA = ('n_estructuras', 'n_elementos', 'area', 'largo', 'ancho',
                   'alto')


def parcial_fila(fila: dict) -> float:
    """Producto de las dimensiones PRESENTES (una vacía no multiplica),
    redondeado a los decimales de metrado; sin ninguna, 0."""
    dims = [fila.get(c) for c in CAMPOS_PLANILLA if fila.get(c) is not None]
    if not dims:
        return 0.0
    p = 1.0
    for d in dims:
        p *= d
    return _rn(p, get_decimales_metrado())


def guardar_planilla(conn, partida_id: int, filas: list[dict]) -> float:
    """Reemplaza la planilla de la partida (y quita la de acero: son
    excluyentes) y fija su metrado = Σ parciales. Devuelve el metrado."""
    conn.execute("DELETE FROM acero_detalle WHERE partida_id=?", (partida_id,))
    conn.execute("DELETE FROM metrados_detalle WHERE partida_id=?", (partida_id,))
    total = 0.0
    for n, f in enumerate(filas, start=1):
        parcial = parcial_fila(f)
        total += parcial
        conn.execute(
            """INSERT INTO metrados_detalle
               (partida_id, orden, descripcion, n_estructuras, n_elementos,
                area, largo, ancho, alto, parcial)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (partida_id, n, (f.get('descripcion') or '').strip(),
             *(f.get(c) for c in CAMPOS_PLANILLA), parcial))
    total = _rn(total, get_decimales_metrado())
    conn.execute("UPDATE partidas SET metrado=? WHERE id=?", (total, partida_id))
    return total


def fijar_metrado(conn, partida_id: int, metrado: float) -> None:
    """Metrado directo, sin planilla (como al teclearlo en el árbol)."""
    conn.execute("DELETE FROM acero_detalle WHERE partida_id=?", (partida_id,))
    conn.execute("DELETE FROM metrados_detalle WHERE partida_id=?", (partida_id,))
    conn.execute("UPDATE partidas SET metrado=? WHERE id=?",
                 (metrado, partida_id))


# ── Cronograma ───────────────────────────────────────────────────────────────

def partidas_en_orden(conn, pid: int) -> list[dict]:
    """Partidas AGRUPADAS por sub-presupuesto, el orden que piden
    `core.cronograma.numerar_filas` y `cpm`."""
    return [dict(r) for r in conn.execute(
        """SELECT p.* FROM partidas_ppto p
           LEFT JOIN sub_presupuestos s ON s.id = p.sub_presupuesto_id
           WHERE p.proyecto_id=?
           ORDER BY (CASE WHEN p.sub_presupuesto_id IS NULL THEN 0 ELSE 1 END),
                    COALESCE(s.orden, 0), p.sub_presupuesto_id, p.item""",
        (pid,))]
