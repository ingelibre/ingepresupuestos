# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Envoltura histórica del importador IFC. La lectura vive en
`core/ifc_lector.py` (STEP) y `core/bim_modelo.py` (elementos y cantidades)."""

from core.ifc_lector import numero


def _float_val(s):
    """Número STEP; los nulos del formato («$», «*») valen 0."""
    return numero((s or '').strip().encode()) or 0.0


def parse_ifc(filepath):
    """``(info, partidas)`` de un .ifc para `guardar_importacion`.

    Agrupa por clase + tipo + unidad. Lo que el modelo no mide queda con
    metrado 0 (antes se ponía 1.0 en silencio). Para conservar los elementos
    y poder actualizar, usar `bim_modelo.crear_proyecto`."""
    from core.bim_modelo import con_titulos, leer_ifc, proponer_partidas
    m = leer_ifc(filepath)
    info = {'nombre': m.nombre, 'cliente': m.info['cliente'],
            'ubicacion': m.info['ubicacion'], 'sub_presupuesto': '', 'costo_al': ''}
    partidas = con_titulos(proponer_partidas(m))
    for p in partidas:
        p['metrado'] = round(p['metrado'], 4)
    return info, partidas
