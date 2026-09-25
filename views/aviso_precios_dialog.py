# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Aviso de precios de referencia del Perú al traer ACU de la biblioteca.

La biblioteca que trae el programa tiene precios del Perú en soles. En un
proyecto en pesos colombianos, «Sugerir partidas → plantilla local» importó
53 partidas con esos precios etiquetados COP$ sin avisar nada (vídeo de
DriveMeca, 23 sep 2026; issue #11). Los rendimientos y las cantidades sí
sirven en cualquier país: por eso la opción de traer solo la estructura.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox, QMessageBox

CON_PRECIOS = 'con_precios'
SOLO_ESTRUCTURA = 'solo_estructura'

_QS_CLAVE = "avisos/precios_referencia_peru"


def moneda_de_proyecto(pid: int) -> str:
    from core.database import get_db
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT moneda FROM proyectos WHERE id=?", (pid,)).fetchone()
    finally:
        conn.close()
    return (row['moneda'] if row else None) or 'Soles'


def preguntar_precios(parent, moneda: str) -> str | None:
    """CON_PRECIOS, SOLO_ESTRUCTURA o None (cancelar).

    En soles no pregunta nada: los precios son de ahí. Si el usuario marcó
    «No volver a preguntar», devuelve la opción que eligió aquella vez."""
    if (moneda or 'Soles') == 'Soles':
        return CON_PRECIOS
    qs = QSettings("ingePresupuestos", "avisos")
    recordada = qs.value(_QS_CLAVE, "")
    if recordada in (CON_PRECIOS, SOLO_ESTRUCTURA):
        return recordada

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Precios de referencia del Perú")
    box.setText(
        "<b>Los ACU de la biblioteca traen precios de referencia del Perú, "
        "en soles.</b>")
    box.setInformativeText(
        f"Este proyecto está en {moneda}. Los rendimientos y las cantidades "
        "sirven en cualquier país; los precios no.<br><br>"
        "<b>Solo la estructura</b> trae rendimientos y cantidades, y cada "
        "insumo toma el precio que ya tiene en este proyecto (o 0 si es "
        "nuevo). Después puedes cargar tus precios en la pestaña Insumos o "
        "importar tu propio catálogo de insumos.")
    b_estr = box.addButton("Solo la estructura", QMessageBox.AcceptRole)
    b_con = box.addButton("Con los precios del Perú", QMessageBox.AcceptRole)
    box.addButton("Cancelar", QMessageBox.RejectRole)
    box.setDefaultButton(b_estr)
    chk = QCheckBox("No volver a preguntar")
    box.setCheckBox(chk)
    box.exec()

    pulsado = box.clickedButton()
    if pulsado is b_estr:
        eleccion = SOLO_ESTRUCTURA
    elif pulsado is b_con:
        eleccion = CON_PRECIOS
    else:
        return None
    if chk.isChecked():
        qs.setValue(_QS_CLAVE, eleccion)
    return eleccion
