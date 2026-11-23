# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Temas de reportes: esquema, aplicación, elección, editor y exportación.

Corre con:  QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_temas.py -q
Usa una COPIA temporal del seed y una carpeta de complementos temporal.
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication                          # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])
RAIZ = Path(__file__).resolve().parent.parent
_fd, _tmpdb = tempfile.mkstemp(suffix='_temas_test.db')
os.close(_fd)
shutil.copy(RAIZ / 'presupuestos_seed.db', _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

from core import paises                                             # noqa: E402
from core import pdf_reports as pr, temas                            # noqa: E402
from core.complementos import (cargador, esquema,                   # noqa: E402
                               gestor, paquete)
from utils import i18n                                              # noqa: E402

BASE = {'esquema': 1, 'id': 'de-prueba', 'nombre': 'De prueba', 'version': '1.0',
        'autor': 'Nadie', 'licencia': 'GPL-3.0-or-later'}


def man(**k):
    return {**BASE, **k}


@pytest.fixture(autouse=True)
def limpio(tmp_path, monkeypatch):
    monkeypatch.setattr(gestor, 'raiz', lambda: tmp_path / 'compl')
    monkeypatch.delenv(gestor.VARIABLE_SEGURO, raising=False)
    conn = d.get_db()
    conn.execute("DELETE FROM configuracion WHERE clave IN ('pais','pais_respaldo',"
                 "'etiqueta_id_tributaria','impuesto_nombre','impuesto_pct',"
                 "'monedas_propias','rep_tema')")
    conn.execute("UPDATE proyectos SET tema_reporte='' WHERE tema_reporte<>''")
    conn.execute("UPDATE configuracion SET valor='Soles' WHERE clave='moneda_defecto'")
    conn.commit()
    conn.close()
    cfg.olvidar_monedas_propias()
    cargador.fallos[:] = []
    for c in cargador.cargados():
        cargador.descargar(c.id)
    gestor.invalidar()
    yield
    for c in cargador.cargados():
        cargador.descargar(c.id)
    cfg.olvidar_monedas_propias()
    i18n.set_idioma('es')
    monkeypatch.undo()
    gestor.invalidar()


def carpeta(tmp_path, m, archivos=None, nombre='fuente'):
    c = tmp_path / nombre
    c.mkdir(exist_ok=True)
    (c / 'complemento.json').write_text(json.dumps(m), encoding='utf-8')
    for r, t in (archivos or {}).items():
        (c / r).parent.mkdir(parents=True, exist_ok=True)
        (c / r).write_text(t, encoding='utf-8')
    return c


def poner(tmp_path, m, archivos=None):
    """Instala y activa."""
    i = gestor.instalar(carpeta(tmp_path, m, archivos))
    return gestor.activar(i.id, i.paquete.huella)

PIDS = [r[0] for r in (lambda c: (c.execute("""SELECT p.proyecto_id FROM partidas p
    JOIN acu_items a ON a.partida_id=p.id GROUP BY p.proyecto_id
    ORDER BY COUNT(*) LIMIT 2""").fetchall(), c.close())[0])(d.get_db())]
PID = PIDS[0]
PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + (8).to_bytes(4, 'big') * 2
       + b'\x08\x02\x00\x00\x00' + b'\x00' * 8)
MINIMO = {'clave': 't', 'nombre': 'T'}


def tema(**k):
    return man(temas=[{**MINIMO, **k}])


def poner_tema(tmp_path, archivos=None, **k):
    poner(tmp_path, tema(**k))
    temas.elegir_global('de-prueba/t')


def _hash(html):
    import hashlib
    return hashlib.sha256(re.sub(r'\d\d/\d\d/\d{4}', 'F', html).encode()).hexdigest()[:16]


def _pixeles(tipo='presupuesto', pid=PID, cover=True):
    import pypdfium2 as pdfium
    fd, f = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    pr.generar_pdf_archivo(tipo, pid, f, with_cover=cover)
    doc = pdfium.PdfDocument(f)
    out = [p.render().to_numpy().tobytes() for p in doc]
    doc.close()
    os.unlink(f)
    return out


def _texto(tipo='presupuesto', pid=PID):
    import pdfplumber
    fd, f = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    pr.generar_pdf_archivo(tipo, pid, f, with_cover=False)
    with pdfplumber.open(f) as p:
        t = "\n".join(x.extract_text() or '' for x in p.pages)
    os.unlink(f)
    return t


# ── Sin tema: idéntico ───────────────────────────────────────────────────────

def test_sin_tema_el_html_es_el_de_antes():
    """Foto tomada ANTES de tocar pdf_reports (v3.2, 9fe2fbd). Si un cambio
    posterior y querido de un reporte la rompe, se vuelve a tomar."""
    foto = json.loads((RAIZ / 'tests/fixtures/reportes_antes_de_temas.json')
                      .read_text(encoding='utf-8'))
    assert _hash(pr._base_css()) == foto.pop('css')
    ahora = {k: _hash(pr._build_html_for(k.split(':')[1], PIDS[int(k[0])])[1])
             for k in foto}
    assert ahora == foto


def test_un_tema_vacio_no_cambia_ni_un_pixel(tmp_path):
    antes = {t: _pixeles(t) for t in ('presupuesto', 'insumos', 'acus')}
    propio = pr.formato_propio()
    poner_tema(tmp_path)
    assert temas.activo(PID) is not None
    f = pr.get_formato(PID)
    assert f.pop('_tema') and f == propio
    assert {t: _pixeles(t) for t in antes} == antes


# ── Esquema ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('cambio', [
    {'colores': {'marca': 'red'}}, {'colores': {'marca': '#fff; } body {'}},
    {'colores': {'otro': '#000000'}}, {'colores': {'titulos': ['#000000'] * 10}},
    {'tipografia': {'familia': "x'; } td { color:red"}},
    {'tipografia': {'familia': 'A<b>'}}, {'tipografia': {'escala': 101}},
    {'margenes': {'superior': 2}}, {'margenes': {'izquierdo': 90}},
    {'encabezado': {'titulo': '{otro}'}}, {'encabezado': {'titulo': '{proyecto.x}'}},
    {'pie': {'centro': '{fecha!r}'}}, {'pie': {'centro': '{'}},
    {'logo': {'archivo': '../x.png'}}, {'logo': {'archivo': '/etc/x.png'}},
    {'logo': {'archivo': 'x.svg'}}, {'logo': {'archivo': 'https://x/y.png'}},
    {'bordes': 'dashed'}, {'css': 'x'}, {'html': 'x'},
    {'nombres': {'inventado': 'x'}},
    {'columnas': {'presupuesto': [{'campo': 'precio'}]}},
    {'columnas': {'presupuesto': [{'campo': 'unidad'}, {'campo': 'descripcion'}]}},
    {'columnas': {'presupuesto': [{'campo': 'descripcion'}] * 2}},
    {'columnas': {'insumos': [{'campo': 'parcial'}, {'campo': 'descripcion'}]}},
    {'columnas': {'insumos': [{'campo': 'descripcion', 'ancho': 5000}]}},
    {'columnas': {'acus': []}}, {'firmas': [{}] * 5}, {'firmas': [{'x': 'y'}]}])
def test_esquema_de_tema_rechaza(cambio):
    with pytest.raises(esquema.ErrorEsquema):
        esquema.validar(tema(**cambio))


@pytest.mark.parametrize('b', [
    b'', b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'GIF89a' + b'0' * 50,
    PNG + b'0' * esquema.MAX_IMAGEN,
    PNG[:16] + (9000).to_bytes(4, 'big') + PNG[20:], b'\xff\xd8\xff\xe0\x00\x01'])
def test_logo_malo_se_rechaza(tmp_path, b):
    c = carpeta(tmp_path, tema(logo={'archivo': 'logo.png'}))
    (c / 'logo.png').write_bytes(b)
    with pytest.raises(paquete.ErrorPaquete, match='logo'):
        paquete.leer_carpeta(c)


def test_logo_que_falta_se_rechaza(tmp_path):
    with pytest.raises(paquete.ErrorPaquete, match='falta'):
        paquete.leer_carpeta(carpeta(tmp_path, tema(logo={'archivo': 'logo.png'})))


# ── Aplicar ──────────────────────────────────────────────────────────────────

def test_colores_margenes_y_bordes(tmp_path):
    poner_tema(tmp_path, colores={'acento': '#112233', 'suave': '#445566',
                                  'titulos': ['#AA0000'], 'cebra': '#FAFA00',
                                  'borde': '#00AA00'},
               margenes={'izquierdo': 30}, bordes='gruesos')
    f = pr.get_formato(PID)
    assert pr.colores_titulos(f)[1] == '#AA0000'
    assert pr.colores_titulos(f)[2] == pr.colores_titulos(pr.formato_propio())[2]
    assert pr.margenes_mm(f) == {'sup': 15, 'inf': 18, 'izq': 30, 'der': 15}
    css = pr._base_css(f)
    assert '#112233' in css and '2px solid #00AA00' in css
    html = pr._build_html_for('presupuesto', PID)[1]
    assert 'background:#445566' in html and 'background:#FAFA00' in html


def test_marcadores_en_encabezado_y_pie(tmp_path):
    poner_tema(tmp_path, encabezado={'titulo': 'DOC {titulo}', 'derecha': 'Sr. {cliente}'},
               pie={'izquierda': 'A{pagina}B{paginas}', 'centro': '', 'derecha': 'Z'})
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET cliente='{fecha} <b>ACME</b>' WHERE id=?", (PID,))
    conn.commit()
    conn.close()
    t = _texto()
    assert 'DOC Presupuesto' in t and 'Sr. {fecha} <b>ACME</b>' in t     # no se expande dos veces
    assert re.search(r'A1B\d', t) and 'Página' not in t
    f = pr.get_formato(PID)
    # Lo que leen Excel, Word y el Gantt: sin marcadores a la vista.
    assert f['rep_pie_izquierdo'] == '' and f['rep_pie_derecho'] == 'Z'
    assert f['rep_pie_cen_oculto'] == '1'


def test_tipografia_que_falta_usa_la_sustituta(tmp_path):
    from PySide6.QtGui import QFontDatabase
    hay = QFontDatabase.families()[0]
    assert temas.familia({'tipografia': {'familia': 'No Existe', 'sustituta': hay}}) == hay
    assert temas.familia({'tipografia': {'familia': 'No Existe'}}) == 'Inter'
    poner_tema(tmp_path, tipografia={'familia': 'No Existe', 'sustituta': hay})
    from views.temas_ui import texto_aviso
    assert 'No Existe' in texto_aviso(PID) and hay in texto_aviso(PID)
    assert hay in pr._base_css()


def test_columnas_del_presupuesto(tmp_path):
    poner_tema(tmp_path, columnas={'presupuesto': [
        {'campo': 'descripcion', 'titulo': 'Concepto <b>'}, {'campo': 'cantidad'},
        {'campo': 'parcial', 'titulo': 'Importe', 'ancho': 60},
        {'campo': 'unidad'}]}, firmas=[{'nombre': 'Ana <i>', 'cargo': 'Jefa'}],
        nombres={'presupuesto': 'Oferta'})
    titulo, html, _p = pr._build_html_for('presupuesto', PID)
    assert titulo == 'Oferta'
    cab = html[html.index('<thead>'):html.index('</thead>')]
    assert 'Concepto &lt;b&gt;' in cab and 'Precio' not in cab
    assert cab.index('Cantidad') < cab.index('Importe') < cab.index('>Und<')
    assert 'width:60pt' in cab and 'Ana &lt;i&gt;' in html
    for fila in re.findall(r'<tr class="titulo\d">.*?</tr>(?=<tr|</tbody)', html):
        celdas = re.sub(r'<table border.*?</table>', '', fila)
        n = sum(int(x) if x else 1 for x in re.findall(r'<td(?: colspan="(\d+)")?[ >]', celdas))
        assert n >= 4
    assert 'Concepto' in _texto()


def test_columnas_sin_parcial_y_de_insumos(tmp_path):
    poner_tema(tmp_path, columnas={
        'presupuesto': [{'campo': 'descripcion'}, {'campo': 'unidad'}],
        'insumos': [{'campo': 'descripcion'}, {'campo': 'parcial'}, {'campo': 'unidad'}]})
    html = pr._build_html_for('presupuesto', PID)[1]
    cab = html[html.index('<thead>'):html.index('</thead>')]
    assert 'Parcial' not in cab and 'Und' in cab
    html = pr._build_html_for('insumos', PID)[1]
    cab = html[html.index('<thead>'):html.index('</thead>')]
    assert cab.index('Parcial') < cab.index('Und') and 'Código' not in cab
    assert 'colspan="3"' in html
    _texto('insumos')


def test_por_proyecto_y_de_fabrica(tmp_path):
    poner_tema(tmp_path, colores={'acento': '#112233'})
    otro = PIDS[1]
    temas.elegir_global('')
    temas.elegir_proyecto(PID, 'de-prueba/t')
    assert '#112233' in pr._build_html_for('resumen', PID)[1] or \
        '#112233' in pr._base_css(pr.get_formato(PID))
    assert temas.activo(otro) is None
    temas.elegir_global('de-prueba/t')
    temas.elegir_proyecto(otro, temas.DE_FABRICA)
    assert temas.activo(otro) is None and temas.activo(PID) is not None


def test_tema_que_falta_sale_el_de_fabrica_con_aviso(tmp_path):
    antes = _pixeles()
    poner_tema(tmp_path, colores={'acento': '#112233'}, margenes={'izquierdo': 35})
    assert _pixeles() != antes
    gestor.desinstalar('de-prueba')
    from views.temas_ui import texto_aviso
    assert 'de-prueba/t' in texto_aviso(PID)
    assert _pixeles() == antes


def test_tema_que_revienta_sale_el_de_fabrica(tmp_path, monkeypatch, capsys):
    poner_tema(tmp_path)
    monkeypatch.setattr(temas, 'aplicar', lambda *a: 1 / 0)
    assert pr.get_formato(PID) == pr.formato_propio()


def test_configurar_formato_no_guarda_el_tema(tmp_path):
    poner_tema(tmp_path, colores={'marca': '#123456'}, margenes={'superior': 33})
    from views.formato_reporte_dialog import FormatoReporteDialog
    dlg = FormatoReporteDialog()
    assert dlg._formato['rep_color_marca'] != '#123456'
    dlg._save_and_accept()
    gestor.desinstalar('de-prueba')
    f = pr.get_formato(PID)
    assert f['rep_color_marca'] != '#123456' and f['rep_margen_sup'] == '15'


def test_excel_y_word_toman_lo_que_entienden(tmp_path):
    poner_tema(tmp_path, colores={'titulos': ['#AB12CD']}, pie={'mostrar': False})
    from openpyxl import load_workbook
    from core import exporter
    buf = exporter.exportar_presupuesto(PID)
    buf = buf if hasattr(buf, 'read') else open(buf, 'rb')
    ws = load_workbook(buf).active
    colores = {c.font.color.rgb for f in ws.iter_rows() for c in f
               if c.font and c.font.color and isinstance(c.font.color.rgb, str)}
    assert any(x.endswith('AB12CD') for x in colores)
    assert pr.pie_oculto(pr.get_formato(PID))


def test_los_bordes_se_ven(tmp_path):
    antes = _pixeles()
    poner_tema(tmp_path, bordes='ninguno')
    assert _pixeles() == antes
    gestor.desinstalar('de-prueba')
    poner_tema(tmp_path, bordes='normales')
    assert _pixeles() != antes


# ── Guardado con el proyecto ─────────────────────────────────────────────────

def test_exportar_db_y_duplicar_conservan_el_tema(tmp_path):
    temas.elegir_proyecto(PID, 'de-prueba/t')
    from core import exporter
    from core.ingepresupuestos_db_importer import importar_proyecto_db_directo
    destino = str(tmp_path / 'p.db')
    exporter.exportar_proyecto_db(PID, destino)
    assert temas.del_proyecto(importar_proyecto_db_directo(destino, PID)) == 'de-prueba/t'
    from views import dashboard_view as dv
    conn = d.get_db()
    nuevo = dv._clonar_proyecto(conn, PID, set())
    conn.commit()
    conn.close()
    assert temas.del_proyecto(nuevo) == 'de-prueba/t'


# ── Crear, editar, exportar ──────────────────────────────────────────────────

def test_crear_desde_el_actual_sale_igual_y_se_exporta(tmp_path):
    antes = _pixeles(cover=False)
    datos, logo = temas.desde_actual(PID)
    ref = temas.guardar('Mío ñandú', datos, logo)
    assert ref == 'mi-tema-mio-nandu/tema' and temas.disponibles()[ref].propio
    temas.elegir_proyecto(PID, ref)
    assert _pixeles(cover=False) == antes
    z = temas.exportar(ref, tmp_path / 't.zip')
    p = paquete.leer_zip(z)
    assert p.manifiesto['temas'][0]['nombre'] == 'Mío ñandú' and not p.con_codigo
    datos['firmas'] = [{'nombre': 'X', 'cargo': 'Y'}]
    assert temas.guardar('Mío 2', datos, PNG, ref) == ref
    t = temas.disponibles()[ref]
    assert t.nombre == 'Mío 2' and t.logo == PNG and t.datos['firmas']
    assert temas.guardar('Mío ñandú', datos, None) == 'mi-tema-mio-nandu-2/tema'


def test_no_se_edita_un_tema_ajeno(tmp_path):
    poner_tema(tmp_path)
    with pytest.raises(ValueError):
        temas.guardar('x', {}, None, 'de-prueba/t')


def test_editor(tmp_path, monkeypatch):
    from views import temas_ui as ui
    datos, logo = temas.desde_actual(PID)
    datos['columnas'] = {'presupuesto': [{'campo': 'descripcion', 'ancho': 200.0},
                                         {'campo': 'parcial', 'titulo': 'Imp'}]}
    datos['encabezado']['titulo'] = '{titulo} X'
    dlg = ui.TemaDialog('T', datos, PNG, PID)
    r = temas.revisar(dlg.nombre(), dlg.datos(), dlg.logo)
    # Abrir y guardar sin tocar nada no cambia nada.
    for k in ('colores', 'margenes', 'encabezado', 'pie', 'columnas'):
        assert r.datos[k] == datos[k], k
    dlg.previsualizar()
    assert not dlg.lbl.pixmap().isNull()
    dichos = []
    monkeypatch.setattr(ui, '_aviso', lambda p, t: dichos.append(t))
    dlg._textos['pie', 'centro'][0].setChecked(True)
    dlg._textos['pie', 'centro'][1].setText('{malo}')
    dlg._aceptar()
    assert dichos and dlg.result() == 0
    dlg._poner_logo(__file__)
    assert len(dichos) == 2 and dlg.logo == PNG


def test_menu_tema(tmp_path):
    from PySide6.QtWidgets import QMenu, QWidget
    from views import temas_ui as ui
    poner(tmp_path, tema(colores={'acento': '#112233'}))
    padre, m, cambios = QWidget(), QMenu(), []
    ui.llenar_menu(m, padre, PID, lambda: cambios.append(1))
    sub = m.findChildren(QMenu)
    a = next(a for a in sub[1].actions() if a.text() == 'T')
    a.trigger()
    assert cambios and temas.del_proyecto(PID) == 'de-prueba/t'
    ui.llenar_menu(m, padre, PID, lambda: None, invitado=True)
    assert not m.findChildren(QMenu)[-1].isEnabled()
    a = next(a for a in m.actions() if a.text().startswith('Editar'))
    assert not a.isEnabled()                       # viene en un complemento
    assert ui.exportar(padre, temas.activo(PID), tmp_path / 'e.zip').exists()


def test_centro_de_reportes_tiene_el_boton_y_avisa(tmp_path):
    from views.reportes_view import ReportesView
    temas.elegir_proyecto(PID, 'no-esta/t')
    v = ReportesView(PID, 'x', autoselect=False)
    assert not v._lbl_tema.isHidden() and 'no-esta/t' in v._lbl_tema.text()
    v._llenar_menu_tema()
    assert v._btn_tema.menu().actions()


@pytest.mark.parametrize('nombre', ['tema-sobrio', 'tema-propuesta'])
def test_los_de_ejemplo(nombre, tmp_path):
    antes = _pixeles(cover=False)
    i = gestor.instalar(RAIZ / 'complementos' / nombre)
    gestor.activar(i.id, i.paquete.huella)
    ref = next(iter(temas.disponibles()))
    temas.elegir_proyecto(PID, ref)
    for t in ('presupuesto', 'insumos', 'acus', 'resumen', 'metrados'):
        assert _pixeles(t)
    assert _pixeles(cover=False) != antes
    if nombre == 'tema-propuesta':
        t = _texto()
        assert 'Propuesta económica' in t and 'Importe' in t and 'Aceptado por' in t
