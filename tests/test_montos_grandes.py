"""Issue #49: montos de miles de millones (pesos colombianos) en los reportes.

El monto en letras reventaba a partir de 1 000 000 000, los números se partían
en dos renglones y Excel mostraba «#####».  Y los grupos de más de 99 partidas
se ordenaban mal («01.100» antes que «01.11»).
"""
import io
import os
import re
import shutil
import sys
import tempfile
import zipfile

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, '..'))

from PySide6.QtCore import QSizeF, Qt                             # noqa: E402
from PySide6.QtGui import QTextDocument                           # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

_app = QApplication.instance() or QApplication([])

import core.database as d                                         # noqa: E402

_fd, _tmpdb = tempfile.mkstemp(suffix='_montos_test.db')
os.close(_fd)
shutil.copy(os.path.join(AQUI, '..', 'presupuestos_seed.db'), _tmpdb)
d.DB_PATH = _tmpdb
d.init_db()

import core.exporter as ex                                        # noqa: E402
import core.pdf_reports as pr                                     # noqa: E402
from utils.formatting import (                                    # noqa: E402
    entero_a_letras, monto_en_letras, siguiente_codigo)

_c = d.get_db()
PID = _c.execute("SELECT id FROM proyectos ORDER BY id DESC").fetchone()['id']
_c.close()


@pytest.mark.parametrize('n, letras', [
    (0, 'cero'), (1, 'uno'), (21, 'veintiuno'), (31, 'treinta y uno'),
    (100, 'cien'), (101, 'ciento uno'), (1000, 'mil'), (1001, 'mil uno'),
    (21_000, 'veintiún mil'), (31_000, 'treinta y un mil'),
    (100_000, 'cien mil'), (101_000, 'ciento un mil'),
    (1_000_000, 'un millón'), (21_000_000, 'veintiún millones'),
    (131_000_000, 'ciento treinta y un millones'),
    (999_999_999, 'novecientos noventa y nueve millones novecientos noventa y '
                  'nueve mil novecientos noventa y nueve'),
    (1_000_000_000, 'mil millones'),
    (1_151_768_681, 'mil ciento cincuenta y un millones setecientos sesenta y '
                    'ocho mil seiscientos ochenta y uno'),
    (21_000_000_000, 'veintiún mil millones'),
    (10 ** 12, 'un billón'), (21 * 10 ** 12, 'veintiún billones'),
    (10 ** 18, 'un millón de billones'.replace(' de', '')),
    (-5, 'menos cinco'),
])
def test_enteros_en_letras(n, letras):
    assert entero_a_letras(n) == letras


def test_monto_en_letras_y_una_sola_funcion():
    assert (monto_en_letras(181_300.28)
            == 'CIENTO OCHENTA Y UN MIL TRESCIENTOS CON 28/100 SOLES')
    assert monto_en_letras(0.999) == 'UNO CON 00/100 SOLES'
    assert monto_en_letras(-5.5) == 'MENOS CINCO CON 50/100 SOLES'
    assert monto_en_letras(None) == 'CERO CON 00/100 SOLES'
    assert ex.monto_en_letras is pr._monto_en_letras is monto_en_letras


def test_el_centavo_de_las_letras_es_el_de_las_cifras():
    for n in (2.675, 1.005, 8.345, 1234567.995, 0.285, 4209.0, 1151768681.685):
        cifras = pr._fmt(n)
        assert f"CON {cifras[-2:]}/100" in monto_en_letras(n), n


@pytest.fixture
def gigante():
    """El proyecto del seed con los precios × 100 000 (miles de millones)."""
    conn = d.get_db()
    precios = conn.execute(
        "SELECT id, precio_unitario FROM partidas WHERE proyecto_id=?",
        (PID,)).fetchall()
    conn.execute("UPDATE partidas SET precio_unitario=precio_unitario*100000 "
                 "WHERE proyecto_id=?", (PID,))
    conn.execute("UPDATE proyectos SET moneda='Pesos Colombianos' WHERE id=?",
                 (PID,))
    conn.commit()
    assert d.calcular_totales(PID)[1]['total'] > 1e9
    yield PID
    conn.executemany("UPDATE partidas SET precio_unitario=? WHERE id=?",
                     [(p['precio_unitario'], p['id']) for p in precios])
    conn.execute("UPDATE proyectos SET moneda='Soles' WHERE id=?", (PID,))
    conn.commit()
    conn.close()


TIPOS = [t for t, _n, _d in pr.REPORT_TYPES if t != 'completo']


def test_todos_los_reportes_con_montos_de_miles_de_millones(gigante, tmp_path):
    for tipo in TIPOS:
        assert pr._build_html_for(tipo, gigante)[1]
    from core.word_reports import generar_word
    generar_word('resumen', gigante, str(tmp_path / 'r.docx'))
    xml = zipfile.ZipFile(tmp_path / 'r.docx').read('word/document.xml').decode()
    assert '<w:w w:val=' in xml          # los montos grandes van estrechos
    for f in (ex.exportar_presupuesto, ex.exportar_acus, ex.exportar_insumos,
              ex.exportar_gastos_generales, ex.exportar_reporte_completo):
        f(gigante)


def test_excel_da_ancho_a_los_montos(gigante):
    import openpyxl
    from openpyxl.utils import get_column_letter as L
    for f in (ex.exportar_presupuesto, ex.exportar_reporte_completo):
        wb = openpyxl.load_workbook(io.BytesIO(f(gigante).getvalue()))
        for ws in wb:
            juntas = {(m.min_row, m.min_col) for m in ws.merged_cells.ranges}
            for fila in ws.iter_rows():
                for c in fila:
                    if (isinstance(c.value, (int, float)) and c.value > 1e6
                            and (c.row, c.column) not in juntas):
                        ancho = ws.column_dimensions[L(c.column)].width
                        assert ancho >= len(f'{c.value:,.2f}') * 0.9, (
                            ws.title, c.coordinate, c.value, ancho, c.number_format)


def _doc(html, ancho):
    doc = QTextDocument()
    doc.setHtml(html)
    doc.setPageSize(QSizeF(ancho, 1000))
    doc.setDocumentMargin(0)
    return doc


def _renglones(doc):
    doc.documentLayout().documentSize()
    out, b = [], doc.begin()
    while b.isValid():
        out.append((b.text(), b.layout().lineCount()))
        b = b.next()
    return [x for x in out if x[0].strip()]


def test_el_monto_que_no_cabe_se_estrecha_y_no_se_parte():
    celda = '<td align="right" width="{w}">{t}</td>'
    html = ('<table width="100%" cellspacing="0"><tr>'
            + celda.format(w=60, t='1,151,768,681.69')
            + celda.format(w=60, t='44,000,000.00')
            + '<td width="60">01.02.03.04.05.06.07</td></tr></table>')
    doc = _doc(html, 180)
    assert dict(_renglones(doc))['1,151,768,681.69'] > 1
    assert pr._ajustar_montos(doc) >= 2
    r = dict(_renglones(doc))
    assert r['1,151,768,681.69'] == 1 and r['44,000,000.00'] == 1
    # Donde todo cabe no se toca nada.
    doc2 = _doc(html.replace('"60"', '"300"'), 1200)
    antes = doc2.toHtml()
    assert pr._ajustar_montos(doc2) == 0 and doc2.toHtml() == antes


def test_escala_de_texto_compacto_maximo():
    assert pr.texto_escala({'rep_escala_texto': '75'}) == 0.75
    assert pr.texto_escala({'rep_escala_texto': '80'}) == 0.80
    assert pr.texto_escala({'rep_escala_texto': ''}) == 1.0


# ── Códigos de tres dígitos ──────────────────────────────────────────────────

def test_siguiente_codigo():
    assert siguiente_codigo('01', {'01', '01.01', '01.02.01'}) == '01.02'
    assert siguiente_codigo('', {'01', '02', '02.01'}) == '03'
    cien = {f'01.{n:02d}' for n in range(1, 100)}
    assert siguiente_codigo('01', cien) == '01.100'
    tres = {f'01.{n:03d}' for n in range(1, 101)}
    assert siguiente_codigo('01', tres) == '01.101'     # y no «01.01»


def test_un_grupo_de_mas_de_99_usa_tres_digitos_y_ordena_bien():
    conn = d.get_db()
    pid = conn.execute("INSERT INTO proyectos (nombre) VALUES ('cien')").lastrowid
    filas = [('01', 1)] + [(f'01.{n:02d}', 0) for n in range(1, 106)]
    filas += [('01.50.01', 0), ('02', 1), ('02.01', 0), ('02.02', 0)]
    conn.executemany(
        "INSERT INTO partidas (proyecto_id,item,descripcion,es_titulo) "
        "VALUES (?,?,?,?)", [(pid, i, i, t) for i, t in filas])
    assert d.igualar_codigos_hermanos(conn, pid) == 99 + 1
    assert d.igualar_codigos_hermanos(conn, pid) == 0
    items = [r['item'] for r in conn.execute(
        "SELECT item FROM partidas WHERE proyecto_id=? ORDER BY item", (pid,))]
    hijas = [i for i in items if re.fullmatch(r'01\.\d+', i)]
    assert hijas == [f'01.{n:03d}' for n in range(1, 106)]
    assert '01.050.01' in items and '02.01' in items and '01' in items
    conn.execute("DELETE FROM partidas WHERE proyecto_id=?", (pid,))
    conn.execute("DELETE FROM proyectos WHERE id=?", (pid,))
    conn.commit()
    conn.close()


def test_renumerar_el_arbol_con_mas_de_99_hermanas():
    from views.proyecto_view import _PresupuestoTree
    from PySide6.QtWidgets import QTreeWidgetItem
    arbol = _PresupuestoTree.__new__(_PresupuestoTree)
    padre, n = QTreeWidgetItem(), 120
    for i in range(n):
        h = QTreeWidgetItem(padre)
        h.setData(0, Qt.UserRole, i + 1)

    class Conn:
        def execute(self, *_a):
            pass
    _PresupuestoTree._procesar_nivel(arbol, padre, '01', 2, Conn())
    codigos = [padre.child(i).text(0) for i in range(n)]
    assert codigos[0] == '01.001' and codigos[-1] == '01.120'
    assert codigos == sorted(codigos)
