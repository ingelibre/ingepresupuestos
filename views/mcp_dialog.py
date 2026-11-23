# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Panel «Conexión con IA (MCP)»: encender, conectar cada cliente y deshacer.

El mismo panel se ve en Configuración y en la ventana que abre el menú
Archivo del proyecto.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from utils.i18n import N_, tr
from utils.theme import BTN_PRIMARY_SS, SLATE_500

NOMBRE = "ingepresupuestos"


# ── Qué escribir en cada cliente ─────────────────────────────────────────────

def comando_servidor(env=None, plataforma=None, congelado=None,
                     ejecutable=None) -> list[str]:
    """Cómo se lanza el servidor MCP en ESTA instalación."""
    env = os.environ if env is None else env
    plataforma = plataforma or sys.platform
    congelado = getattr(sys, 'frozen', False) if congelado is None else congelado
    ejecutable = ejecutable or sys.executable
    if env.get("FLATPAK_ID"):
        return ["flatpak", "run", env["FLATPAK_ID"], "--mcp"]
    if env.get("SNAP_NAME") == NOMBRE:
        return ["snap", "run", NOMBRE, "--mcp"]
    if env.get("APPIMAGE"):
        return [env["APPIMAGE"], "--mcp"]
    if congelado:
        if plataforma.startswith("win"):
            return [str(Path(ejecutable).with_name("ingepresupuestos-mcp.exe"))]
        return [ejecutable, "--mcp"]
    raiz = Path(__file__).resolve().parent.parent
    return [ejecutable, str(raiz / "scripts" / "ingepresupuestos_mcp.py")]


def _linea(cmd: list[str], plataforma: str) -> str:
    return (subprocess.list2cmdline(cmd) if plataforma.startswith("win")
            else shlex.join(cmd))


def ruta_claude_desktop(plataforma: str) -> str:
    if plataforma.startswith("win"):
        return r"%APPDATA%\Claude\claude_desktop_config.json"
    if plataforma == "darwin":
        return "~/Library/Application Support/Claude/claude_desktop_config.json"
    return "~/.config/Claude/claude_desktop_config.json"


def instrucciones(cmd: list[str] | None = None,
                  plataforma: str | None = None) -> list[tuple[str, str, str]]:
    """[(cliente, dónde va, texto exacto)]."""
    cmd = cmd or comando_servidor()
    plataforma = plataforma or sys.platform
    linea = _linea(cmd, plataforma)
    bloque = json.dumps({"mcpServers": {NOMBRE: {
        "command": cmd[0], "args": cmd[1:]}}}, indent=2, ensure_ascii=False)
    vscode = json.dumps({"servers": {NOMBRE: {
        "type": "stdio", "command": cmd[0], "args": cmd[1:]}}},
        indent=2, ensure_ascii=False)
    toml = (f"[mcp_servers.{NOMBRE}]\n"
            f"command = {json.dumps(cmd[0], ensure_ascii=False)}\n"
            f"args = {json.dumps(cmd[1:], ensure_ascii=False)}\n")
    return [
        ("Claude Code", tr("En una terminal:"),
         f"claude mcp add {NOMBRE} -- {linea}"),
        ("Claude Desktop",
         tr("Añade esto a {ruta} y reinicia Claude Desktop:").format(
             ruta=ruta_claude_desktop(plataforma)), bloque),
        ("Codex", tr("Añade esto a {ruta}:").format(ruta="~/.codex/config.toml"),
         toml),
        ("Gemini CLI",
         tr("Añade esto a {ruta}:").format(ruta="~/.gemini/settings.json"), bloque),
        ("Cursor", tr("Añade esto a {ruta}:").format(ruta="~/.cursor/mcp.json"),
         bloque),
        ("VS Code", tr("Añade esto a {ruta}:").format(ruta=".vscode/mcp.json"),
         vscode),
        (tr("Otro cliente"), tr("Servidor MCP por stdio. El comando es:"), linea),
    ]


# ── Panel ────────────────────────────────────────────────────────────────────

class PanelMCP(QWidget):
    def __init__(self, ventana, parent=None):
        """`ventana` es la MainWindow (dueña del puente) o None."""
        super().__init__(parent)
        self._ventana = ventana
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(10)

        nota = QLabel(tr(
            "Permite que un asistente de IA (Claude, Codex, Gemini…) consulte y "
            "edite tus presupuestos con IngePresupuestos abierto. Solo funciona "
            "en esta computadora. Lo que el asistente lea se envía al proveedor "
            "de IA que uses. Está apagado mientras no lo enciendas."))
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color:{SLATE_500}; background:transparent; border:none;")
        vl.addWidget(nota)

        self.chk = QCheckBox(tr("Conexión encendida"))
        vl.addWidget(self.chk)
        self.lbl_estado = QLabel()
        self.lbl_estado.setWordWrap(True)
        vl.addWidget(self.lbl_estado)

        self.cmb = QComboBox()
        self._ins = instrucciones()
        for nombre, _d, _t in self._ins:
            self.cmb.addItem(nombre)
        hl = QHBoxLayout()
        hl.addWidget(QLabel(tr("Conectar con:")))
        hl.addWidget(self.cmb, 1)
        vl.addLayout(hl)
        self.lbl_donde = QLabel()
        self.lbl_donde.setWordWrap(True)
        self.lbl_donde.setTextInteractionFlags(Qt.TextSelectableByMouse)
        vl.addWidget(self.lbl_donde)
        self.txt = QPlainTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setMinimumHeight(130)
        f = self.txt.font()
        f.setFamily("monospace")
        f.setStyleHint(f.StyleHint.Monospace)
        self.txt.setFont(f)
        vl.addWidget(self.txt)
        hl = QHBoxLayout()
        self.lbl_copiado = QLabel("")
        hl.addWidget(self.lbl_copiado)
        hl.addStretch()
        self.btn_copiar = QPushButton(tr("Copiar"))
        self.btn_copiar.setStyleSheet(BTN_PRIMARY_SS)
        hl.addWidget(self.btn_copiar)
        vl.addLayout(hl)

        hl = QHBoxLayout()
        self.btn_deshacer = QPushButton(tr("Deshacer lo último de la IA"))
        hl.addWidget(self.btn_deshacer)
        self.lbl_ultima = QLabel("")
        self.lbl_ultima.setWordWrap(True)
        self.lbl_ultima.setStyleSheet(
            f"color:{SLATE_500}; background:transparent; border:none;")
        hl.addWidget(self.lbl_ultima, 1)
        vl.addLayout(hl)

        self.cmb.currentIndexChanged.connect(self._mostrar)
        self.btn_copiar.clicked.connect(self._copiar)
        self.btn_deshacer.clicked.connect(self._deshacer)
        self._mostrar()
        self._pintar()
        self.chk.clicked.connect(self._alternar)
        p = self._puente()
        if p is not None:
            p.cambio_estado.connect(self._pintar)
            p.actividad.connect(self._pintar)

    def _puente(self):
        if self._ventana is None or not hasattr(self._ventana, 'stack'):
            return None
        from views.mcp_puente import puente_de
        return puente_de(self._ventana)

    def _mostrar(self, *_):
        _n, donde, texto = self._ins[max(self.cmb.currentIndex(), 0)]
        self.lbl_donde.setText(donde)
        self.txt.setPlainText(texto)
        self.lbl_copiado.setText("")

    def _copiar(self):
        QApplication.clipboard().setText(self.txt.toPlainText())
        self.lbl_copiado.setText("✓  " + tr("Copiado"))

    def _pintar(self, *_):
        p = self._puente()
        on = p is not None and p.encendido
        self.chk.setEnabled(p is not None)
        self.chk.setChecked(on)
        self.lbl_estado.setText(
            tr("Encendida. El asistente puede conectarse mientras "
               "IngePresupuestos esté abierto.") if on else tr("Apagada."))
        r = p.pila.resumen() if p is not None else None
        self.btn_deshacer.setEnabled(r is not None)
        if r is None:
            self.lbl_ultima.setText(tr("La IA no ha cambiado nada."))
            return
        self.lbl_ultima.setText(
            tr("{que} en «{proyecto}», {cuando}").format(
                que=tr(NOMBRES.get(r['herramienta'], r['herramienta'])),
                proyecto=_nombre_proyecto(r['pid']),
                cuando=datetime.fromtimestamp(r['cuando']).strftime('%d/%m %H:%M')))

    def showEvent(self, ev):
        super().showEvent(ev)
        self._pintar()

    def _alternar(self, on: bool):
        from core.database import set_config
        from views.mcp_puente import CLAVE_ACTIVO
        p = self._puente()
        if p is None:
            return
        try:
            if on:
                p.encender()
            else:
                p.apagar()
            set_config(CLAVE_ACTIVO, '1' if on else '0')
        except OSError as e:
            self._pintar()
            self.lbl_estado.setText(tr("No se pudo encender: {e}").format(e=e))
            return
        self._pintar()

    def _deshacer(self):
        p = self._puente()
        if p is not None:
            deshacer_con_aviso(self, p)
            self._pintar()


NOMBRES = {
    'create_project': N_("Crear proyecto"), 'add_items': N_("Agregar partidas"),
    'set_metrado': N_("Metrado"), 'set_acu': N_("Análisis de costo unitario"),
    'set_price': N_("Precio de un insumo"), 'set_schedule': N_("Cronograma"),
    'bim_apply': N_("Modelo BIM"), 'link_elements': N_("Vínculos BIM"),
}


def _nombre_proyecto(pid: int) -> str:
    from core.database import get_db
    conn = get_db()
    try:
        r = conn.execute("SELECT nombre FROM proyectos WHERE id=?",
                         (pid,)).fetchone()
    finally:
        conn.close()
    return (r['nombre'] if r else '?')[:60]


def deshacer_con_aviso(parent, puente) -> bool:
    """El botón: deshace y, si el usuario editó después, pregunta."""
    from core.mcp_operaciones import ErrorMCP
    titulo = tr("Deshacer lo último de la IA")
    r = puente.pila.resumen()
    if r is None:
        QMessageBox.information(parent, titulo, tr("La IA no ha cambiado nada."))
        return False
    try:
        puente.deshacer_desde_ui(False)
        return True
    except ErrorMCP as e:
        if not getattr(e, 'editado', False):
            QMessageBox.warning(parent, titulo, str(e))
            return False
    if QMessageBox.question(
            parent, titulo,
            tr("El proyecto «{proyecto}» se editó después de ese cambio de la "
               "IA. Si lo deshaces, también se pierde lo que editaste después. "
               "¿Deshacer de todos modos?").format(
                proyecto=_nombre_proyecto(r['pid'])),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
        return False
    try:
        puente.deshacer_desde_ui(True)
        return True
    except ErrorMCP as e:
        QMessageBox.warning(parent, titulo, str(e))
        return False


class DialogoMCP(QDialog):
    def __init__(self, ventana, parent=None):
        super().__init__(parent or ventana)
        self.setWindowTitle(tr("Conexión con IA (MCP)"))
        self.setWindowModality(Qt.WindowModal)
        self.resize(640, 470)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(20, 18, 20, 16)
        self.panel = PanelMCP(ventana, self)
        vl.addWidget(self.panel, 1)
        hl = QHBoxLayout()
        hl.addStretch()
        b = QPushButton(tr("Cerrar"))
        b.clicked.connect(self.accept)
        hl.addWidget(b)
        vl.addLayout(hl)
