"""Issues #54 y #41: columnas MO/MAT/EQ/SC del PU y especificación bajo cada
partida en el reporte de presupuesto. Apagadas por defecto."""
import io
import os
import re
import shutil
import sys
import tempfile

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, '..'))

from PySide6.QtWidgets import QApplication                        # noqa: E402

_app = QApplication.instance() or QApplication([])

import core.database as d                                         # noqa: E402

_fd, _tmpdb = tempfile.mkstemp(suffix='_desglose_test.db')
os.close(_fd)
shutil.copy(os.path.join(AQUI, '..', 'presupuestos_seed.db'), _tmpdb)
d.DB_PATH = _tmpdb
d.init_db()

import core.exporter as ex                                        # noqa: E402
import core.pdf_reports as pr                                     # noqa: E402

_c = d.get_db()
PID = _c.execute("SELECT id FROM proyectos ORDER BY id DESC").fetchone()['id']
PART = _c.execute("SELECT id FROM partidas WHERE proyecto_id=? AND es_titulo=0"
                  " ORDER BY item LIMIT 1", (PID,)).fetchone()['id']
_c.execute("UPDATE partidas SET especificaciones='' WHERE proyecto_id=?", (PID,))
_c.execute("UPDATE partidas SET especificaciones=? WHERE id=?",
           ('<p>Primer <b>párrafo</b> &amp; más</p><ul><li>viñeta</li></ul>'
            '<p><img src="data:x">=SUMA(A1)</p>', PART))
_c.commit()
_c.close()


@pytest.fixture(autouse=True)
def _apagado():
    yield
    _opciones('', '0')


def _opciones(desglose, spec):
    f = pr.get_formato()
    f['rep_ppto_desglose'], f['rep_ppto_especificacion'] = desglose, spec
    pr.set_formato(f)


def _celdas(pid=PID):
    import openpyxl
    return openpyxl.load_workbook(io.BytesIO(ex.exportar_presupuesto(pid).getvalue())).active


def test_apagadas_por_defecto():
    assert pr.FORMATO_CLAVES['rep_ppto_desglose'] == ''
    assert pr.FORMATO_CLAVES['rep_ppto_especificacion'] == '0'
    h = pr._build_html_for('presupuesto', PID)[1]
    assert 'M. obra' not in h and 'viñeta' not in h
    assert 'colspan="5"' in h and 'colspan="6"' not in h
    ws = _celdas()
    assert max(c.column for r in ws.iter_rows() for c in r if c.value is not None) <= 7


def test_las_columnas_suman_el_precio():
    items, _t = d.calcular_totales(PID)
    val = pr.desglose_pu_partidas(items)
    assert len(val) > 10
    for e in items:
        v = val.get(e['partida']['id'])
        if v:
            assert sum(v.values()) == pytest.approx(e['partida']['precio_unitario'])


def test_pdf_y_excel_llevan_las_columnas_pedidas():
    _opciones('MO,SC,MAT', '0')
    h = pr._build_html_for('presupuesto', PID)[1]
    ths = re.findall(r'<th[^>]*>([^<]+)</th>', h)
    assert [t for t in ths if t in ('M. obra', 'Material', 'Equipo', 'Subc.')] == [
        'M. obra', 'Material', 'Subc.']
    # Todas las filas ocupan las mismas columnas.
    tabla = h[h.index('<tbody>'):h.index('</tbody>')]
    sin_anidadas, n_sub = tabla, 1
    while n_sub:
        sin_anidadas, n_sub = re.subn(r'<table(?:(?!<table).)*?</table>', '',
                                      sin_anidadas, flags=re.S)
    for fila in re.findall(r'<tr.*?</tr>', sin_anidadas, flags=re.S):
        n = sum(int((re.search(r'colspan="(\d+)"', td) or [0, 1])[1])
                for td in re.findall(r'<td[^>]*>', fila))
        assert n == 8, fila[:200]
    ws = _celdas()
    cab = next(r for r in ws.iter_rows() if r[0].value == 'Ítem')
    assert [c.value for c in cab if c.value] == [
        'Ítem', 'Descripción', 'Und', 'Cantidad', 'M. obra', 'Material',
        'Subc.', 'Precio', 'Parcial']
    # El presupuesto del cliente no abre los costos.
    assert 'M. obra' not in pr._build_html_for('presupuesto_cerrado', PID)[1]


def test_especificacion_debajo_de_su_partida(tmp_path):
    _opciones('', '1')
    h = pr._build_html_for('presupuesto', PID)[1]
    assert h.count('Primer párrafo &amp; más') == 1
    assert '•  viñeta' in h and '<img' not in h
    ws = _celdas()
    vals = [[c.value for c in r] for r in ws.iter_rows()]
    fila = next(i for i, r in enumerate(vals) if 'Primer párrafo & más' in r)
    assert '•  viñeta' in vals[fila + 1]
    # Un texto que empieza por «=» no es una fórmula.
    assert ws.cell(fila + 3, 2).value == '=SUMA(A1)'
    assert ws.cell(fila + 3, 2).data_type == 's'
    import pypdf
    ruta = str(tmp_path / 'p.pdf')
    _opciones('MO,MAT,EQ,SC', '1')
    pr.generar_pdf_archivo('presupuesto', PID, ruta)
    texto = ''.join(p.extract_text() for p in pypdf.PdfReader(ruta).pages).replace('\t', ' ')
    assert 'viñeta' in texto and 'M. obra' in texto


def test_el_dialogo_guarda_las_casillas():
    from views.formato_reporte_dialog import FormatoReporteDialog
    dlg = FormatoReporteDialog()
    assert not any(c.isChecked() for c in dlg.chk_desglose.values())
    dlg.chk_desglose['MO'].setChecked(True)
    dlg.chk_desglose['SC'].setChecked(True)
    dlg.chk_ppto_spec.setChecked(True)
    dlg._save_and_accept()
    assert pr.desglose_ppto() == ['MO', 'SC'] and pr.especificacion_en_ppto()
    dlg2 = FormatoReporteDialog()
    assert dlg2.chk_desglose['SC'].isChecked() and not dlg2.chk_desglose['EQ'].isChecked()
    dlg.hide()
    dlg2.hide()
