# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Puente con IngeTrazo contra un servidor que habla su protocolo."""
import json
import os
import socket
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import ingetrazo_puente as ip  # noqa: E402

TAKE = {"schema": "inge-takeoff", "version": 1, "source": {"app": "IngeTrazo"},
        "elements": [{"global_id": "A" * 22, "ifc_class": "IfcWall"}]}


class Falso:
    """Como plugins/ai_bridge.py: una línea JSON por petición, exige
    instance_id y document_id salvo en list_documents."""

    def __init__(self, carpeta, inst, takeoff=TAKE):
        self.inst, self.takeoff, self.pedidos = inst, takeoff, []
        self.s = socket.socket()
        self.s.bind(("127.0.0.1", 0))
        self.s.listen(1)
        carpeta.mkdir(exist_ok=True)
        (carpeta / f"{inst}.json").write_text(json.dumps({
            "protocol": 2, "instance_id": inst, "pid": 1, "host": "127.0.0.1",
            "port": self.s.getsockname()[1]}))
        threading.Thread(target=self._servir, daemon=True).start()

    def _servir(self):
        while True:
            try:
                con, _ = self.s.accept()
            except OSError:
                return
            with con, con.makefile("rb") as fh:
                req = json.loads(fh.readline())
                self.pedidos.append(req)
                doc = f"{self.inst}:d1"
                if req["tool"] == "list_documents":
                    res = {"documents": [{"document_id": doc, "name": "Casa.igz",
                                          "instance_id": self.inst}]}
                else:
                    assert req["instance_id"] == self.inst
                    assert req["document_id"] == doc
                    res = (self.takeoff if req["tool"] == "get_takeoff" else
                           {"selected": len(req["args"]["global_ids"])})
                con.sendall((json.dumps({"id": req["id"], "ok": True,
                                         "result": res}) + "\n").encode())


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setenv("INGETRAZO_AI_REGISTRY", str(tmp_path))
    return tmp_path


def test_trae_y_selecciona(reg):
    f = Falso(reg, "uno")
    assert ip.traer_takeoff() == TAKE
    assert ip.seleccionar_en_ingetrazo(["A", "B"]) == {"selected": 2}
    assert f.pedidos[-1]["args"] == {"global_ids": ["A", "B"]}


def test_sin_ingetrazo_o_muerto(reg):
    with pytest.raises(ip.SinIngeTrazo):
        ip.traer_takeoff()
    f = Falso(reg, "muerto")
    f.s.shutdown(socket.SHUT_RDWR)      # despierta al accept() y deja de escuchar
    f.s.close()
    with pytest.raises(ip.SinIngeTrazo):
        ip.traer_takeoff()


def test_varios_documentos_piden_elegir(reg):
    Falso(reg, "uno")
    Falso(reg, "dos")
    with pytest.raises(ip.VariosDocumentos) as e:
        ip.traer_takeoff()
    assert len(e.value.documentos) == 2
    assert ip.traer_takeoff("dos:d1") == TAKE
    with pytest.raises(ip.ErrorIngeTrazo, match="ya no"):
        ip.traer_takeoff("tres:d1")


@pytest.mark.parametrize("malo", [{"schema": "otro", "version": 1},
                                  {"schema": "inge-takeoff", "version": 2},
                                  {"schema": "inge-takeoff", "version": 1}])
def test_esquema_desconocido_se_rechaza(reg, malo):
    Falso(reg, "uno", malo)
    with pytest.raises(ip.ErrorIngeTrazo):
        ip.traer_takeoff()


def test_el_boton_espera_en_un_hilo_y_abre_el_dialogo(reg, monkeypatch):
    import types
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    from views import ingetrazo_traer as it
    Falso(reg, "uno")
    visto = {}
    import views
    doble = types.ModuleType('views.bim_dialog')
    doble.abrir_takeoff = lambda parent, pid, t: visto.update(
        pid=pid, t=t, hilo=threading.current_thread())
    monkeypatch.setitem(sys.modules, 'views.bim_dialog', doble)
    monkeypatch.setattr(views, 'bim_dialog', doble, raising=False)
    it.traer_de_ingetrazo(None, 7)
    assert visto == {"pid": 7, "t": TAKE, "hilo": threading.main_thread()}
