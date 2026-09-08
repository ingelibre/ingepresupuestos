# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Vista previa de la sincronización con Microsoft Project.

Muestra el plan que arma `core.msproject_importer.planificar` —qué
duraciones y qué predecesoras cambiarían, y qué tareas del archivo no son
de aquí— y deja elegir qué aplicar. Es lo que hace segura la sincronización
frente a pegar columnas: nada cambia sin verlo antes.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.msproject_importer import resumen
from utils.theme import BTN_PRIMARY_SS, btn_secondary

SLATE_700 = "#2E3C52"
SLATE_500 = "#485A6C"
SLATE_300 = "#94A3B8"
SLATE_100 = "#E2E8F0"
SILVER_100 = "#F8F9FA"
WHITE = "#FFFFFF"

PASOS_PROJECT = (
    "En Project: abre el XML exportado con «MPP», edita duraciones y "
    "predecesoras, y guarda con Archivo → Guardar como → tipo XML "
    "(Ctrl+S guarda en .mpp, que este programa no lee)."
)


class SincronizarProjectDialog(QDialog):
    """`exec()` devuelve Accepted si el usuario pulsó Aplicar; lee
    `aplicar_duraciones` y `aplicar_predecesoras` para saber qué eligió."""

    def __init__(self, plan: dict, archivo: str, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.aplicar_duraciones = True
        self.aplicar_predecesoras = True
        self.setWindowTitle("Sincronizar con Microsoft Project")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumSize(720, 420)
        self.resize(860, 560)
        self.setStyleSheet(f"QDialog {{ background:{SILVER_100}; }}")
        self._build(archivo)

    def _build(self, archivo: str):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{SLATE_700};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18, 0, 18, 0)
        t = QLabel("Sincronizar con Microsoft Project")
        t.setStyleSheet("color:white; font-size:14px; font-weight:700;"
                        " background:transparent; border:none;")
        hl.addWidget(t)
        hl.addStretch(1)
        v.addWidget(hdr)

        cuerpo = QFrame()
        cuerpo.setStyleSheet(f"background:{SILVER_100};")
        cl = QVBoxLayout(cuerpo)
        cl.setContentsMargins(18, 12, 18, 10)
        cl.setSpacing(8)

        lbl_arch = QLabel(archivo)
        lbl_arch.setStyleSheet(f"color:{SLATE_300}; font-size:10px;")
        lbl_arch.setWordWrap(True)
        cl.addWidget(lbl_arch)

        lbl_res = QLabel(resumen(self.plan))
        lbl_res.setStyleSheet(f"color:{SLATE_700}; font-size:13px; font-weight:700;")
        cl.addWidget(lbl_res)

        p = self.plan
        if p.get('emparejadas', 0) == 0:
            aviso = QLabel(
                "Ninguna tarea del archivo corresponde a una partida de este "
                "proyecto. Esto pasa si el archivo no salió de aquí con el botón "
                "«MPP» (no trae el identificador de cada partida) o si es de otro "
                "proyecto.")
            aviso.setWordWrap(True)
            aviso.setStyleSheet(f"color:#B71C1C; font-size:12px;")
            cl.addWidget(aviso)

        self.chk_dur = QCheckBox(f"Aplicar duraciones ({len(p.get('duraciones', []))})")
        self.chk_dur.setChecked(bool(p.get('duraciones')))
        self.chk_dur.setEnabled(bool(p.get('duraciones')))
        cl.addWidget(self.chk_dur)
        self.tbl_dur = self._tabla(["Ítem", "Partida", "Ahora", "Desde Project"])
        for c in p.get('duraciones', []):
            self._fila(self.tbl_dur, [c['item'], c['descripcion'],
                                      f"{c['antes']} d", f"{c['despues']} d"])
        self.tbl_dur.setVisible(bool(p.get('duraciones')))
        cl.addWidget(self.tbl_dur, 1)

        self.chk_pre = QCheckBox(f"Aplicar predecesoras ({len(p.get('predecesoras', []))})")
        self.chk_pre.setChecked(bool(p.get('predecesoras')))
        self.chk_pre.setEnabled(bool(p.get('predecesoras')))
        cl.addWidget(self.chk_pre)
        self.tbl_pre = self._tabla(["Ítem", "Partida", "Ahora", "Desde Project"])
        for c in p.get('predecesoras', []):
            self._fila(self.tbl_pre, [c['item'], c['descripcion'],
                                      c['antes'] or '—', c['despues'] or '—'])
        self.tbl_pre.setVisible(bool(p.get('predecesoras')))
        cl.addWidget(self.tbl_pre, 1)

        avisos = []
        if p.get('sin_correspondencia'):
            sc = p['sin_correspondencia']
            avisos.append("No se tocan (no son partidas de aquí): "
                          + ", ".join(sc[:6]) + (f" y {len(sc) - 6} más" if len(sc) > 6 else "") + ".")
        for ig in p.get('ignoradas', [])[:4]:
            avisos.append("Vínculo ignorado — " + ig + ".")
        if p.get('no_en_archivo'):
            avisos.append(f"{p['no_en_archivo']} partida(s) de aquí no están en el archivo: "
                          "conservan lo que tienen.")
        if avisos:
            lbl_av = QLabel("\n".join(avisos))
            lbl_av.setWordWrap(True)
            lbl_av.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
            cl.addWidget(lbl_av)

        pasos = QLabel(PASOS_PROJECT + " Las predecesoras se traducen a la numeración "
                       "de este Gantt por el identificador de cada partida, no por el "
                       "número de fila de Project.")
        pasos.setWordWrap(True)
        pasos.setStyleSheet(f"color:{SLATE_300}; font-size:10px; font-style:italic;")
        cl.addWidget(pasos)
        v.addWidget(cuerpo, 1)

        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"background:{WHITE}; border-top:1px solid {SLATE_100};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(18, 8, 18, 8)
        bl.setSpacing(10)
        bl.addStretch(1)
        b_cancel = QPushButton("Cancelar")
        b_cancel.setCursor(Qt.PointingHandCursor)
        b_cancel.setStyleSheet(btn_secondary())
        b_cancel.clicked.connect(self.reject)
        bl.addWidget(b_cancel)
        self.b_ok = QPushButton("Aplicar al cronograma")
        self.b_ok.setCursor(Qt.PointingHandCursor)
        self.b_ok.setStyleSheet(BTN_PRIMARY_SS)
        self.b_ok.clicked.connect(self._aceptar)
        self.b_ok.setEnabled(bool(p.get('duraciones') or p.get('predecesoras')))
        bl.addWidget(self.b_ok)
        v.addWidget(bar)
        for chk in (self.chk_dur, self.chk_pre):
            chk.toggled.connect(self._refrescar_boton)

    def _refrescar_boton(self):
        self.b_ok.setEnabled(self.chk_dur.isChecked() or self.chk_pre.isChecked())

    def _tabla(self, cabeceras):
        t = QTableWidget(0, len(cabeceras))
        t.setHorizontalHeaderLabels(cabeceras)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.setAlternatingRowColors(True)
        t.setShowGrid(False)
        t.setStyleSheet(
            f"QTableWidget {{ background:{WHITE}; border:1px solid {SLATE_100};"
            f" border-radius:6px; font-size:11px; alternate-background-color:{SILVER_100}; }}"
            f"QHeaderView::section {{ background:{SILVER_100}; color:{SLATE_700};"
            f" font-weight:700; font-size:10px; border:none;"
            f" border-bottom:1px solid {SLATE_100}; padding:4px; }}")
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        return t

    @staticmethod
    def _fila(t, valores):
        r = t.rowCount()
        t.insertRow(r)
        for c, val in enumerate(valores):
            it = QTableWidgetItem(str(val))
            if c >= 2:
                it.setTextAlignment(int(Qt.AlignCenter))
            t.setItem(r, c, it)

    def _aceptar(self):
        self.aplicar_duraciones = self.chk_dur.isChecked()
        self.aplicar_predecesoras = self.chk_pre.isChecked()
        self.accept()
