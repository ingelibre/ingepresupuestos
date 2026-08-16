# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
from dataclasses import dataclass
from typing import Optional


@dataclass
class Recurso:
    id: int = 0
    codigo: str = ""        # 7 dígitos: IU(2) + seq(5). Ej: '4700023'
    descripcion: str = ""
    tipo: str = "MAT"       # 'MO' | 'MAT' | 'EQ'
    unidad: str = ""        # '%MO'/'%mat'/'%eq' → overhead, precio=0 siempre
    precio: float = 0.0     # precio REFERENCIAL del catálogo
    indice_inei: str = ""   # 2 dígitos. Ej: '47'=MO, '48'=EQ, '39'=MAT/IPC

    @property
    def es_overhead(self) -> bool:
        return self.unidad.startswith('%')
