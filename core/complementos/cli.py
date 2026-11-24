# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Línea de comandos para quien desarrolla. No instala, no activa y no ejecuta
código del complemento: lo lee.

    ingepresupuestos --nuevo-complemento "Nombre" [carpeta] [--datos]
    ingepresupuestos --validar-complemento <carpeta o .zip>
    ingepresupuestos --empaquetar-complemento <carpeta> [destino.zip]
    ingepresupuestos --catalogo-complemento <carpeta> <repositorio>
    ingepresupuestos --textos-de-complemento <palabra>
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from core.complementos import esquema, paquete, plantilla

_INTERNOS = {'core', 'views', 'widgets', 'utils', 'models', 'worker', 'main',
             'sqlite3'}


def textos_del_programa() -> set[str]:
    """Los textos de la interfaz que el vocabulario puede cambiar."""
    raiz = Path(__file__).resolve().parents[2]
    try:
        return set(json.loads((raiz / 'resources' / 'i18n' / 'pt_BR.json')
                              .read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return set()


def revisar(paq: paquete.Paquete) -> tuple[list[str], list[str]]:
    """(errores, avisos) más allá del esquema. Sin ejecutar nada."""
    errores, avisos = [], []
    m = paq.manifiesto
    for rel, b in paq.archivos.items():
        if not rel.endswith('.py'):
            continue
        try:
            arbol = ast.parse(b, filename=rel)
        except (SyntaxError, ValueError) as e:
            errores.append(f"{rel}: no compila ({e})")
            continue
        if rel == m['codigo'] and not any(
                isinstance(n, ast.FunctionDef) and n.name == 'registrar'
                for n in arbol.body):
            errores.append(f"{rel}: no define registrar(app)")
        for n in ast.walk(arbol):
            mods = ([a.name for a in n.names] if isinstance(n, ast.Import) else
                    [n.module or ''] if isinstance(n, ast.ImportFrom)
                    and not n.level else [])
            for x in mods:
                if x.split('.')[0] in _INTERNOS:
                    avisos.append(f"{rel}:{n.lineno}: usa «{x}», que no es parte "
                                  "de la API y puede cambiar en cualquier versión")
    from ingepresupuestos.api import API_VERSION
    if (m['api_version'] or 1) > API_VERSION:
        avisos.append(f"pide la API {m['api_version']}; este programa tiene la "
                      f"{API_VERSION}")
    conocidos = textos_del_programa()
    if conocidos:
        for v in m['vocabulario']:
            for t in v['textos']:
                if t not in conocidos:
                    avisos.append(f"vocabulario: el programa no usa el texto «{t}»")
    if m['autor'] == 'Tu nombre':
        avisos.append("autor: sigue siendo «Tu nombre»")
    return errores, avisos


def _validar(ruta: str) -> int:
    try:
        paq = paquete.leer(ruta)
    except paquete.ErrorPaquete as e:
        print("NO es válido:")
        for linea in str(e).splitlines():
            print("  -", linea)
        return 1
    errores, avisos = revisar(paq)
    m = paq.manifiesto
    print(f"{m['nombre']} {m['version']} ({m['id']}) — "
          + ("con código" if paq.con_codigo else "solo datos"))
    print(f"archivos: {len(paq.archivos)}   huella: {paq.huella}")
    for d in esquema.tiene_datos(m):
        print(f"  {d}: {len(m[d])}")
    for a in avisos:
        print("  aviso:", a)
    for e in errores:
        print("  ERROR:", e)
    print("NO es válido" if errores else "Válido")
    return 1 if errores else 0


def _consola() -> None:
    """El .exe de Windows no tiene consola: se usa la de quien lo lanzó."""
    if sys.stdout is not None or not sys.platform.startswith('win'):
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open('CONOUT$', 'w', encoding='utf-8', errors='replace')
    except (OSError, AttributeError):
        pass


def main(argv: list[str]) -> int:
    _consola()
    if sys.stdout is None:
        import io
        sys.stdout = io.StringIO()
    op, resto = argv[0], argv[1:]
    datos = '--datos' in resto
    resto = [a for a in resto if a != '--datos']
    if op == '--textos-de-complemento' and resto:
        for t in sorted(t for t in textos_del_programa()
                        if resto[0].lower() in t.lower()):
            print(json.dumps(t, ensure_ascii=False))
        return 0
    if op == '--validar-complemento' and len(resto) == 1:
        return _validar(resto[0])
    if op == '--nuevo-complemento' and 1 <= len(resto) <= 2:
        try:
            print("Creado:", plantilla.crear(
                resto[0], resto[1] if len(resto) > 1 else '.', datos=datos))
            return 0
        except FileExistsError as e:
            print("Ya existe:", e)
            return 1
        except OSError as e:
            print("No se pudo crear:", e)
            return 1
    if op == '--empaquetar-complemento' and 1 <= len(resto) <= 2:
        try:
            p = paquete.leer_carpeta(resto[0])
            destino = resto[1] if len(resto) > 1 else \
                f"{p.id}-{p.manifiesto['version']}.zip"
            print("Creado:", paquete.empaquetar(resto[0], destino))
            return _validar(destino)
        except (paquete.ErrorPaquete, OSError) as e:
            print("No se pudo empaquetar:", e)
            return 1
    if op == '--catalogo-complemento' and len(resto) == 2:
        from core.complementos import catalogo, gestor
        try:
            print(catalogo.publicar(*resto), "complementos en el catálogo")
            return 0
        except (paquete.ErrorPaquete, gestor.ErrorGestor, OSError) as e:
            print("No se pudo publicar:", e)
            return 1
    print(__doc__.strip())
    return 2
