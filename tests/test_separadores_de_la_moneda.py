"""Issue #48: los reportes y las cantidades en pantalla llevan los separadores
de la moneda del proyecto.  En Soles no cambia un carácter."""
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

from PySide6.QtWidgets import QApplication                        # noqa: E402

_app = QApplication.instance() or QApplication([])

import core.database as d                                         # noqa: E402

_fd, _tmpdb = tempfile.mkstemp(suffix='_separadores_test.db')
os.close(_fd)
shutil.copy(os.path.join(AQUI, '..', 'presupuestos_seed.db'), _tmpdb)
d.DB_PATH = _tmpdb
d.init_db()

import core.exporter as ex                                        # noqa: E402
import core.pdf_reports as pr                                     # noqa: E402
from core.word_reports import generar_word                        # noqa: E402
from utils import formatting as F                                 # noqa: E402

_c = d.get_db()
PID = _c.execute("SELECT id FROM proyectos ORDER BY id DESC").fetchone()['id']
_c.close()
UY, CH = 'Pesos Uruguayos', 'Franco de prueba'


def _moneda(nombre):
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET moneda=? WHERE id=?", (nombre, PID))
    conn.commit()
    conn.close()


@pytest.fixture
def uruguay():
    _moneda(UY)
    yield
    _moneda('Soles')


TIPOS = [t for t, _n, _d in pr.REPORT_TYPES if t != 'completo']
# Número con separadores peruanos, solo en su celda o tras el símbolo.
INGLES = re.compile(r'^(?:[^\w<>]*\$ ?)?-?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{1,4}%|\d+\.\d{4})$')


def _textos(html):
    return [t.strip() for t in re.findall(r'>([^<>]+)<', html)]


def test_fmt_doc_en_soles_es_el_formato_de_siempre():
    for n in (0, 1234.5, -1234.567, 0.125, 1e9, None):
        for dec in (0, 2, 3, 4):
            esperado = f'{float(n or 0):,.{dec}f}'
            assert F.fmt_doc(n, dec) == esperado
            assert F.fmt_doc(n, dec, moneda='Soles') == esperado
            assert pr._fmt(n, dec) == esperado
    assert F.fmt_pct(1234.56) == '1234.6%'
    assert F.fmt_doc(1234.5, 2, moneda=UY) == '1.234,50'
    assert F.fmt_pct(12.34, 2, moneda=UY) == '12,34%'


def test_los_numeros_de_un_reporte_son_los_de_soles_con_otros_separadores(uruguay):
    """Mismo documento, número a número: solo cambian los separadores."""
    for tipo in TIPOS:
        uy = _textos(pr._build_html_for(tipo, PID)[1])
        malos = [t for t in uy if INGLES.match(t)]
        assert not malos, (tipo, malos[:5])
    _moneda('Soles')
    for tipo in ('presupuesto', 'acus', 'insumos', 'metrados', 'cronograma_valorizado'):
        _moneda('Soles')
        pe = _textos(pr._build_html_for(tipo, PID)[1])
        _moneda(UY)
        uy = _textos(pr._build_html_for(tipo, PID)[1])
        num = re.compile(r'^-?[\d,]+\.\d+$')
        assert len(pe) == len(uy)
        comparados = 0
        for a, b in zip(pe, uy):
            if num.match(a) and b != a:
                comparados += 1
                assert b == a.translate({ord(','): '.', ord('.'): ','}), (tipo, a, b)
        assert comparados > 20, tipo


def test_word_y_excel(uruguay, tmp_path):
    generar_word('resumen', PID, str(tmp_path / 'r.docx'))
    xml = zipfile.ZipFile(tmp_path / 'r.docx').read('word/document.xml').decode()
    assert not [t for t in _textos(xml) if INGLES.match(t)]
    total = F.fmt_doc(d.calcular_totales(PID)[1]['total'], 2, moneda=UY)
    assert total in xml
    import openpyxl
    for f in (ex.exportar_presupuesto, ex.exportar_insumos, ex.exportar_acus,
              ex.exportar_metrados):
        wb = openpyxl.load_workbook(io.BytesIO(f(PID).getvalue()))
        for ws in wb:
            for fila in ws.iter_rows():
                for c in fila:
                    assert '[$-0409]' not in c.number_format
                    if isinstance(c.value, str):
                        assert not INGLES.match(c.value.strip()), c.value


def test_el_pdf_real_lleva_los_separadores(uruguay, tmp_path):
    import pypdf
    ruta = str(tmp_path / 'p.pdf')
    pr.generar_pdf_archivo('presupuesto', PID, ruta)
    texto = ''.join(p.extract_text() for p in pypdf.PdfReader(ruta).pages).replace('\t', ' ')
    total = F.fmt_doc(d.calcular_totales(PID)[1]['total'], 2, moneda=UY)
    assert total in texto
    # El documento acabado no deja la moneda puesta para el siguiente.
    assert F.fmt_doc(1234.5) == '1,234.50'


def test_excel_en_soles_conserva_sus_formatos():
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(ex.exportar_presupuesto(PID).getvalue()))
    formatos = {c.number_format for ws in wb for r in ws.iter_rows() for c in r}
    assert '[$-0409]#,##0.00' in formatos


def test_los_generadores_con_proyecto_estan_decorados():
    for mod, prefijos in ((pr, ('generar_', '_html_')), (ex, ('exportar_',))):
        for nombre, fn in vars(mod).items():
            if (callable(fn) and nombre.startswith(prefijos)
                    and getattr(fn, '__module__', '') == mod.__name__
                    and nombre != 'exportar_proyecto_db'):
                import inspect
                args = set(inspect.signature(fn).parameters)
                if args & {'pid', 'proy', 'proyecto_id', 'val_id', 'req_id'}:
                    assert hasattr(fn, '__wrapped__'), nombre


def test_leer_de_vuelta_lo_que_se_muestra():
    for n in (0.125, 12.345, 1234.5, 12345.678, 1234567.0):
        for dec in (0, 2, 3, 4):
            for m in ('Soles', UY, 'Dólares'):
                t = F.fmt_doc(n, dec, moneda=m)
                assert F.parse_num(t, m, mostrado=True) == pytest.approx(round(n, dec)), (t, m)
                ed = F.texto_para_editar(t, m)
                if dec:
                    assert F.parse_num(ed, m) == pytest.approx(round(n, dec)), (ed, m)
    # Lo tecleado: la coma es decimal y el punto del teclado numérico también.
    assert F.parse_num('0,125', UY) == 0.125
    assert F.parse_num('0.125', UY) == 0.125
    assert F.texto_para_editar('1.5', UY) == '1.5'
    assert F.parse_num('1,234') == 1234       # sin moneda, como siempre


def test_el_arbol_y_la_planilla_en_pantalla(uruguay):
    from PySide6.QtWidgets import QStyleOptionViewItem
    from views.proyecto_view import ProyectoView
    from models.usuario import Usuario
    conn = d.get_db()
    p = conn.execute("SELECT id, metrado, precio_unitario FROM partidas WHERE"
                     " proyecto_id=? AND es_titulo=0 AND metrado>0 LIMIT 1",
                     (PID,)).fetchone()
    conn.execute("DELETE FROM metrados_detalle WHERE partida_id=?", (p['id'],))
    conn.execute("UPDATE partidas SET metrado=12345.67 WHERE id=?", (p['id'],))
    conn.commit()
    conn.close()
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET estado='elaboracion' WHERE id=?", (PID,))
    conn.commit()
    conn.close()
    v = ProyectoView(PID, Usuario(id=1, nombre="t", rol="admin"))
    try:
        v.recargar_partidas()
        tw = v._id_to_item[p['id']]
        assert tw.text(3) == '12.345,67'
        assert tw.text(4) == F.fmt_doc(p['precio_unitario'], 2, moneda=UY)

        dele, idx = v._metrado_delegate, v.tree.indexFromItem(tw, 3)
        ed = dele.createEditor(v.tree.viewport(), QStyleOptionViewItem(), idx)
        dele.setEditorData(ed, idx)
        assert ed.text() == '12345,67'
        for escrito, vale, se_ve in (('2500,5', 2500.5, '2.500,50'),
                                     ('12.5', 12.5, '12,50')):
            ed.setText(escrito)
            dele.setModelData(ed, v.tree.model(), idx)
            assert v._id_to_item[p['id']].text(3) == se_ve
            conn = d.get_db()
            assert conn.execute("SELECT metrado FROM partidas WHERE id=?",
                                (p['id'],)).fetchone()[0] == vale
            conn.close()
    finally:
        v.hide()
        v.deleteLater()
