# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Ronda 6 de David Ramos (16 sep 2026, `TITULO.docx`).

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_pie_insumos_y_columnas.py

Bugs:
- La ✕ de una línea del pie de presupuesto borraba SIEMPRE la última.
- El Resumen no seguía al sub-presupuesto al cambiar de pestaña.
- El donut se encogía hasta 160 px y «Total» se pisaba con el monto.
- En la pestaña Insumos los subcontratos salían mezclados con materiales.
- «Exportar Gantt» traía Pred. aunque estuviera oculta en pantalla.
Mejoras:
- La línea nueva del pie entra debajo de la seleccionada, con código único.
- Insumos ordena por columna (número, no texto; Tipo por jerarquía).
- La línea sobre el pie del reporte se puede apagar.
- El menú de columnas del Gantt alterna «todas» / «solo id y Descripción».
- Título corto «SUB-PRESUPUESTO n/N» en el Resumen por sub.
Usa una COPIA temporal del seed.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt                                       # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton     # noqa: E402
from PySide6.QtGui import QFont, QFontMetrics                       # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_ronda6_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

import core.pdf_reports as pr                                       # noqa: E402
from utils.formatting import fmt                                    # noqa: E402
from views.proyecto_view import (ProyectoView, _DonutChart, COLS_ACU,   # noqa: E402
                                 _RubDragList)
from models.usuario import Usuario                                  # noqa: E402

PID_SUBS = 396      # dos sub-presupuestos y 21 subcontratos
PID_SIMPLE = 186    # sin sub-presupuestos

_VIVAS = []


def _vista(pid) -> ProyectoView:
    v = ProyectoView(pid, Usuario(id=1, nombre="t", rol="admin"))
    v._completar_panel_tabs()
    v._cargar_datos_inicial()
    _VIVAS.append(v)
    return v


def _labels(v) -> list:
    lay = v._resumen_layout
    out = []
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is None:
            continue
        if isinstance(w, QLabel):
            out.append(w.text())
        out += [l.text() for l in w.findChildren(QLabel)]
    return out


def _card_pie(v):
    """La tarjeta «Plantillas» que está HOY en el layout (cada guardado la
    reconstruye; la vieja sigue siendo hija hasta que corra el bucle de
    eventos, así que no vale `findChildren` sobre el panel)."""
    card = v._pie_left_vl.itemAt(1).widget()
    assert card is not None and card.findChild(_RubDragList) is not None
    return card


def _lista_pie(v) -> _RubDragList:
    return _card_pie(v).findChild(_RubDragList)


def _boton_pie(v, texto) -> QPushButton:
    return [b for b in _card_pie(v).findChildren(QPushButton) if b.text() == texto][0]


def _nombres_pie(v) -> list:
    conn = d.get_db()
    out = [r[0] for r in conn.execute(
        "SELECT nombre FROM pie_rubros WHERE proyecto_id=? ORDER BY orden",
        (v.pid,)).fetchall()]
    conn.close()
    return out


# ── 1. Pie de presupuesto ────────────────────────────────────────────────────

def test_la_x_borra_la_linea_de_su_fila():
    v = _vista(PID_SIMPLE)
    v.cargar_pie()
    antes = _nombres_pie(v)
    assert len(antes) >= 3, antes
    lista = _lista_pie(v)
    fila = lista.itemWidget(lista.item(1))
    x = [b for b in fila.findChildren(QPushButton) if b.text() == "✕"][0]
    x.click()
    despues = _nombres_pie(v)
    assert despues == antes[:1] + antes[2:], (antes, despues)   # se fue la 2ª, no la última


def test_la_linea_nueva_entra_debajo_de_la_seleccion_con_codigo_unico():
    v = _vista(PID_SIMPLE)
    v.cargar_pie()
    antes = _nombres_pie(v)
    lista = _lista_pie(v)
    lista.setCurrentRow(0)
    _boton_pie(v, "% CD").click()
    despues = _nombres_pie(v)
    assert despues[0] == antes[0] and despues[1] == 'Nueva línea', despues
    assert despues[2:] == antes[1:], despues
    # Queda seleccionada la línea nueva.
    assert _lista_pie(v).currentRow() == 1
    # Sin selección, al final (como siempre).
    _lista_pie(v).setCurrentRow(-1)
    _boton_pie(v, "Separador").click()
    assert _nombres_pie(v)[-1] == 'Nueva línea'
    # Códigos únicos aunque se borre y se vuelva a agregar.
    conn = d.get_db()
    cods = [r[0] for r in conn.execute(
        "SELECT codigo FROM pie_rubros WHERE proyecto_id=?", (v.pid,)).fetchall()]
    conn.close()
    assert len(cods) == len(set(cods)), cods
    assert v._codigo_linea_pie_nuevo() not in cods


def test_costo_directo_en_mayusculas_como_las_demas_filas():
    v = _vista(PID_SIMPLE)
    filas, _ = v._filas_resumen(all_subs=True)
    assert filas[0][0] == "COSTO DIRECTO", filas[0]
    assert filas[-1][0] == "PRESUPUESTO TOTAL"


# ── 2. Resumen ───────────────────────────────────────────────────────────────

def test_el_resumen_sigue_al_sub_presupuesto_al_cambiar_de_pestana():
    v = _vista(PID_SUBS)
    v.tabs.setCurrentIndex(4)                       # Resumen a la vista
    v._resumen_solo_sub = True
    v.cargar_resumen()
    conn = d.get_db()
    subs = [r[0] for r in conn.execute(
        "SELECT id FROM sub_presupuestos WHERE proyecto_id=? ORDER BY orden, id",
        (PID_SUBS,)).fetchall()]
    conn.close()
    assert any(l == "RESUMEN DE COSTOS — SUB-PRESUPUESTO 1/3" for l in _labels(v)), _labels(v)
    v._on_sub_ppto_cambiado(subs[1])                # sin pulsar recalcular
    labs = _labels(v)
    assert "RESUMEN DE COSTOS — SUB-PRESUPUESTO 3/3" in labs, labs
    assert fmt(v._total_proyecto(all_subs=False), v._moneda) in labs
    assert v._posicion_sub_actual() == (3, 3)
    # Con el Resumen fuera de la vista no se recarga (lo hace al entrar).
    v.tabs.setCurrentIndex(0)
    v._on_sub_ppto_cambiado(subs[0])
    assert "RESUMEN DE COSTOS — SUB-PRESUPUESTO 3/3" in _labels(v)


def test_el_donut_pide_el_ancho_de_su_leyenda():
    datos = [("Mano de Obra", 544272.24, "#F39C12"), ("Materiales", 920353.48, "#27AE60"),
             ("Equipo", 96091.58, "#607D8B")]
    ch = _DonutChart(datos, moneda="S/")
    f = QFont(); f.setPointSize(8); fm = QFontMetrics(f)
    w_amt, w_pct = ch._columnas_leyenda(fm)
    fb = QFont(f); fb.setBold(True)
    minimo = 28 + QFontMetrics(fb).horizontalAdvance("Total") + 8 + w_amt + ch._GAP + w_pct + 10
    assert ch.minimumSizeHint().width() == minimo > 160, (ch.minimumSizeHint(), minimo)
    assert ch.sizeHint().width() >= minimo
    assert ch.minimumWidth() == 0            # el hint manda, no un fijo
    # Sin moneda no hay fila Total ni columna de montos: cabe en lo de siempre.
    assert _DonutChart(datos).minimumSizeHint().width() == 160


# ── 3. Insumos ───────────────────────────────────────────────────────────────

def test_los_insumos_van_mo_mat_eq_sc():
    conn = d.get_db()
    tipos = [r['tipo'] for r in d.get_insumos_proyecto(conn, PID_SUBS)]
    conn.close()
    assert 'SC' in tipos and 'MAT' in tipos and 'EQ' in tipos, set(tipos)
    orden = {'MO': 1, 'MAT': 2, 'EQ': 3, 'SC': 4}
    assert [orden[t] for t in tipos] == sorted(orden[t] for t in tipos), tipos


def test_la_tabla_de_insumos_ordena_por_columna_y_lo_recuerda():
    v = _vista(PID_SUBS)
    t = v.tbl_ins
    assert COLS_ACU[0] == "Tipo"
    v.cargar_insumos(None)
    assert t.isSortingEnabled() and t.rowCount() > 10
    assert t.horizontalHeader().sortIndicatorSection() == -1     # agrupado por tipo
    tipos = [t.item(r, 0).text() for r in range(t.rowCount())]
    orden = {'MO': 1, 'MAT': 2, 'EQ': 3, 'SC': 4}
    assert [orden[x] for x in tipos] == sorted(orden[x] for x in tipos)

    t.sortItems(4, Qt.DescendingOrder)          # Precio, de mayor a menor
    precios = [t.item(r, 4).data(Qt.UserRole) for r in range(t.rowCount())]
    assert precios == sorted(precios, reverse=True) and precios[0] > 100, precios[:5]
    # Es el número el que ordena, no el texto («S/ 1,000.00» < «S/ 999.00»).
    assert t.item(0, 4).text() == fmt(precios[0], v._moneda)
    # La fila entera viaja: el badge sigue siendo el del insumo más caro.
    rid = t.item(0, 0).data(Qt.UserRole)
    conn = d.get_db()
    caro = max(d.get_insumos_proyecto(conn, PID_SUBS), key=lambda r: r['precio'])
    conn.close()
    assert rid == caro['recurso_id']
    # Recargar (buscar, Esc, cambiar precio) conserva el orden elegido.
    v.cargar_insumos(None)
    assert t.horizontalHeader().sortIndicatorSection() == 4
    precios2 = [t.item(r, 4).data(Qt.UserRole) for r in range(t.rowCount())]
    assert precios2 == precios
    # Tipo ordena por jerarquía, no por alfabeto (EQ < MAT < MO).
    t.sortItems(0, Qt.AscendingOrder)
    tipos = [t.item(r, 0).text() for r in range(t.rowCount())]
    assert tipos[0] == 'MO' and tipos[-1] == 'SC', (tipos[0], tipos[-1])
    t.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)


# ── 4. Gantt ─────────────────────────────────────────────────────────────────

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
    _VIVAS.append(cv)
    return cv._gantt_w


def test_el_menu_del_gantt_alterna_todas_y_el_minimo():
    g = _gantt(PID_SIMPLE)
    for c in range(g.tbl.columnCount()):
        g.tbl.setColumnHidden(c, False)
    assert not g._hay_columnas_ocultas()
    g._alternar_todas_las_columnas()                # → solo id y Descripción
    vis = [c for c in range(g.tbl.columnCount()) if not g.tbl.isColumnHidden(c)]
    assert vis == [0, 2], vis
    g._alternar_todas_las_columnas()                # → todas
    assert not g._hay_columnas_ocultas()
    g.tbl.setColumnHidden(5, True)                  # con UNA oculta también muestra todas
    g._alternar_todas_las_columnas()
    assert not g._hay_columnas_ocultas()


def test_exportar_gantt_arranca_con_pred_como_la_pantalla():
    from views.cronograma_view import _DialogExportarGanttPdf as D
    assert D().chk_pred.isChecked()                          # por defecto, como antes
    assert D(pred_visible=True).chk_pred.isChecked()
    assert not D(pred_visible=False).chk_pred.isChecked()
    assert not D(pred_visible=False)._opts()['incluir_pred']


# ── 5. Línea sobre el pie del reporte ────────────────────────────────────────

def _lineas_del_pie(flag: str) -> int:
    import pdfplumber
    d.set_config('rep_pie_linea_oculta', flag)
    fd, path = tempfile.mkstemp(suffix='_pie.pdf')
    os.close(fd)
    try:
        pr.generar_pdf_archivo('presupuesto', PID_SIMPLE, path, with_cover=False)
        with pdfplumber.open(path) as pdf:
            pg = pdf.pages[0]
            n = len([l for l in pg.lines + pg.rects + pg.curves
                     if l['top'] > pg.height - 45])
            pie = ' '.join(w['text'] for w in pg.crop(
                (0, pg.height - 30, pg.width, pg.height)).extract_words())
    finally:
        os.unlink(path)
        d.set_config('rep_pie_linea_oculta', '0')
    assert 'Página' in pie, pie          # los textos del pie siguen
    return n


def test_la_linea_sobre_el_pie_se_puede_apagar():
    assert 'rep_pie_linea_oculta' in pr.FORMATO_CLAVES
    assert pr.FORMATO_CLAVES['rep_pie_linea_oculta'] == '0'
    assert pr.pie_linea_oculta({'rep_pie_linea_oculta': '1'})
    assert not pr.pie_linea_oculta({})
    assert _lineas_del_pie('0') == 1
    assert _lineas_del_pie('1') == 0


def test_el_dialogo_de_formato_guarda_la_casilla_de_la_linea():
    from views.formato_reporte_dialog import FormatoReporteDialog
    dlg = FormatoReporteDialog()
    assert dlg.chk_pie_linea.isChecked()
    dlg.chk_pie_linea.setChecked(False)
    dlg._save_and_accept()
    assert pr.get_formato()['rep_pie_linea_oculta'] == '1'
    dlg2 = FormatoReporteDialog()                    # ida y vuelta
    assert not dlg2.chk_pie_linea.isChecked()
    dlg2.chk_pie.setChecked(False)                   # pie apagado → casilla gris
    assert not dlg2.chk_pie_linea.isEnabled()
    d.set_config('rep_pie_linea_oculta', '0')


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
    # Cerrar las vistas antes de salir: si Python las suelta en el atexit,
    # los filtros de eventos del Gantt y del tooltip se llaman en cadena
    # sobre widgets ya destruidos y ensucian la salida con un traceback.
    for w in _VIVAS:
        w.close()
        w.deleteLater()
    _app.processEvents()
    sys.exit(1 if fallos else 0)
