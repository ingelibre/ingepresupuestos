# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Fichas técnicas (PDF) adjuntas a una fila de la BD — mecánica compartida.

Nació en los requerimientos de Control de Obra y se generalizó al llegar a
las especificaciones técnicas de las partidas. El patrón es el mismo en
ambos: la lista viaja como JSON [{nombre, ruta}, …] en una columna TEXT de
la fila dueña, y el archivo se COPIA a
``USER_DATA_DIR/uploads/<subdir>/<fila_id>/`` (la ruta original del usuario
puede vivir en un USB o moverse).

Usos actuales:
- requerimientos:  tabla `requerimientos`, columna `adjuntos`,      subdir «requerimientos»
- especificaciones: tabla `partidas`,      columna `spec_adjuntos`, subdir «especificaciones»
"""
from __future__ import annotations

import json
import os
import shutil

from core.database import get_db

# Solo nombres de tabla/columna de esta whitelist entran al SQL (se
# interpolan porque SQLite no admite placeholders para identificadores).
_PERMITIDOS = {
    ('requerimientos', 'adjuntos'),
    ('partidas', 'spec_adjuntos'),
}


def _check(tabla: str, columna: str):
    if (tabla, columna) not in _PERMITIDOS:
        raise ValueError(f"adjuntos: destino no permitido {tabla}.{columna}")


def get_adjuntos(tabla: str, columna: str, fila_id: int) -> list[dict]:
    _check(tabla, columna)
    conn = get_db()
    try:
        r = conn.execute(f"SELECT {columna} FROM {tabla} WHERE id=?",
                         (fila_id,)).fetchone()
    finally:
        conn.close()
    if not r or not (r[columna] or '').strip():
        return []
    try:
        lista = json.loads(r[columna])
        return lista if isinstance(lista, list) else []
    except (ValueError, TypeError):
        return []


def _set_adjuntos(tabla: str, columna: str, fila_id: int, lista: list[dict]):
    _check(tabla, columna)
    conn = get_db()
    try:
        conn.execute(f"UPDATE {tabla} SET {columna}=? WHERE id=?",
                     (json.dumps(lista, ensure_ascii=False), fila_id))
        conn.commit()
    finally:
        conn.close()


def _dir_adjuntos(subdir: str, fila_id: int):
    from core.config import UPLOADS_DIR
    d = UPLOADS_DIR / subdir / str(fila_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def agregar_adjunto(tabla: str, columna: str, fila_id: int, subdir: str,
                    ruta_origen: str) -> dict:
    """Copia el PDF junto a la fila dueña y lo registra. Devuelve la entrada
    {nombre, ruta}. Un adjunto con el mismo nombre se pisa."""
    nombre = os.path.basename(ruta_origen)
    destino = _dir_adjuntos(subdir, fila_id) / nombre
    shutil.copyfile(ruta_origen, destino)
    lista = [a for a in get_adjuntos(tabla, columna, fila_id)
             if a.get('nombre') != nombre]
    lista.append({'nombre': nombre, 'ruta': str(destino)})
    _set_adjuntos(tabla, columna, fila_id, lista)
    return {'nombre': nombre, 'ruta': str(destino)}


def quitar_adjunto(tabla: str, columna: str, fila_id: int, nombre: str):
    lista = get_adjuntos(tabla, columna, fila_id)
    for a in lista:
        if a.get('nombre') == nombre:
            try:
                os.remove(a.get('ruta') or '')
            except OSError:
                pass
    _set_adjuntos(tabla, columna, fila_id,
                  [a for a in lista if a.get('nombre') != nombre])


def limpiar_carpeta(subdir: str, fila_id: int):
    """Al eliminar la fila dueña: sus fichas ya no tienen dueño."""
    from core.config import UPLOADS_DIR
    shutil.rmtree(UPLOADS_DIR / subdir / str(fila_id), ignore_errors=True)


def texto_adjunto_pdf(ruta: str, max_pags: int = 6, max_chars: int = 6000) -> str:
    """Texto de la ficha técnica (PDF digital). Un PDF escaneado —solo
    imagen, sin capa de texto— devuelve ''. Import perezoso: pdfplumber
    tarda en cargar y solo hace falta aquí y en el importador de PDF."""
    try:
        import pdfplumber
        partes = []
        with pdfplumber.open(ruta) as pdf:
            for pagina in pdf.pages[:max_pags]:
                partes.append(pagina.extract_text() or '')
        texto = '\n'.join(partes).strip()
        return texto[:max_chars]
    except Exception:
        return ''


def bloque_prompt_fichas(fichas: list[dict], proposito: str) -> str:
    """Bloque «FICHAS TÉCNICAS ADJUNTAS» listo para pegar al prompt de la IA.
    `proposito` dice a qué texto aplicarlas (p.ej. «las especificaciones del
    insumo correspondiente»)."""
    if not fichas:
        return ''
    partes = []
    for f in fichas:
        t = texto_adjunto_pdf(f.get('ruta') or '')
        if t:
            partes.append(f"--- FICHA TÉCNICA: {f.get('nombre')} ---\n{t}")
        else:
            partes.append(f"--- FICHA TÉCNICA: {f.get('nombre')} "
                          f"(sin texto legible; solo anexo) ---")
    return (f"\n\nFICHAS TÉCNICAS ADJUNTAS (al redactar {proposito}, usa ESTOS "
            "datos reales — norma, tipo, resistencia, presentación — por "
            "encima de lo genérico):\n" + '\n\n'.join(partes))


# ── Atajos por dominio ───────────────────────────────────────────────────────

def spec_adjuntos(partida_id: int) -> list[dict]:
    return get_adjuntos('partidas', 'spec_adjuntos', partida_id)


def spec_agregar(partida_id: int, ruta: str) -> dict:
    return agregar_adjunto('partidas', 'spec_adjuntos', partida_id,
                           'especificaciones', ruta)


def spec_quitar(partida_id: int, nombre: str):
    quitar_adjunto('partidas', 'spec_adjuntos', partida_id, nombre)
