# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (C) 2026 Marco Sumari / Sumari SAC. Todos los derechos reservados.
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software propietario. Uso sujeto al Contrato de Licencia (archivo LICENSE).
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
