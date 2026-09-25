# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #1 — la moneda no llegaba a todas partes (dos usuarios de Colombia,
21 y 22 sep 2026: «al crear un elemento me sale en soles»).

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_moneda_en_todas_partes.py

- Catálogo de Insumos y Biblioteca de ACU: usan `moneda_defecto`.
- Excel de ACU: `exporter` importaba `_moneda_simbolo` de un módulo donde no
  existe y el `except` dejaba `S/` siempre.
- «Son: … SOLES» en Excel y PDF ignoraba la moneda del proyecto.
Usa una COPIA temporal del seed.
"""
import os
import re
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
_fd, _tmpdb = tempfile.mkstemp(suffix='_moneda_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

import openpyxl                                                     # noqa: E402
import core.exporter as ex                                          # noqa: E402

PID = 186
COP = 'Pesos Colombianos'
_VIVAS = []


def _poner_moneda_al_proyecto(moneda):
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET moneda=? WHERE id=?", (moneda, PID))
    conn.commit()
    conn.close()


def _textos_xlsx(buf) -> list[str]:
    wb = openpyxl.load_workbook(buf)
    out = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            out += [str(c) for c in row if isinstance(c, str)]
    return out


def test_el_excel_de_acus_usa_el_simbolo_del_proyecto():
    _poner_moneda_al_proyecto(COP)
    textos = _textos_xlsx(ex.exportar_acus(PID))
    assert any('COP$' in t for t in textos), 'el Excel de ACU no muestra COP$'
    assert not any(re.search(r'S/\.?\s*\d', t) for t in textos), \
        [t for t in textos if 'S/' in t][:3]


def test_son_en_letras_lleva_la_moneda_del_proyecto():
    _poner_moneda_al_proyecto(COP)
    textos = _textos_xlsx(ex.exportar_presupuesto(PID))
    son = [t for t in textos if t.startswith('Son')]
    assert son and 'PESOS COLOMBIANOS' in son[0], son
    assert 'SOLES' not in son[0]


def test_monto_letras_sin_moneda_sigue_en_soles():
    assert ex._monto_letras(10.5).endswith('CON 50/100 SOLES')
    assert ex._monto_letras(10.5, 'Dólares').endswith('DÓLARES AMERICANOS')


def test_ningun_modulo_importa_moneda_simbolo_de_formatting():
    raiz = os.path.join(os.path.dirname(__file__), '..')
    malos = []
    for carpeta in ('core', 'views', 'widgets', 'utils'):
        for f in os.listdir(os.path.join(raiz, carpeta)):
            if f.endswith('.py'):
                src = open(os.path.join(raiz, carpeta, f), encoding='utf-8').read()
                if 'from utils.formatting import _moneda_simbolo' in src:
                    malos.append(f)
    assert not malos, malos


def test_catalogo_de_insumos_usa_la_moneda_de_configuracion():
    from views.recursos_view import RecursosView
    d.set_config('moneda_defecto', COP)
    try:
        v = RecursosView()
        _VIVAS.append(v)
        v.cargar()
        assert v.kpi_valor.lbl_valor.text().startswith('COP$'), v.kpi_valor.lbl_valor.text()
        precio = v.tbl.item(0, 4).text()
        assert precio.startswith('COP$'), precio
    finally:
        d.set_config('moneda_defecto', 'Soles')


def test_biblioteca_usa_la_moneda_de_configuracion():
    from views.biblioteca_view import BibliotecaView
    d.set_config('moneda_defecto', COP)
    try:
        v = BibliotecaView()
        _VIVAS.append(v)
        v.cargar()
        col_cu = [c for c in range(v.tbl.columnCount())
                  if v.tbl.item(0, c) and v.tbl.item(0, c).text().startswith('COP$')]
        assert col_cu, [v.tbl.item(0, c).text() for c in range(v.tbl.columnCount())
                        if v.tbl.item(0, c)]
    finally:
        d.set_config('moneda_defecto', 'Soles')


if __name__ == "__main__":
    fallos = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  OK  {name}")
            except Exception as e:                       # noqa: BLE001
                fallos += 1
                import traceback
                print(f"  FAIL {name}: {e}")
                traceback.print_exc()
    print("\nTODO OK" if not fallos else f"\n{fallos} FALLOS")
    for w in _VIVAS:
        w.close()
        w.deleteLater()
    _app.processEvents()
    try:
        os.remove(_tmpdb)
    except OSError:
        pass
    sys.exit(1 if fallos else 0)
