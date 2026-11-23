# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Sesión MCP completa y de verdad: la app entera en un proceso, el servidor
stdio (`main.py --mcp`) en otro, y JSON-RPC por sus tuberías."""
import base64
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SEED = RAIZ / 'presupuestos_seed.db'


class Cliente:
    def __init__(self, env, cmd):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, env=env,
                                  encoding='utf-8')
        self.n = 0

    def rpc(self, metodo, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n,
                                       "method": metodo,
                                       "params": params or {}}) + "\n")
        self.p.stdin.flush()
        r = json.loads(self.p.stdout.readline())
        assert r["id"] == self.n
        return r

    def crudo(self, nombre, **args):
        return self.rpc("tools/call", {"name": nombre, "arguments": args})["result"]

    def __call__(self, nombre, **args):
        r = self.crudo(nombre, **args)
        assert not r.get("isError"), r
        return json.loads(r["content"][-1]["text"])

    def error(self, nombre, **args):
        r = self.crudo(nombre, **args)
        assert r["isError"], r
        return r["content"][0]["text"]

    def cerrar(self):
        self.p.stdin.close()
        assert self.p.wait(10) == 0


@pytest.fixture(scope='module')
def app(tmp_path_factory):
    base = tmp_path_factory.mktemp('mcp')
    datos = base / 'xdg' / 'ingepresupuestos'
    datos.mkdir(parents=True)
    shutil.copy(SEED, datos / 'presupuestos.db')
    env = dict(os.environ, XDG_DATA_HOME=str(base / 'xdg'),
               XDG_CONFIG_HOME=str(base / 'cfg'),
               INGEPRESUPUESTOS_MCP_REGISTRO=str(base / 'reg'),
               QT_QPA_PLATFORM='offscreen')
    p = subprocess.Popen([sys.executable, str(RAIZ / 'tests' / '_mcp_app.py')],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         env=env, text=True)
    linea = p.stdout.readline()
    while linea and linea.strip() != 'LISTA':
        linea = p.stdout.readline()
    assert linea, 'la app no arrancó'
    yield base, env
    p.stdin.close()
    p.wait(30)
    assert not list((base / 'reg').glob('*.json'))     # se despidió


def test_sesion_completa(app, tmp_path):
    base, env = app
    c = Cliente(env, [sys.executable, str(RAIZ / 'main.py'), '--mcp'])
    ini = c.rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]
    assert ini["serverInfo"]["name"] == "ingepresupuestos"
    tools = {t["name"]: t for t in c.rpc("tools/list")["result"]["tools"]}
    assert len(tools) == 23 and "run_python" not in tools
    assert all(t["inputSchema"]["additionalProperties"] is False
               for t in tools.values())

    antes = c("list_projects")["total"]
    pid = c("create_project", name="Casa de prueba", client="Nadie")["project_id"]
    assert c("list_projects")["total"] == antes + 1

    lib = c("search_library", query="concreto columnas", limit=5)["results"]
    assert lib
    r = c("add_items", project_id=pid, items=[
        {"title": True, "description": "ESTRUCTURAS"},
        {"library_id": lib[0]["library_id"], "parent_item": "01"},
        {"description": "Partida sin ACU", "unit": "m2", "parent_item": "01"}])
    codigos = [x["item"] for x in r["added"]]
    assert codigos == ["01", "01.01", "01.02"]
    part = r["added"][1]["item_id"]
    acu = c("get_acu", item_id=part)
    assert acu["resources"] and acu["unit_price"] > 0

    m = c("set_metrado", item_id=part, rows=[
        {"description": "Eje A", "elements": 4, "length": 0.3, "width": 0.4,
         "height": 3},
        {"description": "Eje B", "elements": 2, "area": 0.1, "height": 3}])
    assert m["quantity"] == pytest.approx(2.04)        # 1.44 + 0.60
    tot = c("totals", project_id=pid)
    assert tot["direct_cost"] == pytest.approx(round(2.04 * acu["unit_price"], 2))
    assert tot["total"] > tot["direct_cost"]

    # La planilla no se pisa sin decirlo.
    assert "replace" in c.error("set_metrado", item_id=part, quantity=1)
    v = c("validate", project_id=pid)
    assert v["counts"]["no_acu"] == 1

    s = c("set_schedule", project_id=pid, tasks=[
        {"item_id": part, "duration": 5},
        {"item_id": r["added"][2]["item_id"], "duration": 3,
         "predecessors": [{"item_id": part, "lag": 2}]}])
    t = {x["item_id"]: x for x in s["tasks"]}
    assert t[r["added"][2]["item_id"]]["start"] > t[part]["finish"]
    assert "ciclo" in c.error("set_schedule", project_id=pid, tasks=[
        {"item_id": part, "predecessors": [
            {"item_id": r["added"][2]["item_id"]}]}])

    pdf = tmp_path / 'presupuesto.pdf'
    assert c("export_report", project_id=pid, report="presupuesto",
             path=str(pdf))["bytes"] > 1000
    assert pdf.read_bytes()[:5] == b"%PDF-"
    assert "overwrite" in c.error("export_report", project_id=pid,
                                  report="presupuesto", path=str(pdf))
    xls = tmp_path / 'acus.xlsx'
    c("export_report", project_id=pid, report="acus", path=str(xls))
    assert xls.read_bytes()[:2] == b"PK"
    assert sorted(p.name for p in tmp_path.iterdir()) == ['acus.xlsx',
                                                          'presupuesto.pdf']
    img = c.crudo("screenshot")["content"][0]
    assert base64.b64decode(img["data"])[:4] == b"\x89PNG"

    # Deshacer, de la última a la primera, hasta que no queda el proyecto.
    for esperado in ("set_schedule", "set_metrado", "add_items",
                     "create_project"):
        assert c("undo_last")["undone"] == esperado
    assert c("list_projects")["total"] == antes
    assert "nada" in c.error("undo_last")
    c.cerrar()


def test_el_script_suelto_tambien_sirve(app):
    _b, env = app
    c = Cliente(env, [sys.executable, '-S',
                      str(RAIZ / 'scripts' / 'ingepresupuestos_mcp.py')])
    assert c("list_projects")["projects"]
    c.cerrar()


def test_argumentos_estrictos_y_mensajes(app):
    _b, env = app
    c = Cliente(env, [sys.executable, str(RAIZ / 'main.py'), '--mcp'])
    assert "no existe" in c.error("list_projects", sql="SELECT 1")
    assert "falta" in c.error("totals")
    assert "entero" in c.error("totals", project_id=True)
    assert "desconocida" in c.error("run_python", code="1")
    assert "no existe el proyecto" in c.error("totals", project_id=999999)
    assert "absoluta" in c.error("export_report", project_id=397,
                                 report="resumen", path="x.pdf")
    assert ".pdf" in c.error("export_report", project_id=397,
                             report="resumen", path="/tmp/x.db")
    r = c.rpc("inventado")
    assert r["error"]["code"] == -32601
    c.p.stdin.write("esto no es json\n")
    c.p.stdin.flush()
    assert json.loads(c.p.stdout.readline())["error"]["code"] == -32700
    assert c.rpc("ping")["result"] == {}
    c.cerrar()


def _registro(base):
    a, = (base / 'reg').glob('*.json')
    return a, json.loads(a.read_text())


def _mandar(puerto, datos: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", puerto), 5) as s:
        s.settimeout(10)
        s.sendall(datos)
        out = b""
        try:
            while True:
                t = s.recv(65536)
                if not t:
                    return out
                out += t
                if out.endswith(b"\n") and b'"ok": true' in out:
                    return out
        except (socket.timeout, ConnectionResetError):
            return out


def test_registro_privado_y_token(app):
    base, _env = app
    a, reg = _registro(base)
    assert stat.S_IMODE(a.stat().st_mode) == 0o600
    assert stat.S_IMODE(a.parent.stat().st_mode) == 0o700
    req = {"id": 1, "instancia": reg["instancia"], "tool": "list_projects",
           "args": {}}

    def linea(**k):
        return (json.dumps(dict(req, **k)) + "\n").encode()
    assert b'"ok": true' in _mandar(reg["puerto"], linea(token=reg["token"]))
    for malo in (linea(), linea(token="x" * 64), linea(token=None),
                 linea(token="ñ"), linea(token=reg["token"], instancia="otra"),
                 b"[1]\n", b"[" * 100000 + b"\n"):
        r = _mandar(reg["puerto"], malo)
        assert b'"ok": true' not in r and b"projects" not in r


def test_http_se_rechaza_sin_leer_el_cuerpo(app):
    base, _env = app
    _a, reg = _registro(base)
    cuerpo = json.dumps({"id": 1, "token": reg["token"],
                         "instancia": reg["instancia"],
                         "tool": "create_project", "args": {"name": "HTTP"}})
    r = _mandar(reg["puerto"], (
        "POST / HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: text/plain\r\n\r\n"
        + cuerpo + "\n").encode())
    assert b'"ok": false' in r and r.count(b"\n") == 1
    r = _mandar(reg["puerto"], (json.dumps({
        "id": 1, "token": reg["token"], "instancia": reg["instancia"],
        "tool": "list_projects", "args": {"query": "HTTP"}}) + "\n").encode())
    assert json.loads(r)["result"]["total"] == 0


def test_sin_app_lo_explica(tmp_path):
    env = dict(os.environ, INGEPRESUPUESTOS_MCP_REGISTRO=str(tmp_path))
    c = Cliente(env, [sys.executable, str(RAIZ / 'main.py'), '--mcp'])
    assert "encienda" in c.error("list_projects")
    c.cerrar()


def test_mcp_no_importa_qt_ni_sqlite():
    r = subprocess.run(
        [sys.executable, '-X', 'importtime', str(RAIZ / 'main.py'), '--mcp'],
        input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n',
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "PySide6" not in r.stderr
    assert "sqlite3" not in r.stderr
    assert len(json.loads(r.stdout)["result"]["tools"]) == 23
