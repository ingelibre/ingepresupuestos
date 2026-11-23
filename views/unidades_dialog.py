# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Lista desplegable de unidades y gestor de variantes (issue #55)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QCompleter, QDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from core import unidades
from core.database import get_db
from utils.i18n import tr
from utils.theme import BTN_PRIMARY_SS, C

_FLECHA = Path(__file__).resolve().parent.parent / "resources" / "icons" / "arrow_down.svg"
_POPUP_SS = (
    "QListView { background:white; border:1px solid #D4D4D4;"
    " border-radius:6px; font-size:12px; padding:4px; color:#273445; }"
    "QListView::item { padding:4px 10px; }"
    "QListView::item:selected { background:#FDE8D0; color:#7A3800; }")


def poner_lista(inp: QLineEdit) -> QLineEdit:
    """Da al campo de unidad una lista desplegable (▾). Sigue siendo editable:
    se puede escribir cualquier unidad; al escribir, la lista filtra."""
    comp = QCompleter(unidades.lista(), inp)
    comp.setCaseSensitivity(Qt.CaseInsensitive)
    comp.setFilterMode(Qt.MatchContains)
    comp.setCompletionMode(QCompleter.PopupCompletion)
    comp.setMaxVisibleItems(12)
    comp.popup().setStyleSheet(_POPUP_SS)
    inp.setCompleter(comp)

    def abrir():
        comp.setCompletionPrefix('')        # todas, no solo las que casan
        inp.setFocus()
        comp.complete()
    act = QAction(QIcon(str(_FLECHA)), tr("Elegir de la lista"), inp)
    act.triggered.connect(abrir)
    inp.addAction(act, QLineEdit.TrailingPosition)
    inp.accion_lista = act
    return inp


class GestorUnidadesDialog(QDialog):
    """Vista previa de las grafías repetidas; solo une las marcadas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Unidades repetidas"))
        self.resize(720, 480)
        self.cambiadas = 0
        vl = QVBoxLayout(self)
        vl.setContentsMargins(18, 16, 18, 16)
        vl.setSpacing(10)
        nota = QLabel(tr(
            "Une las formas de escribir una misma unidad. Solo cambia el texto: "
            "ningún precio ni cantidad se recalcula. Los presupuestos en revisión, "
            "aprobados o ejecutados no se tocan."))
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color:{C.text}; font-size:12px;")
        vl.addWidget(nota)

        conn = get_db()
        self._grupos = unidades.variantes(conn)
        conn.close()
        self.tbl = QTableWidget(len(self._grupos), 6)
        self.tbl.setHorizontalHeaderLabels([
            tr("Se escribe hoy"), tr("Quedará como"), tr("Insumos"),
            tr("Biblioteca"), tr("Partidas"), tr("Gastos generales")])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._combos = []
        for r, g in enumerate(self._grupos):
            it = QTableWidgetItem("   ".join(f"{u} ({n})" for u, n in g['grafias'].items()))
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.tbl.setItem(r, 0, it)
            cmb = QComboBox()
            cmb.addItems(list(dict.fromkeys([g['sugerida'], *g['grafias']])))
            self.tbl.setCellWidget(r, 1, cmb)
            self._combos.append(cmb)
            for c, t in enumerate(('recursos', 'biblioteca_cu', 'partidas',
                                   'gastos_generales'), start=2):
                n = QTableWidgetItem(str(g['tablas'][t] or ''))
                n.setFlags(Qt.ItemIsEnabled)
                n.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl.setItem(r, c, n)
        self.tbl.itemChanged.connect(lambda _i: self._actualizar())
        vl.addWidget(self.tbl, 1)

        hl = QHBoxLayout()
        b_todas = QPushButton(tr("Marcar todas"))
        b_todas.clicked.connect(self.marcar_todas)
        hl.addWidget(b_todas)
        self.lbl = QLabel("")
        hl.addWidget(self.lbl)
        hl.addStretch()
        b_no = QPushButton(tr("Cancelar"))
        b_no.clicked.connect(self.reject)
        hl.addWidget(b_no)
        self.btn_unir = QPushButton(tr("Unir las marcadas"))
        self.btn_unir.setStyleSheet(BTN_PRIMARY_SS)
        self.btn_unir.clicked.connect(self._unir)
        hl.addWidget(self.btn_unir)
        vl.addLayout(hl)
        for cmb in self._combos:
            cmb.currentIndexChanged.connect(lambda _i: self._actualizar())
        self._actualizar()

    def marcar_todas(self):
        for r in range(self.tbl.rowCount()):
            self.tbl.item(r, 0).setCheckState(Qt.Checked)

    def cambios(self) -> dict:
        out = {}
        for r, g in enumerate(self._grupos):
            if self.tbl.item(r, 0).checkState() == Qt.Checked:
                destino = self._combos[r].currentText()
                out.update({u: destino for u in g['grafias'] if u != destino})
        return out

    def _actualizar(self):
        cambios = self.cambios()
        n = sum(g['grafias'].get(u, 0) for g in self._grupos for u in cambios)
        self.lbl.setText(
            tr("Cambiarán {n} filas").format(n=n) if n else
            "" if self._grupos else tr("No hay unidades repetidas."))
        self.btn_unir.setEnabled(bool(cambios))

    def _unir(self):
        conn = get_db()
        try:
            self.cambiadas = unidades.unir(conn, self.cambios())
        except Exception as e:
            QMessageBox.warning(self, tr("Unidades repetidas"), str(e))
            return
        finally:
            conn.close()
        self.accept()
