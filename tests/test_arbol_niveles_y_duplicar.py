# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Dos pedidos de David Ramos del 9 sep 2026 sobre el árbol del presupuesto.

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_arbol_niveles_y_duplicar.py

1. «Mostrar hasta el nivel N» (botón «≡» junto a recalcular): abre el árbol
   hasta ese nivel y lo deja cerrado de ahí para abajo, para ver los montos
   agrupados sin plegar rama por rama. El nivel elegido sobrevive a la recarga.
2. Duplicar una partida abre su ficha para renombrarla; si se CANCELA, la
   copia se descarta (antes quedaba insertada igual).

Usa una COPIA temporal del seed y una ProyectoView real en `offscreen`; el
diálogo de la ficha se sustituye por uno que acepta o cancela sin abrirse.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem

import core.database as d

_app = QApplication.instance() or QApplication([])

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_arbol_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)


def _usar_bd_temporal():
    """Apunta `get_db()` a la copia. Se llama en cada prueba, no al importar:
    en la suite completa otros módulos también fijan `DB_PATH` al importarse
    y el último en cargarse ganaría."""
    if d.DB_PATH != _tmpdb:
        d.DB_PATH = _tmpdb
        d.init_db()      # migraciones sobre la copia, como hace la app al arrancar


_usar_bd_temporal()

import views.proyecto_view as PV                    # noqa: E402
from views.proyecto_view import (                   # noqa: E402
    expandir_hasta_nivel, profundidad_titulos, ProyectoView)
from models.usuario import Usuario                  # noqa: E402

PID = 186  # RESERVORIOS DE 600 M3: en elaboración, 62 filas, títulos a 2 niveles


def _vista() -> ProyectoView:
    """ProyectoView real con el árbol ya cargado (la app lo difiere con
    QTimer al abrir la pestaña)."""
    _usar_bd_temporal()
    v = ProyectoView(PID, Usuario(id=1, nombre="t", rol="admin"))
    v._completar_panel_tabs()      # panel ACU/insumos (segunda etapa)
    v._cargar_datos_inicial()      # partidas + total
    return v


# ── 1. Expandir hasta un nivel ───────────────────────────────────────────────

def _arbol_de_prueba():
    """01 (t1) → 01.01 (t2) → 01.01.01 (t3) → partida ; 02 (t1) → partida."""
    tw = QTreeWidget()
    t1 = QTreeWidgetItem(tw, ["01"])
    t2 = QTreeWidgetItem(t1, ["01.01"])
    t3 = QTreeWidgetItem(t2, ["01.01.01"])
    QTreeWidgetItem(t3, ["01.01.01.01"])
    t1b = QTreeWidgetItem(tw, ["02"])
    QTreeWidgetItem(t1b, ["02.01"])
    tw.expandAll()
    return tw, (t1, t2, t3, t1b)


def test_profundidad_cuenta_solo_los_titulos():
    tw, _ = _arbol_de_prueba()
    assert profundidad_titulos(tw.invisibleRootItem()) == 3
    assert profundidad_titulos(QTreeWidget().invisibleRootItem()) == 0


def test_nivel_1_deja_solo_los_capitulos_cerrados():
    tw, (t1, t2, t3, t1b) = _arbol_de_prueba()
    expandir_hasta_nivel(tw.invisibleRootItem(), 1)
    assert not t1.isExpanded() and not t1b.isExpanded()
    # Los de abajo también quedan cerrados: al abrir el capítulo a mano no
    # debe aparecer todo el sub-árbol de golpe.
    assert not t2.isExpanded() and not t3.isExpanded()


def test_nivel_2_abre_los_capitulos_y_cierra_los_subcapitulos():
    tw, (t1, t2, t3, t1b) = _arbol_de_prueba()
    expandir_hasta_nivel(tw.invisibleRootItem(), 2)
    assert t1.isExpanded() and t1b.isExpanded()
    assert not t2.isExpanded()
    assert not t3.isExpanded()


def test_todos_abre_el_arbol_entero():
    tw, nodos = _arbol_de_prueba()
    expandir_hasta_nivel(tw.invisibleRootItem(), 1)
    expandir_hasta_nivel(tw.invisibleRootItem(), None)
    assert all(n.isExpanded() for n in nodos)


def test_el_nivel_elegido_sobrevive_a_la_recarga():
    v = _vista()
    root = v.tree.invisibleRootItem()
    n_max = profundidad_titulos(root)
    assert n_max >= 2, "el proyecto de prueba necesita al menos 2 niveles"
    v.mostrar_hasta_nivel(1)
    assert all(not root.child(i).isExpanded() for i in range(root.childCount()))
    v.recargar_partidas()               # lo que hace recalcular, editar, etc.
    assert all(not root.child(i).isExpanded() for i in range(root.childCount()))
    v.mostrar_hasta_nivel(None)
    v.recargar_partidas()
    assert all(root.child(i).isExpanded() for i in range(root.childCount()))


def test_el_menu_ofrece_tantos_niveles_como_hay():
    v = _vista()
    n_max = profundidad_titulos(v.tree.invisibleRootItem())
    v._armar_menu_niveles()
    textos = [a.text() for a in v._menu_niveles.actions() if not a.isSeparator()]
    assert textos == ["Todos"] + [f"Nivel {n}" for n in range(1, n_max + 1)]
    assert v._menu_niveles.actions()[0].isChecked()   # «Todos» es el activo


# ── 2. Duplicar y cancelar ───────────────────────────────────────────────────

class _FichaFalsa:
    """Sustituto de PartidaFormDialog: no abre nada, solo acepta o cancela."""
    resultado = 0
    abiertas: list = []

    def __init__(self, pid, part_id, usuario, parent=None, **kw):
        _FichaFalsa.abiertas.append(part_id)

    def exec(self):
        return _FichaFalsa.resultado


def _partidas(pid):
    conn = d.get_db()
    rows = conn.execute(
        "SELECT id, item, descripcion FROM partidas WHERE proyecto_id=? "
        "AND es_titulo=0 ORDER BY item", (pid,)).fetchall()
    conn.close()
    return [tuple(r) for r in rows]


def _con_ficha_falsa(fn):
    import views.partida_form_dialog as PFD
    real = PFD.PartidaFormDialog
    PFD.PartidaFormDialog = _FichaFalsa
    try:
        return fn()
    finally:
        PFD.PartidaFormDialog = real


def test_cancelar_la_ficha_descarta_la_copia():
    v = _vista()
    antes = _partidas(PID)
    orig_id = antes[0][0]
    _FichaFalsa.resultado = 0
    _FichaFalsa.abiertas = []
    _con_ficha_falsa(lambda: v._duplicar_partida(orig_id))
    despues = _partidas(PID)
    assert despues == antes, "al cancelar no debe quedar ninguna partida nueva"
    assert len(_FichaFalsa.abiertas) == 1 and _FichaFalsa.abiertas[0] != orig_id
    # La ficha se abrió sobre la copia, y esa copia ya no existe.
    conn = d.get_db()
    assert conn.execute("SELECT COUNT(*) FROM partidas WHERE id=?",
                        (_FichaFalsa.abiertas[0],)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM acu_items WHERE partida_id=?",
                        (_FichaFalsa.abiertas[0],)).fetchone()[0] == 0
    conn.close()
    # Y el árbol vuelve a la original.
    cur = v.tree.currentItem()
    assert cur is not None and cur.data(0, 0x0100) == orig_id


def test_aceptar_la_ficha_conserva_la_copia_como_hermana():
    v = _vista()
    antes = _partidas(PID)
    orig_id, orig_item, orig_desc = antes[0]
    _FichaFalsa.resultado = 1
    _FichaFalsa.abiertas = []
    _con_ficha_falsa(lambda: v._duplicar_partida(orig_id))
    despues = _partidas(PID)
    assert len(despues) == len(antes) + 1
    nuevo = [r for r in despues if r[0] == _FichaFalsa.abiertas[0]][0]
    assert nuevo[2] == orig_desc
    # Hermana justo debajo: mismo prefijo, correlativo siguiente.
    pref, n = orig_item.rsplit('.', 1)
    assert nuevo[1] == f"{pref}.{int(n) + 1:02d}"
    # La copia trae los insumos del ACU.
    conn = d.get_db()
    n_orig = conn.execute("SELECT COUNT(*) FROM acu_items WHERE partida_id=?",
                          (orig_id,)).fetchone()[0]
    n_new = conn.execute("SELECT COUNT(*) FROM acu_items WHERE partida_id=?",
                         (nuevo[0],)).fetchone()[0]
    conn.close()
    assert n_new == n_orig


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-q']))


# ── 3. Ítems hondos ──────────────────────────────────────────────────────────
# Marco, 9 sep 2026: con títulos a nueve niveles la columna Ítem crecía hasta
# el código más largo y quedaba un hueco entre el ítem y la descripción de
# las filas superficiales. En el árbol el código desborda sobre la
# descripción (como Excel); en el PDF, Ítem + Descripción van en una celda
# con tabla anidada y el código hondo empuja solo su descripción.

def test_partir_item_solo_toca_los_de_mas_de_cinco_tramos():
    from utils.formatting import partir_item
    assert partir_item('01') == '01'
    assert partir_item('01.02.02.03.06') == '01.02.02.03.06'
    assert partir_item('01.02.02.03.06.01') == '01.02.02.03.06.\n01'
    assert partir_item('01.02.02.03.06.01.01.01.01') == '01.02.02.03.06.\n01.01.01.01'
    assert partir_item('01.02.02.03.06.01.01.01.01', sep='<br>') == '01.02.02.03.06.<br>01.01.01.01'
    assert partir_item('') == '' and partir_item(None) == ''


def _con_cadena_honda():
    """Cuelga de 01 una cadena de títulos hasta el nivel 9 y una partida."""
    _usar_bd_temporal()
    conn = d.get_db()
    item = '01'
    for n in range(2, 10):
        item += '.09'
        conn.execute(
            "INSERT INTO partidas (proyecto_id,item,descripcion,unidad,metrado,"
            "precio_unitario,nivel,es_titulo) VALUES (?,?,?,?,?,?,?,?)",
            (PID, item, f'TITULO DE NIVEL {n}', '', 0, 0, n, 1))
    conn.execute(
        "INSERT INTO partidas (proyecto_id,item,descripcion,unidad,metrado,"
        "precio_unitario,nivel,es_titulo) VALUES (?,?,?,?,?,?,?,?)",
        (PID, item + '.01', 'PARTIDA HONDA', 'm2', 10, 5, 10, 0))
    conn.commit()
    conn.close()
    return item + '.01'


def test_el_item_hondo_desborda_sobre_la_descripcion_sin_ensanchar_la_columna():
    from PySide6.QtGui import QFontMetrics
    hondo = _con_cadena_honda()
    v = _vista()
    v.show()
    ancho = v.tree.columnWidth(0)
    nodo = next(it for pid, it in v._id_to_item.items() if it.text(0) == hondo)
    normal = next(it for pid, it in v._id_to_item.items() if it.text(0) == '01.01')
    # El texto del ítem sigue siendo el código completo (renumerar, buscar y
    # los reportes lo leen de ahí); solo cambia cómo se pinta.
    assert nodo.text(0) == hondo
    # La columna Ítem es PLANA (el árbol sangra la Descripción,
    # `setTreePosition(1)`) y NO crece hasta el código hondo: queda por
    # debajo de lo que mide ese código con su fuente.
    assert v.tree.treePosition() == 1
    fm = QFontMetrics(nodo.font(0))
    assert ancho < fm.horizontalAdvance(hondo), (ancho, fm.horizontalAdvance(hondo))
    # …y la descripción sabe que el ítem desborda.
    dd = v._desc_delegate
    idx_h = v.tree.indexFromItem(nodo, 1)
    idx_n = v.tree.indexFromItem(normal, 1)
    des = dd._desborde_item(idx_h, v.tree.font())
    assert des is not None and des[0] == hondo
    assert dd._desborde_item(idx_n, v.tree.font()) is None
    # La sangría de jerarquía la pone el árbol; el delegado solo añade la
    # extra cuando el código llega hasta la celda. Con la columna muy
    # angosta y el título de nueve tramos en negrita (8 niveles de
    # sangría), el código alcanza la celda y la descripción se corre.
    titulo9 = next(it for pid, it in v._id_to_item.items()
                   if it.text(0) == '01.09.09.09.09.09.09.09.09')
    idx_t = v.tree.indexFromItem(titulo9, 1)
    v.tree.setColumnWidth(0, 20)
    left = v.tree.header().sectionViewportPosition(1) + dd._indent_px(idx_t)
    assert dd._sangria(idx_t, left, v.tree.font()) > 0
    left_n = v.tree.header().sectionViewportPosition(1) + dd._indent_px(idx_n)
    assert dd._sangria(idx_n, left_n, v.tree.font()) == 0
    # Con la columna ancha de sobra, nada desborda.
    v.tree.setColumnWidth(0, 600)
    assert dd._desborde_item(idx_h, v.tree.font()) is None


def test_el_pdf_lleva_item_y_descripcion_en_una_celda_y_el_hondo_entero():
    """Ítem + Descripción van en UNA celda con tabla anidada: el código de
    hasta cinco tramos ocupa un ancho fijo y el hondo se pinta entero (sin
    partir ni recortar) en una celda más ancha solo en su fila."""
    import re
    import core.pdf_reports as pr
    hondo = _con_cadena_honda()
    _usar_bd_temporal()
    _, body, _ = pr._build_html_for('presupuesto', PID, None)
    assert hondo in body and '<br>' not in body.split(hondo)[0][-200:]
    # Un mismo ancho fijo para los códigos normales…
    anchos = [int(w) for w in re.findall(r'<td width="(\d+)" style="border:none;padding:0;background:transparent;vertical-align:top">', body)]
    assert anchos and len(set(anchos)) >= 2, anchos
    w_fijo = min(anchos)
    # …y el de la fila honda, más ancho.
    m = re.search(r'<td width="(\d+)" style="[^"]*vertical-align:top">' + re.escape(hondo), body)
    assert m and int(m.group(1)) > w_fijo, (m and m.group(1), w_fijo)
    # La cabecera lleva el mismo ancho fijo que las filas.
    assert f'<td width="{w_fijo}" style="border:none;padding:0;background:transparent;">Ítem</td>' in body


def test_el_excel_deja_la_col_b_vacia_para_que_el_item_hondo_desborde():
    """Excel/LibreOffice solo dejan que una celda siga de largo sobre una
    vecina VACÍA: con más de cinco tramos la descripción pasa a la col C y
    la B queda sin nada ni merge. Hasta cinco, la col A se ensancha al código
    más largo y nada cambia de columna (con umbral 4, las partidas de nivel
    5 saltaban a C mientras sus títulos seguían en B: «se ve fatal», Marco).
    El ODS sale del mismo .xlsx, así que vale para los dos."""
    import io
    import openpyxl
    import core.exporter as EX
    hondo = _con_cadena_honda()
    _usar_bd_temporal()
    wb = openpyxl.load_workbook(io.BytesIO(EX.exportar_presupuesto(PID).getvalue()))
    ws = wb.worksheets[0]
    filas = {r[0].value: r for r in ws.iter_rows() if isinstance(r[0].value, str)}
    merges = {(m.min_row, m.min_col) for m in ws.merged_cells.ranges}
    # Cuatro y cinco tramos: como siempre, descripción en B (mergeada)
    for item, desc in (('01.09.09.09', 'TITULO DE NIVEL 4'), ('01.09.09.09.09', 'TITULO DE NIVEL 5')):
        f = filas[item]
        assert f[1].value == desc and (f[0].row, 2) in merges, item
    # La col A se ajustó al código de cinco tramos (14 caracteres + 2)
    assert ws.column_dimensions['A'].width == 16
    # Nueve tramos y la partida honda: B vacía, descripción en C
    for item, desc in ((hondo, 'PARTIDA HONDA'), ('01.09.09.09.09.09.09.09.09', 'TITULO DE NIVEL 9')):
        f = filas[item]
        assert f[1].value is None, item
        assert (f[2].value or '').startswith(desc), item
        assert (f[0].row, 2) not in merges, item
    # El ítem de nueve tramos cabe en A+B en negrita (29 unidades ≈ 27 chars)
    assert ws.column_dimensions['A'].width + ws.column_dimensions['B'].width >= 29


def test_el_excel_de_un_proyecto_normal_no_mueve_nada_de_columna():
    """Sin ítems de más de cinco tramos, cada descripción está en B y la
    col A mide lo que su código más largo (mínimo 12)."""
    import io
    import openpyxl
    import core.exporter as EX
    _usar_bd_temporal()
    # Proyecto 32 (Arequipa, 4 niveles): otros tests le cuelgan cadenas
    # hondas al 186 y la BD temporal es compartida.
    wb = openpyxl.load_workbook(io.BytesIO(EX.exportar_presupuesto(32).getvalue()))
    ws = wb.worksheets[0]
    filas = [r for r in ws.iter_rows() if isinstance(r[0].value, str) and r[0].value[:1].isdigit()]
    assert filas and all(r[1].value for r in filas), [r[0].value for r in filas if not r[1].value]
    assert 12 <= ws.column_dimensions['A'].width <= 16
    assert ws.column_dimensions['A'].width + ws.column_dimensions['B'].width == 30


# ── 4. Cronograma valorizado: mismo tratamiento del ítem hondo ───────────────
# Marco, 9 sep 2026: «ahora cómo hacemos con el reporte de cronograma
# valorizado». Pantalla: desborda sobre la Descripción (la columna Ítem es
# fija, 60 px). PDF: dos líneas. Excel/ODS: col B vacía y descripción en C.

def _cronograma_view_con_cadena_honda():
    from views.cronograma_view import CronogramaView
    hondo = _con_cadena_honda()
    conn = d.get_db()
    proy = dict(conn.execute("SELECT * FROM proyectos WHERE id=?", (PID,)).fetchone())
    conn.close()
    cv = CronogramaView(PID, proy, lambda: None)
    cv.show()
    try:
        cv.cargar()
    except Exception:
        pass
    cv._valorz_w.cargar()
    return cv, hondo


def test_el_valorizado_en_pantalla_desborda_el_item_hondo():
    cv, hondo = _cronograma_view_con_cadena_honda()
    w = cv._valorz_w
    filas = {w.tbl_l.item(r, 0).text(): r for r in range(w.tbl_l.rowCount())
             if w.tbl_l.item(r, 0) is not None}
    idx_h = w.tbl_l.model().index(filas[hondo], 1)
    idx_n = w.tbl_l.model().index(filas['01.01'], 1)
    des = w._item_delegate.desborde(idx_h)
    assert des is not None and des[0] == hondo
    assert w._item_delegate.desborde(idx_n) is None
    # Con la columna ancha de sobra nada desborda.
    w.tbl_l.setColumnWidth(0, 400)
    assert w._item_delegate.desborde(idx_h) is None
    assert not w.tbl_l.showGrid()      # la cuadrícula la pintan los delegados


def test_el_valorizado_en_excel_deja_la_col_b_vacia_para_el_item_hondo():
    import openpyxl
    cv, hondo = _cronograma_view_con_cadena_honda()
    fd, path = tempfile.mkstemp(suffix='_val.xlsx')
    os.close(fd)
    cv._valorz_w._build_xlsx_valorizado(path)
    ws = openpyxl.load_workbook(path).worksheets[0]
    os.unlink(path)
    filas = {r[0].value: r for r in ws.iter_rows() if isinstance(r[0].value, str)}
    merges = {(m.min_row, m.min_col) for m in ws.merged_cells.ranges}
    f5 = filas['01.09.09.09.09']
    assert f5[1].value == 'TITULO DE NIVEL 5' and (f5[0].row, 2) in merges
    for item, desc in ((hondo, 'PARTIDA HONDA'), ('01.09.09.09.09.09.09.09.09', 'TITULO DE NIVEL 9')):
        f = filas[item]
        assert f[1].value is None and (f[2].value or '').startswith(desc), item
        assert (f[0].row, 2) not in merges, item
        assert not f[0].alignment.wrap_text, item      # sigue de largo, no se envuelve
    assert ws.column_dimensions['A'].width + ws.column_dimensions['B'].width == 29


def test_el_pdf_del_valorizado_lleva_el_item_hondo_entero_en_su_celda():
    import re
    import core.pdf_reports as pr
    hondo = _con_cadena_honda()
    _usar_bd_temporal()
    _, body, _ = pr._build_html_for('cronograma_valorizado', PID, None)
    assert hondo in body and '<br>' not in body.split(hondo)[0][-200:]
    anchos = [int(w) for w in re.findall(r'<td width="(\d+)" style="border:none;padding:0;background:transparent;vertical-align:top">', body)]
    m = re.search(r'<td width="(\d+)" style="[^"]*vertical-align:top">' + re.escape(hondo), body)
    assert anchos and m and int(m.group(1)) > min(anchos)


# ── 5. Diagrama de Gantt: tabla en pantalla y PDF ────────────────────────────
# Marco, 9 sep 2026 (captura de la vista previa del PDF): el ítem salía
# «01.02.…» y la descripción recortada. Pantalla: el código de largo sobre
# la Descripción cuando no cabe en su columna (fija, 60 px). PDF: la columna
# Ítem se mide con la fuente hasta cinco tramos y los más hondos siguen de
# largo; las fechas se miden con la fuente en negrita.

def test_la_tabla_del_gantt_desborda_el_item_hondo():
    cv, hondo = _cronograma_view_con_cadena_honda()
    g = cv._gantt_w
    g.tbl.setColumnWidth(1, 60)
    filas = {g.tbl.item(r, 1).text(): r for r in range(g.tbl.rowCount())
             if g.tbl.item(r, 1) is not None}
    idx_h = g.tbl.model().index(filas[hondo], 2)
    idx_n = g.tbl.model().index(filas['01.01'], 2)
    des = g._item_delegate.desborde(idx_h)
    assert des is not None and des[0] == hondo
    assert g._item_delegate.desborde(idx_n) is None
    g.tbl.setColumnWidth(1, 400)
    assert g._item_delegate.desborde(idx_h) is None
    assert not g.tbl.showGrid()


def test_el_pdf_del_gantt_se_genera_con_la_cadena_honda():
    """El PDF del Gantt se pinta con QPainter: aquí solo se comprueba que
    con ítems de nueve tramos y fechas en negrita sigue generándose y que la
    columna Ítem no se ensancha más allá de los cinco tramos."""
    import pypdf
    cv, hondo = _cronograma_view_con_cadena_honda()
    fd, path = tempfile.mkstemp(suffix='_gantt.pdf')
    os.close(fd)
    cv._gantt_w._render_pdf_completo(path, 'multi', 'landscape', True)
    texto = "\n".join(pg.extract_text() for pg in pypdf.PdfReader(path).pages)
    os.unlink(path)
    import re
    assert '01.09.09.09.09.09.09.09.09' in texto     # nueve tramos, entero
    assert hondo in texto                             # la partida honda también
    assert not re.search(r'01\.09[\d.]*…', texto)   # ningún ítem recortado con «…»


def test_el_pdf_del_gantt_parte_en_dos_lineas_la_descripcion_larga():
    """Marco, 9 sep 2026: en el PDF del Gantt las descripciones largas salían
    «…». Ahora la columna se mide y lo que no cabe va en dos líneas con una
    fila más alta; la MISMA lista de alturas la usan la tabla, las barras y la
    paginación, que es lo que mantiene tabla y barras alineadas."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    cv, _ = _cronograma_view_con_cadena_honda()
    conn = d.get_db()
    conn.execute(
        "INSERT INTO partidas (proyecto_id,item,descripcion,unidad,metrado,"
        "precio_unitario,nivel,es_titulo) VALUES (?,?,?,?,?,?,?,?)",
        (PID, '01.99', 'PARTIDA CON UNA DESCRIPCION LARGUISIMA QUE NO CABE EN '
                       'UNA SOLA LINEA DE LA COLUMNA DEL GANTT NI DE BROMA', 'm2', 1, 1, 2, 0))
    conn.commit()
    conn.close()
    cv.cargar()
    g = cv._gantt_w
    partidas = cv.filas_con_hitos()
    img = QImage(200, 200, QImage.Format_RGB32)
    p = QPainter(img)
    try:
        mm = lambda v: v * p.device().logicalDpiX() / 25.4
        col_defs = [('id', mm(9), 0), ('Ítem', mm(14), 0), ('Descripción', mm(50), 0)]
        hs = g._pdf_row_heights(p, partidas, col_defs, mm(5))
        assert len(hs) == len(partidas)
        larga = next(i for i, pt in enumerate(partidas) if (pt.get('descripcion') or '').startswith('PARTIDA CON UNA'))
        corta = next(i for i, pt in enumerate(partidas) if (pt.get('descripcion') or '') == 'AGUA PARA LA CONSTRUCCION')
        assert hs[larga] > hs[corta] == mm(5)
        # Con la columna ancha de sobra, todas las filas vuelven al alto base.
        col_defs[2] = ('Descripción', mm(400), 0)
        assert set(g._pdf_row_heights(p, partidas, col_defs, mm(5))) == {mm(5)}
        # La medida de la columna crece con la descripción más larga.
        assert g._pdf_desc_width(p, partidas, mm(5)) > mm(50)
        # Partir en dos: la primera línea cabe y la segunda se elide si sobra.
        fm = p.fontMetrics()
        lineas = g._pdf_dos_lineas(fm, 'UNA DOS TRES CUATRO CINCO SEIS SIETE OCHO', fm.horizontalAdvance('UNA DOS TRES X'))
        assert len(lineas) == 2 and lineas[0] == 'UNA DOS TRES'
    finally:
        p.end()
