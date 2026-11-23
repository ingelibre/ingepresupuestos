# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Servidor MCP por stdio (`ingepresupuestos --mcp`). Solo stdlib, sin Qt.

No abre la base de datos ni calcula nada: encuentra la app abierta por su
registro (`core/mcp_registro.py`) y le pasa cada llamada por 127.0.0.1. Una
llamada dudosa NUNCA se repite sola.
"""
from __future__ import annotations

import json
import socket
import sys

from core import mcp_esquemas, mcp_prompts, mcp_registro

PROTOCOLOS = ("2025-06-18", "2025-03-26", "2024-11-05")
ESPERA_CONEXION = 2.0
ESPERA_OPERACION = 300.0

INSTRUCCIONES = (
    "IngePresupuestos: presupuestos de obra. Trabajas sobre la app ABIERTA "
    "del usuario, que ve tus cambios. Empieza por list_projects. Flujo: "
    "create_project, search_library, add_items (con su ACU), set_metrado, "
    "set_footer, totals, export_report. Corrige con edit_items, move_item, "
    "edit_acu y delete_items en vez de rehacer. Antes de un cambio grande, o "
    "que el usuario no pidió tal cual, usa dry_run: true y enséñale el total "
    "antes y después. Las cantidades, parciales y totales los calcula "
    "la app: no los calcules tú ni los inventes. Cada escritura es una sola "
    "operación (si falla no queda nada) y undo_last la deshace. Si responde "
    "«ocupado», el usuario está editando: espera y reintenta. Los catálogos "
    "(biblioteca e insumos) son de solo lectura. Los precios de la "
    "biblioteca son referenciales del Perú: adviértelo.")

SIN_APP = ("No hay ningún IngePresupuestos con la conexión MCP encendida. Pide "
           "al usuario que abra IngePresupuestos, inicie sesión y encienda "
           "Configuración ▸ Conexión con IA (MCP).")

_n = 0


class ErrorDelPuente(Exception):
    def __init__(self, texto: str, incierto: bool = False):
        super().__init__(texto)
        self.incierto = incierto


def _pedir(reg: dict, herramienta: str, args: dict,
           espera: float = ESPERA_OPERACION) -> dict:
    global _n
    _n += 1
    req = {"id": _n, "token": reg["token"], "instancia": reg["instancia"],
           "tool": herramienta, "args": args}
    try:
        con = socket.create_connection((reg["host"], reg["puerto"]),
                                       timeout=ESPERA_CONEXION)
    except OSError as e:
        raise ErrorDelPuente(f"la app no responde ({e})") from None
    with con:
        con.settimeout(espera)
        try:
            con.sendall((json.dumps(req) + "\n").encode())
            with con.makefile("rb") as fh:
                linea = fh.readline()
        except OSError as e:
            raise ErrorDelPuente(
                f"se cortó la conexión ({e}); la operación no se repitió, "
                "comprueba el estado antes de reintentar", True) from None
    if not linea.endswith(b"\n"):
        raise ErrorDelPuente("la app cerró la conexión sin responder; la "
                             "operación no se repitió", True)
    try:
        resp = json.loads(linea)
    except ValueError:
        raise ErrorDelPuente("respuesta ilegible de la app", True) from None
    if not isinstance(resp, dict) or resp.get("id") not in (_n, None):
        raise ErrorDelPuente("respuesta que no corresponde a la petición", True)
    return resp


def instancias_vivas() -> list[tuple[dict, dict]]:
    out = []
    for reg in mcp_registro.leer():
        try:
            r = _pedir(reg, "ping", {}, espera=5.0)
        except ErrorDelPuente as e:
            # Contesta tarde (un diálogo, un reporte largo) pero está viva.
            if e.incierto:
                out.append((reg, {"instancia": reg["instancia"], "ocupada": True}))
            continue
        if r.get("ok"):
            out.append((reg, r.get("result") or {}))
    return out


def _elegir(instancia) -> dict:
    vivas = instancias_vivas()
    if instancia:
        for reg, _info in vivas:
            if reg["instancia"] == instancia:
                return reg
        raise ErrorDelPuente(f"la instancia {instancia!r} ya no está abierta")
    if not vivas:
        raise ErrorDelPuente(SIN_APP)
    if len(vivas) > 1:
        raise ErrorDelPuente(
            "hay varias ventanas de IngePresupuestos; repite la llamada con "
            "instance_id: " + json.dumps([i for _r, i in vivas],
                                         ensure_ascii=False))
    return vivas[0][0]


def _texto(t: str, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": t}], "isError": error}


def llamar(nombre: str, args) -> dict:
    if not isinstance(args, dict):
        return _texto("los argumentos deben ser un objeto", True)
    args = dict(args)
    instancia = args.pop("instance_id", None)
    try:
        mcp_esquemas.validar(nombre, args)
        reg = _elegir(instancia)
        r = _pedir(reg, nombre, args)
    except (mcp_esquemas.ErrorDeArgumentos, ErrorDelPuente) as e:
        return _texto(str(e), True)
    if not r.get("ok"):
        return _texto(str(r.get("error") or "error sin detalle"), True)
    res = r.get("result")
    if isinstance(res, dict) and res.get("mimeType") == "image/png":
        res = dict(res)
        dato, _mime = res.pop("data", ""), res.pop("mimeType")
        return {"content": [
            {"type": "image", "data": dato, "mimeType": "image/png"},
            {"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}
    return _texto(json.dumps(res, ensure_ascii=False, indent=1))


def _no_finito(x):
    raise ValueError(f"número no válido: {x}")


def atender(msg) -> dict | None:
    """Un mensaje JSON-RPC → su respuesta (None para notificaciones)."""
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "petición no válida"}}
    metodo, mid = msg.get("method"), msg.get("id")
    if "id" not in msg:
        return None
    params = msg.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32602, "message": "params debe ser objeto"}}
    if metodo == "initialize":
        pedido = params.get("protocolVersion")
        res = {"protocolVersion": pedido if pedido in PROTOCOLOS else PROTOCOLOS[0],
               "capabilities": {"tools": {}, "prompts": {}},
               "serverInfo": {"name": "ingepresupuestos", "version": "1.0.0"},
               "instructions": INSTRUCCIONES}
    elif metodo == "tools/list":
        res = {"tools": mcp_esquemas.publicas()}
    elif metodo == "tools/call":
        args = params.get("arguments")
        res = llamar(str(params.get("name", "")), {} if args is None else args)
    elif metodo == "prompts/list":
        res = {"prompts": mcp_prompts.publicos()}
    elif metodo == "prompts/get":
        try:
            res = mcp_prompts.obtener(params.get("name"), params.get("arguments"))
        except ValueError as e:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": str(e)}}
    elif metodo == "ping":
        res = {}
    else:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"método desconocido: {metodo}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def _abrir_stdio():
    """En Windows un .exe de ventana puede no traer stdin/stdout de Python
    aunque el cliente le haya dado tuberías."""
    if sys.stdin is None or sys.stdout is None:
        sys.stdin = open(0, "r", encoding="utf-8")
        sys.stdout = open(1, "w", encoding="utf-8")
    for f in (sys.stdin, sys.stdout):
        try:
            f.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass


def main() -> int:
    try:
        _abrir_stdio()
    except OSError:
        return 2
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            msg = json.loads(linea, parse_constant=_no_finito)
        except ValueError as e:
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": f"JSON no válido: {e}"}}
        else:
            try:
                resp = atender(msg)
            except Exception as e:  # noqa: BLE001 — nunca morir por una llamada
                resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                        "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}
        if resp is not None:
            try:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except (BrokenPipeError, OSError):
                return 0
    return 0
