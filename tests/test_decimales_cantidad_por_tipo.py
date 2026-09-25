# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #2 — los decimales de cantidad del ACU no se aplicaban al cálculo.

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_decimales_cantidad_por_tipo.py

Reporte (24 sep 2026), rendimiento 12, jornada 8: con la MO a 2 decimales S10
da 0.67 × 24.96 = 16.72 y el programa seguía multiplicando 0.666667 → 16.64,
aunque se configuraran 2 decimales. Ahora hay un ajuste por tipo
(MO · MAT · EQ · SC) y la cantidad se redondea antes de multiplicar.
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
_fd, _tmpdb = tempfile.mkstemp(suffix='_dec_cant_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

# El ACU del reporte: cuadrilla 1/1/2, rendimiento 12, jornada 8.
ACU_DAVID = [
    {'tipo': 'MO', 'unidad': 'hh', 'cantidad': 1 / 12 * 8, 'precio': 24.96},
    {'tipo': 'MO', 'unidad': 'hh', 'cantidad': 1 / 12 * 8, 'precio': 19.63},
    {'tipo': 'MO', 'unidad': 'hh', 'cantidad': 2 / 12 * 8, 'precio': 17.76},
]


def _con(**por_tipo):
    antes = dict(d._DECIMALES_CANT_ACU)
    for t, n in por_tipo.items():
        d.set_decimales_cant_acu(n, t)
    return antes


def test_con_4_decimales_da_lo_de_siempre():
    antes = _con(MO=4)
    try:
        assert d._pu_desde_items(ACU_DAVID) == 53.41
    finally:
        d._DECIMALES_CANT_ACU.update(antes)


def test_con_2_decimales_en_mo_cuadra_con_s10():
    antes = _con(MO=2)
    try:
        assert d._pu_desde_items(ACU_DAVID) == 53.49   # 16.72 + 13.15 + 23.62
    finally:
        d._DECIMALES_CANT_ACU.update(antes)


def test_cada_tipo_tiene_su_ajuste():
    antes = _con(MO=2, MAT=4)
    try:
        items = ACU_DAVID[:1] + [
            {'tipo': 'MAT', 'unidad': 'kg', 'cantidad': 0.123456, 'precio': 100.0}]
        # MO 0.67 × 24.96 = 16.72 · MAT 0.1235 × 100 = 12.35
        assert d._pu_desde_items(items) == 29.07
        assert d.get_decimales_cant_acu('MO') == 2
        assert d.get_decimales_cant_acu('MAT') == 4
        assert d.get_decimales_cant_acu('XYZ') == 4    # desconocido → MAT
    finally:
        d._DECIMALES_CANT_ACU.update(antes)


def test_get_acu_items_calcula_igual_que_el_pu_guardado():
    """La pantalla y los reportes (get_acu_items) y el PU que se guarda
    (_pu_desde_items) deben dar lo mismo con cualquier ajuste."""
    antes = _con(MO=2, EQ=2)
    try:
        conn = d.get_db()
        pids = [r[0] for r in conn.execute(
            "SELECT DISTINCT partida_id FROM acu_items LIMIT 200").fetchall()]
        for pid in pids:
            items, tot = d.get_acu_items(conn, pid)
            d._recalcular_pu(conn, pid)
            pu = conn.execute("SELECT precio_unitario FROM partidas WHERE id=?",
                              (pid,)).fetchone()[0]
            assert abs(sum(tot.values()) - pu) < 0.011, (pid, sum(tot.values()), pu)
            for it in items:
                if not (it['unidad'] or '').startswith('%'):
                    n = d.get_decimales_cant_acu(it['tipo'])
                    assert it['cantidad'] == d._rn(it['cantidad'], n), it
        conn.rollback()
        conn.close()
    finally:
        d._DECIMALES_CANT_ACU.update(antes)


def test_la_configuracion_se_guarda_por_tipo_y_hereda_el_valor_viejo():
    conn = d.get_db()
    claves = {r[0]: r[1] for r in conn.execute(
        "SELECT clave, valor FROM configuracion WHERE clave LIKE 'decimales_cantidad_%'")}
    conn.close()
    for t in ('mo', 'mat', 'eq', 'sc'):
        assert claves.get(f'decimales_cantidad_{t}') == claves['decimales_cantidad_acu'], claves


def test_configuracion_muestra_cuatro_ajustes():
    from views.configuracion_view import ConfiguracionView
    v = ConfiguracionView()
    card = v._card_decimales()   # las secciones se construyen al abrirlas; sin
    assert card is not None      # referencia, Qt borra la tarjeta y sus spins
    assert set(v.spin_dec_cant) == {'MO', 'MAT', 'EQ', 'SC'}
    antes = dict(d._DECIMALES_CANT_ACU)
    try:
        v.spin_dec_cant['MO'].setValue(2)
        v._guardar_decimales()
        assert d.get_decimales_cant_acu('MO') == 2
        assert d.get_config('decimales_cantidad_mo') == '2'
        assert d.get_decimales_cant_acu('MAT') == antes['MAT']
    finally:
        d._DECIMALES_CANT_ACU.update(antes)
        d.set_config('decimales_cantidad_mo', str(antes['MO']))
        v.close()


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
    try:
        os.remove(_tmpdb)
    except OSError:
        pass
    sys.exit(1 if fallos else 0)
