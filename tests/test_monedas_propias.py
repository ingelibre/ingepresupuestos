# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #13: monedas propias (solo formato, sin tipo de cambio).

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_monedas_propias.py

Usa una COPIA temporal del seed.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication                          # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_monedas_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()
cfg.olvidar_monedas_propias()

from utils.formatting import fmt, fmt_num, parse_num                # noqa: E402


def _limpiar():
    cfg.guardar_monedas_propias({})


def test_sin_monedas_propias_todo_es_como_antes():
    _limpiar()
    assert cfg.monedas() == cfg.MONEDAS
    assert fmt(1234.5, 'Soles') == 'S/ 1,234.50'
    assert cfg.moneda_cfg('No existe') == cfg.MONEDAS['Soles']


def test_una_moneda_nueva_formatea_con_sus_separadores():
    _limpiar()
    cfg.guardar_monedas_propias({
        'Francos suizos': {'simbolo': 'CHF', 'sep_miles': "'", 'sep_dec': '.'},
        'Coronas': {'simbolo': 'kr', 'sep_miles': ' ', 'sep_dec': ','},
    })
    assert 'Francos suizos' in cfg.monedas()
    assert fmt(1234567.891, 'Francos suizos') == "CHF 1'234'567.89"
    assert fmt(1234567.891, 'Coronas') == 'kr 1 234 567,89'
    assert fmt_num(-1234.5, 'Coronas') == '-1 234,50'
    # Lo que la app escribe, la app lo vuelve a leer.
    assert parse_num(fmt(1234567.89, 'Francos suizos')) == 1234567.89
    assert parse_num(fmt(1234567.89, 'Coronas')) == 1234567.89


def test_una_propia_con_nombre_de_fabrica_la_reemplaza():
    _limpiar()
    cfg.guardar_monedas_propias({'Dólares': {'simbolo': '$', 'sep_miles': ',', 'sep_dec': '.'}})
    assert fmt(10, 'Dólares') == '$ 10.00'
    _limpiar()
    assert fmt(10, 'Dólares') == 'US$ 10.00'


def test_lo_invalido_se_descarta_y_un_json_roto_no_rompe_nada():
    _limpiar()
    cfg.guardar_monedas_propias({
        'Sin símbolo': {'simbolo': '', 'sep_miles': ',', 'sep_dec': '.'},
        'Separadores iguales': {'simbolo': 'X', 'sep_miles': '.', 'sep_dec': '.'},
        '  ': {'simbolo': 'Y', 'sep_miles': ',', 'sep_dec': '.'},
        'Buena': {'simbolo': 'B', 'sep_miles': ',', 'sep_dec': '.'},
    })
    assert list(cfg.monedas_propias()) == ['Buena']
    d.set_config(cfg.CLAVE_MONEDAS_PROPIAS, '{roto')
    cfg.olvidar_monedas_propias()
    assert cfg.monedas_propias() == {}
    assert fmt(1, 'Soles') == 'S/ 1.00'


def test_los_desplegables_ofrecen_las_propias():
    _limpiar()
    cfg.guardar_monedas_propias({'Lempiras HN': {'simbolo': 'L.', 'sep_miles': ',', 'sep_dec': '.'}})
    from views.pais_dialog import PaisForm
    f = PaisForm()
    textos = [f.cmb_moneda.itemText(i) for i in range(f.cmb_moneda.count())]
    assert 'Lempiras HN' in textos and 'Soles' in textos


def test_no_se_quita_una_moneda_en_uso():
    _limpiar()
    from views.monedas_dialog import moneda_en_uso
    cfg.guardar_monedas_propias({'Pesos de prueba': {'simbolo': 'P$', 'sep_miles': '.', 'sep_dec': ','}})
    assert moneda_en_uso('Pesos de prueba') == 0
    conn = d.get_db()
    conn.execute("INSERT INTO proyectos (nombre, moneda) VALUES ('x', 'Pesos de prueba')")
    conn.commit()
    conn.close()
    assert moneda_en_uso('Pesos de prueba') == 1


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in list(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  OK  {nombre}")
            except Exception as e:
                fallos += 1
                import traceback
                traceback.print_exc()
                print(f"  FAIL {nombre}: {e!r}")
    try:
        os.unlink(_tmpdb)
    except OSError:
        pass
    print("TODO OK" if not fallos else f"FALLOS: {fallos}")
    sys.stdout.flush()
    os._exit(1 if fallos else 0)
