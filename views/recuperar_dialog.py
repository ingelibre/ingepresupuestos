# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Recuperar la contraseña sin internet (issue #32)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout,
)

from utils.auth import restablecer_con_codigo
from utils.i18n import tr
from utils.theme import BTN_PRIMARY_SS, C

_INP_SS = (f"QLineEdit {{ border:1px solid #CBD5E1; border-radius:6px; padding:0 10px;"
           f" font-size:13px; color:{C.text}; background:white; }}")
_TXT_SS = f"color:{C.text}; font-size:12px; background:transparent;"


class CodigoRecuperacionDialog(QDialog):
    """Muestra el código UNA vez: en la base solo queda su hash."""

    def __init__(self, codigo: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Código de recuperación"))
        self.setMinimumWidth(420)
        self.setStyleSheet("QDialog { background:white; }")
        vl = QVBoxLayout(self)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(12)
        nota = QLabel(tr(
            "Guarda este código fuera del equipo (anótalo o imprímelo). Si olvidas "
            "tu contraseña, con él podrás poner una nueva. Solo se muestra esta vez."))
        nota.setWordWrap(True)
        nota.setStyleSheet(_TXT_SS)
        vl.addWidget(nota)
        self.inp_codigo = QLineEdit(codigo)
        self.inp_codigo.setReadOnly(True)
        self.inp_codigo.setAlignment(Qt.AlignCenter)
        self.inp_codigo.setFixedHeight(44)
        self.inp_codigo.setStyleSheet(_INP_SS + "QLineEdit { font-size:17px;"
                                      " font-weight:700; letter-spacing:1px; }")
        vl.addWidget(self.inp_codigo)
        hl = QHBoxLayout()
        b_copiar = QPushButton(tr("Copiar"))
        b_copiar.setFixedHeight(34)
        b_copiar.clicked.connect(
            lambda: QApplication.clipboard().setText(codigo))
        hl.addWidget(b_copiar)
        hl.addStretch()
        b_ok = QPushButton(tr("Ya lo guardé"))
        b_ok.setFixedHeight(34)
        b_ok.setStyleSheet(BTN_PRIMARY_SS)
        b_ok.clicked.connect(self.accept)
        hl.addWidget(b_ok)
        vl.addLayout(hl)


class RecuperarPasswordDialog(QDialog):
    """«¿Olvidaste tu contraseña?»: con código, o el camino si no lo hay."""

    def __init__(self, parent=None, usuario: str = ''):
        super().__init__(parent)
        self.setWindowTitle(tr("Recuperar contraseña"))
        self.setFixedWidth(420)
        self.setStyleSheet("QDialog { background:white; }")
        vl = QVBoxLayout(self)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(8)

        def campo(texto, oculto=False):
            lbl = QLabel(texto)
            lbl.setStyleSheet(_TXT_SS)
            vl.addWidget(lbl)
            inp = QLineEdit()
            inp.setFixedHeight(36)
            inp.setStyleSheet(_INP_SS)
            if oculto:
                inp.setEchoMode(QLineEdit.Password)
            vl.addWidget(inp)
            return inp

        self.inp_user = campo(tr("Usuario o correo electrónico"))
        self.inp_user.setText(usuario)
        self.inp_codigo = campo(tr("Código de recuperación"))
        self.inp_codigo.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        self.inp_p1 = campo(tr("Nueva contraseña"), True)
        self.inp_p2 = campo(tr("Confirmar contraseña"), True)
        self.lbl_err = QLabel("")
        self.lbl_err.setWordWrap(True)
        self.lbl_err.setStyleSheet("color:#C6262E; font-size:12px; background:transparent;")
        vl.addWidget(self.lbl_err)

        self.lbl_sin_codigo = QLabel(tr(
            "<b>¿No tienes código?</b> Las cuentas creadas con versiones anteriores "
            "no lo tienen. Tus presupuestos siguen en este equipo:<br>"
            "1. Si hay otra persona con cuenta de administrador, puede cambiar tu "
            "contraseña en Configuración → Usuarios → Cambiar contraseña.<br>"
            "2. Si no la hay, crea una cuenta nueva en «Crear cuenta» (con otro "
            "usuario y otro correo), entra con ella y cambia tu contraseña en "
            "Configuración → Usuarios. Con «Código de recuperación», en esa misma "
            "página, la próxima vez ya tendrás uno."))
        self.lbl_sin_codigo.setTextFormat(Qt.RichText)
        self.lbl_sin_codigo.setWordWrap(True)
        self.lbl_sin_codigo.setStyleSheet(
            f"{_TXT_SS} QLabel {{ background:#F1F5F9; border-radius:6px; padding:10px; }}")
        self.lbl_sin_codigo.setVisible(False)
        self.btn_sin = QPushButton(tr("No tengo código…"))
        self.btn_sin.setCursor(Qt.PointingHandCursor)
        self.btn_sin.setStyleSheet("QPushButton { border:none; background:transparent;"
                                   f" color:{C.brand}; font-size:12px; text-align:left; }}")
        self.btn_sin.clicked.connect(self._mostrar_camino)
        vl.addWidget(self.btn_sin)
        vl.addWidget(self.lbl_sin_codigo)

        hl = QHBoxLayout()
        hl.addStretch()
        b_c = QPushButton(tr("Cancelar"))
        b_c.setFixedHeight(34)
        b_c.clicked.connect(self.reject)
        hl.addWidget(b_c)
        b_ok = QPushButton(tr("Cambiar contraseña"))
        b_ok.setFixedHeight(34)
        b_ok.setStyleSheet(BTN_PRIMARY_SS)
        b_ok.clicked.connect(self._cambiar)
        hl.addWidget(b_ok)
        vl.addLayout(hl)

    def _mostrar_camino(self):
        self.btn_sin.setVisible(False)
        self.lbl_sin_codigo.setVisible(True)
        self.adjustSize()

    def _cambiar(self):
        p1 = self.inp_p1.text()
        if p1 != self.inp_p2.text():
            self.lbl_err.setText(tr("Las contraseñas no coinciden"))
            return
        ok, msg, nuevo = restablecer_con_codigo(
            self.inp_user.text().strip(), self.inp_codigo.text(), p1)
        if not ok:
            self.lbl_err.setText(tr(msg))
            return
        # El código usado ya no vale: se entrega el siguiente.
        CodigoRecuperacionDialog(nuevo, self).exec()
        self.accept()
