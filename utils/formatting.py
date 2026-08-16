# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Formateo de números y monedas (equivale a fmt()/parseFmt() del JS + _parse_num() de Flask)."""
import re as _re
import unicodedata as _ud
from core.config import moneda_cfg


def norm_busqueda(s: str) -> str:
    return ''.join(
        c for c in _ud.normalize('NFKD', s.lower())
        if not _ud.combining(c)
    )


def fmt_num(valor: float, moneda: str = 'Soles', decimales: int = 2) -> str:
    cfg = moneda_cfg(moneda)
    sep_miles = cfg['sep_miles']
    sep_dec   = cfg['sep_dec']
    try:
        entero = int(round(abs(valor) * (10 ** decimales)))
        dec_part = str(entero % (10 ** decimales)).zfill(decimales)
        miles_part = entero // (10 ** decimales)
        miles_str = f"{miles_part:,}".replace(',', sep_miles)
        signo = '-' if valor < 0 else ''
        return f"{signo}{miles_str}{sep_dec}{dec_part}"
    except (TypeError, ValueError):
        return f"0{sep_dec}{'0' * decimales}"


def fmt(valor: float, moneda: str = 'Soles', decimales: int = 2) -> str:
    cfg = moneda_cfg(moneda)
    sep_miles = cfg['sep_miles']
    sep_dec   = cfg['sep_dec']
    simbolo   = cfg['simbolo']

    try:
        entero = int(round(abs(valor) * (10 ** decimales)))
        dec_part = str(entero % (10 ** decimales)).zfill(decimales)
        miles_part = entero // (10 ** decimales)
        miles_str = f"{miles_part:,}".replace(',', sep_miles)
        signo = '-' if valor < 0 else ''
        return f"{signo}{simbolo} {miles_str}{sep_dec}{dec_part}"
    except (TypeError, ValueError):
        return f"{simbolo} 0{sep_dec}{'0' * decimales}"


# Agrupación de miles perfecta con coma: 1,000 · 12,500 · 1,234,567
_RE_MILES_COMA = _re.compile(r'^\d{1,3}(?:,\d{3})+$')


def parse_num(val) -> float:
    """Convierte a float un número escrito por el usuario o formateado por la app.

    Acepta '21.36' y '21,36' como decimales, entiende el separador de miles
    ('1,234.56' y '1.234,56') e ignora símbolos de moneda, %, espacios y
    cualquier otro adorno ('S/ 1,234.56' → 1234.56). Devuelve 0.0 si no hay
    número.

    El separador de miles importa: las tablas de la app formatean con
    f"{v:,.2f}", así que todo valor de 4 cifras o más vuelve del widget con
    coma. Tratar esa coma como decimal partía el número (1,000.00 → error) y
    la cantidad se perdía en el cálculo.
    """
    if val is None or val == '':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    # Descartar todo lo que no sea dígito, separador o signo
    s = _re.sub(r'[^\d,.\-]', '', str(val).strip())
    neg = s.startswith('-')
    s   = s.replace('-', '')
    if not s:
        return 0.0
    if ',' in s and '.' in s:
        # Con ambos separadores, el ÚLTIMO en aparecer es el decimal
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        # Una sola clase de separador: agrupación de miles exacta → miles;
        # cualquier otra cosa ('21,36') → coma decimal
        s = s.replace(',', '') if _RE_MILES_COMA.match(s) else s.replace(',', '.')
    elif s.count('.') > 1:
        s = s.replace('.', '')   # 1.234.567 → miles (un solo punto es decimal)
    try:
        return -float(s) if neg else float(s)
    except ValueError:
        return 0.0


def parse_num_opt(val) -> 'float | None':
    """Como parse_num, pero devuelve None cuando el texto no contiene número.

    Para celdas de planilla donde «vacío» y «cero» significan cosas distintas
    (una dimensión ausente no multiplica; un 0 anularía el parcial)."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or not _re.search(r'\d', s):
        return None
    return parse_num(s)


def pad_codigo(codigo: str) -> str:
    """Normaliza código de recurso a 7 dígitos (right-pad ceros)."""
    return str(codigo).ljust(7, '0')[:7]
