# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""FlowLayout — fila de widgets que se envuelve a la siguiente línea cuando
no caben. Vivía dentro de `views/dashboard_view.py` (chips de portafolio);
el 8 sep 2026 pasó aquí para que el chat de Tuxia use el mismo: su fila de
botones rápidos imponía 587 px de ancho mínimo al panel y el texto salía
cortado por la derecha hasta redimensionar la ventana.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QStyle, QWidget


class FlowLayout(QLayout):
    """Layout que coloca widgets en una fila y los envuelve a la siguiente
    cuando no caben. Equivalente al QtFlowLayout de los ejemplos oficiales,
    portado a Python.
    """

    def __init__(self, parent=None, *, margin_h: int = 0, margin_v: int = 0,
                 h_spacing: int = 6, v_spacing: int = 4):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_space = h_spacing
        self._v_space = v_spacing
        self.setContentsMargins(margin_h, margin_v, margin_h, margin_v)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        l, t, r, b = self.getContentsMargins()
        size += QSize(l + r, t + b)
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        l, t, r, b = self.getContentsMargins()
        effective = rect.adjusted(l, t, -r, -b)
        x = effective.x()
        y = effective.y()
        line_h = 0
        for item in self._items:
            wid = item.widget()
            if wid is None:
                continue
            # NO filtramos por wid.isVisible() — widgets recién agregados
            # vía addWidget() todavía no son "visible" cuando Qt calcula el
            # primer layout. Saltarlos los deja en (0,0) superpuestos.
            sh = item.sizeHint()
            next_x = x + sh.width() + self._h_space
            if next_x - self._h_space > effective.right() and line_h > 0:
                # Wrap a siguiente fila
                x = effective.x()
                y = y + line_h + self._v_space
                next_x = x + sh.width() + self._h_space
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), sh))
            x = next_x
            line_h = max(line_h, sh.height())
        return y + line_h - rect.y() + b


# ── Grid responsivo ───────────────────────────────────────────────────────────
