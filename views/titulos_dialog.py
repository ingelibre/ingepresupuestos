# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Gestor de la lista de títulos que ofrece «Agregar título» (issue #20).

Nada se guarda hasta «Guardar», y ningún presupuesto cambia."""
from __future__ import annotations

from bisect import bisect_left

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from core import titulos
from core.database import get_db
from utils.formatting import norm_busqueda
from utils.i18n import tr
from utils.theme import BTN_PRIMARY_SS, C

_ROL_FILA = Qt.UserRole


class GestorTitulosDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Lista de títulos"))
        self.setWindowModality(Qt.WindowModal)
        self.resize(620, 520)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(18, 16, 18, 16)
        vl.setSpacing(10)
        nota = QLabel(tr(
            "Son los títulos que se ofrecen al agregar un título. Cambiar esta "
            "lista no modifica ningún presupuesto. Doble clic para corregir; "
            "se puede arrastrar para ordenar."))
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color:{C.text}; font-size:12px;")
        vl.addWidget(nota)

        self.inp_buscar = QLineEdit()
        self.inp_buscar.setPlaceholderText(tr("Buscar") + "…")
        self.inp_buscar.setClearButtonEnabled(True)
        self.inp_buscar.textChanged.connect(self._filtrar)
        vl.addWidget(self.inp_buscar)

        hl = QHBoxLayout()
        self.lst = QListWidget()
        self.lst.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lst.setDragDropMode(QAbstractItemView.InternalMove)
        self.lst.setUniformItemSizes(True)
        self.lst.itemChanged.connect(self._editado)
        self.lst.itemSelectionChanged.connect(self._actualizar)
        hl.addWidget(self.lst, 1)
        col = QVBoxLayout()
        self.btn_agregar = self._boton(col, tr("Agregar"), self._agregar)
        self.btn_editar = self._boton(col, tr("Editar"), self._editar)
        self.btn_borrar = self._boton(col, tr("Eliminar"), self._borrar)
        col.addSpacing(12)
        self.btn_subir = self._boton(col, tr("Subir"), lambda: self._mover(-1))
        self.btn_bajar = self._boton(col, tr("Bajar"), lambda: self._mover(1))
        col.addStretch()
        hl.addLayout(col)
        vl.addLayout(hl, 1)

        pie = QHBoxLayout()
        b_rest = QPushButton(tr("Restaurar lista de fábrica"))
        b_rest.setAutoDefault(False)
        b_rest.clicked.connect(self._restaurar)
        pie.addWidget(b_rest)
        self.lbl = QLabel("")
        self.lbl.setStyleSheet(f"color:{C.text}; font-size:11px;")
        pie.addWidget(self.lbl)
        pie.addStretch()
        b_no = QPushButton(tr("Cancelar"))
        b_no.setAutoDefault(False)
        b_no.clicked.connect(self.reject)
        pie.addWidget(b_no)
        self.btn_guardar = QPushButton(tr("Guardar"))
        self.btn_guardar.setStyleSheet(BTN_PRIMARY_SS)
        self.btn_guardar.setAutoDefault(False)
        self.btn_guardar.clicked.connect(self._guardar)
        pie.addWidget(self.btn_guardar)
        vl.addLayout(pie)
        self._cargar()

    def _boton(self, layout, texto, accion):
        b = QPushButton(texto)
        b.setAutoDefault(False)
        b.clicked.connect(lambda _c=False: accion())
        layout.addWidget(b)
        return b

    # ── Lista ────────────────────────────────────────────────────────────────

    def _cargar(self):
        conn = get_db()
        try:
            filas = titulos.filas(conn)
        finally:
            conn.close()
        self.lst.blockSignals(True)
        self.lst.clear()
        for f in filas:
            self.lst.addItem(self._item(f))
        self.lst.blockSignals(False)
        self._filtrar()

    def _item(self, fila: dict) -> QListWidgetItem:
        it = QListWidgetItem(fila['descripcion'])
        it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable
                    | Qt.ItemIsDragEnabled)
        it.setData(_ROL_FILA, fila)
        return it

    def _textos(self) -> list[str]:
        return [self.lst.item(i).text() for i in range(self.lst.count())]

    def filas(self) -> list[dict]:
        out = []
        for i in range(self.lst.count()):
            it = self.lst.item(i)
            f = dict(it.data(_ROL_FILA))
            f['descripcion'] = it.text()
            out.append(f)
        return out

    def _filtrar(self):
        clave = norm_busqueda(self.inp_buscar.text().strip())
        for i in range(self.lst.count()):
            it = self.lst.item(i)
            it.setHidden(bool(clave) and clave not in norm_busqueda(it.text()))
        # Con un filtro puesto no se ve entre qué filas cae lo que se mueve.
        self.lst.setDragEnabled(not clave)
        self._actualizar()

    def _actualizar(self):
        sel = [i for i in range(self.lst.count())
               if self.lst.item(i).isSelected() and not self.lst.item(i).isHidden()]
        libre = not self.inp_buscar.text().strip()
        self.btn_editar.setEnabled(len(sel) == 1)
        self.btn_borrar.setEnabled(bool(sel))
        self.btn_subir.setEnabled(libre and len(sel) == 1 and sel[0] > 0)
        self.btn_bajar.setEnabled(
            libre and len(sel) == 1 and sel[0] < self.lst.count() - 1)
        self.lbl.setText(tr("{n} títulos").format(n=self.lst.count()))

    # ── Acciones ─────────────────────────────────────────────────────────────

    def _en_orden(self, sin: int | None = None) -> bool:
        t = self._textos()
        if sin is not None:
            del t[sin]
        return all(a <= b for a, b in zip(t, t[1:]))

    def agregar(self, texto: str) -> bool:
        """Agrega un título: en su sitio si la lista va en orden alfabético;
        si no, debajo del seleccionado."""
        texto = texto.strip()
        if not texto or texto in self._textos():
            return False
        if self._en_orden():
            pos = bisect_left(self._textos(), texto)
        else:
            pos = self.lst.currentRow() + 1
        it = self._item({'descripcion': texto, 'claves': [], 'propia': True})
        self.lst.blockSignals(True)
        self.lst.insertItem(pos, it)
        self.lst.blockSignals(False)
        self.lst.setCurrentItem(it)
        self.lst.scrollToItem(it)
        self._filtrar()
        return True

    def _agregar(self):
        from PySide6.QtWidgets import QInputDialog
        texto, ok = QInputDialog.getText(
            self, tr("Lista de títulos"), tr("Título nuevo:"))
        if ok and texto.strip() and not self.agregar(texto):
            self._avisar_repetido()

    def _avisar_repetido(self):
        QMessageBox.information(self, tr("Lista de títulos"),
                                tr("Ese título ya está en la lista."))

    def _editar(self):
        sel = [it for it in self.lst.selectedItems() if not it.isHidden()]
        if len(sel) == 1:
            self.lst.editItem(sel[0])

    def _editado(self, it: QListWidgetItem):
        fila = it.data(_ROL_FILA)
        if not fila or it.text() == fila['descripcion']:
            return
        texto = it.text().strip()
        repetido = self._textos().count(it.text()) > 1 or (
            texto != it.text() and texto in self._textos())
        self.lst.blockSignals(True)
        if not texto or repetido:
            it.setText(fila['descripcion'])
        else:
            it.setText(texto)
            it.setData(_ROL_FILA, dict(fila, descripcion=texto))
            fila_n = self.lst.row(it)
            if self._en_orden(sin=fila_n):      # sin orden propio: a su sitio
                self.lst.takeItem(fila_n)
                self.lst.insertItem(bisect_left(self._textos(), texto), it)
                self.lst.setCurrentItem(it)
        self.lst.blockSignals(False)
        self._actualizar()
        if repetido:
            self._avisar_repetido()

    def _borrar(self):
        for it in self.lst.selectedItems():
            if not it.isHidden():
                self.lst.takeItem(self.lst.row(it))
        self._actualizar()

    def _mover(self, paso: int):
        r = self.lst.row(self.lst.selectedItems()[0])
        if not 0 <= r + paso < self.lst.count():
            return
        it = self.lst.takeItem(r)
        self.lst.insertItem(r + paso, it)
        self.lst.clearSelection()
        self.lst.setCurrentItem(it)
        self._actualizar()

    def _restaurar(self):
        r = QMessageBox.question(
            self, tr("Restaurar lista de fábrica"),
            tr("Vuelven los títulos borrados, sus textos originales y el orden "
               "alfabético. Los títulos que agregaste se conservan. ¿Continuar?"))
        if r != QMessageBox.Yes:
            return
        self._en_bd(titulos.restaurar)

    def _guardar(self):
        filas = self.filas()
        self._en_bd(lambda conn: titulos.guardar(conn, filas))

    def _en_bd(self, accion):
        conn = get_db()
        try:
            accion(conn)
        except Exception as e:
            QMessageBox.warning(self, tr("Lista de títulos"), str(e))
            return
        finally:
            conn.close()
        self.accept()
