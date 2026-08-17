# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Diálogo de fichas técnicas (PDF) adjuntas — compartido.

Lo usan los requerimientos de Control de Obra y las especificaciones
técnicas de las partidas: mismo diálogo, distinto dueño. El dueño se
inyecta con tres callbacks (listar / agregar / quitar) para que el diálogo
no sepa de tablas.
"""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QFileDialog, QMessageBox,
)

_ORANGE = "#F37329"
_SLATE_700 = "#273445"
_SLATE_500 = "#485A6C"
_SILVER_200 = "#F0F1F2"
_SILVER_300 = "#D4D4D4"
_SELECT_BG = "#FDEBD0"


class FichasDialog(QDialog):
    """Gestión de fichas técnicas (PDF) del dueño que la invoca.

    `listar()` → list[{nombre, ruta}] · `agregar(ruta)` → {nombre, ruta}
    · `quitar(nombre)`. `intro` es el texto explicativo de cabecera.
    """

    def __init__(self, listar, agregar, quitar, intro: str, parent=None):
        super().__init__(parent)
        self._listar = listar
        self._agregar_cb = agregar
        self._quitar_cb = quitar
        self.setWindowTitle("Fichas técnicas adjuntas")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumSize(480, 320)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16); v.setSpacing(8)

        lbl = QLabel(intro)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{_SLATE_500}; font-size:11px;"
                          " background:transparent; border:none;")
        v.addWidget(lbl)

        self.lista = QListWidget()
        self.lista.setStyleSheet(
            f"QListWidget {{ background:white; border:1px solid {_SILVER_300};"
            f" border-radius:6px; font-size:12px; }}"
            f"QListWidget::item {{ padding:5px 8px;"
            f" border-bottom:1px solid {_SILVER_200}; }}"
            f"QListWidget::item:selected {{ background:{_SELECT_BG};"
            f" color:{_SLATE_700}; }}")
        self.lista.itemDoubleClicked.connect(self._abrir)
        v.addWidget(self.lista, 1)

        fila = QHBoxLayout(); fila.setSpacing(6)
        b_add = QPushButton("＋ Agregar PDF…")
        b_add.setStyleSheet(
            f"QPushButton {{ background:{_ORANGE}; color:white; border:none;"
            f" border-radius:6px; padding:6px 14px; font-weight:600; }}")
        b_add.clicked.connect(self._agregar)
        b_del = QPushButton("Quitar")
        b_del.clicked.connect(self._quitar)
        b_ok = QPushButton("Cerrar")
        b_ok.clicked.connect(self.accept)
        for b in (b_del, b_ok):
            b.setStyleSheet(
                f"QPushButton {{ background:white; color:{_SLATE_700};"
                f" border:1px solid {_SILVER_300}; border-radius:6px;"
                f" padding:6px 14px; }}")
        fila.addWidget(b_add); fila.addWidget(b_del)
        fila.addStretch(); fila.addWidget(b_ok)
        v.addLayout(fila)
        self._recargar()

    def _recargar(self):
        from core.adjuntos import texto_adjunto_pdf
        self.lista.clear()
        for a in self._listar():
            legible = bool(texto_adjunto_pdf(a.get('ruta') or '',
                                             max_pags=1, max_chars=200))
            marca = "📄" if legible else "🖼"
            extra = "" if legible else "   (escaneado: solo anexo, la IA no lo lee)"
            it = QListWidgetItem(f"{marca}  {a.get('nombre')}{extra}")
            it.setData(Qt.UserRole, a.get('nombre'))
            it.setToolTip(a.get('ruta') or '')
            self.lista.addItem(it)

    def _agregar(self):
        from core.adjuntos import texto_adjunto_pdf
        rutas, _ = QFileDialog.getOpenFileNames(
            self, "Fichas técnicas (PDF)", "", "PDF (*.pdf)")
        escaneadas = []
        for ruta in rutas:
            a = self._agregar_cb(ruta)
            if not texto_adjunto_pdf(a['ruta'], max_pags=1, max_chars=200):
                escaneadas.append(a['nombre'])
        if escaneadas:
            QMessageBox.information(self, "Ficha escaneada",
                "Estas fichas no tienen texto legible (parecen escaneadas):\n\n"
                + "\n".join(f"• {n}" for n in escaneadas)
                + "\n\nIrán como ANEXO en el PDF, pero la IA no podrá leer su "
                  "contenido. Si quieres que la IA las use, busca la versión "
                  "digital del fabricante.")
        self._recargar()

    def _quitar(self):
        it = self.lista.currentItem()
        if not it:
            return
        self._quitar_cb(it.data(Qt.UserRole))
        self._recargar()

    def _abrir(self, it):
        for a in self._listar():
            if a.get('nombre') == it.data(Qt.UserRole):
                QDesktopServices.openUrl(QUrl.fromLocalFile(a.get('ruta') or ''))
                return
