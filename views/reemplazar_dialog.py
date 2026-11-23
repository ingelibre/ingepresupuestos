# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Buscar y reemplazar en las partidas del proyecto, viendo antes el cambio."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from core.database import get_db
from utils.i18n import tr

MAX_FILAS = 2000


def reemplazos(filas, campo, buscar, poner, mayus=False, entera=False):
    """[(id, ítem, antes, después)] de las filas que cambian."""
    if not buscar:
        return []
    patron = re.escape(buscar)
    if entera:
        patron = rf"(?<!\w){patron}(?!\w)"
    if campo == 'unidad':           # «m» no debe tocar «m2»: la unidad entera
        patron = rf"^\s*{re.escape(buscar)}\s*$"
    rx = re.compile(patron, 0 if mayus else re.IGNORECASE)
    out = []
    for f in filas:
        antes = f[campo] or ''
        despues = rx.sub(lambda _m: poner, antes)
        if despues != antes and despues.strip():
            out.append((f['id'], f['item'], antes, despues))
    return out


class ReemplazarDialog(QDialog):
    def __init__(self, pid, parent=None):
        super().__init__(parent)
        self.pid = pid
        self.setWindowTitle(tr("Buscar y reemplazar"))
        self.setWindowModality(Qt.WindowModal)
        self.resize(760, 520)
        vl = QVBoxLayout(self)
        fl = QFormLayout()
        self.cmb = QComboBox()
        self.cmb.addItem(tr("Descripción"), 'descripcion')
        self.cmb.addItem(tr("Unidad"), 'unidad')
        self.ed_buscar, self.ed_poner = QLineEdit(), QLineEdit()
        fl.addRow(tr("En") + ":", self.cmb)
        fl.addRow(tr("Buscar") + ":", self.ed_buscar)
        fl.addRow(tr("Reemplazar por") + ":", self.ed_poner)
        vl.addLayout(fl)
        hl = QHBoxLayout()
        self.chk_mayus = QCheckBox(tr("Distinguir mayúsculas"))
        self.chk_entera = QCheckBox(tr("Solo palabras completas"))
        hl.addWidget(self.chk_mayus)
        hl.addWidget(self.chk_entera)
        hl.addStretch()
        vl.addLayout(hl)
        self.lista = QTreeWidget()
        self.lista.setHeaderLabels([tr("Ítem"), tr("Antes"), tr("Después")])
        self.lista.setRootIsDecorated(False)
        self.lista.setColumnWidth(0, 110)
        self.lista.setColumnWidth(1, 300)
        vl.addWidget(self.lista, 1)
        hl = QHBoxLayout()
        self.lbl = QLabel()
        hl.addWidget(self.lbl, 1)
        self.btn = QPushButton(tr("Reemplazar"))
        self.btn.clicked.connect(self._aplicar)
        b = QPushButton(tr("Cancelar"))
        b.setAutoDefault(False)
        b.clicked.connect(self.reject)
        hl.addWidget(b)
        hl.addWidget(self.btn)
        vl.addLayout(hl)
        conn = get_db()
        self._filas = conn.execute(
            "SELECT id, item, descripcion, unidad FROM partidas_ppto WHERE"
            " proyecto_id=? ORDER BY item", (pid,)).fetchall()
        conn.close()
        for w in (self.ed_buscar, self.ed_poner):
            w.textChanged.connect(self._ver)
        self.cmb.currentIndexChanged.connect(self._ver)
        for w in (self.chk_mayus, self.chk_entera):
            w.toggled.connect(self._ver)
        self.lista.itemChanged.connect(lambda *_: self._contar())
        self._ver()

    def _ver(self, *_):
        self.chk_entera.setEnabled(self.cmb.currentData() == 'descripcion')
        self._cambios = reemplazos(
            self._filas, self.cmb.currentData(), self.ed_buscar.text(),
            self.ed_poner.text(), self.chk_mayus.isChecked(),
            self.chk_entera.isChecked())
        self.lista.blockSignals(True)
        self.lista.clear()
        for i, item, antes, despues in self._cambios[:MAX_FILAS]:
            it = QTreeWidgetItem([item, antes, despues])
            it.setData(0, Qt.UserRole, (i, despues))
            it.setCheckState(0, Qt.Checked)
            self.lista.addTopLevelItem(it)
        self.lista.blockSignals(False)
        self._contar()

    def _marcados(self):
        return [self.lista.topLevelItem(k).data(0, Qt.UserRole)
                for k in range(self.lista.topLevelItemCount())
                if self.lista.topLevelItem(k).checkState(0) == Qt.Checked]

    def _contar(self):
        n = len(self._marcados())
        self.btn.setEnabled(n > 0)
        self.lbl.setText(tr("{n} de {t} por cambiar").format(
            n=n, t=len(self._cambios)))

    def _aplicar(self):
        campo = self.cmb.currentData()
        conn = get_db()
        try:
            conn.executemany(
                f"UPDATE partidas SET {campo}=? WHERE id=? AND proyecto_id=?",
                [(txt, i, self.pid) for i, txt in self._marcados()])
            conn.commit()
        finally:
            conn.close()
        self.accept()
