"""Issue #42: de las herramientas manuales (%MO), imprimir solo el monto.
Apagada por defecto; ningún cálculo cambia."""
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

_fd, _tmpdb = tempfile.mkstemp(suffix='_herr_test.db')
os.close(_fd)
shutil.copy(os.path.join(AQUI, '..', 'presupuestos_seed.db'), _tmpdb)
d.DB_PATH = _tmpdb
d.init_db()

import core.exporter as ex                                        # noqa: E402
import core.pdf_reports as pr                                     # noqa: E402

_c = d.get_db()
PID = _c.execute("SELECT id FROM proyectos ORDER BY id DESC").fetchone()['id']
NOMBRE = 'ZZ HERRAMIENTAS PRUEBA'
_HAY = [r['id'] for r in _c.execute(
    "SELECT p.id FROM partidas p WHERE p.proyecto_id=? AND p.es_titulo=0 AND EXISTS("
    " SELECT 1 FROM acu_items a JOIN recursos r ON r.id=a.recurso_id"
    " WHERE a.partida_id=p.id AND r.tipo='MO' AND r.unidad NOT LIKE '%\\%%' ESCAPE '\\')"
    " AND p.metrado>0 ORDER BY p.item LIMIT 1", (PID,))]
PART = _HAY[0]
_c.execute("DELETE FROM acu_items WHERE partida_id=? AND recurso_id IN"
           " (SELECT id FROM recursos WHERE SUBSTR(unidad,1,1)='%')", (PART,))
for _cod, _desc, _tipo, _und, _cant in (
        ('ZZ1', NOMBRE, 'EQ', '%MO', 7), ('ZZ2', 'ZZ VARIOS PRUEBA', 'MAT', '%MT', 5)):
    _rid = _c.execute("INSERT INTO recursos (codigo, descripcion, tipo, unidad, precio)"
                      " VALUES (?,?,?,?,0)", (_cod, _desc, _tipo, _und)).lastrowid
    # Precio guardado con basura (archivos importados): no es el monto.
    _c.execute("INSERT INTO acu_items (partida_id, recurso_id, cantidad, precio)"
               " VALUES (?,?,?,99)", (PART, _rid, _cant))
d._recalcular_pu(_c, PART)
_c.execute("UPDATE partidas SET especificaciones='' WHERE proyecto_id=?", (PID,))
_c.commit()
MONTO = next(i['parcial'] for i in d.get_acu_items(_c, PART)[0]
             if i['descripcion'] == NOMBRE)
_c.close()
assert MONTO > 0


@pytest.fixture(autouse=True)
def _apagado():
    yield
    _poner('0')


def _poner(v):
    f = pr.get_formato()
    f['rep_herr_solo_monto'] = v
    pr.set_formato(f)


def _fila_html(tipo, nombre):
    h = pr._build_html_for(tipo, PID)[1]
    fila = next(x for x in re.findall(r'<tr.*?</tr>', h, flags=re.S) if nombre in x)
    return [re.sub('<[^>]+>', '', td).strip()
            for td in re.findall(r'<td[^>]*>.*?</td>', fila, flags=re.S)]


def _fila_xlsx(buf, nombre):
    import openpyxl
    for ws in openpyxl.load_workbook(io.BytesIO(buf.getvalue())).worksheets:
        for r in ws.iter_rows():
            vals = [c.value for c in r]
            if nombre in vals:
                return vals
    raise AssertionError(nombre)


def test_apagada_por_defecto_sale_como_siempre():
    assert pr.FORMATO_CLAVES['rep_herr_solo_monto'] == '0'
    assert not pr.herramientas_solo_monto()
    f = _fila_html('acus', NOMBRE)
    assert f[2] == '%MO' and '7.00' in f[4] and f[5] and f[6]
    assert '%MO' in _fila_html('insumos', NOMBRE)
    v = _fila_xlsx(ex.exportar_acus(PID), NOMBRE)
    assert v[3] == '%MO' and v[5] == 7 and v[6] and v[7] == pytest.approx(MONTO)
    # El «completo» sigue como estaba: cantidad × precio guardado.
    v = _fila_xlsx(ex.exportar_reporte_completo(PID), NOMBRE)
    assert v[3] == '%MO' and v[7] == pytest.approx(7 * 99)


@pytest.mark.parametrize('tipo,vacias,monto', [
    ('acus', (2, 3, 4, 5), 6), ('insumos', (2, 3, 4), 5),
    ('cronograma_adquisiciones', (3, 4), 5)])
def test_pdf_solo_el_monto(tipo, vacias, monto):
    antes = _fila_html(tipo, NOMBRE)
    varios = _fila_html(tipo, 'ZZ VARIOS PRUEBA')
    _poner('1')
    f = _fila_html(tipo, NOMBRE)
    assert [f[i] for i in vacias] == [''] * len(vacias)
    assert f[monto] == antes[monto] != ''
    # Un % de materiales no es herramienta: no cambia.
    assert _fila_html(tipo, 'ZZ VARIOS PRUEBA') == varios


def test_excel_solo_el_monto():
    antes = _fila_xlsx(ex.exportar_insumos(PID), NOMBRE)
    _poner('1')
    v = _fila_xlsx(ex.exportar_acus(PID), NOMBRE)
    assert not any(v[3:7]) and v[7] == pytest.approx(MONTO)
    v = _fila_xlsx(ex.exportar_insumos(PID), NOMBRE)
    assert not any(v[3:6]) and v[6] == antes[6] > 0
    v = _fila_xlsx(ex.exportar_reporte_completo(PID), NOMBRE)
    assert not any(v[3:7]) and v[7] == pytest.approx(MONTO)
    assert _fila_xlsx(ex.exportar_acus(PID), 'ZZ VARIOS PRUEBA')[3] == '%MT'


def test_pdf_completo_antiguo(monkeypatch):
    rl = pytest.importorskip('reportlab.platypus')
    vistas = []
    orig = rl.Table.__init__

    def _init(self, data, *a, **k):
        vistas.extend(data)
        orig(self, data, *a, **k)
    monkeypatch.setattr(rl.Table, '__init__', _init)
    _poner('1')
    ex.exportar_pdf(PID)
    f = next(x for x in vistas if NOMBRE in x)
    assert list(f[2:6]) == [''] * 4 and f[6] == f"{MONTO:,.2f}"


def test_el_cronograma_de_adquisiciones_en_pantalla():
    """De esa tabla sale el Excel."""
    from views.cronograma_view import CronogramaView, InsumosWidget
    c = d.get_db()
    proy = dict(c.execute('SELECT * FROM proyectos WHERE id=?', (PID,)).fetchone())
    c.close()
    vista = CronogramaView(PID, proy, lambda: None)
    if hasattr(vista, 'cargar'):
        vista.cargar()
    for v, und in (('0', '%MO'), ('1', '')):
        _poner(v)
        w = InsumosWidget(vista)
        w.cargar()
        fila = next(r for r in range(w.tbl_l.rowCount())
                    if w.tbl_l.item(r, 2) and w.tbl_l.item(r, 2).text() == NOMBRE)
        assert w.tbl_l.item(fila, 3).text() == und
        assert w.tbl_l.item(fila, 5).text()


def test_solo_presentacion_y_que_cuenta_como_herramienta():
    assert d.es_herramienta_pct('EQ', '%mo') and d.es_herramienta_pct('MAT', '%MO')
    assert not d.es_herramienta_pct('EQ', '%mt') and not d.es_herramienta_pct('EQ', 'hm')
    assert not d.es_herramienta_pct('MO', '%mo')      # leyes sociales
    t0 = d.calcular_totales(PID)[1]
    _poner('1')
    assert d.calcular_totales(PID)[1] == t0


def test_el_dialogo_la_guarda_y_la_restaura():
    from views.formato_reporte_dialog import FormatoReporteDialog
    dlg = FormatoReporteDialog()
    assert not dlg.chk_herr_monto.isChecked()
    dlg.chk_herr_monto.setChecked(True)
    dlg._save_and_accept()
    assert pr.herramientas_solo_monto()
    dlg2 = FormatoReporteDialog()
    assert dlg2.chk_herr_monto.isChecked()
    dlg2._reset_defaults()
    assert not dlg2.chk_herr_monto.isChecked()
