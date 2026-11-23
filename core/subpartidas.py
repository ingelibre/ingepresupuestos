# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Sub-partidas (issue #23): un análisis propio —mortero, concreto, cuadrilla
tipo— que entra como una línea dentro del ACU de otras partidas.

Modelo: la sub-partida es una fila de `partidas` con `es_subanalisis=1` y
metrado 0, que NO está en el presupuesto (la vista `partidas_ppto` la deja
fuera). La línea que la usa es un `acu_items` con `sub_partida_id`.

`acu_items.recurso_id` sigue siendo NOT NULL: la línea apunta a un recurso
único «SUB-PARTIDA» de tipo SC, y su `precio` guarda el costo del hijo
(lo mantiene `database._recalcular_pu`). Así ninguna de las consultas que
hacen JOIN con `recursos` pierde la línea, la suma del ACU sale bien aunque
quien la lea no sepa de sub-partidas, y no hay que reconstruir la tabla.

Reglas (decididas por Marco, nov 2026): la base de %MO/%MT del padre no
incluye lo que hay dentro de la sub-partida, que entra como bloque; y hay un
solo nivel: una sub-partida no contiene otra.
"""
from utils.i18n import tr

CODIGO_RECURSO = 'SUBPARTIDA'
DESC_RECURSO = 'SUB-PARTIDA'


def recurso_subpartida(conn) -> int:
    """El recurso al que apuntan todas las líneas de sub-partida."""
    r = conn.execute("SELECT id FROM recursos WHERE codigo=?",
                     (CODIGO_RECURSO,)).fetchone()
    if r:
        return r[0]
    return conn.execute(
        "INSERT INTO recursos (codigo, descripcion, tipo, unidad, precio, indice_inei)"
        " VALUES (?,?,'SC','',0,'')", (CODIGO_RECURSO, DESC_RECURSO)).lastrowid


def es_subpartida(conn, part_id) -> bool:
    r = conn.execute("SELECT es_subanalisis FROM partidas WHERE id=?",
                     (part_id,)).fetchone()
    return bool(r and r[0])


def contiene_subpartidas(conn, part_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM acu_items WHERE partida_id=? AND sub_partida_id IS NOT NULL"
        " LIMIT 1", (part_id,)).fetchone() is not None


def listar(conn, proyecto_id) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT p.id, p.item, p.descripcion, p.unidad, p.precio_unitario,"
        "       (SELECT COUNT(DISTINCT ai.partida_id) FROM acu_items ai"
        "         WHERE ai.sub_partida_id = p.id) AS n_usos"
        "  FROM partidas p WHERE p.proyecto_id=? AND p.es_subanalisis=1"
        " ORDER BY p.descripcion, p.id", (proyecto_id,))]


def usos(conn, sub_id) -> list[dict]:
    """Las partidas cuyo ACU usa la sub-partida."""
    return [dict(r) for r in conn.execute(
        "SELECT DISTINCT p.id, p.item, p.descripcion FROM acu_items ai"
        " JOIN partidas p ON p.id = ai.partida_id WHERE ai.sub_partida_id=?"
        " ORDER BY p.item", (sub_id,))]


# ── Alta ─────────────────────────────────────────────────────────────────────

def _siguiente_item(conn, proyecto_id) -> str:
    nums = [int(r[0][3:]) for r in conn.execute(
        "SELECT item FROM partidas WHERE proyecto_id=? AND es_subanalisis=1",
        (proyecto_id,)) if r[0][:3] == 'SP-' and r[0][3:].isdigit()]
    return f"SP-{max(nums, default=0) + 1:03d}"


def _buscar(conn, proyecto_id, descripcion, unidad) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT id FROM partidas WHERE proyecto_id=? AND es_subanalisis=1"
        " AND UPPER(TRIM(descripcion))=? AND TRIM(COALESCE(unidad,''))=? ORDER BY id",
        (proyecto_id, (descripcion or '').strip().upper(), (unidad or '').strip()))]


def validar_datos(conn, proyecto_id, descripcion, unidad, *, excluir=None):
    """ValueError con el motivo si la ficha no sirve."""
    if not (descripcion or '').strip():
        raise ValueError(tr("La sub-partida necesita una descripción."))
    if (unidad or '').strip().startswith('%'):
        raise ValueError(tr("La unidad de una sub-partida no puede ser un porcentaje."))
    if any(i != excluir for i in _buscar(conn, proyecto_id, descripcion, unidad)):
        raise ValueError(tr("Ya hay una sub-partida con esa descripción y unidad en el proyecto."))


def crear(conn, proyecto_id, descripcion, unidad='', rendimiento=0) -> int:
    """Sub-partida nueva, con el análisis vacío."""
    validar_datos(conn, proyecto_id, descripcion, unidad)
    return conn.execute(
        "INSERT INTO partidas (proyecto_id, item, descripcion, unidad, metrado,"
        " precio_unitario, nivel, es_titulo, rendimiento, es_subanalisis)"
        " VALUES (?,?,?,?,0,0,1,0,?,1)",
        (proyecto_id, _siguiente_item(conn, proyecto_id), descripcion.strip(),
         (unidad or '').strip(), rendimiento or 0)).lastrowid


def _nombre_libre(conn, proyecto_id, descripcion, unidad) -> str:
    base = (descripcion or '').strip() or DESC_RECURSO
    nombre, n = base, 1
    while _buscar(conn, proyecto_id, nombre, unidad):
        n += 1
        nombre = f"{base} ({n})"
    return nombre


def _crear_con_items(conn, proyecto_id, descripcion, unidad, rendimiento, items,
                     solo_estructura=False) -> int:
    from core.database import _recalcular_pu, copiar_items_acu
    items = [dict(i) for i in items]
    if any(i.get('sub_partida_id') for i in items):
        raise ValueError(tr("Ese análisis ya usa una sub-partida, y una sub-partida "
                            "no puede contener otra."))
    if (unidad or '').strip().startswith('%'):
        raise ValueError(tr("La unidad de una sub-partida no puede ser un porcentaje."))
    sid = crear(conn, proyecto_id,
                _nombre_libre(conn, proyecto_id, descripcion, unidad),
                unidad, rendimiento)
    copiar_items_acu(conn, sid, items, proyecto_id=proyecto_id,
                     solo_estructura=solo_estructura)
    _recalcular_pu(conn, sid)
    return sid


def crear_desde_partida(conn, proyecto_id, part_id) -> int:
    """Copia el análisis de una partida (de este proyecto o de otro)."""
    p = conn.execute("SELECT * FROM partidas WHERE id=?", (part_id,)).fetchone()
    if not p or p['es_titulo']:
        raise ValueError(tr("Elija una partida con análisis de costos."))
    items = conn.execute(
        "SELECT ai.recurso_id, ai.cuadrilla, ai.cantidad, ai.sub_partida_id,"
        "       COALESCE(ai.precio, r.precio) AS precio FROM acu_items ai"
        " JOIN recursos r ON r.id = ai.recurso_id WHERE ai.partida_id=?"
        " ORDER BY ai.orden IS NULL, ai.orden, ai.id", (part_id,)).fetchall()
    return _crear_con_items(conn, proyecto_id, p['descripcion'], p['unidad'],
                            p['rendimiento'], items)


def crear_desde_biblioteca(conn, proyecto_id, cu_id, solo_estructura=False) -> int:
    cu = conn.execute("SELECT * FROM biblioteca_cu WHERE id=?", (cu_id,)).fetchone()
    if not cu:
        raise ValueError(tr("Elija una partida con análisis de costos."))
    items = conn.execute("SELECT * FROM biblioteca_acu_items WHERE cu_id=?",
                         (cu_id,)).fetchall()
    return _crear_con_items(conn, proyecto_id, cu['descripcion'], cu['unidad'],
                            cu['rendimiento'], items, solo_estructura)


# ── Enlace con el ACU ────────────────────────────────────────────────────────

def validar_enlace(conn, part_id, sub_id):
    """ValueError si `sub_id` no puede entrar en el ACU de `part_id`."""
    padre = conn.execute("SELECT * FROM partidas WHERE id=?", (part_id,)).fetchone()
    sub = conn.execute("SELECT * FROM partidas WHERE id=?", (sub_id,)).fetchone()
    if not padre or not sub or padre['es_titulo'] or not sub['es_subanalisis']:
        raise ValueError(tr("Elija una sub-partida del proyecto."))
    if part_id == sub_id:
        raise ValueError(tr("Una sub-partida no puede usarse a sí misma."))
    if padre['es_subanalisis']:
        raise ValueError(tr("Una sub-partida no puede contener otra sub-partida."))
    if padre['proyecto_id'] != sub['proyecto_id']:
        raise ValueError(tr("La sub-partida es de otro proyecto."))
    if contiene_subpartidas(conn, sub_id):
        raise ValueError(tr("Ese análisis ya usa una sub-partida, y una sub-partida "
                            "no puede contener otra."))


def enlazar(conn, part_id, sub_id, cantidad=1.0, orden=None) -> int:
    """Agrega la sub-partida como línea del ACU. No recalcula el PU."""
    validar_enlace(conn, part_id, sub_id)
    pu = conn.execute("SELECT precio_unitario FROM partidas WHERE id=?",
                      (sub_id,)).fetchone()[0] or 0
    return conn.execute(
        "INSERT INTO acu_items (partida_id, recurso_id, cuadrilla, cantidad,"
        " precio, orden, sub_partida_id) VALUES (?,?,0,?,?,?,?)",
        (part_id, recurso_subpartida(conn), cantidad, pu, orden, sub_id)).lastrowid


def _firma(items) -> list:
    return sorted((i['recurso_id'], round(i['cantidad'] or 0, 6)) for i in items)


def _gemela(conn, proyecto_id, descripcion, unidad, items):
    """La sub-partida del proyecto con la misma ficha y la misma composición
    (los precios los pone el proyecto). None si no hay."""
    firma = _firma(items)
    for sid in _buscar(conn, proyecto_id, descripcion, unidad):
        if _firma(conn.execute("SELECT recurso_id, cantidad FROM acu_items"
                               " WHERE partida_id=?", (sid,)).fetchall()) == firma:
            return sid
    return None


def traer(conn, sub_id, proyecto_id, solo_estructura=False):
    """Id de la sub-partida DENTRO de `proyecto_id`: la misma si ya es suya,
    su gemela si la hay, o una copia. None si el origen no existe."""
    s = conn.execute("SELECT * FROM partidas WHERE id=?", (sub_id,)).fetchone()
    if not s:
        return None
    if s['proyecto_id'] == proyecto_id:
        return sub_id
    items = conn.execute("SELECT * FROM acu_items WHERE partida_id=?",
                         (sub_id,)).fetchall()
    return (_gemela(conn, proyecto_id, s['descripcion'], s['unidad'], items)
            or _crear_con_items(conn, proyecto_id, s['descripcion'], s['unidad'],
                                s['rendimiento'], items, solo_estructura))


def enlazar_copia(conn, part_id, sub_id, cantidad, proyecto_id,
                  solo_estructura=False, orden=None) -> bool:
    """Para copiar ACU entre partidas o proyectos. False si no puede entrar
    (p. ej. pegar una sub-partida dentro de otra)."""
    if es_subpartida(conn, part_id):
        return False
    sid = traer(conn, sub_id, proyecto_id, solo_estructura)
    if sid is None:
        return False
    enlazar(conn, part_id, sid, cantidad, orden)
    return True


def recurso_equivalente(conn, sub_id) -> int:
    """Recurso SC con el nombre de la sub-partida: cómo entra su línea en la
    biblioteca, que no tiene sub-partidas (el precio lo guarda el ítem)."""
    s = conn.execute("SELECT descripcion, unidad, precio_unitario FROM partidas"
                     " WHERE id=?", (sub_id,)).fetchone()
    r = conn.execute(
        "SELECT id FROM recursos WHERE tipo='SC' AND UPPER(TRIM(descripcion))=?"
        " AND TRIM(COALESCE(unidad,''))=? ORDER BY id LIMIT 1",
        (s['descripcion'].strip().upper(), (s['unidad'] or '').strip())).fetchone()
    if r:
        return r[0]
    from core.database import _siguiente_codigo_inei
    return conn.execute(
        "INSERT INTO recursos (codigo, descripcion, tipo, unidad, precio, indice_inei)"
        " VALUES (?,?,'SC',?,?,'39')",
        (_siguiente_codigo_inei(conn, '39'), s['descripcion'].strip(),
         (s['unidad'] or '').strip(), s['precio_unitario'] or 0)).lastrowid


# ── Baja ─────────────────────────────────────────────────────────────────────

def eliminar(conn, sub_id, forzar=False) -> list[int]:
    """Borra la sub-partida. Si algún ACU la usa, ValueError; con `forzar`
    quita esas líneas y recalcula. Devuelve las partidas afectadas."""
    if not es_subpartida(conn, sub_id):
        raise ValueError(tr("Elija una sub-partida del proyecto."))
    afectadas = usos(conn, sub_id)
    if afectadas and not forzar:
        raise ValueError(tr("La sub-partida se usa en {n} análisis: {items}").format(
            n=len(afectadas), items=', '.join(a['item'] for a in afectadas[:8])))
    from core.database import _recalcular_pu
    conn.execute("DELETE FROM acu_items WHERE sub_partida_id=?", (sub_id,))
    conn.execute("DELETE FROM partidas WHERE id=?", (sub_id,))
    for a in afectadas:
        _recalcular_pu(conn, a['id'])
    return [a['id'] for a in afectadas]


def usadas_en(conn, part_ids) -> list:
    """Las sub-partidas (filas de `partidas`) que usan esas partidas, para
    imprimir su análisis después de los del presupuesto."""
    ids = set(part_ids)
    sub_ids = {r[1] for r in conn.execute(
        "SELECT partida_id, sub_partida_id FROM acu_items"
        " WHERE sub_partida_id IS NOT NULL") if r[0] in ids}
    filas = [conn.execute("SELECT * FROM partidas WHERE id=?", (i,)).fetchone()
             for i in sub_ids]
    return sorted((f for f in filas if f), key=lambda f: (f['item'], f['id']))
