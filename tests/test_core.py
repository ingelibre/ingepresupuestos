# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Tests básicos de la capa core (sin GUI)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.formatting import fmt, fmt_num, parse_num, parse_num_opt, pad_codigo


def test_fmt_soles():
    assert fmt(1234.5, 'Soles') == "S/ 1,234.50"

def test_fmt_euros():
    assert fmt(1234.5, 'Euros') == "€ 1.234,50"

def test_parse_num_punto():
    assert parse_num("21.36") == 21.36

def test_parse_num_coma():
    assert parse_num("21,36") == 21.36

def test_parse_num_separador_de_miles():
    """4 cifras o más: la coma es separador de miles, no decimal.

    Las tablas pintan f"{v:,.2f}" y ese mismo texto se vuelve a leer del
    widget; leerlo mal descartaba la cantidad y el cálculo se detenía.
    """
    assert parse_num("1,000.00")    == 1000.0
    assert parse_num("1,000")       == 1000.0
    assert parse_num("12,500")      == 12500.0
    assert parse_num("1,234,567.89") == 1234567.89
    assert parse_num("1.234.567")   == 1234567.0
    # coma decimal: intacta
    assert parse_num("21,36") == 21.36
    assert parse_num("1,5")   == 1.5

def test_parse_num_ida_y_vuelta():
    for v in (999.99, 1000.0, 25000.5, 1234567.89):
        assert parse_num(f"{v:,.2f}") == v
        assert parse_num(fmt(v, 'Soles')) == v
        assert parse_num(fmt(v, 'Euros')) == v
        assert parse_num(fmt_num(v, 'Soles')) == v

def test_parse_num_simbolos():
    assert parse_num("S/ 1,234.56") == 1234.56
    assert parse_num("€ 1.500,75")  == 1500.75
    assert parse_num("85%")         == 85.0
    assert parse_num("-1,500.25")   == -1500.25
    assert parse_num("abc")         == 0.0

def test_parse_num_opt_distingue_vacio_de_cero():
    assert parse_num_opt("")     is None
    assert parse_num_opt("   ")  is None
    assert parse_num_opt("abc")  is None
    assert parse_num_opt("0.00") == 0.0
    assert parse_num_opt("1,000.00") == 1000.0

def test_safe_float_importador_separador_de_miles():
    """Celdas de TEXTO en Excel importados: «1,234.56» debe ser 1234.56,
    no 0.0 (el viejo replace(',', '.') la partía en dos puntos)."""
    from core.importer import safe_float
    assert safe_float("1,234.56") == 1234.56
    assert safe_float("21,36")    == 21.36     # coma decimal, se conserva
    assert safe_float("1,000")    == 1000.0
    assert safe_float(1234)       == 1234.0    # celda numérica, intacta
    assert safe_float(12.5)       == 12.5
    assert safe_float(None)       == 0.0
    assert safe_float("abc")      == 0.0

def test_pad_codigo():
    assert pad_codigo("47") == "4700000"
    assert pad_codigo("4700023") == "4700023"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  OK  {name}")
            except AssertionError as e:
                print(f"  FAIL {name}: {e}")
