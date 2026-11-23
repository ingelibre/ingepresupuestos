# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Lector STEP (ISO 10303-21) propio para IFC2x3, IFC4 e IFC4x3, sin
dependencias. Aquí solo está la sintaxis y las unidades; qué significa cada
elemento para un presupuesto vive en `core/bim_modelo.py`."""
from __future__ import annotations

import math
import re

# Una sentencia: «#12 = IFCWALL(…);». Respeta «;», «#» y «''» dentro de las
# cadenas, varias sentencias por línea y sentencias de varias líneas. Los
# cuantificadores posesivos evitan el retroceso en archivos mal cerrados.
_RE_ENT = re.compile(rb"#(\d+)\s*=\s*([A-Za-z0-9_]*)\s*((?:[^';]++|'[^']*+')*+);")
_RE_COMENT = re.compile(rb"'[^']*+'|/\*.*?\*/", re.S)
_RE_TOK = re.compile(rb"'(?:[^']|'')*'|[(),]|[^'(),\s][^'(),]*")
_RE_REF = re.compile(rb"#(\d+)")
_RE_CADENA = re.compile(rb"'[^']*+'")


def sentencias(datos: bytes):
    """``(id, TIPO, args)`` de la sección DATA, con `args` aún en bytes y sin
    los paréntesis exteriores."""
    m = re.search(rb"\bDATA\s*(?:\([^;]*\))?\s*;", datos)
    if m:
        datos = datos[m.end():]
    if b'/*' in datos:
        datos = _RE_COMENT.sub(lambda x: x.group() if x.group()[:1] == b"'" else b' ', datos)
    for m in _RE_ENT.finditer(datos):
        a = m.group(3).strip()
        if a[:1] == b'(' and a[-1:] == b')' and m.group(2):
            yield int(m.group(1)), m.group(2).upper().decode('ascii'), a[1:-1]


def argumentos(raw: bytes) -> list:
    """Argumentos de una sentencia: bytes sueltos, listas anidadas. Un valor
    con tipo («IFCLABEL('x')») queda como ``[b'IFCLABEL', [b"'x'"]]``."""
    if b'(' not in raw and b"'" not in raw:
        return [p.strip() for p in raw.split(b',')]
    pila: list = [[]]
    for t in _RE_TOK.findall(raw):
        if t == b',':
            continue
        if t == b'(':
            pila.append([])
        elif t == b')':
            if len(pila) > 1:
                l = pila.pop()
                arriba = pila[-1]
                if arriba and isinstance(arriba[-1], bytes) and arriba[-1][:1].isalpha():
                    arriba[-1] = [arriba[-1], l]
                else:
                    arriba.append(l)
        else:
            pila[-1].append(t if t[:1] == b"'" else t.strip())
    return pila[0]


def refs(x) -> list[int]:
    """Todos los #id de un argumento (suelto, lista o lista con tipo)."""
    if isinstance(x, list):
        return [r for y in x for r in refs(y)]
    return [int(x[1:])] if x[:1] == b'#' and x[1:].isdigit() else []


def ref(x) -> int | None:
    r = refs(x)
    return r[0] if r else None


def refs_crudas(raw: bytes) -> list[int]:
    """Los #id de una sentencia entera, sin analizarla."""
    if b"'" in raw:
        raw = _RE_CADENA.sub(b'', raw)
    return [int(x) for x in _RE_REF.findall(raw)]


def numero(x) -> float | None:
    if isinstance(x, list):              # IFCLENGTHMEASURE(0.3048)
        x = x[1][0] if len(x) == 2 and isinstance(x[1], list) and x[1] else b''
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


_RE_ESC = re.compile(r"\\X2\\((?:[0-9A-Fa-f]{4})*)\\X0\\|\\X4\\((?:[0-9A-Fa-f]{8})*)\\X0\\"
                     r"|\\X\\([0-9A-Fa-f]{2})|\\S\\(.)|\\P([A-I])\\|(\\\\)", re.S)


def texto(x) -> str:
    """Cadena STEP → texto: '' → ', \\\\ → \\, \\S\\, \\X\\, \\X2\\, \\X4\\, \\P?\\.
    Los archivos que traen UTF-8 o Latin-1 crudo (fuera de norma, frecuentes)
    también se leen."""
    if isinstance(x, list):
        x = x[1][0] if len(x) == 2 and isinstance(x[1], list) and x[1] else b''
    if x[:1] != b"'":
        return ''
    b = x[1:-1]
    try:
        s = b.decode('utf-8')
    except UnicodeDecodeError:
        s = b.decode('latin-1')
    s = s.replace("''", "'")
    if '\\' not in s:
        return s.strip()
    pagina = ['A']

    def _sub(m):
        x2, x4, x1, s1, p, barra = m.groups()
        try:
            if x2 is not None:
                return bytes.fromhex(x2).decode('utf-16-be')
            if x4 is not None:
                return bytes.fromhex(x4).decode('utf-32-be')
            if x1 is not None:
                return bytes.fromhex(x1).decode('latin-1')
            if s1 is not None:
                return bytes([(ord(s1) + 128) & 255]).decode(
                    f"iso8859-{ord(pagina[0]) - 64}")
        except (ValueError, UnicodeError):
            return ''
        if p is not None:
            pagina[0] = p
            return ''
        return '\\'
    return _RE_ESC.sub(_sub, s).strip()


# ── Unidades ─────────────────────────────────────────────────────────────────

_PREFIJOS = {b'.EXA.': 1e18, b'.PETA.': 1e15, b'.TERA.': 1e12, b'.GIGA.': 1e9,
             b'.MEGA.': 1e6, b'.KILO.': 1e3, b'.HECTO.': 1e2, b'.DECA.': 10.0,
             b'.DECI.': 0.1, b'.CENTI.': 1e-2, b'.MILLI.': 1e-3, b'.MICRO.': 1e-6,
             b'.NANO.': 1e-9, b'.PICO.': 1e-12}


def factor_unidad(eid, ents, _prof=0) -> float | None:
    """Factor de la unidad #eid a SI (m, m2, m3, kg); None si no se sabe."""
    if eid not in ents or _prof > 6:
        return None
    tipo, raw = ents[eid]
    a = argumentos(raw)
    if tipo == 'IFCSIUNIT' and len(a) >= 4:
        f = _PREFIJOS.get(a[2].upper(), 1.0) if a[2] not in (b'$', b'*') else 1.0
        nombre = a[3].upper()
        if nombre == b'.SQUARE_METRE.':
            return f ** 2
        if nombre == b'.CUBIC_METRE.':
            return f ** 3
        if nombre == b'.GRAM.':
            return f * 1e-3
        return f
    if tipo == 'IFCCONVERSIONBASEDUNIT' and len(a) >= 4:
        mu = ents.get(ref(a[3]))
        if not mu:
            return None
        m = argumentos(mu[1])
        v = numero(m[0]) if m else None
        base = factor_unidad(ref(m[1]), ents, _prof + 1) if len(m) > 1 else None
        return v * base if v and base else None
    return None


def factores_proyecto(ents, asignacion: int | None) -> dict[str, float]:
    """{'LENGTHUNIT': f, 'AREAUNIT': f, 'VOLUMEUNIT': f, 'MASSUNIT': f} con lo
    que el archivo declara; lo que no declara no aparece."""
    out = {}
    if asignacion not in ents:
        return out
    for u in refs_crudas(ents[asignacion][1]):
        if u not in ents:
            continue
        tipo, raw = ents[u]
        if tipo not in ('IFCSIUNIT', 'IFCCONVERSIONBASEDUNIT'):
            continue
        clase = argumentos(raw)[1].strip(b'.').decode('ascii', 'replace').upper()
        f = factor_unidad(u, ents)
        if f:
            out[clase] = f
    return out
