# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Impresión física de un PDF ya generado sobre un QPrinter.

Único punto donde se rasteriza PDF → papel. Dos trampas que este helper
resuelve y que ya mordieron dos veces (imprimir_seleccion_dialog y
metrados_view tenían copias viejas del código):

- El QPainter sobre un QPrinter (sin fullPage) ya arranca DENTRO del margen.
  Dibujar sobre ``printer.pageRect(DevicePixel)`` — cuyo origen ES el margen —
  corría el contenido a doble margen y recortaba ~7 mm abajo y a la derecha
  (verificado imprimiendo a PDF: la imagen caía en 20 pt con margen de 10 pt).
- Renderizar la página a 2× su tamaño en puntos son ~144 dpi: texto blando
  en una impresora de 1200 dpi.
"""
from __future__ import annotations

#: Tope de rasterizado. 600 dpi ya es calidad imprenta; a los 1200 dpi que
#: reporta QPrinter.HighResolution una A4 sería un QImage de ~530 MB.
_DPI_RASTER_MAX = 600


def pintar_pdf_en_printer(printer, pdf_path: str) -> None:
    """Renderiza cada página de `pdf_path` sobre `printer`, centrada en el
    área imprimible y respetando el aspect ratio de la página."""
    from PySide6.QtCore import QRectF, QSize
    from PySide6.QtGui import QPageLayout, QPainter
    from PySide6.QtPdf import QPdfDocument

    doc = QPdfDocument()
    doc.load(pdf_path)
    n = doc.pageCount()
    if n <= 0:
        return
    painter = QPainter(printer)
    try:
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        paint_pts = printer.pageLayout().paintRect(QPageLayout.Unit.Point)
        # En Qt6 el QPainter sobre QPrinter trabaja en device pixels, con el
        # ORIGEN en la esquina del área imprimible → las posiciones se
        # calculan desde (0,0), nunca desde pageRect().topLeft().
        dpi_dev = printer.resolution()
        dpi_img = min(dpi_dev, _DPI_RASTER_MAX)
        target_w = paint_pts.width() * dpi_dev / 72.0
        target_h = paint_pts.height() * dpi_dev / 72.0
        if target_w <= 0 or target_h <= 0:
            return
        for i in range(n):
            if i > 0:
                printer.newPage()
            tam = doc.pagePointSize(i)
            pw, ph = tam.width(), tam.height()
            if pw <= 0 or ph <= 0:
                continue
            # Escala que cabe en el área imprimible (aspect ratio)
            escala = min(paint_pts.width() / pw, paint_pts.height() / ph)
            dest_w = pw * escala * dpi_dev / 72.0
            dest_h = ph * escala * dpi_dev / 72.0
            img_w = int(pw * escala * dpi_img / 72.0)
            img_h = int(ph * escala * dpi_img / 72.0)
            if img_w <= 0 or img_h <= 0:
                continue
            # QPdfDocument.render() exige QSize — una tupla lanza TypeError.
            imagen = doc.render(i, QSize(img_w, img_h))
            ox = max(0.0, (target_w - dest_w) / 2)
            oy = max(0.0, (target_h - dest_h) / 2)
            painter.drawImage(QRectF(ox, oy, dest_w, dest_h), imagen)
    finally:
        painter.end()
