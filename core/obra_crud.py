# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Ciclo de vida común de los documentos de Control de Obra.

Requerimientos, partes diarios y valorizaciones son tres documentos distintos
pero comparten el mismo esqueleto: cuelgan de un proyecto, se leen por id, se
listan por proyecto, se cierran y se reabren, y dos de ellos guardan un detalle
por categoría reemplazándolo entero. Eso estaba escrito **tres veces** en
`requerimientos.py`, `parte_diario.py` y `valorizacion.py`.

Acá vive el esqueleto. Lo que NO está acá, y es a propósito:

* **`crear_*`** — cada uno crea distinto. El requerimiento deriva su `tipo` de
  la categoría, el parte es *get-or-create* por fecha (uno por día) y la
  valorización arrastra los partes del período al nacer.
* **`eliminar_*`** — tres reglas de negocio distintas. El requerimiento
  recompacta la numeración y borra sus adjuntos; el parte re-sincroniza la
  valorización que lo contenía; la valorización solo deja borrar la ÚLTIMA,
  para no romper la correlatividad del acumulado.

Duplicado no es lo mismo que parecido: esas seis se quedan en su módulo.

**Trampa del estado:** requerimientos y partes usan `'abierto'`/`'cerrado'`;
las valorizaciones, `'abierta'`/`'cerrada'`. El género no es un descuido —
hay consultas por todo el proyecto que filtran por esas cadenas exactas. Por
eso el estado sale de `_DOCS` y no se escribe a mano.
"""
from __future__ import annotations

from core.database import get_db


# Nombre de tabla → estados que usa ese documento. Este diccionario es además
# la LISTA BLANCA: los nombres de tabla se interpolan en el SQL, así que solo
# pueden venir de acá (nunca de un argumento del usuario).
_DOCS = {
    'requerimientos': {'abierto': 'abierto', 'cerrado': 'cerrado'},
    'parte_diario':   {'abierto': 'abierto', 'cerrado': 'cerrado'},
    'valorizaciones': {'abierto': 'abierta', 'cerrado': 'cerrada'},
}

# Tabla de detalle → (columna que apunta al documento, columna que agrupa,
#                     tabla del documento dueño)
_DETALLES = {
    'requerimiento_detalle': ('requerimiento_id', 'tipo',  'requerimientos'),
    'parte_diario_recurso':  ('parte_id',         'clase', 'parte_diario'),
}


def _tabla(doc: str) -> str:
    if doc not in _DOCS:
        raise ValueError(f"documento de obra desconocido: {doc!r}")
    return doc


def estado_cerrado(doc: str) -> str:
    """La cadena exacta que marca «cerrado» en ese documento."""
    return _DOCS[_tabla(doc)]['cerrado']


def estado_abierto(doc: str) -> str:
    """La cadena exacta que marca «abierto» en ese documento."""
    return _DOCS[_tabla(doc)]['abierto']


# ── Lectura ──────────────────────────────────────────────────────────────────

def obtener(doc: str, doc_id: int) -> dict | None:
    """El documento por id, o None si no existe."""
    t = _tabla(doc)
    conn = get_db()
    try:
        r = conn.execute(f"SELECT * FROM {t} WHERE id=?", (doc_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def listar(doc: str, proyecto_id: int, *, orden: str = 'numero') -> list[dict]:
    """Los documentos del proyecto. ``orden`` es un nombre de columna."""
    t = _tabla(doc)
    if not orden.replace('_', '').isalnum():
        raise ValueError(f"orden inválido: {orden!r}")
    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT * FROM {t} WHERE proyecto_id=? ORDER BY {orden}",
            (proyecto_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def siguiente_numero(conn, doc: str, proyecto_id: int) -> int:
    """Correlativo siguiente dentro del proyecto. Usa la conexión que le pasen
    porque va dentro de la misma transacción que el INSERT."""
    t = _tabla(doc)
    return conn.execute(
        f"SELECT COALESCE(MAX(numero), 0) + 1 AS n FROM {t} WHERE proyecto_id=?",
        (proyecto_id,)).fetchone()['n']


# ── Estado ───────────────────────────────────────────────────────────────────

def set_estado(doc: str, doc_id: int, *, abierto: bool) -> None:
    """Abre o cierra el documento con la cadena de estado que le corresponde."""
    t = _tabla(doc)
    nuevo = _DOCS[t]['abierto' if abierto else 'cerrado']
    conn = get_db()
    try:
        conn.execute(f"UPDATE {t} SET estado=? WHERE id=?", (nuevo, doc_id))
        conn.commit()
    finally:
        conn.close()


# ── Detalle por categoría ────────────────────────────────────────────────────

def reemplazar_detalle(detalle: str, doc_id: int, grupo: str,
                       filas: list[dict]) -> bool:
    """Reemplaza entero el detalle de una categoría del documento.

    Devuelve False —sin tocar nada— si el documento está cerrado o no existe.
    Las filas sin descripción **y** sin cantidad se saltan; el ``orden`` se
    renumera desde 1 sobre las que sí entran, así que los huecos que deja el
    usuario en la tabla no viajan a la base.
    """
    if detalle not in _DETALLES:
        raise ValueError(f"tabla de detalle desconocida: {detalle!r}")
    col_doc, col_grupo, doc = _DETALLES[detalle]
    cerrado = _DOCS[doc]['cerrado']

    conn = get_db()
    try:
        r = conn.execute(f"SELECT estado FROM {doc} WHERE id=?",
                         (doc_id,)).fetchone()
        if not r or r['estado'] == cerrado:
            return False
        conn.execute(f"DELETE FROM {detalle} WHERE {col_doc}=? AND {col_grupo}=?",
                     (doc_id, grupo))
        orden = 0
        for f in filas:
            desc = (f.get('descripcion') or '').strip()
            cant = f.get('cantidad')
            if not desc and not cant:
                continue
            orden += 1
            conn.execute(
                f"INSERT INTO {detalle} ({col_doc}, {col_grupo}, recurso_id, "
                f"descripcion, unidad, cantidad, orden) VALUES (?,?,?,?,?,?,?)",
                (doc_id, grupo, f.get('recurso_id'), desc,
                 (f.get('unidad') or ''), float(cant or 0), orden))
        conn.commit()
        return True
    finally:
        conn.close()
