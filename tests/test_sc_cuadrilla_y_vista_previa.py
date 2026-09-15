# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Bugs del `VISTA.docx` de David Ramos (15 sep 2026), sin GUI o con widgets
sueltos en `offscreen`.

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_sc_cuadrilla_y_vista_previa.py

1. Un subcontrato (SC) tiene su propio subtotal en el ACU: hasta la 3.0.10
   se sumaba como material (chip «SC: 0.00», y «Materiales» en el PDF).
   EQ y SC ya no se intercalan.
2. La celda Cuadrilla del ACU en pantalla va vacía cuando no se edita
   (MAT, SC, %MO, partida global); antes pintaba «0.000».
3. Los iconos de radio y casilla de los QSS se resuelven con ruta absoluta:
   en el instalador de Windows el `url(resources/icons/…)` relativo no
   cargaba y el diálogo «Exportar Gantt» salía sin indicadores.
4. La tabla de la Curva S ensancha las columnas de montos al contenido.
5. La vista previa de impresión es la propia (con «Guardar PDF…»); el
   `QPrintPreviewDialog` de Qt ya no se usa en ninguna vista.
6. El «Resumen de costos» centra nombre y monto en la misma línea.
"""
import glob
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt                                  # noqa: E402
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem  # noqa: E402

import core.database as d                                      # noqa: E402

_app = QApplication.instance() or QApplication([])

APP = os.path.join(os.path.dirname(__file__), '..')
SEED = os.path.join(APP, 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_sc_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)

PID = 186   # RESERVORIOS DE 600 M3


def _usar_bd_temporal():
    if d.DB_PATH != _tmpdb:
        d.DB_PATH = _tmpdb
        d.init_db()


def _recurso(conn, tipo, extra=""):
    row = conn.execute(
        f"SELECT id, precio FROM recursos WHERE tipo=? {extra} "
        "AND precio > 0 ORDER BY id LIMIT 1", (tipo,)).fetchone()
    assert row is not None, f"el seed no tiene un recurso {tipo} {extra}"
    return row['id'], float(row['precio'])


def _partida_con_sc():
    """Partida temporal con MO + MAT + herramientas %MO + un subcontrato."""
    _usar_bd_temporal()
    conn = d.get_db()
    cur = conn.execute(
        "INSERT INTO partidas (proyecto_id,item,descripcion,unidad,metrado,"
        "precio_unitario,nivel,es_titulo,rendimiento) VALUES (?,?,?,?,?,?,?,?,?)",
        (PID, '01.98', 'PARTIDA CON SUBCONTRATO', 'm3', 1, 0, 2, 0, 10))
    part_id = cur.lastrowid
    mo, p_mo = _recurso(conn, 'MO', "AND lower(unidad)='hh'")
    mat, p_mat = _recurso(conn, 'MAT', "AND SUBSTR(unidad,1,1) != '%'")
    eq_pct, _ = _recurso(conn, 'EQ', "AND lower(unidad)='%mo'")
    sc, p_sc = _recurso(conn, 'SC', "AND SUBSTR(unidad,1,1) != '%'")
    filas = [(mo, 1.0, 0.8), (mat, 0, 2.0), (eq_pct, 0, 3.0), (sc, 0, 1.0)]
    for rid, cuad, cant in filas:
        conn.execute(
            "INSERT INTO acu_items (partida_id, recurso_id, cuadrilla, cantidad)"
            " VALUES (?,?,?,?)", (part_id, rid, cuad, cant))
    conn.commit()
    esperado = {'MO': d._r2(0.8 * p_mo), 'MAT': d._r2(2.0 * p_mat),
                'SC': d._r2(1.0 * p_sc)}
    esperado['EQ'] = d._r2(3.0 / 100 * esperado['MO'])
    return conn, part_id, esperado


# ── 1. SC con su propio subtotal ─────────────────────────────────────────────

def test_el_subcontrato_suma_en_sc_y_no_en_materiales():
    conn, part_id, esperado = _partida_con_sc()
    items, totales = d.get_acu_items(conn, part_id)
    assert set(totales) == {'MO', 'MAT', 'EQ', 'SC'}
    for k, v in esperado.items():
        assert abs(totales[k] - v) < 0.005, (k, totales[k], v)
    # El PU recalculado sigue siendo la suma de los cuatro (mismo dueño).
    pu = d._recalcular_pu(conn, part_id)
    assert abs(pu - sum(esperado.values())) < 0.011, (pu, esperado)
    # Orden: MO, MAT, EQ y SC al final, sin intercalar EQ con SC.
    tipos = [it['tipo'] for it in items]
    assert tipos == sorted(tipos, key={'MO': 1, 'MAT': 2, 'EQ': 3, 'SC': 4}.get), tipos
    conn.close()


def test_el_pdf_del_acu_imprime_el_subtotal_de_subcontratos():
    from core.pdf_reports import _html_acus
    conn, part_id, esperado = _partida_con_sc()
    proy = dict(conn.execute("SELECT * FROM proyectos WHERE id=?", (PID,)).fetchone())
    p = dict(conn.execute("SELECT * FROM partidas WHERE id=?", (part_id,)).fetchone())
    conn.close()
    html = _html_acus(PID, proy, [{'partida': p}])
    assert 'Sub-contratos' in html
    # «Materiales» lleva solo los materiales, no el subcontrato.
    m = re.search(r'Materiales</td>\s*<td[^>]*>([\d.,]+)</td>', html)
    assert m, html[-1500:]
    assert abs(float(m.group(1).replace(',', '')) - esperado['MAT']) < 0.005, m.group(1)


def test_los_tres_duenos_del_subtotal_conocen_sc():
    """`get_acu_items`, `_pu_desde_items` y la vista previa del diálogo de
    agregar partida reparten por tipo con el MISMO diccionario: si uno
    ignora SC, el %mt (base = materiales) daría un PU distinto en cada uno."""
    import inspect
    import views.agregar_partida_dialog as apd
    for src in (inspect.getsource(d._pu_desde_items),
                inspect.getsource(d.get_acu_items)):
        assert "'SC': 0.0" in src
    assert "tot = {'MO': 0.0, 'MAT': 0.0, 'EQ': 0.0, 'SC': 0.0}" in inspect.getsource(apd)


# ── 2. Cuadrilla vacía en pantalla cuando no se edita ────────────────────────

def test_la_cuadrilla_en_pantalla_va_vacia_donde_no_se_edita():
    from views.proyecto_view import ProyectoView

    class _Vista:
        _acu_partida_global = False
    v = _Vista()
    f = ProyectoView._texto_cuadrilla
    assert f(v, 'MO', 'hh', 1) == '1.000'
    assert f(v, 'MO', 'hh', 0) == '0.000'        # editable: el 0 se ve
    assert f(v, 'EQ', 'hm', 0.5) == '0.500'
    assert f(v, 'EQ', 'día', 2) == '2.000'
    assert f(v, 'MAT', 'kg', 0) == ''
    assert f(v, 'MAT', 'kg', 3) == ''            # aunque traiga un valor viejo
    assert f(v, 'SC', 'mes', 0) == ''
    assert f(v, 'EQ', '%mo', 0) == ''
    v._acu_partida_global = True
    assert f(v, 'MO', 'hh', 1) == ''             # partida global: sin cuadrilla


# ── 3. Iconos de QSS con ruta absoluta ───────────────────────────────────────

def test_ningun_qss_usa_una_ruta_relativa_de_iconos():
    from utils.icons import qss_icon_url
    ruta = qss_icon_url('radio_orange_on.svg')
    assert os.path.isabs(ruta) and os.path.exists(ruta), ruta
    assert '\\' not in ruta
    culpables = []
    for f in glob.glob(os.path.join(APP, '*', '*.py')) + glob.glob(os.path.join(APP, '*.py')):
        if '/venv/' in f or '/tests/' in f:
            continue
        with open(f, encoding='utf-8') as fh:
            if re.search(r'url\(\s*resources/', fh.read()):
                culpables.append(os.path.relpath(f, APP))
    assert not culpables, culpables


def test_los_dialogos_de_exportar_se_abren_con_sus_iconos():
    """El import de `qss_icon_url` va a nivel de módulo: los dos diálogos
    lo usan en su QSS y con un import local en GanttWidget se caían con
    NameError al abrirlos (quedó así tras cortarse la sesión del 15 sep)."""
    import views.cronograma_view as cv
    for cls in (cv._DialogExportarGanttPdf, cv._DialogExportarReportePdf):
        d = cls()
        assert 'url(/' in d.styleSheet() or 'url(' in d.styleSheet(), cls.__name__
        assert 'resources/icons/' in d.styleSheet(), cls.__name__
        d.deleteLater()


# ── 4. Curva S: los montos no se truncan ────────────────────────────────────

def test_la_curva_s_ensancha_las_columnas_de_montos_al_contenido():
    from views.cronograma_view import CurvaSWidget

    class _Stub:
        _ANCHOS_BASE = CurvaSWidget._ANCHOS_BASE
        _COLS_ELASTICAS = CurvaSWidget._COLS_ELASTICAS
    s = _Stub()
    s.tbl = QTableWidget(2, 6)
    s.tbl_ftr = QTableWidget(1, 6)
    for c, w in enumerate(s._ANCHOS_BASE):
        s.tbl.setColumnWidth(c, w)
        s.tbl_ftr.setColumnWidth(c, w)
    largo = "S/ 12,758,000.0000"
    s.tbl.setItem(0, 2, QTableWidgetItem(largo))
    s.tbl.setItem(0, 4, QTableWidgetItem("S/ 1.00"))
    s.tbl_ftr.setItem(0, 4, QTableWidgetItem(largo))     # el TOTAL también cuenta
    s.tbl.setItem(0, 3, QTableWidgetItem("0.29%"))
    CurvaSWidget._ajustar_anchos_montos(s)
    from PySide6.QtGui import QFontMetrics
    ancho_texto = QFontMetrics(s.tbl.font()).horizontalAdvance(largo)
    for c in (2, 4):
        assert s.tbl.columnWidth(c) >= ancho_texto + 8, (c, s.tbl.columnWidth(c), ancho_texto)
        assert s.tbl.columnWidth(c) == s.tbl_ftr.columnWidth(c)
    assert s.tbl.columnWidth(3) == s._ANCHOS_BASE[3]     # el % no cambia
    assert s.tbl.columnWidth(1) == s._ANCHOS_BASE[1]     # vacía: se queda en su base


# ── 5. Vista previa propia en toda la app ────────────────────────────────────

def test_la_vista_previa_de_qt_ya_no_se_usa():
    culpables = []
    for f in glob.glob(os.path.join(APP, 'views', '*.py')):
        with open(f, encoding='utf-8') as fh:
            if re.search(r'QPrintPreviewDialog\(', fh.read()):
                culpables.append(os.path.basename(f))
    assert not culpables, culpables


def test_el_nombre_del_pdf_sale_del_titulo():
    from views.imprimir_seleccion_dialog import nombre_archivo_pdf, VistaPreviaDialog
    assert nombre_archivo_pdf('Análisis de Costos') == 'analisis-de-costos.pdf'
    assert nombre_archivo_pdf('Cronograma — Gantt') == 'cronograma-gantt.pdf'
    assert nombre_archivo_pdf('') == 'reporte.pdf'
    import inspect
    assert 'nombre_archivo' in inspect.signature(VistaPreviaDialog.__init__).parameters
    # Al imprimir toma papel y orientación del PDF, como hacía Ctrl+P.
    assert 'ajustar_printer_al_pdf' in inspect.getsource(VistaPreviaDialog._imprimir)


# ── 6. Resumen de costos alineado ────────────────────────────────────────────

def test_el_resumen_de_costos_centra_nombre_y_monto():
    import inspect
    from views.proyecto_view import ProyectoView
    src = inspect.getsource(ProyectoView._build_resumen_card)
    assert 'Qt.AlignRight | Qt.AlignVCenter' in src
    assert 'Qt.AlignLeft | Qt.AlignVCenter' in src
    src2 = inspect.getsource(ProyectoView.cargar_resumen)
    assert 'alignment=Qt.AlignTop' in src2      # la card no se estira al alto del donut


if __name__ == "__main__":
    fallos = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  OK  {name}")
            except AssertionError as e:
                fallos += 1
                print(f"  FAIL {name}: {e}")
    if os.path.exists(_tmpdb):
        os.unlink(_tmpdb)
    sys.exit(1 if fallos else 0)
