# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""`api.Documento` → PDF o Excel, con el formato de empresa del usuario."""
from __future__ import annotations

import os
import tempfile
from html import escape
from pathlib import Path

from core.complementos import contexto
from ingepresupuestos import api

MAX_FILAS = 200_000
_ALINEAR = {'izquierda': 'left', 'centro': 'center', 'derecha': 'right'}
_TITULOS = {1: 'h2', 2: 'h3', 3: 'h3'}


def comprobar(doc) -> None:
    """Que lo que devolvió el complemento sea un Documento bien formado."""
    def mal(que):
        raise api.ErrorComplemento(f"el reporte no es válido: {que}")
    if not isinstance(doc, api.Documento):
        mal("la función debe devolver un Documento")
    n = 0
    for b in doc.bloques:
        if isinstance(b, api.Tabla):
            if not b.columnas:
                mal("una tabla sin columnas")
            for c in b.columnas:
                if not isinstance(c, api.Columna) or c.alinear not in _ALINEAR:
                    mal("columna no válida")
            for f in b.filas:
                n += 1
                if n > MAX_FILAS:
                    mal(f"más de {MAX_FILAS} filas")
                celdas = f.celdas if isinstance(f, api.Fila) else f
                if isinstance(celdas, str) or len(celdas) > len(b.columnas):
                    mal("una fila con más celdas que columnas")
        elif isinstance(b, api.Parrafo):
            if b.alinear not in _ALINEAR:
                mal(f"alinear={b.alinear!r}")
        elif not isinstance(b, (api.Titulo, api.Campos, api.SaltoPagina)):
            mal(f"bloque desconocido {type(b).__name__}")


def _fila(f) -> api.Fila:
    return f if isinstance(f, api.Fila) else api.Fila(tuple(f))


def _es_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _dec(col) -> int:
    return 2 if col.decimales is None else max(0, min(8, int(col.decimales)))


# QTextDocument no separa una tabla de lo que la rodea: se separa con un
# párrafo bajo. Y el fondo de una fila solo lo pinta si va en cada celda.
def _aire(px: int) -> str:
    return (f'<p style="margin:0;font-size:{px}px;line-height:{px}px">&nbsp;</p>')


def _html(doc: api.Documento, moneda: api.Moneda, fondo: str = '#F0F1F2') -> str:
    out, antes = [], None
    for b in doc.bloques:
        if antes is not None and not isinstance(antes, api.SaltoPagina):
            out.append(_aire(12 if isinstance(b, api.Titulo) else
                             3 if isinstance(antes, api.Titulo) else 6))
        antes = b
        if isinstance(b, api.Titulo):
            tag = _TITULOS.get(b.nivel, 'h3')
            out.append(f"<{tag}>{escape(str(b.texto))}</{tag}>")
        elif isinstance(b, api.Parrafo):
            t = escape(str(b.texto)).replace('\n', '<br>')
            out.append(f'<p align="{_ALINEAR[b.alinear]}">'
                       + (f"<b>{t}</b>" if b.negrita else t) + "</p>")
        elif isinstance(b, api.Campos):
            ancho = max([110] + [7 * len(str(k)) for k, _v in b.pares])
            out.append('<table class="meta-info">' + "".join(
                f'<tr><td class="k" width="{ancho}" style="padding:1px 12px 1px 0">'
                f'{escape(str(k))}</td><td class="v" style="padding:1px 0">'
                f'{escape(str(v))}</td></tr>'
                for k, v in b.pares) + '</table>')
        elif isinstance(b, api.SaltoPagina):
            out.append('<p style="page-break-before:always"></p>')
        else:
            out.append(_html_tabla(b, moneda, fondo))
    return "\n".join(out)


def _html_tabla(b: api.Tabla, moneda, fondo) -> str:
    aire = 'padding:2px 5px'
    lleno = f'{aire};background:{fondo}'
    def ancho(c):
        return f' width="{int(c.ancho)}%"' if c.ancho else ''
    h = ['<table class="data" width="100%" cellspacing="0">']
    if b.cabecera:
        h.append('<thead><tr>' + "".join(
            f'<th align="{_ALINEAR[c.alinear]}"{ancho(c)} style="{lleno}">{escape(str(c.titulo))}</th>'
            for c in b.columnas) + '</tr></thead>')
    for f in map(_fila, b.filas):
        h.append('<tr>')
        celdas = list(f.celdas)
        # Un título de una sola celda ocupa toda la tabla.
        if f.estilo == 'titulo' and len(celdas) == 1:
            h.append(f'<td colspan="{len(b.columnas)}" style="{aire}"><b>'
                     f'{escape(str(celdas[0]))}</b></td></tr>')
            continue
        celdas += [None] * (len(b.columnas) - len(celdas))
        for c, v in zip(b.columnas, celdas):
            if v is None:
                t = ''
            elif _es_num(v):
                t = moneda.numero(v, _dec(c))
            else:
                t = escape(str(v)).replace('\n', '<br>')
            if f.estilo != 'normal':
                t = f"<b>{t}</b>"
            h.append(f'<td align="{_ALINEAR[c.alinear]}"{ancho(c)} style="'
                     f'{lleno if f.estilo == "subtotal" else aire}">{t}</td>')
        h.append('</tr>')
    h.append('</table>')
    return "".join(h)


def _a_pdf(doc, p: api.Presupuesto, ruta: str) -> None:
    from core import pdf_reports
    from utils.formatting import moneda_documento
    with moneda_documento(p.moneda.nombre):
        proy = pdf_reports._proyecto_info(p.id)
        r = pdf_reports._PdfRenderer(
            proy, str(doc.titulo), with_cover=False,
            orient='landscape' if doc.horizontal else 'portrait')
        r.render_to_file(_html(doc, p.moneda, pdf_reports._brand_colors(
            r.formato)[2]), ruta)


def _a_excel(doc, p: api.Presupuesto, ruta: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = _hoja(doc.titulo)
    negrita = Font(bold=True)
    linea = Border(bottom=Side(style='thin', color='999999'))
    anchos: dict[int, float] = {}
    n = 0

    def poner(col, v, *, fuente=None, alinear=None, formato=None, borde=None):
        c = ws.cell(row=n, column=col)
        if v is not None:
            c.value = v if _es_num(v) else _texto_excel(v)
            if not _es_num(v):
                c.data_type = 's'       # «=…» es texto, nunca una fórmula
        if fuente:
            c.font = fuente
        if formato:
            c.number_format = formato
        if borde:
            c.border = borde
        c.alignment = Alignment(horizontal=alinear, vertical='top',
                                wrap_text=not _es_num(v))

    def linea_de(texto, fuente):
        c = ws.cell(row=n, column=1, value=_texto_excel(texto))
        c.data_type = 's'
        c.font = fuente

    n += 1
    linea_de(doc.titulo, Font(bold=True, size=14))
    n += 1
    linea_de(p.nombre, Font(size=11))
    n += 1
    for b in doc.bloques:
        n += 1
        if isinstance(b, api.Titulo):
            linea_de(b.texto, Font(bold=True, size=max(10, 14 - b.nivel)))
        elif isinstance(b, api.Parrafo):
            linea_de(b.texto, negrita if b.negrita else Font())
        elif isinstance(b, api.Campos):
            for k, v in b.pares:
                poner(1, k, fuente=negrita)
                poner(2, v)
                n += 1
        elif isinstance(b, api.SaltoPagina):
            from openpyxl.worksheet.pagebreak import Break
            ws.row_breaks.append(Break(id=n))
        else:
            total = sum(c.ancho for c in b.columnas) or 0
            for i, c in enumerate(b.columnas, 1):
                a = c.ancho / total * 100 if (c.ancho and total) else 14
                anchos[i] = max(anchos.get(i, 0), min(70, max(9, a)))
            if b.cabecera:
                for i, c in enumerate(b.columnas, 1):
                    poner(i, c.titulo, fuente=negrita, borde=linea,
                          alinear=_ALINEAR[c.alinear])
                n += 1
            for f in map(_fila, b.filas):
                fu = None if f.estilo == 'normal' else negrita
                for i, (c, v) in enumerate(zip(b.columnas, f.celdas), 1):
                    d = _dec(c)
                    poner(i, v, fuente=fu, alinear=_ALINEAR[c.alinear],
                          formato=('#,##0' + ('.' + '0' * d if d else ''))
                          if _es_num(v) else None)
                n += 1
    for i, a in anchos.items():
        ws.column_dimensions[get_column_letter(i)].width = a
    ws.page_setup.orientation = 'landscape' if doc.horizontal else 'portrait'
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    wb.save(ruta)


def _texto_excel(v) -> str:
    return "".join(c for c in str(v) if ord(c) >= 32 or c in '\n\t')[:32000]


def _hoja(titulo) -> str:
    return "".join(c for c in str(titulo) if c not in '[]:*?/\\').strip("' ")[:31] \
        or 'Reporte'


def generar(registro, p: api.Presupuesto, ruta) -> None:
    """Llama al complemento y escribe el archivo entero o no escribe nada."""
    ruta = Path(ruta)
    ext = ruta.suffix.lower().lstrip('.')
    if ext not in registro.extra['formatos']:
        raise api.ErrorComplemento(f"este reporte no sale en .{ext}")
    doc = registro.funcion(p)
    comprobar(doc)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix='.ingeppto-',
                               suffix=f'.{ext}')
    os.close(fd)
    try:
        (_a_pdf if ext == 'pdf' else _a_excel)(doc, p, tmp)
        if not os.path.getsize(tmp):
            raise api.ErrorComplemento("el reporte salió vacío")
        try:
            um = os.umask(0)
            os.umask(um)
            os.chmod(tmp, 0o666 & ~um)
        except OSError:
            pass
        os.replace(tmp, ruta)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def presupuesto(pid, usuario) -> api.Presupuesto:
    return contexto.presupuesto(pid, usuario)
