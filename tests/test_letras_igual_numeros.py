"""El total en cifras y el «Son: …» salen del mismo número, en todos lados.

Un usuario con una partida de 3000, 10 % + 5 % e IVA 22 % vio 3.000 en el pie
y 4.209 en letras: el proyecto nunca había abierto su pestaña «Pie» y el pie
impreso ignoraba los porcentajes que el total sí aplicaba.
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

from PySide6.QtWidgets import QApplication                        # noqa: E402

_app = QApplication.instance() or QApplication([])

import core.database as d                                         # noqa: E402

_fd, _tmpdb = tempfile.mkstemp(suffix='_letras_test.db')
os.close(_fd)
shutil.copy(os.path.join(AQUI, '..', 'presupuestos_seed.db'), _tmpdb)
d.DB_PATH = _tmpdb
d.init_db()

import core.exporter as ex                                        # noqa: E402
import core.paises as paises                                      # noqa: E402
import core.pdf_reports as pr                                     # noqa: E402
from core.pie import lineas_por_defecto                           # noqa: E402
from core.word_reports import generar_word                        # noqa: E402
from utils.formatting import fmt_doc, monto_en_letras             # noqa: E402


def _proyecto(pie, subs=1, pais='UY', gf=10.0, util=5.0, imp=22.0, precio=3000.0):
    paises.aplicar_pais(pais)
    conn = d.get_db()
    pid = conn.execute(
        "INSERT INTO proyectos (nombre, moneda, gf_pct, utilidad_pct, igv_pct)"
        " VALUES ('p','Pesos Uruguayos',?,?,?)", (gf, util, imp)).lastrowid
    for k in range(subs):
        sub = None
        if k:
            sub = conn.execute("INSERT INTO sub_presupuestos (proyecto_id,nombre,"
                               "orden) VALUES (?,?,?)", (pid, f's{k}', k)).lastrowid
        conn.execute("INSERT INTO partidas (proyecto_id,item,descripcion,es_titulo,"
                     "nivel,sub_presupuesto_id) VALUES (?,'01','T',1,1,?)", (pid, sub))
        conn.execute(
            "INSERT INTO partidas (proyecto_id,item,descripcion,unidad,metrado,"
            "precio_unitario,nivel,es_titulo,sub_presupuesto_id)"
            " VALUES (?,'01.01','Subcontrato','glb',1,?,2,0,?)", (pid, precio, sub))
    if pie != 'vacio':
        proy = conn.execute("SELECT * FROM proyectos WHERE id=?", (pid,)).fetchone()
        lineas = lineas_por_defecto(proy)
        if pie == 'apagado':
            lineas = [l[:3] + (0,) + l[4:] for l in lineas]
        elif pie == 'solo_impuesto':
            lineas = [l[:3] + (1 if l[0] == 'IGV' else 0,) + l[4:] for l in lineas]
        conn.executemany(
            "INSERT INTO pie_rubros (proyecto_id,codigo,nombre,pct,activo,orden,"
            "tipo,mostrar_pct) VALUES (?,?,?,?,?,?,?,?)",
            [(pid,) + tuple(l) for l in lineas])
    conn.commit()
    conn.close()
    return pid


@pytest.fixture(autouse=True)
def _pais_peru():
    yield
    paises.aplicar_pais('PE')


def test_el_caso_del_usuario():
    pid = _proyecto('vacio')
    assert d.calcular_totales(pid)[1]['total'] == 4209.0
    filas = pr._build_pie_rows(pid, 3000.0)
    assert [f[0] for f in filas] == [
        'Costo Directo', 'Gastos Generales (10%)', 'Utilidad (5%)', 'Sub Total',
        'IVA (22%)', 'PRESUPUESTO TOTAL']
    assert filas[-1][1] == 4209.0
    # «Presupuesto para Cliente»: disuelve GG y utilidad, deja el IVA.
    factor, pie = pr._todo_costo_factor_pie(pid, 3000.0)
    assert factor == pytest.approx(1.15)
    assert pie[-1][1] == 4209.0


@pytest.mark.parametrize('subs', [1, 3])
@pytest.mark.parametrize('pais', ['UY', 'CO', 'PE'])
@pytest.mark.parametrize('pie', ['vacio', 'defecto', 'apagado', 'solo_impuesto'])
def test_letras_y_cifras_coinciden_en_todos_los_formatos(pie, pais, subs, tmp_path):
    for precio in (3000.0, 1234.567):
        pid = _proyecto(pie, subs=subs, pais=pais, precio=precio)
        cd = d.calcular_totales(pid)[1]['cd']
        total = d.calcular_totales(pid)[1]['total']
        letras = monto_en_letras(total, 'Pesos Uruguayos')
        cifras = re.compile(re.escape(fmt_doc(total, 2, moneda='Pesos Uruguayos')))
        if pie in ('vacio', 'defecto'):
            assert total > cd

        assert pr._build_pie_rows(pid, cd)[-1][1] == total
        for tipo in ('presupuesto', 'resumen', 'presupuesto_cerrado'):
            h = pr._build_html_for(tipo, pid)[1]
            assert letras in h, tipo
            # KPI del resumen y/o fila PRESUPUESTO TOTAL del pie
            assert len(cifras.findall(h)) >= (2 if tipo == 'resumen' else 1), tipo

        ruta = tmp_path / 'r.docx'
        generar_word('resumen', pid, str(ruta))
        xml = zipfile.ZipFile(ruta).read('word/document.xml').decode()
        assert letras in xml and len(cifras.findall(xml)) >= 2

        import openpyxl
        for f in (ex.exportar_presupuesto, ex.exportar_reporte_completo):
            wb = openpyxl.load_workbook(io.BytesIO(f(pid).getvalue()))
            vals = [c.value for ws in wb for r in ws.iter_rows() for c in r]
            assert any(isinstance(v, str) and letras in v for v in vals), f
        wb = openpyxl.load_workbook(io.BytesIO(ex.exportar_presupuesto(pid).getvalue()))
        vals = [c.value for ws in wb for r in ws.iter_rows() for c in r]
        assert any(isinstance(v, (int, float)) and abs(v - total) < 1e-6 for v in vals)


@pytest.mark.parametrize('pie', ['vacio', 'defecto', 'apagado'])
def test_la_pantalla_muestra_el_mismo_total(pie):
    from views.proyecto_view import ProyectoView

    class V:
        pass
    v = V()
    v.pid = _proyecto(pie)
    v._total_proyecto = lambda all_subs=False: 3000.0
    filas, total = ProyectoView._filas_resumen(v, all_subs=True)
    assert total == filas[-1][1] == d.calcular_totales(v.pid)[1]['total']
