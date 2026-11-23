# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #34: nombre del total final, monto fijo a la vista, totales destacados."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QPushButton             # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])
SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_pietotal_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

from core import pie                                                # noqa: E402
import core.pdf_reports as pr                                       # noqa: E402
import core.exporter as ex                                          # noqa: E402

_VIVAS = []
CD = 5064029.95

# El modelo del issue, con el subtotal bien calculado.
LINEAS = [
    ('GG',   'Gastos generales',    15, 'pct_cd',   0),
    ('UTIL', 'Utilidad',            12, 'pct_cd',   0),
    ('SUB',  'Sub total',            0, 'subtotal', 0),
    ('IGV',  'IGV',                 18, 'pct_sub',  0),
    ('PO',   'Presupuesto de obra',  0, 'subtotal', 1),
    ('ET',   'Expediente técnico',   0, 'rubro',    0),
    ('SUP',  'Supervisión',          4, 'pct_sub',  0),
    ('GP',   'Gestión de proyecto',  2, 'pct_sub',  0),
]


def _proyecto(nombre_total='Costo de inversión', destacar=True):
    conn = d.get_db()
    pid = conn.execute("INSERT INTO proyectos (nombre, moneda, total_nombre) VALUES"
                       " ('pie','Soles',?)", (nombre_total,)).lastrowid
    for i, (cod, nom, pct, tipo, dest) in enumerate(LINEAS):
        conn.execute("INSERT INTO pie_rubros (proyecto_id, codigo, nombre, pct, activo,"
                     " orden, tipo, mostrar_pct, destacado) VALUES (?,?,?,?,1,?,?,1,?)",
                     (pid, cod, nom, pct, i, tipo, dest if destacar else 0))
    conn.execute("INSERT INTO gastos_generales (proyecto_id, rubro, tipo, descripcion,"
                 " precio, orden) VALUES (?,'ET','manual','__manual__',40000,0)", (pid,))
    conn.execute("INSERT INTO partidas (proyecto_id,item,descripcion,unidad,metrado,"
                 "precio_unitario,nivel,es_titulo) VALUES (?,'01','OBRA','glb',1,?,1,0)",
                 (pid, CD))
    conn.commit()
    conn.close()
    return pid


def test_modelo_del_issue():
    pid = _proyecto()
    filas = pr._build_pie_rows(pid, CD)
    m = {l: (v, c) for l, v, c in filas}
    obra, cls = m['Presupuesto de obra']
    assert cls == 'gran' and m['Sub total'][1] == 'sub'
    sup = m['Supervisión (4%)'][0]
    assert sup == round(obra * 0.04, 2)
    total, cls = m['COSTO DE INVERSIÓN']
    assert filas[-1][0] == 'COSTO DE INVERSIÓN' and cls == 'gran'
    assert total == round(obra + 40000 + sup + round(obra * 0.02, 2), 2)
    # Lo que usan la fórmula polinómica y las valorizaciones no cambia.
    _, tot = d.calcular_totales(pid)
    assert tot['cd'] == CD and tot['gf'] == round(CD * .15, 2)
    assert tot['utilidad'] == round(CD * .12, 2) and tot['total'] == total


def test_sin_configurar_todo_igual_que_antes():
    pid = _proyecto('', destacar=False)
    filas = pr._build_pie_rows(pid, CD)
    assert filas[-1][0] == 'PRESUPUESTO TOTAL'
    assert [c for _l, _v, c in filas].count('gran') == 1
    _it, tot = d.calcular_totales(pid)
    html = pr._html_gastos_generales(pid, {'moneda': 'Soles', 'total_nombre': ''}, tot)
    assert 'COSTO TOTAL DE OBRA' in html
    assert pie.nombre_total(pid, 'Presupuesto Total') == 'Presupuesto Total'


def _textos_xlsx(salida):
    import io
    import openpyxl
    datos = salida.getvalue() if hasattr(salida, 'getvalue') else salida
    wb = openpyxl.load_workbook(io.BytesIO(datos))
    return [str(c.value) for ws in wb for f in ws.iter_rows() for c in f if c.value]


def test_nombre_en_todas_las_exportaciones():
    pid = _proyecto()
    conn = d.get_db()
    proy = dict(conn.execute("SELECT * FROM proyectos WHERE id=?", (pid,)).fetchone())
    conn.close()
    items, tot = d.calcular_totales(pid)
    n = 'COSTO DE INVERSIÓN'
    assert n in pr._html_gastos_generales(pid, proy, tot)
    html = pr._html_resumen_ejecutivo(pid, proy, items, tot)
    assert html.count(n) == 2 and 'PRESUPUESTO TOTAL' not in html.upper()
    assert pr._todo_costo_factor_pie(pid, CD)[1][-1][0] == n
    for fn in (ex.exportar_presupuesto, ex.exportar_gastos_generales,
               ex.exportar_reporte_completo):
        textos = _textos_xlsx(fn(pid))
        assert n in textos, fn.__name__
        assert 'PRESUPUESTO TOTAL' not in textos, fn.__name__
    from core.word_reports import generar_word_resumen_ejecutivo
    import docx
    ruta = os.path.join(tempfile.mkdtemp(), 'r.docx')
    generar_word_resumen_ejecutivo(pid, ruta)
    doc = docx.Document(ruta)
    textos = [c.text for t in doc.tables for f in t.rows for c in f.cells]
    assert n in textos
    negritas = {c.text: c.paragraphs[0].runs[-1].font.size.pt
                for t in doc.tables for f in t.rows for c in f.cells
                if c.paragraphs[0].runs and c.paragraphs[0].runs[-1].font.size}
    assert negritas['Presupuesto de obra'] == 11 and negritas['Sub total'] == 10
    from core.asistente_local import totales_detalle
    assert n in totales_detalle(pid)


def test_editor_del_pie():
    from views.proyecto_view import ProyectoView
    from models.usuario import Usuario
    pid = _proyecto()
    v = ProyectoView(pid, Usuario(id=1, nombre='t', rol='admin'))
    _VIVAS.append(v)
    v.cargar_pie()
    filas, total = v._filas_resumen(all_subs=True)
    assert filas[-1][0] == 'COSTO DE INVERSIÓN'
    obra = next(f for f in filas if f[0] == 'Presupuesto de obra')
    assert obra[2] == filas[-1][2]                     # mismo realce que el total
    assert v.inp_total_nombre.text() == 'Costo de inversión'
    v.inp_total_nombre.setText('Inversión total')
    v.inp_total_nombre.editingFinished.emit()
    assert pie.nombre_total(pid) == 'INVERSIÓN TOTAL'

    def boton(texto):
        return next(b for b in v._pie_left_w.findChildren(QPushButton)
                    if b.text() == texto)
    boton('★').click()                                 # quitar el realce
    _app.processEvents()
    assert [c for _l, _x, c in pr._build_pie_rows(pid, CD)].count('gran') == 1

    v.cargar_pie()
    boton('Monto fijo').click()
    conn = d.get_db()
    r = conn.execute("SELECT * FROM pie_rubros WHERE proyecto_id=? AND codigo LIKE 'CUSTOM%'",
                     (pid,)).fetchone()
    g = conn.execute("SELECT * FROM gastos_generales WHERE proyecto_id=? AND rubro=?",
                     (pid, r['codigo'])).fetchone()
    conn.close()
    assert r['tipo'] == 'rubro' and g['tipo'] == 'manual'
    assert d.calcular_totales(pid)[1]['total'] == total  # entra en 0


def test_exportar_e_importar_db_y_duplicar_conservan_el_pie():
    from core.ingepresupuestos_db_importer import importar_proyecto_db_directo
    from views.dashboard_view import _clonar_proyecto
    pid = _proyecto()
    ruta = os.path.join(tempfile.mkdtemp(), 'p.db')
    ex.exportar_proyecto_db(pid, ruta)
    nuevo = importar_proyecto_db_directo(ruta, pid)
    conn = d.get_db()
    clon = _clonar_proyecto(conn, pid, {'pie'})
    conn.commit()
    conn.close()
    for p in (nuevo, clon):
        assert pr._build_pie_rows(p, CD) == pr._build_pie_rows(pid, CD)
