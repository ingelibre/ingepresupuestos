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


def ajustar_printer_al_pdf(printer, pdf_path: str) -> None:
    """Deja `printer` con el tamaño de papel y la orientación de la PRIMERA
    página del PDF, para que la vista previa de impresión arranque igual
    que el documento. Sin esto la impresora nace en A4 vertical y un Gantt
    A3 apaisado salía encogido dentro de una hoja vertical (Marco, 9 sep
    2026, con Ctrl+P). Llamar ANTES de abrir el QPrintPreviewDialog."""
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtPdf import QPdfDocument

    doc = QPdfDocument()
    doc.load(pdf_path)
    if doc.pageCount() <= 0:
        return
    tam = doc.pagePointSize(0)
    pw, ph = tam.width(), tam.height()
    if pw <= 0 or ph <= 0:
        return
    # Tamaño en retrato (lado corto × lado largo) + orientación aparte:
    # QPageSize con un QSizeF ya apaisado más Landscape lo giraría dos veces.
    printer.setPageSize(QPageSize(QSizeF(min(pw, ph), max(pw, ph)), QPageSize.Point))
    printer.setPageOrientation(QPageLayout.Landscape if pw > ph else QPageLayout.Portrait)


def pintar_pdf_en_printer(printer, pdf_path: str) -> None:
    """Renderiza cada página de `pdf_path` sobre `printer`, centrada en el
    área imprimible y respetando el aspect ratio de la página.

    La orientación del papel es la que traiga `printer` (ver
    `ajustar_printer_al_pdf`): NO se cambia entre páginas, porque el
    QPrintPreviewDialog la ignora a mitad del documento y mostraba un Gantt
    apaisado recortado dentro de una hoja vertical (se probó). Una página de
    la otra orientación (el Reporte Completo mezcla núcleo vertical y
    cronogramas apaisados) se dibuja GIRADA 90° para llenar el papel: sale
    bien en la vista previa y en la impresora."""
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
        papel_apaisado = paint_pts.width() > paint_pts.height()
        for i in range(n):
            if i > 0:
                printer.newPage()
            tam = doc.pagePointSize(i)
            pw, ph = tam.width(), tam.height()
            if pw <= 0 or ph <= 0:
                continue
            girar = (pw > ph) != papel_apaisado
            # Escala que cabe en el área imprimible (aspect ratio); girada, el
            # ancho de la página se mide contra el ALTO del papel.
            if girar:
                escala = min(paint_pts.width() / ph, paint_pts.height() / pw)
            else:
                escala = min(paint_pts.width() / pw, paint_pts.height() / ph)
            dest_w = pw * escala * dpi_dev / 72.0
            dest_h = ph * escala * dpi_dev / 72.0
            img_w = int(pw * escala * dpi_img / 72.0)
            img_h = int(ph * escala * dpi_img / 72.0)
            if img_w <= 0 or img_h <= 0:
                continue
            # QPdfDocument.render() exige QSize — una tupla lanza TypeError.
            imagen = doc.render(i, QSize(img_w, img_h))
            if girar:
                # Girada 90° en sentido horario ocupa dest_h × dest_w.
                ox = max(0.0, (target_w - dest_h) / 2)
                oy = max(0.0, (target_h - dest_w) / 2)
                painter.save()
                painter.translate(ox + dest_h, oy)
                painter.rotate(90)
                painter.drawImage(QRectF(0, 0, dest_w, dest_h), imagen)
                painter.restore()
            else:
                ox = max(0.0, (target_w - dest_w) / 2)
                oy = max(0.0, (target_h - dest_h) / 2)
                painter.drawImage(QRectF(ox, oy, dest_w, dest_h), imagen)
    finally:
        painter.end()
