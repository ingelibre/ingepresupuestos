# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Impresión de las partidas seleccionadas en el árbol del proyecto.

Flujo: clic derecho sobre la selección → «Imprimir seleccionadas…» →
elegir qué reportes incluir → vista previa → guardar PDF o imprimir.

Los reportes se generan con `solo_pids`, que recorta las partidas
conservando los títulos padre (ver `pdf_reports.filtrar_items_por_pids`).
El presupuesto sale en modo **extracto**: sin GG, utilidad ni IGV, porque
esos porcentajes son del proyecto completo.
"""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QFrame, QMessageBox, QFileDialog, QWidget, QApplication,
)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog

from utils.theme import BTN_PRIMARY_SS

SLATE_700 = "#273445"
SLATE_500 = "#485A6C"
SLATE_300 = "#667885"
SILVER_300 = "#D4D4D4"
WHITE = "#FFFFFF"

#: (clave del reporte, etiqueta, marcado por defecto)
REPORTES = [
    ('acus',             "Análisis de Costos Unitarios", True),
    ('metrados',         "Hoja de Metrados",             False),
    ('especificaciones', "Especificaciones Técnicas",    False),
    ('presupuesto',      "Presupuesto (extracto)",       False),
]

BTN_GHOST_SS = (
    f"QPushButton {{ background:{WHITE}; color:{SLATE_500};"
    f" border:1px solid {SILVER_300}; border-radius:6px;"
    f" padding:8px 16px; font-size:12px; font-weight:600; }}"
    f"QPushButton:hover {{ border-color:#F37329; color:#C0621A; }}"
)


class ImprimirSeleccionDialog(QDialog):
    """Elige qué reportes generar para las partidas seleccionadas."""

    def __init__(self, parent, n_partidas: int):
        super().__init__(parent)
        self.setWindowTitle("Imprimir partidas seleccionadas")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(420)
        self.setStyleSheet(
            f"QDialog {{ background:{WHITE}; }}"
            f"QDialog QLabel {{ background:transparent; border:none; }}"
        )
        self._checks: dict[str, QCheckBox] = {}
        self._build(n_partidas)

    def _build(self, n: int):
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)

        titulo = QLabel(
            f"{n} partida{'s' if n != 1 else ''} seleccionada{'s' if n != 1 else ''}"
        )
        titulo.setStyleSheet(
            f"color:{SLATE_700}; font-size:15px; font-weight:700;")
        v.addWidget(titulo)

        sub = QLabel("¿Qué quieres incluir en la impresión?")
        sub.setStyleSheet(f"color:{SLATE_500}; font-size:12px;")
        v.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        v.addWidget(sep)

        for clave, etiqueta, por_defecto in REPORTES:
            chk = QCheckBox(etiqueta)
            chk.setChecked(por_defecto)
            chk.setCursor(Qt.PointingHandCursor)
            chk.setStyleSheet(f"color:{SLATE_700}; font-size:13px; padding:3px 0;")
            chk.toggled.connect(self._actualizar_estado)
            self._checks[clave] = chk
            v.addWidget(chk)

        self.lbl_aviso = QLabel(
            "El extracto del presupuesto no lleva gastos generales, utilidad "
            "ni IGV: esos porcentajes son del proyecto completo."
        )
        self.lbl_aviso.setWordWrap(True)
        self.lbl_aviso.setStyleSheet(
            f"color:{SLATE_300}; font-size:11px; font-style:italic;"
            f" padding:2px 0 0 22px;")
        self.lbl_aviso.setVisible(False)
        v.addWidget(self.lbl_aviso)

        v.addSpacing(4)
        h = QHBoxLayout(); h.setSpacing(8)
        h.addStretch(1)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet(BTN_GHOST_SS)
        btn_cancel.clicked.connect(self.reject)
        h.addWidget(btn_cancel)

        self.btn_ok = QPushButton("Vista previa")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setStyleSheet(BTN_PRIMARY_SS)
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        h.addWidget(self.btn_ok)
        v.addLayout(h)

        self._actualizar_estado()

    def _actualizar_estado(self):
        """El botón solo se habilita con al menos un reporte marcado."""
        self.btn_ok.setEnabled(bool(self.seleccion()))
        self.lbl_aviso.setVisible(self._checks['presupuesto'].isChecked())

    def seleccion(self) -> list[str]:
        """Claves de reporte marcadas, en el orden de `REPORTES`."""
        return [c for c, _e, _d in REPORTES if self._checks[c].isChecked()]


class VistaPreviaDialog(QDialog):
    """Vista previa del PDF con opción de guardarlo o mandarlo a imprimir."""

    def __init__(self, parent, pdf_path: str, titulo: str):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self.setWindowTitle(f"Vista previa — {titulo}")
        self.setWindowModality(Qt.WindowModal)
        self.resize(880, 720)
        self.setStyleSheet(f"QDialog {{ background:{WHITE}; }}")
        self._build()

    def _build(self):
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._doc = QPdfDocument(self)
        self._doc.load(self._pdf_path)
        vista = QPdfView(self)
        vista.setDocument(self._doc)
        vista.setPageMode(QPdfView.PageMode.MultiPage)
        vista.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        v.addWidget(vista, 1)

        barra = QWidget()
        barra.setStyleSheet(f"background:{WHITE}; border-top:1px solid {SILVER_300};")
        h = QHBoxLayout(barra)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(8)

        n = self._doc.pageCount()
        lbl = QLabel(f"{n} página{'s' if n != 1 else ''}")
        lbl.setStyleSheet(f"color:{SLATE_300}; font-size:11px; border:none;")
        h.addWidget(lbl)
        h.addStretch(1)

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setCursor(Qt.PointingHandCursor)
        btn_cerrar.setStyleSheet(BTN_GHOST_SS)
        btn_cerrar.clicked.connect(self.reject)
        h.addWidget(btn_cerrar)

        btn_pdf = QPushButton("Guardar PDF…")
        btn_pdf.setCursor(Qt.PointingHandCursor)
        btn_pdf.setStyleSheet(BTN_GHOST_SS)
        btn_pdf.clicked.connect(self._guardar)
        h.addWidget(btn_pdf)

        btn_imp = QPushButton("Imprimir…")
        btn_imp.setCursor(Qt.PointingHandCursor)
        btn_imp.setStyleSheet(BTN_PRIMARY_SS)
        btn_imp.setDefault(True)
        btn_imp.clicked.connect(self._imprimir)
        h.addWidget(btn_imp)

        v.addWidget(barra)

    def _guardar(self):
        destino, _ = QFileDialog.getSaveFileName(
            self, "Guardar PDF", "partidas-seleccionadas.pdf", "PDF (*.pdf)")
        if not destino:
            return
        if not destino.lower().endswith('.pdf'):
            destino += '.pdf'
        try:
            import shutil
            shutil.copy(self._pdf_path, destino)
        except OSError as e:
            QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{e}")
            return
        QMessageBox.information(self, "Guardado", f"Archivo guardado:\n{destino}")

    def _imprimir(self):
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Imprimir")
        if dlg.exec() != QDialog.Accepted:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from utils.impresion import pintar_pdf_en_printer
            pintar_pdf_en_printer(printer, self._pdf_path)
        except Exception as e:                      # noqa: BLE001
            QMessageBox.warning(self, "Error de impresión", str(e))
        finally:
            QApplication.restoreOverrideCursor()


def _unir_pdfs(rutas: list[str], destino: str) -> bool:
    """Une los PDFs en uno solo. Devuelve False si falta `pypdf`."""
    try:
        from pypdf import PdfWriter
    except ImportError:
        return False
    w = PdfWriter()
    for r in rutas:
        w.append(r)
    with open(destino, 'wb') as f:
        w.write(f)
    return True


def imprimir_seleccion(parent, pid: int, pids: list[int]) -> None:
    """Punto de entrada desde el menú contextual del árbol de partidas."""
    if not pids:
        QMessageBox.information(
            parent, "Sin selección",
            "Selecciona al menos una partida (los títulos no cuentan).")
        return

    dlg = ImprimirSeleccionDialog(parent, len(pids))
    if dlg.exec() != QDialog.Accepted:
        return
    tipos = dlg.seleccion()

    from core.pdf_reports import generar_pdf_archivo
    QApplication.setOverrideCursor(Qt.WaitCursor)
    temporales: list[str] = []
    try:
        for tipo in tipos:
            tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            tmp.close()
            # SIN portada, y no es cosmético: la portada pinta «Monto Total»
            # con el total del proyecto ENTERO (`calcular_totales` sobre el
            # pid, ajeno al filtro). En un extracto de 4 partidas eso sería
            # un monto que no corresponde a lo impreso. Además evita una
            # portada por cada reporte en el PDF combinado.
            generar_pdf_archivo(tipo, pid, tmp.name,
                                with_cover=False, solo_pids=set(pids))
            temporales.append(tmp.name)

        if len(temporales) == 1:
            final = temporales[0]
        else:
            unido = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            unido.close()
            if not _unir_pdfs(temporales, unido.name):
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(
                    parent, "Falta pypdf",
                    "Para combinar varios reportes en un solo PDF se necesita "
                    "el paquete «pypdf».\n\nInstálalo con:\n  pip install pypdf"
                    "\n\nMientras tanto, imprime un reporte a la vez.")
                return
            final = unido.name
            temporales.append(unido.name)
    except Exception as e:                          # noqa: BLE001
        QApplication.restoreOverrideCursor()
        import traceback; traceback.print_exc()
        QMessageBox.critical(parent, "Error",
                             f"No se pudo generar la impresión:\n{e}")
        for r in temporales:
            try: os.unlink(r)
            except OSError: pass
        return
    finally:
        QApplication.restoreOverrideCursor()

    try:
        VistaPreviaDialog(parent, final, "partidas seleccionadas").exec()
    finally:
        # El QPdfDocument ya cerró el archivo al destruirse el diálogo.
        for r in temporales:
            try: os.unlink(r)
            except OSError: pass
