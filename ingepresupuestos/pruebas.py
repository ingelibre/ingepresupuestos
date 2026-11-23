# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Un presupuesto de mentira para probar un complemento sin abrir el programa.

    from ingepresupuestos.pruebas import presupuesto_ejemplo
    doc = complemento.generar(presupuesto_ejemplo())
"""
from __future__ import annotations

from ingepresupuestos.api import (Insumo, InsumoTotal, LineaPie, Moneda, Partida,
                                  Presupuesto)


def presupuesto_ejemplo() -> Presupuesto:
    acu = (
        Insumo(1, '0101', 'OPERARIO', 'MO', 'hh', 1.0, 0.5, 20.0, 10.0),
        Insumo(2, '0201', 'CEMENTO', 'MAT', 'bls', 0.0, 2.0, 25.0, 50.0),
        Insumo(3, '0301', 'HERRAMIENTAS', 'EQ', '%mo', 0.0, 3.0, 10.0, 0.3),
        Insumo(4, '0401', 'FLETE', 'SC', 'glb', 0.0, 1.0, 5.0, 5.0),
    )
    return Presupuesto(
        id=1, nombre='Vivienda de ejemplo', cliente='Cliente de ejemplo',
        ubicacion='', fecha_costos='01/01/2026', plazo_dias=60, jornada=8.0,
        estado='elaboracion', moneda=Moneda('Soles', 'S/', ',', '.'), decimales=2,
        partidas=(
            Partida(1, '01', 'ESTRUCTURAS', 1, True, '', 0.0, 0.0, 653.0, 0.0, ''),
            Partida(2, '01.01', 'CONCRETO', 2, False, 'm3', 10.0, 65.3, 653.0,
                    16.0, '', acu),
        ),
        pie=(
            LineaPie('Gastos Generales', 'GG', 'pct_cd', 10.0, 65.3, False),
            LineaPie('Utilidad', 'UTIL', 'pct_cd', 5.0, 32.65, False),
            LineaPie('Sub Total', 'SUB', 'subtotal', 0.0, 750.95, False),
            LineaPie('IGV (18%)', 'IGV', 'pct_sub', 18.0, 135.17, True),
        ),
        insumos=tuple(InsumoTotal(i.recurso_id, i.codigo, i.descripcion, i.tipo,
                                  i.unidad, i.precio, i.cantidad * 10,
                                  i.parcial * 10) for i in acu),
        costo_directo=653.0, total=886.12)
