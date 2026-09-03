# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Tamaño del texto del cuerpo del PDF (`rep_escala_texto`).

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_pdf_escala_texto.py

Pedido de David Ramos (2 sep 2026): que el reporte quepa en menos páginas.
Se resolvió con UN factor al dibujar (`_PdfRenderer._aplicar_escala`) y
pasos fijos `ESCALAS_TEXTO = (100, 90, 80)`. Lo que estos tests fijan:

* la clave solo admite esos pasos y lo raro cae al 100;
* reducir da menos páginas con exactamente las mismas palabras;
* el cuerpo nunca pisa los márgenes laterales, ni al 100 ni reducido
  (rasteriza las páginas y exige blanco en las franjas de margen).

La igualdad byte a byte del 100 % con la versión anterior se verificó a mano
el 3 sep 2026 sobre los 13 tipos; no se puede fijar aquí sin un baseline.
Usa una copia temporal del seed, nunca la BD activa.
"""
import html
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QSize
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

import core.config as cfg
import core.database as d

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_escala_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

import core.pdf_reports as pr   # noqa: E402  (después de fijar la BD)

_conn = d.get_db()
# Un proyecto mediano del seed: bastante para varias páginas, no tanto como
# para que el test tarde.
PID = _conn.execute(
    "SELECT proyecto_id FROM partidas GROUP BY proyecto_id "
    "HAVING COUNT(*) BETWEEN 100 AND 400 ORDER BY COUNT(*) DESC LIMIT 1"
).fetchone()[0]
_conn.close()

_tmpfiles = []


# ── Andamio ──────────────────────────────────────────────────────────────────

def _pdf(tipo: str, escala, *, with_cover=False) -> QPdfDocument:
    d.set_config('rep_escala_texto', str(escala))
    fd, path = tempfile.mkstemp(suffix=f'_{tipo}_{escala}.pdf')
    os.close(fd)
    _tmpfiles.append(path)
    pr.generar_pdf_archivo(tipo, PID, path, with_cover=with_cover)
    doc = QPdfDocument()
    doc.load(path)
    assert doc.pageCount() > 0, f"{tipo} @ {escala}: PDF vacío"
    return doc


def _tokens(texto: str) -> set:
    """Runs alfanuméricos con al menos una letra. Se parte en todo lo que no
    sea letra o dígito porque el corte de línea cae en espacios, guiones y
    barras: «PLASTIFICANTE-CARAVISTA» sale como dos tokens en un ancho y como
    uno en otro. Los números sueltos quedan fuera: el «Página X de N» del pie
    cambia con la paginación."""
    return {w for w in re.findall(r'\w+', texto) if re.search(r'[^\d_]', w)}


def _palabras_pdf(doc: QPdfDocument) -> set:
    out = set()
    for i in range(doc.pageCount()):
        out |= _tokens(doc.getAllText(i).text())
    return out


def _palabras_html(tipo: str) -> set:
    """Las palabras del cuerpo del reporte según su HTML: lo que el PDF tiene
    que contener sí o sí. Se compara «HTML ⊆ PDF» y no «PDF == PDF» porque la
    extracción de texto de un PDF trae basura propia —cabeceras de tabla
    repetidas que se solapan en un corte de página salen como
    «DDeessccripción»— y esa basura cambia con la paginación."""
    _titulo, body, _proy = pr._build_html_for(tipo, PID, None)
    body = re.sub(r'<style.*?</style>', ' ', body, flags=re.S)
    return _tokens(html.unescape(re.sub(r'<[^>]+>', ' ', body)))


def _franja_blanca(img, x0, x1, y0, y1) -> bool:
    """Sin tinta en el rectángulo. QPdfDocument.render devuelve ARGB con el
    fondo TRANSPARENTE (alfa 0, rgb 0): lo vacío no es blanco, es nada."""
    for y in range(int(y0), int(y1), 2):
        for x in range(int(x0), int(x1), 2):
            c = img.pixelColor(x, y)
            if c.alpha() > 0 and min(c.red(), c.green(), c.blue()) < 250:
                return False
    return True


# ── Tests ────────────────────────────────────────────────────────────────────

def test_texto_escala_solo_admite_los_pasos_fijos():
    assert pr.ESCALAS_TEXTO == (100, 90, 80)
    for valor, esperado in (('100', 1.0), ('90', 0.9), ('80', 0.8),
                            ('', 1.0), (None, 1.0), ('abc', 1.0),
                            ('120', 1.0),      # no hay pasos por encima de 100
                            ('50', 0.8),       # ni por debajo de 80
                            ('88', 0.9), ('92', 0.9), ('97', 1.0)):
        assert pr.texto_escala({'rep_escala_texto': valor}) == esperado, valor


def test_reducir_da_menos_paginas_con_el_mismo_texto():
    for tipo in ('presupuesto', 'insumos', 'metrados'):
        p100 = _pdf(tipo, 100)
        p80 = _pdf(tipo, 80)
        assert p80.pageCount() <= p100.pageCount(), tipo
        if p100.pageCount() >= 4:
            assert p80.pageCount() < p100.pageCount(), \
                f"{tipo}: {p100.pageCount()} páginas al 100 y {p80.pageCount()} al 80"
        esperadas = _palabras_html(tipo)
        assert esperadas, tipo
        for doc, esc in ((p100, 100), (p80, 80)):
            faltan = esperadas - _palabras_pdf(doc)
            assert not faltan, f"{tipo} @ {esc} %: faltan {sorted(faltan)[:10]}"


def test_el_cuerpo_no_pisa_los_margenes():
    """Rasteriza cada página y exige blanco en las franjas laterales del
    cuerpo (entre encabezado y pie). Es la guardia contra una tabla que se
    salga por el margen — hoy imposible reduciendo, pero es lo primero que
    rompería un paso >100 si alguien lo agrega."""
    r = pr._PdfRenderer({'nombre': 'x'}, 'x')      # geometría A4 retrato
    px_por_pt = 1.5
    pt = 72.0 / r.dpi                               # px de layout → puntos
    mx = r.margin_x * pt * px_por_pt
    top = r.margin_top_body * pt * px_por_pt
    bot = r.margin_bot_body * pt * px_por_pt
    for escala in (100, 80):
        doc = _pdf('presupuesto', escala)
        for i in range(doc.pageCount()):
            sz = doc.pagePointSize(i)
            img = doc.render(i, QSize(int(sz.width() * px_por_pt),
                                      int(sz.height() * px_por_pt)))
            w, h = img.width(), img.height()
            y0, y1 = top + 2, h - bot - 2
            assert _franja_blanca(img, 0, mx - 2, y0, y1), \
                f"tinta en el margen izquierdo, página {i + 1} @ {escala} %"
            assert _franja_blanca(img, w - mx + 2, w, y0, y1), \
                f"tinta en el margen derecho, página {i + 1} @ {escala} %"


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
    for p in _tmpfiles + [_tmpdb]:
        if os.path.exists(p):
            os.unlink(p)
    sys.exit(1 if fallos else 0)
