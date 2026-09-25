# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Monedas propias (issue #13): añadir, editar y quitar monedas.

Solo formato —nombre, símbolo y separadores—, sin tipo de cambio: cambiar
la moneda de un proyecto nunca convierte sus precios. Una moneda propia con
el nombre de una de fábrica la reemplaza (p. ej. «Dólares» con «$» para
Ecuador). Se guardan con `config.guardar_monedas_propias`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.config import (MONEDAS, SEPARADORES, guardar_monedas_propias,
                         monedas_propias)
from utils.theme import BTN_PRIMARY_SS, SLATE_500


def ejemplo(simbolo: str, sep_miles: str, sep_dec: str) -> str:
    return f"{simbolo} 1{sep_miles}234{sep_miles}567{sep_dec}89"


def _nombre_formato(sep_miles: str, sep_dec: str) -> str:
    return ejemplo('', sep_miles, sep_dec).strip()


def moneda_en_uso(nombre: str) -> int:
    """Cuántos proyectos la usan (+1 si es la moneda por defecto)."""
    from core.database import get_db, get_config
    conn = get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM proyectos WHERE moneda=?",
                         (nombre,)).fetchone()[0]
    finally:
        conn.close()
    if get_config('moneda_defecto', 'Soles') == nombre:
        n += 1
    return int(n)


class _MonedaForm(QDialog):
    def __init__(self, parent=None, nombre='', cfg=None, nombre_fijo=False):
        super().__init__(parent)
        self.setWindowTitle("Moneda")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(380)
        cfg = cfg or {'simbolo': '', 'sep_miles': ',', 'sep_dec': '.'}
        vl = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.inp_nombre = QLineEdit(nombre)
        self.inp_nombre.setPlaceholderText("Ej.: Dólares (Ecuador)")
        self.inp_nombre.setEnabled(not nombre_fijo)
        if nombre_fijo:
            self.inp_nombre.setToolTip(
                "Hay proyectos con esta moneda: el nombre no se cambia para no dejarlos sin ella.")
        form.addRow("Nombre:", self.inp_nombre)
        self.inp_simbolo = QLineEdit(cfg['simbolo'])
        self.inp_simbolo.setPlaceholderText("Ej.: $")
        self.inp_simbolo.setMaxLength(8)
        self.inp_simbolo.setMaximumWidth(120)
        form.addRow("Símbolo:", self.inp_simbolo)
        self.cmb_formato = QComboBox()
        for miles, dec in SEPARADORES:
            self.cmb_formato.addItem(_nombre_formato(miles, dec), (miles, dec))
        i = self.cmb_formato.findData((cfg['sep_miles'], cfg['sep_dec']))
        self.cmb_formato.setCurrentIndex(max(i, 0))
        form.addRow("Formato:", self.cmb_formato)
        self.lbl_ejemplo = QLabel()
        self.lbl_ejemplo.setStyleSheet("font-weight:700;")
        form.addRow("Se verá así:", self.lbl_ejemplo)
        vl.addLayout(form)
        nota = QLabel("Solo cambia cómo se escriben los montos: los precios no se convierten.")
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
        vl.addWidget(nota)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Guardar")
        bb.button(QDialogButtonBox.Ok).setStyleSheet(BTN_PRIMARY_SS)
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self._aceptar)
        bb.rejected.connect(self.reject)
        vl.addWidget(bb)
        self.inp_simbolo.textChanged.connect(self._refrescar)
        self.cmb_formato.currentIndexChanged.connect(self._refrescar)
        self._refrescar()

    def _refrescar(self, *_):
        miles, dec = self.cmb_formato.currentData()
        self.lbl_ejemplo.setText(ejemplo(self.inp_simbolo.text().strip() or '¤', miles, dec))

    def _aceptar(self):
        if not self.inp_nombre.text().strip() or not self.inp_simbolo.text().strip():
            QMessageBox.warning(self, "Moneda", "Escribe el nombre y el símbolo.")
            return
        self.accept()

    def valor(self) -> tuple[str, dict]:
        miles, dec = self.cmb_formato.currentData()
        return (self.inp_nombre.text().strip(),
                {'simbolo': self.inp_simbolo.text().strip(),
                 'sep_miles': miles, 'sep_dec': dec})


class MonedasDialog(QDialog):
    """Lista de monedas propias con Agregar / Editar / Quitar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Monedas propias")
        self.setWindowModality(Qt.WindowModal)
        self.resize(560, 360)
        self._propias = monedas_propias()
        vl = QVBoxLayout(self)
        intro = QLabel(
            "Añade una moneda que no está en la lista, o corrige una de fábrica "
            "creando otra con el mismo nombre. Solo es formato: no hay tipo de cambio.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
        vl.addWidget(intro)
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["Nombre", "Símbolo", "Se verá así"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.doubleClicked.connect(lambda *_: self._editar())
        vl.addWidget(self.tbl, 1)
        fila = QHBoxLayout()
        for texto, fn in (("Agregar…", self._agregar), ("Editar…", self._editar),
                          ("Quitar", self._quitar)):
            b = QPushButton(texto)
            b.clicked.connect(fn)
            fila.addWidget(b)
        fila.addStretch(1)
        b_cerrar = QPushButton("Cerrar")
        b_cerrar.clicked.connect(self.accept)
        fila.addWidget(b_cerrar)
        vl.addLayout(fila)
        self._llenar()

    def _llenar(self):
        self.tbl.setRowCount(0)
        for nombre, c in sorted(self._propias.items()):
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            etiqueta = nombre + ("  (reemplaza la de fábrica)" if nombre in MONEDAS else "")
            it = QTableWidgetItem(etiqueta)
            it.setData(Qt.UserRole, nombre)
            self.tbl.setItem(r, 0, it)
            self.tbl.setItem(r, 1, QTableWidgetItem(c['simbolo']))
            self.tbl.setItem(r, 2, QTableWidgetItem(
                ejemplo(c['simbolo'], c['sep_miles'], c['sep_dec'])))

    def _actual(self) -> str | None:
        r = self.tbl.currentRow()
        return self.tbl.item(r, 0).data(Qt.UserRole) if r >= 0 else None

    def _guardar(self):
        guardar_monedas_propias(self._propias)
        self._propias = monedas_propias()
        self._llenar()

    def _agregar(self):
        dlg = _MonedaForm(self)
        if dlg.exec() != QDialog.Accepted:
            return
        nombre, cfg = dlg.valor()
        if nombre in self._propias and QMessageBox.question(
                self, "Moneda", f"Ya tienes «{nombre}». ¿Reemplazarla?") != QMessageBox.Yes:
            return
        self._propias[nombre] = cfg
        self._guardar()

    def _editar(self):
        nombre = self._actual()
        if nombre is None:
            return
        dlg = _MonedaForm(self, nombre, self._propias[nombre],
                          nombre_fijo=moneda_en_uso(nombre) > 0)
        if dlg.exec() != QDialog.Accepted:
            return
        nuevo, cfg = dlg.valor()
        if nuevo != nombre:
            del self._propias[nombre]
        self._propias[nuevo] = cfg
        self._guardar()

    def _quitar(self):
        nombre = self._actual()
        if nombre is None:
            return
        if nombre not in MONEDAS and moneda_en_uso(nombre):
            QMessageBox.information(
                self, "Moneda",
                f"«{nombre}» la usan proyectos (o es la moneda por defecto). "
                "Cámbiales la moneda antes de quitarla.")
            return
        if QMessageBox.question(self, "Moneda", f"¿Quitar «{nombre}»?") != QMessageBox.Yes:
            return
        del self._propias[nombre]
        self._guardar()
