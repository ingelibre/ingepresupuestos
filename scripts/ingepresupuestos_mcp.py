#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Servidor MCP de IngePresupuestos por stdio, desde el código fuente:

    claude mcp add ingepresupuestos -- python3 /ruta/scripts/ingepresupuestos_mcp.py

No necesita el venv: solo la biblioteca estándar. Es también la entrada del
`ingepresupuestos-mcp.exe` de consola (ver ingepresupuestos.spec).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.mcp_stdio import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
