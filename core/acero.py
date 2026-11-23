# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Diámetros y pesos de la planilla de acero."""

# Diámetros comerciales de acero corrugado en Perú (SIDERPERU / ACEROS AREQUIPA)
# Ordenados de menor a mayor; mezcla mm y pulgadas comerciales
ACERO_KG_ML = {
    # ── métricos ─────────────────────────────────────────────
    '6':      0.222,   # Ø6 mm
    '8':      0.395,   # Ø8 mm
    '10':     0.617,   # Ø10 mm
    '12':     0.888,   # Ø12 mm
    '16':     1.578,   # Ø16 mm
    '19':     2.226,   # Ø19 mm
    '22':     2.984,   # Ø22 mm
    '25':     3.853,   # Ø25 mm
    '32':     6.313,   # Ø32 mm
    # ── pulgadas comerciales (ASTM A615 / NTP 341.031) ───────
    '1/4"':   0.249,   # 6.35 mm
    '3/8"':   0.560,   # 9.53 mm
    '1/2"':   0.994,   # 12.70 mm
    '5/8"':   1.552,   # 15.88 mm
    '3/4"':   2.235,   # 19.05 mm
    '1"':     3.973,   # 25.40 mm
    '1-1/4"': 6.204,   # 31.75 mm
    '1-3/8"': 7.507,   # 34.93 mm
    '1-1/2"': 8.938,   # 38.10 mm
}


def normalizar_diametro(txt: str) -> str:
    """Normaliza la entrada de diámetro a una clave de `ACERO_KG_ML`.

    Asume pulgadas cuando el usuario omite la comilla: '1/2' → '1/2\"',
    '1' → '1\"', '1-1/4' → '1-1/4\"'. Los métricos ('6', '12', …) quedan
    igual. Devuelve el texto tal cual si no logra normalizar.
    """
    t = (txt or '').strip().lstrip('ø').strip()
    if not t:
        return ''
    if t in ACERO_KG_ML:
        return t
    cand = t.rstrip('"').strip() + '"'
    if cand in ACERO_KG_ML:
        return cand
    return t
