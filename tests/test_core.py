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

def test_num_importado_respeta_el_default():
    """El default NO es decorativo: varios campos lo usan como valor de negocio.

    `jornada = _num(..., 8.0)`, `rendimiento = _num(..., 1.0)`,
    `participacion = _num(..., 1.0)`. Devolver 0 ahí anularía el ACU entero,
    porque `cantidad = (cuadrilla / rendimiento) * jornada`. Por eso no se
    puede usar `parse_num` a secas, que siempre cae a 0.0.
    """
    from utils.formatting import num_importado
    assert num_importado(None, 8.0) == 8.0
    assert num_importado('', 1.0) == 1.0
    assert num_importado('abc', 8.0) == 8.0, "un texto sin número cae al default"
    assert num_importado(None) == 0.0        # sin default explícito


def test_num_importado_lee_las_tres_formas_que_llegan():
    """Nativo (SQLite / celda numérica), texto (mdb-export / celda de texto)
    y ausente. Las tres tienen que dar lo mismo que daba antes."""
    from utils.formatting import num_importado
    # nativos — como llegan de Delphin
    assert num_importado(1) == 1.0
    assert num_importado(23.73) == 23.73
    # texto canónico — como llega de mdb-export (PowerCost)
    assert num_importado('194.4') == 194.4
    assert num_importado('80') == 80.0
    # texto con formato — lo que antes se perdía en 0.0 silencioso
    assert num_importado('1,234.56') == 1234.56
    assert num_importado('12,500') == 12500.0
    assert num_importado('S/ 8,900.50') == 8900.5
    # un booleano no es un número de archivo
    assert num_importado(True, 5.0) == 5.0 or num_importado(True, 5.0) == 1.0


def test_los_importadores_comparten_un_solo_parser():
    """`safe_float` (Excel) y los dos `_num` (Delphin, PowerCost) delegan.

    Eran tres implementaciones: la de Excel ya usaba parse_num y las dos de
    los importadores binarios hacían `float(v)` pelado. La versión ingenua
    convivía con la buena.
    """
    import inspect
    from core import delphin_sqlite_importer as DL
    from core import importer as IMP
    from core import powercost_prs_importer as PC
    for fn in (IMP.safe_float, DL._num, PC._num):
        # el cuerpo, sin la línea del `def` (que contiene «float(val)» en el
        # propio nombre de la función y daba un falso positivo)
        cuerpo = "\n".join(l for l in inspect.getsource(fn).splitlines()
                           if not l.lstrip().startswith('def '))
        assert 'num_importado' in cuerpo, f"{fn.__module__}.{fn.__name__} dejó de delegar"
        assert 'except' not in cuerpo, \
            f"{fn.__module__}.{fn.__name__} volvió a parsear a mano"
    # el de IFC NO delega: '$' y '*' son marcadores nulos propios del formato
    from core import ifc_importer as IFC
    assert IFC._float_val('$') == 0.0 and IFC._float_val('*') == 0.0


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
