# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Registro local de instancias con el puente MCP encendido (solo stdlib).

Cada ventana con el puente encendido publica un archivo JSON con su puerto y
un TOKEN propio de esa instancia. El archivo es 0600 dentro de una carpeta
0700: otro usuario de la máquina, o una página web que le hable a 127.0.0.1,
no puede leerlo, y sin token el puente no atiende nada.

La carpeta no depende de XDG_* a propósito: Flatpak cambia XDG_STATE_HOME por
aplicación y el proceso `--mcp` puede correr fuera del sandbox. Con snap
estricto la app no puede escribir en `~/.local`, así que usa su
`SNAP_USER_COMMON` y quien corre fuera mira también allí.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import tempfile
from pathlib import Path

PROTOCOLO = 1
VARIABLE = "INGEPRESUPUESTOS_MCP_REGISTRO"
_SNAP = "ingepresupuestos"


def _casa() -> Path:
    """El home de verdad, también dentro de un snap (que cambia $HOME)."""
    real = os.environ.get("SNAP_REAL_HOME")
    return Path(real) if real else Path.home()


def _carpeta_normal() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "IngePresupuestos" / "mcp"
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support"
                / "ingepresupuestos" / "mcp")
    return _casa() / ".local" / "state" / "ingepresupuestos" / "mcp"


def _en_nuestro_snap() -> bool:
    return (os.environ.get("SNAP_NAME") == _SNAP
            and bool(os.environ.get("SNAP_USER_COMMON")))


def carpeta() -> Path:
    """Dónde publica esta instancia."""
    forzada = os.environ.get(VARIABLE)
    if forzada:
        return Path(forzada).expanduser()
    if _en_nuestro_snap():
        return Path(os.environ["SNAP_USER_COMMON"]) / "mcp"
    return _carpeta_normal()


def carpetas_lectura() -> list[Path]:
    """Dónde buscar instancias: la propia, la normal y la del snap."""
    if os.environ.get(VARIABLE):
        return [carpeta()]
    out = [carpeta(), _carpeta_normal()]
    if sys.platform.startswith("linux"):
        out.append(_casa() / "snap" / _SNAP / "common" / "mcp")
    unicas: list[Path] = []
    for c in out:
        if c not in unicas:
            unicas.append(c)
    return unicas


def nuevo_token() -> str:
    return secrets.token_hex(32)


def publicar(instancia: str, puerto: int, token: str) -> Path:
    """Publica el registro completo de una vez (archivo temporal + replace)."""
    dir_ = carpeta()
    dir_.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(dir_, 0o700)
    except OSError:
        pass
    registro = {"protocolo": PROTOCOLO, "instancia": instancia,
                "pid": os.getpid(), "host": "127.0.0.1", "puerto": puerto,
                "token": token}
    destino = dir_ / f"{instancia}.json"
    # mkstemp ya crea el archivo con 0600.
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(registro, fh)
        os.replace(tmp, destino)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return destino


def _valido(reg, archivo: Path) -> bool:
    return (isinstance(reg, dict)
            and reg.get("protocolo") == PROTOCOLO
            and isinstance(reg.get("instancia"), str)
            and archivo.name == reg["instancia"] + ".json"
            and reg.get("host") == "127.0.0.1"
            and type(reg.get("puerto")) is int
            and 0 < reg["puerto"] < 65536
            and isinstance(reg.get("token"), str)
            and len(reg["token"]) >= 32)


def leer() -> list[dict]:
    """Registros bien formados. Que la instancia viva lo comprueba el cliente."""
    out: list[dict] = []
    vistos: set[str] = set()
    for dir_ in carpetas_lectura():
        try:
            archivos = sorted(dir_.glob("*.json"))
        except OSError:
            continue
        for archivo in archivos:
            try:
                reg = json.loads(archivo.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if _valido(reg, archivo) and reg["instancia"] not in vistos:
                vistos.add(reg["instancia"])
                out.append(reg)
    return out


def podar() -> int:
    """Borra de la carpeta propia los registros que ya nadie atiende (una app
    que murió sin despedirse). Solo si el puerto RECHAZA la conexión: un pid
    no sirve entre sandboxes."""
    n = 0
    try:
        archivos = list(carpeta().glob("*.json"))
    except OSError:
        return 0
    for archivo in archivos:
        try:
            reg = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not _valido(reg, archivo):
            continue
        try:
            socket.create_connection((reg["host"], reg["puerto"]), 0.5).close()
        except ConnectionRefusedError:
            try:
                archivo.unlink()
                n += 1
            except OSError:
                pass
        except OSError:
            pass
    return n
