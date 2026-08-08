# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (C) 2026 Marco Sumari / Sumari SAC. Todos los derechos reservados.
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software propietario. Uso sujeto al Contrato de Licencia (archivo LICENSE).
"""Persistencia de estado de sesión (último proyecto abierto, etc.)."""
from PySide6.QtCore import QSettings

_S = lambda: QSettings("ingePresupuestos", "session")


def get_ultimo_proyecto() -> int | None:
    v = _S().value("last_project")
    return int(v) if v is not None else None


def set_ultimo_proyecto(pid: int):
    _S().setValue("last_project", pid)
