# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Puente con un IngeTrazo abierto, sin IA de por medio (solo stdlib).

Habla el mismo protocolo que su MCP (`core/ai_discovery.py` y
`plugins/ai_bridge.py` de IngeTrazo): registro en disco, JSON por líneas en
127.0.0.1, `list_documents` y después la herramienta con `instance_id` y
`document_id`. Los nombres de aquí no importan nada de Qt: se puede llamar
desde un hilo cualquiera.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

from core.mcp_registro import _casa

PROTOCOLO = 2
ESPERA_DESCUBRIR = 1.5
ESPERA_OPERACION = 180.0
MAX_RESPUESTA = 256 * 1024 * 1024

SIN_INGETRAZO = ("No hay ningún IngeTrazo abierto con el puente encendido. "
                 "En IngeTrazo: pestaña IA ▸ Puente de IA (MCP) ▸ Iniciar.")


class ErrorIngeTrazo(Exception):
    pass


class SinIngeTrazo(ErrorIngeTrazo):
    pass


class VariosDocumentos(ErrorIngeTrazo):
    def __init__(self, documentos):
        self.documentos = documentos
        super().__init__(
            "IngeTrazo tiene varios documentos abiertos; elige document_id: "
            + json.dumps([{k: d.get(k) for k in ("document_id", "name")}
                          for d in documentos], ensure_ascii=False))


def carpetas_registro() -> list[Path]:
    forzada = os.environ.get("INGETRAZO_AI_REGISTRY")
    if forzada:
        return [Path(forzada).expanduser()]
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA",
                                   Path.home() / "AppData" / "Local"))
        return [base / "IngeTrazo" / "ai-bridges"]
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "IngeTrazo"
                / "ai-bridges"]
    casa = _casa()
    out = [casa / ".local" / "state" / "ingetrazo" / "ai-bridges"]
    # IngeTrazo en snap: su $HOME es ~/snap/ingetrazo/<revisión>.
    out.append(casa / "snap" / "ingetrazo" / "current" / ".local" / "state"
               / "ingetrazo" / "ai-bridges")
    return out


def _registros() -> list[dict]:
    out, vistos = [], set()
    for dir_ in carpetas_registro():
        try:
            archivos = sorted(dir_.glob("*.json"))
        except OSError:
            continue
        for a in archivos:
            try:
                r = json.loads(a.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if (isinstance(r, dict) and r.get("protocol") == PROTOCOLO
                    and isinstance(r.get("instance_id"), str)
                    and a.name == r["instance_id"] + ".json"
                    and r.get("host") == "127.0.0.1"
                    and type(r.get("port")) is int and 0 < r["port"] < 65536
                    and r["instance_id"] not in vistos):
                vistos.add(r["instance_id"])
                out.append(r)
    return out


def _pedir(reg: dict, herramienta: str, args: dict,
           document_id: str | None, espera: float) -> dict:
    req = {"id": 1, "tool": herramienta, "args": args,
           "instance_id": reg["instance_id"]}
    if reg.get("token"):
        req["token"] = reg["token"]
    if document_id is not None:
        req["document_id"] = document_id
    try:
        with socket.create_connection((reg["host"], reg["port"]),
                                      timeout=ESPERA_DESCUBRIR) as con:
            con.settimeout(espera)
            con.sendall((json.dumps(req) + "\n").encode())
            with con.makefile("rb") as fh:
                linea = fh.readline(MAX_RESPUESTA)
    except OSError as e:
        raise ErrorIngeTrazo(f"IngeTrazo no responde ({e})") from None
    if not linea.endswith(b"\n"):
        raise ErrorIngeTrazo("IngeTrazo cerró la conexión sin responder")
    try:
        resp = json.loads(linea)
    except ValueError:
        raise ErrorIngeTrazo("respuesta ilegible de IngeTrazo") from None
    if not isinstance(resp, dict) or resp.get("id") != 1:
        raise ErrorIngeTrazo("respuesta no válida de IngeTrazo")
    if resp.get("ok") is not True:
        raise ErrorIngeTrazo("IngeTrazo: " + str(resp.get("error") or "error"))
    if not isinstance(resp.get("result"), dict):
        raise ErrorIngeTrazo("respuesta no válida de IngeTrazo")
    return resp["result"]


def documentos() -> list[dict]:
    """Documentos abiertos en los IngeTrazo con el puente encendido."""
    out = []
    for reg in _registros():
        try:
            docs = _pedir(reg, "list_documents", {}, None,
                          ESPERA_DESCUBRIR).get("documents")
        except ErrorIngeTrazo:
            continue
        for d in docs if isinstance(docs, list) else []:
            if (isinstance(d, dict)
                    and d.get("instance_id") == reg["instance_id"]
                    and str(d.get("document_id", "")).startswith(
                        reg["instance_id"] + ":")):
                out.append(dict(d, _registro=reg))
    return out


def _elegir(document_id: str | None) -> dict:
    docs = documentos()
    if document_id:
        for d in docs:
            if d["document_id"] == document_id:
                return d
        raise ErrorIngeTrazo("ese documento de IngeTrazo ya no está abierto")
    if not docs:
        raise SinIngeTrazo(SIN_INGETRAZO)
    if len(docs) > 1:
        raise VariosDocumentos([{k: v for k, v in d.items()
                                 if k != "_registro"} for d in docs])
    return docs[0]


def _llamar(herramienta: str, args: dict, document_id: str | None) -> dict:
    d = _elegir(document_id)
    return _pedir(d["_registro"], herramienta, args, d["document_id"],
                  ESPERA_OPERACION)


def traer_takeoff(document_id: str | None = None) -> dict:
    """El metrado del modelo abierto, como dict «inge-takeoff» v1."""
    r = _llamar("get_takeoff", {}, document_id)
    if "schema" not in r and isinstance(r.get("takeoff"), dict):
        r = r["takeoff"]
    if r.get("schema") != "inge-takeoff" or r.get("version") != 1:
        raise ErrorIngeTrazo(
            "esta versión de IngeTrazo no envía un metrado que se entienda "
            f"(esquema {r.get('schema')!r}, versión {r.get('version')!r})")
    if not isinstance(r.get("elements"), list):
        raise ErrorIngeTrazo("el metrado de IngeTrazo llegó sin elementos")
    return r


def seleccionar_en_ingetrazo(global_ids, document_id: str | None = None) -> dict:
    """Selecciona en IngeTrazo los elementos con esos GlobalId."""
    ids = [str(g) for g in global_ids]
    if not ids:
        raise ErrorIngeTrazo("no hay elementos que mostrar")
    return _llamar("select", {"global_ids": ids}, document_id)
