# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""País del usuario (issue #9): el formulario y el diálogo de bienvenida.

`PaisForm` lo usan dos puertas al mismo dato: la sección «País» de
Configuración y `PaisBienvenidaDialog`, que sale UNA vez —cuando la clave
`pais` todavía no existe— proponiendo el país detectado del sistema, como
Delphin Express al instalar. Elegir un país rellena moneda, identificación
tributaria e impuesto con los valores de ese país; el usuario puede
corregir cualquiera antes de guardar.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from core.config import monedas
from core import paises
from utils.theme import BTN_PRIMARY_SS, SLATE_500, SLATE_700


class PaisForm(QWidget):
    """País + los cuatro valores que fija. `guardar()` los escribe."""

    guardado = Signal(str)   # iso

    def __init__(self, parent=None, iso: str | None = None, proponer_detectado: bool = False):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        self.cmb_pais = QComboBox()
        for code, p in sorted(paises.PAISES.items(), key=lambda kv: kv[1]['nombre']):
            self.cmb_pais.addItem(p['nombre'], code)
        self.cmb_pais.setMinimumHeight(34)
        form.addRow("País:", self.cmb_pais)

        self.cmb_moneda = QComboBox()
        self.cmb_moneda.addItems(list(monedas().keys()))
        self.cmb_moneda.setMinimumHeight(34)
        fila_mon = QHBoxLayout()
        fila_mon.addWidget(self.cmb_moneda, 1)
        # Monedas propias (issue #13): la lista de fábrica no tiene todas.
        btn_monedas = QPushButton("Monedas…")
        btn_monedas.setMinimumHeight(34)
        btn_monedas.setToolTip("Añadir o editar monedas (nombre, símbolo y separadores)")
        btn_monedas.clicked.connect(self._editar_monedas)
        fila_mon.addWidget(btn_monedas)
        form.addRow("Moneda:", fila_mon)

        self.inp_etiqueta = QLineEdit()
        self.inp_etiqueta.setMinimumHeight(34)
        self.inp_etiqueta.setMaximumWidth(160)
        form.addRow("Identificación tributaria:", self.inp_etiqueta)

        fila_imp = QHBoxLayout()
        self.inp_imp_nombre = QLineEdit()
        self.inp_imp_nombre.setMinimumHeight(34)
        self.inp_imp_nombre.setMaximumWidth(110)
        self.spn_imp_pct = QDoubleSpinBox()
        self.spn_imp_pct.setRange(0, 50)
        self.spn_imp_pct.setDecimals(2)
        self.spn_imp_pct.setSuffix(" %")
        self.spn_imp_pct.setMinimumHeight(34)
        fila_imp.addWidget(self.inp_imp_nombre)
        fila_imp.addWidget(self.spn_imp_pct)
        fila_imp.addStretch()
        form.addRow("Impuesto:", fila_imp)

        # Estado inicial: lo guardado; si no hay nada, el país propuesto.
        guardado = paises.pais_configurado()
        # Solo la bienvenida propone el país del sistema; Configuración muestra
        # lo que rige (Perú mientras no se elija otro).
        propuesto = paises.detectar_pais() if proponer_detectado else paises.pais_actual()
        self._poner_pais(iso or guardado or propuesto)
        if guardado and not iso:
            self.cmb_moneda.setCurrentText(paises._cfg('moneda_defecto', 'Soles'))
            self.inp_etiqueta.setText(paises.etiqueta_tributaria())
            nombre, pct = paises.impuesto()
            self.inp_imp_nombre.setText(nombre)
            self.spn_imp_pct.setValue(pct)
        self.cmb_pais.currentIndexChanged.connect(
            lambda _i: self._rellenar(self.cmb_pais.currentData()))

    def _poner_pais(self, iso: str):
        idx = self.cmb_pais.findData(iso)
        self.cmb_pais.setCurrentIndex(max(idx, 0))
        self._rellenar(self.cmb_pais.currentData())

    def _rellenar(self, iso: str):
        p = paises.PAISES[iso]
        self.cmb_moneda.setCurrentText(p['moneda'])
        self.inp_etiqueta.setText(p['id'])
        self.inp_imp_nombre.setText(p['imp'][0])
        self.spn_imp_pct.setValue(p['imp'][1])

    def _editar_monedas(self):
        from views.monedas_dialog import MonedasDialog
        actual = self.cmb_moneda.currentText()
        MonedasDialog(self).exec()
        self.cmb_moneda.blockSignals(True)
        self.cmb_moneda.clear()
        self.cmb_moneda.addItems(list(monedas().keys()))
        self.cmb_moneda.setCurrentText(actual)
        self.cmb_moneda.blockSignals(False)

    def iso(self) -> str:
        return self.cmb_pais.currentData()

    def guardar(self) -> str:
        iso = self.iso()
        paises.aplicar_pais(
            iso,
            moneda=self.cmb_moneda.currentText(),
            etiqueta=self.inp_etiqueta.text().strip() or None,
            imp_nombre=self.inp_imp_nombre.text().strip() or None,
            imp_pct=self.spn_imp_pct.value(),
        )
        self.guardado.emit(iso)
        return iso


class PaisBienvenidaDialog(QDialog):
    """Sale una sola vez, cuando todavía no hay país elegido."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("¿Desde qué país trabajas?")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(460)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(12)

        titulo = QLabel("¿Desde qué país trabajas?")
        titulo.setStyleSheet(f"color:{SLATE_700}; font-size:16px; font-weight:700;")
        vl.addWidget(titulo)
        nota = QLabel(
            "Con esto IngePresupuestos ajusta la moneda, el nombre de la "
            "identificación tributaria (RUC, NIT, RUT…) y el impuesto de los "
            "proyectos nuevos. Puedes cambiarlo cuando quieras en "
            "Configuración → País.\n\n"
            "Cambiar la moneda solo cambia el símbolo y los separadores: los "
            "precios no se convierten, y los de la biblioteca de ejemplo son "
            "referenciales del Perú.")
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color:{SLATE_500}; font-size:12px;")
        vl.addWidget(nota)

        self.form = PaisForm(self, proponer_detectado=True)
        vl.addWidget(self.form)

        botones = QHBoxLayout()
        botones.addStretch()
        btn = QPushButton("Guardar")
        btn.setStyleSheet(BTN_PRIMARY_SS)
        btn.setMinimumHeight(34)
        btn.clicked.connect(self._aceptar)
        botones.addWidget(btn)
        vl.addLayout(botones)

    def _aceptar(self):
        self.form.guardar()
        self.accept()

    def reject(self):
        # Cerrar sin elegir también deja un país (el propuesto): si no, el
        # diálogo volvería a salir en cada arranque.
        self.form.guardar()
        super().reject()


def preguntar_pais_si_falta(parent=None) -> None:
    """Muestra la bienvenida solo si todavía no hay país guardado."""
    if paises.pais_configurado():
        return
    PaisBienvenidaDialog(parent).exec()
