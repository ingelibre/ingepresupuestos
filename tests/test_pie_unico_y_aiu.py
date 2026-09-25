# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #3 (redondeo del pie) e issue #10 (AIU de Colombia).

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_pie_unico_y_aiu.py

- El pie se calcula en UN sitio (`core.pie.calcular_pie`) y cada línea se
  redondea antes de sumarse: el total es la suma de lo impreso.
- `pct_util`: el IVA colombiano grava solo la utilidad del AIU.
- Un proyecto nuevo en Colombia nace con A · I · U · Sub Total · IVA.
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
_fd, _tmpdb = tempfile.mkstemp(suffix='_pie_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

from core import pie, paises                                        # noqa: E402
import core.pdf_reports as pr                                       # noqa: E402

_VIVAS = []


def _proyecto_con_pie(lineas):
    conn = d.get_db()
    pid = conn.execute(
        "INSERT INTO proyectos (nombre, moneda, igv_pct) VALUES ('pie test','Soles',18)"
    ).lastrowid
    for i, (cod, nom, pct, tipo) in enumerate(lineas):
        conn.execute(
            "INSERT INTO pie_rubros (proyecto_id, codigo, nombre, pct, activo, orden,"
            " tipo, mostrar_pct) VALUES (?,?,?,?,1,?,?,1)", (pid, cod, nom, pct, i, tipo))
    conn.commit()
    return conn, pid


def test_cada_linea_se_redondea_antes_de_sumar():
    conn, pid = _proyecto_con_pie([
        ('GG', 'GG', 10.333, 'pct_cd'), ('UTIL', 'Util', 5.555, 'pct_cd'),
        ('SUB', 'Sub', 0, 'subtotal'), ('IGV', 'IGV', 18, 'pct_sub')])
    lineas, total = pie.calcular_pie(conn, pid, 1234.57)
    conn.close()
    for l in lineas:
        assert l['valor'] == round(l['valor'], 2), l
    impresas = [l['valor'] for l in lineas if l['tipo'] != 'subtotal']
    assert abs(total - round(1234.57 + sum(impresas), 2)) < 1e-9, (total, impresas)
    sub = [l for l in lineas if l['tipo'] == 'subtotal'][0]['valor']
    assert sub == round(1234.57 + lineas[0]['valor'] + lineas[1]['valor'], 2)


def test_aiu_con_iva_solo_sobre_la_utilidad():
    conn, pid = _proyecto_con_pie([
        ('GG', 'Administración', 20, 'pct_cd'), ('IMP', 'Imprevistos', 2, 'pct_cd'),
        ('UTIL', 'Utilidad', 5, 'pct_cd'), ('SUB', 'Sub Total', 0, 'subtotal'),
        ('IGV', 'IVA', 19, 'pct_util')])
    lineas, total = pie.calcular_pie(conn, pid, 1000)
    conn.close()
    valores = {l['codigo']: l['valor'] for l in lineas}
    assert valores == {'GG': 200, 'IMP': 20, 'UTIL': 50, 'SUB': 1270, 'IGV': 9.5}, valores
    assert total == 1279.5


def test_calcular_totales_y_reportes_dan_el_mismo_total():
    conn = d.get_db()
    pids = [r[0] for r in conn.execute("SELECT id FROM proyectos")]
    conn.close()
    for pid in pids:
        _, tot = d.calcular_totales(pid)
        filas = pr._build_pie_rows(pid, tot['cd'])
        conn = d.get_db()
        lineas, total = pie.calcular_pie(conn, pid, tot['cd'])
        conn.close()
        if lineas is None:
            continue                 # sin pie: la fórmula simple, otro camino
        assert abs(filas[-1][1] - tot['total']) < 1e-6, (pid, filas[-1], tot['total'])


def test_el_calculo_del_pie_tiene_un_solo_dueno():
    """Nadie más vuelve a escribir `last_sub * pct / 100`."""
    raiz = os.path.join(os.path.dirname(__file__), '..')
    culpables = []
    for carpeta in ('core', 'views', 'widgets', 'utils'):
        for f in os.listdir(os.path.join(raiz, carpeta)):
            if f.endswith('.py') and f != 'pie.py':
                src = open(os.path.join(raiz, carpeta, f), encoding='utf-8').read()
                if re.search(r'last_sub\s*\*\s*pct', src):
                    culpables.append(f)
    assert not culpables, culpables


def test_impuestos_de_todos_los_paises_se_reconocen():
    for nombre in ('IGV (18%)', 'IVA (19%)', 'ISV (15%)', 'ITBMS (7%)', 'ITBIS (18%)'):
        assert pie.es_impuesto({'codigo': 'X', 'nombre': nombre}), nombre
    assert pie.es_impuesto({'codigo': 'IGV', 'nombre': 'Impuesto'})
    assert not pie.es_impuesto({'codigo': 'GG', 'nombre': 'Gastos generales'})


def test_proyecto_nuevo_en_colombia_nace_con_aiu():
    from views.proyecto_view import ProyectoView
    from models.usuario import Usuario
    paises.aplicar_pais('CO')
    try:
        conn = d.get_db()
        pid = conn.execute(
            "INSERT INTO proyectos (nombre, moneda, igv_pct) VALUES ('aiu','Pesos Colombianos',19)"
        ).lastrowid
        conn.commit()
        proy = conn.execute("SELECT * FROM proyectos WHERE id=?", (pid,)).fetchone()
        conn.close()
        v = ProyectoView.__new__(ProyectoView)       # solo el método de siembra
        v.pid = pid
        ProyectoView._pie_crear_rubros_default(v, proy)
        conn = d.get_db()
        filas = conn.execute("SELECT codigo, tipo, pct FROM pie_rubros WHERE proyecto_id=?"
                             " ORDER BY orden", (pid,)).fetchall()
        conn.close()
        assert [(f['codigo'], f['tipo']) for f in filas] == [
            ('GG', 'pct_cd'), ('IMP', 'pct_cd'), ('UTIL', 'pct_cd'),
            ('SUB', 'subtotal'), ('IGV', 'pct_util')], [tuple(f) for f in filas]
        assert filas[-1]['pct'] == 19
    finally:
        conn = d.get_db()
        conn.execute("DELETE FROM configuracion WHERE clave IN ('pais',"
                     " 'etiqueta_id_tributaria','impuesto_nombre','impuesto_pct')")
        conn.execute("UPDATE configuracion SET valor='Soles' WHERE clave='moneda_defecto'")
        conn.commit()
        conn.close()


def test_presupuesto_para_cliente_deja_el_iva_aparte():
    conn, pid = _proyecto_con_pie([
        ('GG', 'Administración', 20, 'pct_cd'), ('IMP', 'Imprevistos', 2, 'pct_cd'),
        ('UTIL', 'Utilidad', 5, 'pct_cd'), ('SUB', 'Sub Total', 0, 'subtotal'),
        ('IGV', 'IVA (19%) sobre la utilidad', 19, 'pct_util')])
    conn.close()
    factor, filas = pr._todo_costo_factor_pie(pid, 1000)
    assert abs(factor - 1.27) < 1e-9, factor
    assert any('IVA' in f[0] and f[1] == 9.5 for f in filas), filas


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
