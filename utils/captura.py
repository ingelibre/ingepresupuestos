# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Captura de un widget como imagen nítida (para el portapapeles)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter


def imagen_nitida(widget, escala: float = 3.0) -> QImage:
    """El widget pintado a `escala` veces su tamaño, sobre fondo blanco.

    `QWidget.grab()` captura a la densidad de la pantalla: en un monitor
    normal (1×) el resumen pegado en Word o en un chat salía borroso al
    ampliarlo. Pintar con `render()` sobre una imagen con devicePixelRatio
    alto redibuja textos y el donut vectorialmente (issue #15)."""
    w = max(1, int(widget.width() * escala))
    h = max(1, int(widget.height() * escala))
    img = QImage(w, h, QImage.Format_ARGB32)
    img.setDevicePixelRatio(escala)
    img.fill(Qt.white)
    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        widget.render(p, QPoint(0, 0))
    finally:
        p.end()
    return img
