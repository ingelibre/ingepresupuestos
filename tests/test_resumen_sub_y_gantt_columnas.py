# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Ronda 5 de David Ramos (15 sep 2026), las tres mejoras baratas:

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_resumen_sub_y_gantt_columnas.py

- La leyenda del donut lleva el MONTO además del porcentaje.
- El tab Resumen ofrece «Solo el sub-presupuesto a la vista» cuando el
  proyecto tiene sub-presupuestos, y con la casilla el resumen, el donut y
  el top 5 se limitan al sub abierto.
- El PDF del Gantt omite las columnas ocultas en pantalla (Inicio/Fin…);
  Descripción nunca se oculta y Pred. sigue mandando la casilla del diálogo.
Usa una COPIA temporal del seed.
"""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel      # noqa: E402

import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_fase3_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
d.init_db()

from utils.formatting import fmt                                    # noqa: E402
from views.proyecto_view import ProyectoView, _DonutChart           # noqa: E402
from models.usuario import Usuario                                  # noqa: E402

PID_SUBS = 396      # dos sub-presupuestos: ACTIVIDAD 1 y ACTIVIDAD 2
PID_SIMPLE = 186    # sin sub-presupuestos


_VIVAS = []     # las vistas se conservan: si Python las suelta, sus timers
                # tocan widgets ya destruidos al procesar eventos


def _vista(pid) -> ProyectoView:
    v = ProyectoView(pid, Usuario(id=1, nombre="t", rol="admin"))
    v._completar_panel_tabs()
    v._cargar_datos_inicial()
    _VIVAS.append(v)
    return v


def _en_layout(v) -> list:
    """Widgets que están HOY en el layout del Resumen. `cargar_resumen`
    destruye los anteriores con deleteLater, así que siguen siendo hijos
    hasta que corra el bucle de eventos (y procesarlo aquí dispara la
    construcción diferida de las pestañas, que reemplaza todo)."""
    lay = v._resumen_layout
    return [lay.itemAt(i).widget() for i in range(lay.count())
            if lay.itemAt(i).widget() is not None]


def _labels(v) -> list:
    out = []
    for w in _en_layout(v):
        if isinstance(w, QLabel):
            out.append(w.text())
        out += [l.text() for l in w.findChildren(QLabel)]
    return out


def _checks(v) -> list:
    return [w for w in _en_layout(v)
            if isinstance(w, QCheckBox) and w.objectName() == "chkResumenSoloSub"]


# ── 1. Donut con montos ──────────────────────────────────────────────────────

def test_la_leyenda_del_donut_lleva_monto_y_porcentaje():
    datos = [("Mano de Obra", 250.0, "#F39C12"), ("Materiales", 750.0, "#27AE60")]
    con = _DonutChart(datos, moneda="S/")._leyenda_textos()
    assert con[0] == ("Mano de Obra", fmt(250.0, 'S/'), "25.0%"), con
    assert con[1][2] == "75.0%"
    assert _DonutChart(datos, moneda="S/")._texto_total() == fmt(1000.0, 'S/')
    assert _DonutChart(datos)._texto_total() == ''
    sin = _DonutChart(datos)._leyenda_textos()      # sin moneda: como antes
    assert sin == [("Mano de Obra", "", "25.0%"), ("Materiales", "", "75.0%")], sin
    v = _vista(PID_SIMPLE)
    v.cargar_resumen()
    assert v._donut._moneda == v._moneda
    # Angosto: el monto baja a la segunda línea en vez de elidir la etiqueta.
    from PySide6.QtGui import QFont, QFontMetrics
    f = QFont(); f.setPointSize(8); fm = QFontMetrics(f)
    ch = _DonutChart(datos, moneda="S/")
    assert all(dos for *_r, dos in ch._filas_leyenda(180, fm))
    assert not any(dos for *_r, dos in ch._filas_leyenda(600, fm))
    # La columna de montos es tan ancha como el más largo, incluido el Total.
    w_amt, w_pct = ch._columnas_leyenda(fm)
    assert w_amt >= fm.horizontalAdvance(ch._texto_total()) and w_pct > 0


# ── 2. Resumen: solo este sub-presupuesto ────────────────────────────────────

def test_sin_sub_presupuestos_no_hay_casilla():
    v = _vista(PID_SIMPLE)
    v.cargar_resumen()
    assert not _checks(v)


def test_la_casilla_limita_el_resumen_al_sub_a_la_vista():
    v = _vista(PID_SUBS)
    v.cargar_resumen()
    chks = _checks(v)
    assert len(chks) == 1 and not chks[0].isChecked()
    total_todo = v._total_proyecto(all_subs=True)
    total_sub = v._total_proyecto(all_subs=False)
    assert total_todo > 0 and total_todo != total_sub, (total_todo, total_sub)
    assert fmt(total_todo, v._moneda) in _labels(v)
    assert "RESUMEN DE COSTOS" in _labels(v)
    assert v._donut._texto_total() == fmt(total_todo, v._moneda)   # Total = CD

    chks[0].setChecked(True)                    # → cargar_resumen de nuevo
    assert v._resumen_solo_sub
    labs = _labels(v)
    assert fmt(total_sub, v._moneda) in labs
    assert v._donut._texto_total() == fmt(total_sub, v._moneda)
    assert any(l.startswith("RESUMEN DE COSTOS — ") for l in labs), labs
    assert _checks(v)[0].isChecked()            # la casilla se reconstruye marcada
    assert v._nombre_sub_actual() in _checks(v)[0].text()

    # Al cambiar de sub-presupuesto, el resumen limitado sigue al nuevo sub.
    conn = d.get_db()
    subs = [r[0] for r in conn.execute(
        "SELECT id FROM sub_presupuestos WHERE proyecto_id=? ORDER BY orden, id",
        (PID_SUBS,)).fetchall()]
    conn.close()
    v._sub_ppto_id = subs[0]
    v.cargar_resumen()
    assert fmt(v._total_proyecto(all_subs=False), v._moneda) in _labels(v)
    assert v._nombre_sub_actual() in _checks(v)[0].text()

    _checks(v)[0].setChecked(False)
    assert fmt(total_todo, v._moneda) in _labels(v)


# ── 3. PDF del Gantt y columnas ocultas ─────────────────────────────────────

def _gantt(pid):
    from views.cronograma_view import CronogramaView
    conn = d.get_db()
    proy = dict(conn.execute("SELECT * FROM proyectos WHERE id=?", (pid,)).fetchone())
    conn.close()
    cv = CronogramaView(pid, proy, lambda: None)
    cv.show()
    try:
        cv.cargar()
    except Exception:
        pass
    return cv._gantt_w


def _texto_pdf(g, incluir_pred=True) -> tuple:
    """(texto de todas las hojas, número de hojas)."""
    import pypdf
    fd, path = tempfile.mkstemp(suffix='_gantt_cols.pdf')
    os.close(fd)
    g._render_pdf_completo(path, 'multi', 'landscape', incluir_pred)
    paginas = pypdf.PdfReader(path).pages
    texto = "\n".join(pg.extract_text() for pg in paginas)
    n = len(paginas)
    os.unlink(path)
    return texto, n


def test_el_pdf_del_gantt_omite_las_columnas_ocultas_en_pantalla():
    g = _gantt(PID_SIMPLE)
    for c in range(g.tbl.columnCount()):        # estado limpio, sin tocar QSettings
        g.tbl.setColumnHidden(c, False)
    assert g._pdf_columnas_ocultas() == set()
    con, hojas = _texto_pdf(g)
    # El encabezado de CADA hoja trae dos fechas («Tramo: … – …»): se cuenta
    # cuántas hay, no si hay alguna. Con las columnas, una o dos por fila.
    fechas = re.compile(r'\b\d{2}/\d{2}/\d{4}\b')
    n_con = len(fechas.findall(con))
    assert 'Inicio' in con and 'Fin' in con and n_con > 2 * hojas + 20, (n_con, con[:300])

    g.tbl.setColumnHidden(5, True)      # Inicio
    g.tbl.setColumnHidden(6, True)      # Fin
    g.tbl.setColumnHidden(2, True)      # Descripción: se ignora
    g.tbl.setColumnHidden(7, True)      # Pred.: manda la casilla del diálogo
    assert g._pdf_columnas_ocultas() == {5, 6}
    sin, hojas = _texto_pdf(g)
    n_sin = len(fechas.findall(sin))
    assert n_sin <= 2 * hojas, (n_sin, hojas, sin[:300])   # solo las del encabezado
    assert 'Descripción' in sin and 'Pred.' in sin
    assert len(sin) < len(con)
    for c in range(g.tbl.columnCount()):
        g.tbl.setColumnHidden(c, False)


def test_los_separadores_saltan_las_columnas_de_ancho_cero():
    from views.cronograma_view import GanttWidget
    defs = [('a', 10, 0), ('b', 0, 0), ('c', 10, 0), ('d', 10, 0), ('e', 0, 0)]
    assert GanttWidget._pdf_separadores(defs) == [0, 2]
    assert GanttWidget._pdf_desc_shift(None, {'item': '01'},
                                       [('a', 1, 0), ('b', 0, 0), ('c', 1, 0)], 300) == 0.0


# ── 4. Issue #7: menú de columnas y ruta crítica ─────────────────────────────

def test_las_opciones_deshabilitadas_de_un_menu_se_ven_grises():
    """«Descripción» ya estaba deshabilitada en el menú de columnas, pero el
    QSS global de menús no tenía `:disabled` y se veía como las demás."""
    from utils.tooltip import _MENU_QSS
    bloque = re.search(r'QMenu::item:disabled[^{]*\{([^}]*)\}', _MENU_QSS)
    assert bloque and '#95A3AB' in bloque.group(1)


def test_la_ruta_critica_no_colorea_el_texto_de_las_partidas():
    from PySide6.QtCore import Qt
    from views.cronograma_view import RED_500
    g = _gantt(PID_SIMPLE)
    tareas = g._cv._tasks
    assert tareas, "el Gantt de prueba no tiene tareas"
    for t in tareas.values():         # todas críticas: el peor caso
        t['critical'] = True
    g._llenar_tabla()
    for r in range(g.tbl.rowCount()):
        for c in range(g.tbl.columnCount()):
            it = g.tbl.item(r, c)
            if it is not None and not it.data(Qt.UserRole + 1):
                assert it.foreground().color().name().upper() != RED_500, (r, c)


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
            except Exception as e:                       # noqa: BLE001
                fallos += 1
                import traceback; traceback.print_exc()
                print(f"  FAIL {name}: {type(e).__name__}: {e}")
    if os.path.exists(_tmpdb):
        os.unlink(_tmpdb)
    sys.exit(1 if fallos else 0)
