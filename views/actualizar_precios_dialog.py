# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""«Actualizar precios desde el catálogo» — vista previa y aplicación.

El precio de cada insumo en un proyecto es una foto (`acu_items.precio`):
editar el catálogo no cambia presupuestos ya armados, a propósito. Este
diálogo es la puerta explícita en sentido contrario: lista los insumos del
proyecto cuyo precio difiere del catálogo, deja elegir cuáles traer, y
aplica con `core.database.actualizar_precios_desde_catalogo`.

Pedido de David Ramos (5 sep 2026): «si se realiza cualquier modificación
que se actualice en todos (catálogo, presupuestos, ACUs, insumos…)».
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.database import actualizar_precios_desde_catalogo, get_db, precios_desactualizados
from utils.formatting import fmt
from utils.theme import BTN_PRIMARY_SS, btn_secondary

SLATE_700 = "#2E3C52"
SLATE_500 = "#485A6C"
SLATE_300 = "#94A3B8"
SLATE_100 = "#E2E8F0"
SILVER_100 = "#F8F9FA"
WHITE = "#FFFFFF"
SUBE = "#B71C1C"     # el precio nuevo es mayor
BAJA = "#2E7D32"     # el precio nuevo es menor

COL_CHK, COL_TIPO, COL_DESC, COL_UND, COL_PROY, COL_CAT, COL_DIF, COL_PART = range(8)


class ActualizarPreciosDialog(QDialog):
    """Vista previa de los insumos cuyo precio difiere del catálogo.

    `exec()` devuelve Accepted solo si se aplicó algo; `partidas_afectadas`
    trae los ids para que la vista recargue lo justo.
    """

    def __init__(self, pid: int, moneda: str = 'S/', parent=None):
        super().__init__(parent)
        self.pid = pid
        self.moneda = moneda
        self.partidas_afectadas: list[int] = []
        self.n_aplicados = 0
        self.setWindowTitle("Actualizar precios desde el catálogo")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumSize(720, 380)
        self.resize(860, 520)
        pantalla = self.screen() or QApplication.primaryScreen()
        if pantalla is not None:
            geo = pantalla.availableGeometry()
            self.resize(min(860, geo.width() - 40), min(520, geo.height() - 80))
        self.setStyleSheet(f"QDialog {{ background:{SILVER_100}; }}")

        conn = get_db()
        try:
            self._items = precios_desactualizados(conn, pid)
        finally:
            conn.close()
        self._build()

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{SLATE_700};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18, 0, 18, 0)
        t = QLabel("Actualizar precios desde el catálogo")
        t.setStyleSheet("color:white; font-size:14px; font-weight:700;"
                        " background:transparent; border:none;")
        hl.addWidget(t)
        hl.addStretch(1)
        v.addWidget(hdr)

        cuerpo = QFrame()
        cuerpo.setStyleSheet(f"background:{SILVER_100};")
        cl = QVBoxLayout(cuerpo)
        cl.setContentsMargins(18, 14, 18, 12)
        cl.setSpacing(8)

        n = len(self._items)
        if n:
            texto = (f"{n} insumo(s) de este proyecto tienen un precio distinto al del "
                     "catálogo. Marca los que quieras traer al proyecto: el precio se "
                     "fija en todas las partidas donde aparece el insumo y se recalcula "
                     "su precio unitario.")
        else:
            texto = ("Todos los insumos de este proyecto ya tienen el precio del "
                     "catálogo. No hay nada que actualizar.")
        intro = QLabel(texto)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
        cl.addWidget(intro)

        self.tbl = QTableWidget(0, 8)
        self.tbl.setHorizontalHeaderLabels(
            ["", "Tipo", "Insumo", "Und", "En el proyecto", "En el catálogo",
             "Diferencia", "Partidas"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setShowGrid(False)
        self.tbl.setStyleSheet(
            f"QTableWidget {{ background:{WHITE}; border:1px solid {SLATE_100};"
            f" border-radius:6px; font-size:11px; alternate-background-color:{SILVER_100}; }}"
            f"QHeaderView::section {{ background:{SILVER_100}; color:{SLATE_700};"
            f" font-weight:700; font-size:10px; border:none;"
            f" border-bottom:1px solid {SLATE_100}; padding:4px; }}"
        )
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_DESC, QHeaderView.Stretch)
        self._poblar()
        self.tbl.itemChanged.connect(self._on_item_changed)
        cl.addWidget(self.tbl, 1)

        pie = QHBoxLayout()
        self.btn_todos = QPushButton("Marcar todos")
        self.btn_todos.setCursor(Qt.PointingHandCursor)
        self.btn_todos.setStyleSheet(btn_secondary(height=26))
        self.btn_todos.clicked.connect(lambda: self._marcar(True))
        self.btn_nada = QPushButton("Desmarcar todos")
        self.btn_nada.setCursor(Qt.PointingHandCursor)
        self.btn_nada.setStyleSheet(btn_secondary(height=26))
        self.btn_nada.clicked.connect(lambda: self._marcar(False))
        pie.addWidget(self.btn_todos)
        pie.addWidget(self.btn_nada)
        pie.addStretch(1)
        self.lbl_resumen = QLabel()
        self.lbl_resumen.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
        pie.addWidget(self.lbl_resumen)
        cl.addLayout(pie)

        nota = QLabel(
            "Los insumos cuyo precio de catálogo es 0 no se listan: «sin precio» en el "
            "catálogo no es una orden de poner a cero el proyecto. Los porcentajes "
            "(%MO, %MT, %EQ) tampoco: su precio se deriva."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color:{SLATE_300}; font-size:10px; font-style:italic;")
        cl.addWidget(nota)
        v.addWidget(cuerpo, 1)

        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"background:{WHITE}; border-top:1px solid {SLATE_100};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(18, 8, 18, 8)
        bl.setSpacing(10)
        bl.addStretch(1)
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet(btn_secondary())
        btn_cancel.clicked.connect(self.reject)
        bl.addWidget(btn_cancel)
        self.btn_aplicar = QPushButton("Actualizar precios")
        self.btn_aplicar.setCursor(Qt.PointingHandCursor)
        self.btn_aplicar.setStyleSheet(BTN_PRIMARY_SS)
        self.btn_aplicar.clicked.connect(self._aplicar)
        bl.addWidget(self.btn_aplicar)
        v.addWidget(bar)

        self._actualizar_resumen()

    def _poblar(self):
        self.tbl.setRowCount(len(self._items))
        for r, it in enumerate(self._items):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked)
            chk.setData(Qt.UserRole, it['recurso_id'])
            self.tbl.setItem(r, COL_CHK, chk)
            self.tbl.setItem(r, COL_TIPO, self._celda(it['tipo'], Qt.AlignCenter))
            self.tbl.setItem(r, COL_DESC, self._celda(it['descripcion']))
            self.tbl.setItem(r, COL_UND, self._celda(it['unidad'], Qt.AlignCenter))
            self.tbl.setItem(r, COL_PROY, self._celda(
                fmt(it['precio_proyecto'], self.moneda), Qt.AlignRight | Qt.AlignVCenter))
            self.tbl.setItem(r, COL_CAT, self._celda(
                fmt(it['precio_catalogo'], self.moneda), Qt.AlignRight | Qt.AlignVCenter))
            dif = it['precio_catalogo'] - it['precio_proyecto']
            c_dif = self._celda(f"{'+' if dif > 0 else ''}{fmt(dif, '')}".strip(),
                                Qt.AlignRight | Qt.AlignVCenter)
            c_dif.setForeground(QColor(SUBE if dif > 0 else BAJA))
            self.tbl.setItem(r, COL_DIF, c_dif)
            self.tbl.setItem(r, COL_PART, self._celda(
                str(it['n_partidas']), Qt.AlignCenter))

    @staticmethod
    def _celda(texto: str, align=Qt.AlignLeft | Qt.AlignVCenter) -> QTableWidgetItem:
        c = QTableWidgetItem(str(texto))
        c.setTextAlignment(int(align))
        return c

    # ── Selección ───────────────────────────────────────────────────────────

    def _marcados(self) -> list[int]:
        out = []
        for r in range(self.tbl.rowCount()):
            c = self.tbl.item(r, COL_CHK)
            if c is not None and c.checkState() == Qt.Checked:
                out.append(int(c.data(Qt.UserRole)))
        return out

    def _marcar(self, on: bool):
        self.tbl.blockSignals(True)
        for r in range(self.tbl.rowCount()):
            self.tbl.item(r, COL_CHK).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.tbl.blockSignals(False)
        self._actualizar_resumen()

    def _on_item_changed(self, item):
        if item.column() == COL_CHK:
            self._actualizar_resumen()

    def _actualizar_resumen(self):
        n = len(self._marcados())
        total = self.tbl.rowCount()
        if total == 0:
            self.lbl_resumen.setText("")
        else:
            self.lbl_resumen.setText(f"{n} de {total} marcados")
        self.btn_aplicar.setEnabled(n > 0)
        self.btn_aplicar.setText(
            f"Actualizar {n} precio(s)" if n else "Actualizar precios")

    # ── Aplicar ─────────────────────────────────────────────────────────────

    def _aplicar(self):
        ids = self._marcados()
        if not ids:
            return
        conn = get_db()
        try:
            self.partidas_afectadas = actualizar_precios_desde_catalogo(conn, self.pid, ids)
            conn.commit()
        finally:
            conn.close()
        self.n_aplicados = len(ids)
        self.accept()
