# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Aviso de partidas con precio de relleno (1.00) o sin precio (issue #53).

El árbol las marca en rojo; este aviso sale antes de imprimir o exportar un
documento con precios. Se apaga con «No volver a avisar» o en Configuración.
"""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QMessageBox

from utils.i18n import tr

CLAVE = 'avisar_partidas_sin_precio'

# Reportes con precios del presupuesto: solo ahí se avisa.
CON_PRECIOS = {'resumen', 'presupuesto', 'gastos_generales', 'insumos',
               'insumos_sub', 'acus', 'completo', 'cronograma_valorizado',
               'cronograma_adquisiciones', 'cronograma_curva_s'}

_confirmados: set[tuple] = set()     # (proyecto, resumen) ya aceptados hoy


def aviso_activo() -> bool:
    from core.database import get_config
    return get_config(CLAVE, '1') != '0'


def motivo_texto(motivo: str) -> str:
    return {
        'precio_1':   tr("Precio de relleno 1.00: revisa su análisis de costos."),
        'sin_precio': tr("Sin precio: el precio unitario es cero."),
        'sin_acu':    tr("Sin análisis de costos (ACU): el precio no sale de sus insumos."),
    }.get(motivo, '')


def resumen(partidas: list[dict]) -> list[str]:
    """Renglones del aviso; vacío si no hay nada que avisar. Una partida sin
    ACU pero con su precio (presupuesto importado) no se avisa, solo se marca."""
    n1 = sum(1 for p in partidas if p['motivo'] == 'precio_1')
    n0 = sum(1 for p in partidas if p['motivo'] == 'sin_precio')
    out = []
    if n1:
        out.append(tr("{n} partidas con precio 1.00").format(n=n1))
    if n0:
        out.append(tr("{n} partidas sin precio").format(n=n0))
    return out


def confirmar_salida(parent, pid: int, tipo: str = '') -> bool:
    """True si se puede imprimir o exportar. Pregunta una sola vez por sesión
    mientras el proyecto no cambie."""
    if (tipo and tipo not in CON_PRECIOS) or not pid or not aviso_activo():
        return True
    from core.database import get_db, partidas_por_revisar, set_config
    conn = get_db()
    try:
        partidas = partidas_por_revisar(conn, pid)
    finally:
        conn.close()
    lineas = resumen(partidas)
    if not lineas:
        return True
    clave = (pid, tuple((p['partida_id'], p['motivo']) for p in partidas))
    if clave in _confirmados:
        return True

    ejemplos = [p for p in partidas if p['motivo'] != 'sin_acu'][:5]
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(tr("Partidas por revisar"))
    box.setText(tr("Hay {lista}.").format(lista=' · '.join(lineas)))
    box.setInformativeText(
        '\n'.join(f"{p['item']}  {p['descripcion'][:60]}" for p in ejemplos)
        + '\n\n' + tr("En el presupuesto aparecen con el precio en rojo. "
                      "¿Continuar de todos modos?"))
    b_si = box.addButton(tr("Continuar"), QMessageBox.AcceptRole)
    b_no = box.addButton(tr("Volver a revisar"), QMessageBox.RejectRole)
    box.setDefaultButton(b_si)
    box.setEscapeButton(b_no)
    chk = QCheckBox(tr("No volver a avisar"))
    box.setCheckBox(chk)
    box.exec()
    if chk.isChecked():
        set_config(CLAVE, '0')
    if box.clickedButton() is not b_si:
        return False
    _confirmados.add(clave)
    return True
