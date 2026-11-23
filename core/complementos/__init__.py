# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Complementos: paquetes de datos por país y extensiones con código.

    esquema   complemento.json: validación estricta
    paquete   leer un .zip o una carpeta sin fiarse de nada; la huella
    gestor    instalar, activar, desinstalar; qué está activo
    registro  lo que el núcleo consulta (países, unidades, vocabulario…)
    cargador  ejecutar el código de los complementos activos
    contexto  los datos y la escritura que recibe un complemento
    reportes  Documento → PDF o Excel
    plantilla, cli   herramientas para quien desarrolla

Guía: docs/complementos.md. La API pública es `ingepresupuestos.api`.
Ninguna herramienta MCP toca este paquete: la IA no instala ni activa nada.
"""
