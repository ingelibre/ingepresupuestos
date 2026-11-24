# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Texto ↔ HTML de las especificaciones y la memoria descriptiva (sin Qt)."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser


def es_html(contenido: str) -> bool:
    c = (contenido or '').lstrip()
    return c.startswith('<') or bool(re.search(r'</|<p\b|<body', c, re.I))


def a_html(texto: str) -> str:
    """Texto plano → HTML del editor: los títulos de sección («1. DESCRIPCIÓN»
    o una línea en mayúsculas) en negrita, lo demás justificado."""
    partes = []
    for linea in texto.split('\n'):
        linea = linea.strip()
        escapada = html.escape(linea)
        titulo = (
            re.match(r'^\d+\.\s+[A-ZÁÉÍÓÚÑÜ\s\/\-]+$', linea) or
            (len(linea) >= 5 and linea == linea.upper()
             and re.search(r'[A-ZÁÉÍÓÚÑ]', linea)))
        if titulo:
            partes.append(f'<p style="text-align:left;"><b>'
                          f'<span style="color:#000000;">{escapada}</span></b></p>')
        elif linea:
            partes.append(f'<p style="text-align:justify;">{escapada}</p>')
        else:
            partes.append('<p></p>')
    return ''.join(partes)


class _Extractor(HTMLParser):
    _FUERA = ('head', 'style', 'script')
    _BLOQUE = ('p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6')

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.imagenes = 0
        self._dentro = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._FUERA:
            self._dentro += 1
        elif tag == 'br':
            self.out.append('\n')
        elif tag == 'li':
            self.out.append('- ')
        elif tag == 'img':
            self.imagenes += 1
            self.out.append('[imagen]')

    def handle_endtag(self, tag):
        if tag in self._FUERA:
            self._dentro = max(0, self._dentro - 1)
        elif tag in self._BLOQUE:
            self.out.append('\n')
        elif tag in ('td', 'th'):
            self.out.append('\t')

    def handle_data(self, data):
        if not self._dentro:
            self.out.append(data.replace('\n', ' '))


def a_texto(contenido: str) -> tuple[str, int]:
    """(texto plano, nº de imágenes) de lo guardado, sea HTML o texto."""
    contenido = contenido or ''
    if not es_html(contenido):
        return contenido.strip(), 0
    x = _Extractor()
    x.feed(contenido)
    x.close()
    lineas = [ln.strip() for ln in ''.join(x.out).split('\n')]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lineas)).strip(), x.imagenes
