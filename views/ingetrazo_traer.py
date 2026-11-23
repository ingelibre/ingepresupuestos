# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""«Traer de IngeTrazo abierto» y «Mostrar en IngeTrazo», sin IA.

La conversación va en un hilo: medir un modelo grande tarda. El diálogo BIM
(views/bim_dialog.py) se importa solo al usarlo.
"""
from __future__ import annotations

from PySide6.QtCore import QEventLoop, QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QInputDialog, QMessageBox, QProgressDialog

from core import ingetrazo_puente as ip
from utils.i18n import tr


class _Hilo(QThread):
    listo = Signal(object, object)

    def __init__(self, fn, args, parent=None):
        super().__init__(parent)
        self._fn, self._args = fn, args

    def run(self):
        try:
            self.listo.emit(self._fn(*self._args), None)
        except Exception as e:  # noqa: BLE001 — se muestra al usuario
            self.listo.emit(None, e)


class _Fin(QObject):
    """Recibe el resultado EN el hilo principal (método de un QObject suyo)."""

    def __init__(self, bucle):
        super().__init__()
        self._bucle = bucle
        self.res = self.err = None

    def llegar(self, res, err):
        self.res, self.err = res, err
        self._bucle.quit()


def _esperar(parent, texto: str, fn, *args):
    """`fn(*args)` en un hilo con «espere…». Relanza su error."""
    prog = QProgressDialog(texto, "", 0, 0, parent)
    prog.setCancelButton(None)
    prog.setWindowModality(Qt.WindowModal)
    prog.setMinimumDuration(400)
    bucle = QEventLoop()
    fin = _Fin(bucle)
    hilo = _Hilo(fn, args, parent)
    hilo.listo.connect(fin.llegar, Qt.QueuedConnection)
    hilo.start()
    bucle.exec()
    hilo.wait()
    prog.close()
    prog.deleteLater()
    hilo.deleteLater()
    if fin.err is not None:
        raise fin.err
    return fin.res


def pedir_a_ingetrazo(parent, fn, *args):
    """`fn(*args, document_id)`; si hay varios documentos, pregunta cuál.
    None si el usuario canceló o si hubo un error (ya mostrado)."""
    titulo = "IngeTrazo"
    doc = None
    for _ in range(2):
        try:
            return _esperar(parent, tr("Leyendo el modelo de IngeTrazo…"),
                            fn, *args, doc)
        except ip.SinIngeTrazo:
            QMessageBox.information(parent, titulo, tr(
                "No hay ningún IngeTrazo abierto con el puente encendido.\n\n"
                "En IngeTrazo, abre la pestaña IA y pulsa «Iniciar» en Puente "
                "de IA (MCP)."))
            return None
        except ip.VariosDocumentos as e:
            nombres = [f"{i + 1}. {d.get('name') or '?'}"
                       for i, d in enumerate(e.documentos)]
            el, ok = QInputDialog.getItem(parent, titulo,
                                          tr("¿Qué modelo?"), nombres, 0, False)
            if not ok:
                return None
            doc = e.documentos[nombres.index(el)]["document_id"]
        except ip.ErrorIngeTrazo as e:
            QMessageBox.warning(parent, titulo, str(e))
            return None
    return None


def traer_de_ingetrazo(parent, pid: int):
    """Trae el metrado del modelo abierto y lo pasa al diálogo BIM."""
    takeoff = pedir_a_ingetrazo(parent, ip.traer_takeoff)
    if takeoff is None:
        return
    try:
        from views.bim_dialog import abrir_takeoff
    except ImportError:
        QMessageBox.information(parent, "IngeTrazo", tr(
            "Se leyeron {n} elementos, pero esta versión no trae la ventana "
            "BIM.").format(n=len(takeoff["elements"])))
        return
    return abrir_takeoff(parent, pid, takeoff)


def mostrar_en_ingetrazo(parent, global_ids):
    """Selecciona en IngeTrazo. Devuelve su respuesta o None."""
    return pedir_a_ingetrazo(parent, ip.seleccionar_en_ingetrazo,
                             list(global_ids))
