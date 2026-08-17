# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Celda numérica para tablas ordenables (QTableWidget + setSortingEnabled)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem


class NumItem(QTableWidgetItem):
    """Muestra el texto formateado pero ORDENA por el valor numérico.

    QTableWidgetItem compara por el texto visible, así que al ordenar por la
    columna Precio «S/ 1,000.00» quedaba antes que «S/ 999.00», y en Usos
    «10» antes que «9». El valor real viaja en Qt.UserRole (el mismo rol que
    ya usan algunas vistas para el valor previo — el número ES el valor, así
    que ambos usos coinciden).
    """

    def __init__(self, texto: str, valor):
        super().__init__(texto)
        self.setData(Qt.UserRole, float(valor or 0))

    def __lt__(self, other):
        a = self.data(Qt.UserRole)
        b = other.data(Qt.UserRole)
        if a is not None and b is not None:
            try:
                return float(a) < float(b)
            except (TypeError, ValueError):
                pass
        return super().__lt__(other)
