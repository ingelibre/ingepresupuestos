# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (C) 2026 Marco Sumari / Sumari SAC. Todos los derechos reservados.
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software propietario. Uso sujeto al Contrato de Licencia (archivo LICENSE).
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Usuario:
    id: int = 0
    nombre: str = ""
    username: str = ""
    email: str = ""
    password_hash: str = ""
    rol: str = "usuario"      # 'admin' | 'usuario' | 'invitado'
    activo: int = 1
    creado_en: str = ""

    @property
    def es_admin(self) -> bool:
        return self.rol == "admin"

    @property
    def es_invitado(self) -> bool:
        return self.rol == "invitado"
