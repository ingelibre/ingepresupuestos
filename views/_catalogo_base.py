# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Base común de las dos vistas-catálogo: Insumos y Biblioteca de CU.

``views/recursos_view.py`` y ``views/biblioteca_view.py`` son la misma
pantalla —tabla con filtros, KPIs, menú contextual y CRUD— sobre dos tablas
distintas de la BD. Nacieron por copia, y cinco de sus métodos eran idénticos
carácter por carácter: un arreglo en una no llegaba a la otra.

Acá vive lo que de verdad es el mismo concepto. Lo específico de cada catálogo
(las columnas, el SQL, los diálogos de import/export) se queda en su vista.

**Contrato** — la vista concreta debe aportar:

* ``self.tbl``      — el ``QTableWidget``; la columna 0 lleva el id en
  ``Qt.UserRole`` (lo lee `_rid_at`).
* ``_editar_id(id)`` · ``_duplicar_id(id)`` · ``_eliminar_id(id)`` ·
  ``_eliminar_ids([id])`` — las acciones que dispara el menú contextual.

El borrado va por dos caminos a propósito: `_eliminar_id` para una fila y
`_eliminar_ids` para varias, porque cada catálogo valida distinto (los
insumos en uso por un ACU no se pueden borrar; los CU sí, con CASCADE).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QFrame, QMenu, QPushButton,
                               QStyledItemDelegate)

from utils.icons import icon
from utils.theme import BTN_PRIMARY_SS, crear_kpi_card


class EditorPlenoDelegate(QStyledItemDelegate):
    """Hace que el editor de celda ocupe la celda ENTERA.

    `QTableWidget::item { padding: 4px 6px }` no solo separa el texto al
    pintar: recorta también el rectángulo que recibe el EDITOR. Medido en la
    matriz de índices, una celda de 57×27 px daba un editor de 45×19, y un
    valor como «1234.56» —47 px de ancho— no cabía: el texto se entrecortaba
    mientras se escribía y solo se veía entero al confirmar.

    Vive acá porque le pasa a cualquier tabla editable con relleno de celda,
    no a una sola.
    """

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class CatalogoTablaMixin:
    """Widgets y acciones compartidos por las dos vistas-catálogo."""

    # ── construcción de widgets ─────────────────────────────────────────────
    def _mk_btn(self, text: str, primary: bool = False,
                icon_name: str | None = None) -> QPushButton:
        """Botón de la barra de acciones del catálogo.

        Sin ``primary`` se deja sin stylesheet: hereda el QSS global de
        `main.py`, que es lo que da el aspecto de botón secundario.
        """
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(32)
        if icon_name:
            b.setIcon(icon(icon_name))
            b.setIconSize(QSize(18, 18))
        if primary:
            b.setStyleSheet(BTN_PRIMARY_SS)
        return b

    def _mk_kpi(self, etiqueta: str, valor: str, color: str) -> QFrame:
        """Card KPI de la fila superior. La construye el sistema de diseño."""
        return crear_kpi_card(etiqueta, valor, color)

    # ── lectura de la tabla ─────────────────────────────────────────────────
    def _rid_at(self, row: int) -> int | None:
        """Id de BD de la fila, o None si la fila no existe o está vacía."""
        if row < 0 or row >= self.tbl.rowCount():
            return None
        it = self.tbl.item(row, 0)
        v = it.data(Qt.UserRole) if it else None
        return int(v) if v is not None else None

    def _ids_seleccionados(self) -> list[int]:
        """Ids de las filas seleccionadas, sin repetir y en orden de tabla."""
        filas = sorted({i.row() for i in self.tbl.selectedIndexes()})
        return [i for i in (self._rid_at(r) for r in filas) if i is not None]

    # ── acciones ────────────────────────────────────────────────────────────
    def _eliminar_seleccion(self):
        """Atajo Supr: borra lo seleccionado. Sin selección no hace nada."""
        ids = self._ids_seleccionados()
        if ids:
            self._eliminar_ids(ids)

    def _menu_contextual(self, pos):
        """Editar · Duplicar · Eliminar sobre la fila bajo el cursor.

        «Eliminar» pasa a plural cuando hay varias filas seleccionadas;
        editar y duplicar siempre actúan sobre la fila del clic.
        """
        idx = self.tbl.indexAt(pos)
        if not idx.isValid():
            return
        rid = self._rid_at(idx.row())
        if rid is None:
            return
        ids_sel = self._ids_seleccionados()

        m = QMenu(self)
        a_edit = QAction(icon("editar"), "Editar", self)
        a_edit.triggered.connect(lambda: self._editar_id(rid))
        m.addAction(a_edit)
        a_dup = QAction(icon("duplicar"), "Duplicar", self)
        a_dup.triggered.connect(lambda: self._duplicar_id(rid))
        m.addAction(a_dup)
        m.addSeparator()
        if len(ids_sel) > 1:
            a_del = QAction(icon("eliminar"),
                            f"Eliminar {len(ids_sel)} seleccionados", self)
            a_del.triggered.connect(lambda: self._eliminar_ids(ids_sel))
        else:
            a_del = QAction(icon("eliminar"), "Eliminar", self)
            a_del.triggered.connect(lambda: self._eliminar_id(rid))
        m.addAction(a_del)
        m.exec(self.tbl.viewport().mapToGlobal(pos))


class UnidadSuperindiceMixin:
    """Auto-superíndice del campo Unidad de los diálogos de alta/edición.

    Escribir ``m2`` deja ``m²``. Vive acá porque los dos formularios —el de
    insumo y el de CU— tienen el mismo campo ``inp_unidad`` y llevaban el
    mismo método copiado.
    """

    def _auto_superindice_unidad(self, txt: str):
        from utils.formatting import superindice_unidad
        nuevo = superindice_unidad(txt)
        if nuevo is None:
            return
        self.inp_unidad.blockSignals(True)
        self.inp_unidad.setText(nuevo)
        self.inp_unidad.blockSignals(False)
