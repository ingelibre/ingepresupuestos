# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Deshacer/Rehacer en la ventana: escucha los guardados y lleva el historial
de cada proyecto abierto (`core.historial`)."""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import QCoreApplication, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QAbstractItemView, QMessageBox

from core import database
from core.historial import Conflicto, Historial, nivel_de
from utils.i18n import tr


class _Avisos(QObject):
    """Un guardado puede venir de otro hilo: la señal lo trae al principal."""
    guardado = Signal()


_avisos: _Avisos | None = None


def _bus() -> _Avisos:
    global _avisos
    if _avisos is None:
        _avisos = _Avisos(QCoreApplication.instance())
        database.al_guardar = _avisos.guardado.emit
    return _avisos


class HistorialVista(QObject):
    cambio = Signal()

    def __init__(self, vista):
        super().__init__(vista)
        self._vista = vista
        self._h: Historial | None = None
        self._pendiente = False
        self._callado = 0
        _bus().guardado.connect(self._guardado, Qt.QueuedConnection)

    def empezar(self):
        """Con la vista ya cargada: lo de antes no se puede deshacer."""
        if self._h is None:
            try:
                self._h = Historial(self._vista.pid)
            except sqlite3.Error:
                pass

    def _guardado(self):
        # Varios guardados de una misma acción son UN paso.
        if self._h is None or self._pendiente:
            return
        self._pendiente = True
        QTimer.singleShot(0, self, self.al_dia)

    def al_dia(self):
        self._pendiente = False
        if self._h is None:
            return
        try:
            if self._h.revisar(anotar=not self._callado):
                self.cambio.emit()
        except sqlite3.Error:
            pass                    # base ocupada: lo verá el siguiente guardado

    def sin_anotar(self):
        """`with`: lo que la app guarda por su cuenta no es un paso."""
        return _SinAnotar(self)

    # ── Menú ─────────────────────────────────────────────────────────────
    def nombre(self, rehacer=False) -> str | None:
        pila = () if self._h is None else (
            self._h.rehechos if rehacer else self._h.hechos)
        return tr(pila[-1][0]) if pila else None

    def deshacer(self):
        self._hacer('deshacer', tr("Deshacer"))

    def rehacer(self):
        self._hacer('rehacer', tr("Rehacer"))

    def _hacer(self, que, titulo):
        v = self._vista
        if self._h is None:
            return
        if getattr(v, '_spec_modificada', False):
            QMessageBox.information(v, titulo, tr(
                "Hay una especificación técnica sin guardar. Guárdala primero."))
            return
        for t in v.findChildren(QAbstractItemView):
            if t.state() == QAbstractItemView.EditingState:
                return
        self.al_dia()
        pila = self._h.hechos if que == 'deshacer' else self._h.rehechos
        if not pila:
            return
        nivel = nivel_de(pila[-1][1])
        if getattr(v.usuario, 'es_invitado', False) or (
                nivel is not None and not v._require_editable(titulo, nivel)):
            return
        try:
            nombre = getattr(self._h, que)()
        except Conflicto:
            self._h.vaciar()
            self.cambio.emit()
            QMessageBox.warning(v, titulo, tr(
                "Esos datos cambiaron por otro lado y deshacer los perdería. "
                "El historial de este proyecto empieza de nuevo."))
            return
        except (RuntimeError, sqlite3.Error) as e:
            QMessageBox.warning(v, titulo, str(e))
            return
        from views.mcp_puente import refrescar_proyecto_view
        with self.sin_anotar():
            v._tras_deshacer()
            refrescar_proyecto_view(v)
        self.cambio.emit()
        win = v.window()
        if hasattr(win, 'statusBar') and win.statusBar():
            win.statusBar().showMessage(f"{titulo}: {tr(nombre)}", 4000)


class _SinAnotar:
    def __init__(self, hv):
        self._hv = hv

    def __enter__(self):
        if not self._hv._callado:
            self._hv.al_dia()           # lo del usuario, antes, sí se anota
        self._hv._callado += 1

    def __exit__(self, *exc):
        if self._hv._callado == 1:
            self._hv.al_dia()
        self._hv._callado -= 1
