# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Puente MCP dentro de la app: servidor en 127.0.0.1 + ejecución en el hilo
principal de Qt.

Cada petición es una línea JSON con el token de la instancia (ver
`core/mcp_registro.py`). Lo que no sea JSON —por ejemplo HTTP de una página
web— cierra la conexión sin leer nada más. Apagado por defecto: se enciende
en Configuración ▸ Conexión con IA (MCP).
"""
from __future__ import annotations

import base64
import hmac
import json
import socket
import threading
import uuid
from pathlib import Path

from PySide6.QtCore import (QBuffer, QCoreApplication, QIODevice, QObject, Qt,
                            QThread, Signal)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QLineEdit,
                               QPlainTextEdit, QTextEdit)

from core import mcp_esquemas, mcp_registro
from core.mcp_deshacer import Pila
from core.mcp_operaciones import ErrorMCP, Operaciones

CLAVE_ACTIVO = 'mcp_activo'
MAX_LINEA = 4 * 1024 * 1024
MAX_CONEXIONES = 8
ESPERA = 240.0
_RECHAZO = (b'{"id": null, "ok": false, "error": '
            b'"no es una peticion del puente; conexion cerrada"}\n')

#: Vistas que se pueden capturar. Lista blanca: configuración enseña claves
#: de IA y usuarios, y ahí no entra ninguna captura.
VISTAS_CAPTURABLES = ('dashboard', 'recursos', 'biblioteca', 'indices_inei',
                      'nuevo_proyecto')


class Ocupado(ErrorMCP):
    pass


def _no_finito(x):
    raise ValueError(x)


class PuenteMCP(QObject):
    # Signal(object): un dict en conexión encolada puede llegar copiado.
    _despachar = Signal(object)
    cambio_estado = Signal()
    actividad = Signal(str)

    def __init__(self, ventana):
        super().__init__(ventana)
        self._ventana = ventana
        self.instancia = uuid.uuid4().hex
        self.puerto: int | None = None
        self._token = ''
        self._srv: socket.socket | None = None
        self._stop = threading.Event()
        self._registro: Path | None = None
        self._hilo: threading.Thread | None = None
        self._conexiones: set[socket.socket] = set()
        self._candado = threading.Lock()
        self._cola = threading.Lock()      # una llamada a la vez
        self._ocupado = False
        self.pila = Pila()
        self._despachar.connect(self._en_principal, Qt.QueuedConnection)
        QCoreApplication.instance().aboutToQuit.connect(self.apagar)

    # ── Vida ─────────────────────────────────────────────────────────────
    @property
    def encendido(self) -> bool:
        return self._srv is not None

    def encender(self) -> int:
        if self.encendido:
            return self.puerto
        mcp_registro.podar()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            srv.bind(("127.0.0.1", 0))
            srv.listen(8)
            srv.settimeout(0.5)
            self._token = mcp_registro.nuevo_token()
            self.puerto = srv.getsockname()[1]
            self._registro = mcp_registro.publicar(self.instancia, self.puerto,
                                                   self._token)
        except BaseException:
            srv.close()
            self.puerto = None
            raise
        self._srv = srv
        self._stop = threading.Event()
        self._hilo = threading.Thread(target=self._servir,
                                      args=(srv, self._stop, self._token),
                                      name="ingeppto-mcp", daemon=True)
        self._hilo.start()
        self.cambio_estado.emit()
        return self.puerto

    def apagar(self):
        if not self.encendido:
            return
        self._stop.set()
        srv, self._srv = self._srv, None
        reg, self._registro = self._registro, None
        self.puerto, self._token = None, ''
        if reg is not None:
            try:
                reg.unlink()
            except OSError:
                pass
        with self._candado:
            for c in [srv, *self._conexiones]:
                try:
                    c.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                c.close()
        hilo, self._hilo = self._hilo, None
        if hilo is not None:
            hilo.join(2.0)
        self.cambio_estado.emit()

    # ── Hilos de red ─────────────────────────────────────────────────────
    def _servir(self, srv, stop, token):
        while not stop.is_set():
            try:
                con, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._candado:
                if stop.is_set() or len(self._conexiones) >= MAX_CONEXIONES:
                    con.close()
                    continue
                self._conexiones.add(con)
            threading.Thread(target=self._conexion, args=(con, stop, token),
                             daemon=True).start()

    def _conexion(self, con, stop, token):
        buf = b""
        ocioso = 0
        try:
            con.settimeout(0.5)
            while not stop.is_set():
                try:
                    trozo = con.recv(65536)
                except socket.timeout:
                    ocioso += 1
                    if ocioso > 120:
                        return
                    continue
                if not trozo:
                    return
                ocioso = 0
                buf += trozo
                while b"\n" in buf:
                    linea, buf = buf.split(b"\n", 1)
                    if not linea.strip():
                        continue
                    resp = self._linea(linea, stop, token)
                    con.settimeout(30)
                    con.sendall(resp or _RECHAZO)
                    con.settimeout(0.5)
                    if resp is None:
                        return
                if len(buf) > MAX_LINEA:
                    con.sendall(_RECHAZO)
                    return
        except OSError:
            pass
        finally:
            with self._candado:
                self._conexiones.discard(con)
            con.close()

    def _linea(self, linea: bytes, stop, token) -> bytes | None:
        """La respuesta, o None si no es una petición (y se corta)."""
        try:
            req = json.loads(linea, parse_constant=_no_finito)
        except (ValueError, RecursionError):
            return None
        if not isinstance(req, dict):
            return None
        rid = req.get("id")
        dado = req.get("token")
        if not isinstance(dado, str) or not hmac.compare_digest(
                dado.encode(), token.encode()):
            return None
        if type(rid) is not int or req.get("instancia") != self.instancia:
            return None
        nombre, args = req.get("tool"), req.get("args")
        resp = {"id": rid, "ok": False}
        if nombre == "ping":
            resp.update(ok=True, result={"instancia": self.instancia})
            return (json.dumps(resp) + "\n").encode()
        try:
            mcp_esquemas.validar(nombre, args if args is not None else {})
            resp.update(ok=True, result=self._ejecutar(nombre, args or {}, stop))
        except (ErrorMCP, mcp_esquemas.ErrorDeArgumentos) as e:
            resp["error"] = str(e)
        except Exception as e:  # noqa: BLE001 — se le cuenta al agente
            resp["error"] = f"error interno ({type(e).__name__}): {e}"
        try:
            return (json.dumps(resp, ensure_ascii=False, allow_nan=False)
                    + "\n").encode()
        except (TypeError, ValueError) as e:
            return (json.dumps({"id": rid, "ok": False,
                                "error": f"respuesta no serializable: {e}"})
                    + "\n").encode()

    def _ejecutar(self, nombre, args, stop):
        # Lo que espera por IngeTrazo va aquí, fuera del hilo de Qt.
        extra = {}
        if nombre in ('bim_diff', 'bim_apply') and args.get('source') == 'ingetrazo':
            # Sin sesión o sin permiso no se consulta IngeTrazo.
            self._en_qt('_permiso', {'nombre': nombre,
                                     'project_id': args['project_id']}, stop)
            extra['_takeoff'] = self._ingetrazo(
                'traer_takeoff', args.get('document_id'))
        if nombre == 'show_in_model':
            ids = self._en_qt('_elementos_a_mostrar',
                              {k: v for k, v in args.items()
                               if k != 'document_id'}, stop)
            return self._ingetrazo('seleccionar_en_ingetrazo', ids,
                                   args.get('document_id'))
        return self._en_qt(nombre, {**args, **extra}, stop)

    @staticmethod
    def _ingetrazo(fn, *a):
        from core import ingetrazo_puente as ip
        try:
            return getattr(ip, fn)(*a)
        except ip.ErrorIngeTrazo as e:
            raise ErrorMCP(str(e)) from None

    def _en_qt(self, nombre, args, stop):
        """Ejecuta en el hilo principal y espera."""
        with self._cola:
            if stop.is_set():
                raise ErrorMCP("la conexión MCP se apagó")
            job = {"nombre": nombre, "args": args, "fin": threading.Event(),
                   "empezo": False, "anulado": False, "res": None, "err": None,
                   "candado": threading.Lock()}
            self._despachar.emit(job)
            t = 0.0
            while not job["fin"].wait(0.5):
                t += 0.5
                with job["candado"]:
                    if not job["empezo"] and (t > ESPERA or stop.is_set()):
                        job["anulado"] = True      # ya no correrá nunca
                        raise ErrorMCP("la app no atendió a tiempo (¿un diálogo "
                                       "abierto?); no se hizo nada")
                if t > ESPERA or stop.is_set():
                    raise ErrorMCP("la operación sigue en curso en la app; NO la "
                                   "repitas sin comprobar el estado")
        if job["err"] is not None:
            raise job["err"]
        return job["res"]

    # ── Hilo principal ───────────────────────────────────────────────────
    def _en_principal(self, job):
        with job["candado"]:
            if job["anulado"]:
                return
            job["empezo"] = True
        try:
            job["res"] = self.ejecutar(job["nombre"], job["args"])
        except Exception as e:  # noqa: BLE001
            job["err"] = e
        finally:
            job["fin"].set()

    def _operaciones(self) -> Operaciones:
        from utils.auth import usuario_actual
        u = usuario_actual()
        if u is None:
            raise ErrorMCP("nadie ha iniciado sesión en IngePresupuestos")
        return Operaciones(u, self.pila)

    def ejecutar(self, nombre: str, args: dict):
        """Una herramienta, en el hilo de Qt."""
        if QThread.currentThread() is not self.thread():
            raise RuntimeError("fuera del hilo principal")
        if self._ocupado:
            raise Ocupado("ocupado: la llamada anterior no ha terminado")
        ops = self._operaciones()
        if nombre == '_permiso':
            from core.database import get_db
            conn = get_db()
            try:
                p = ops._proyecto(conn, args['project_id'])
            finally:
                conn.close()
            if args['nombre'] == 'bim_apply':
                ops._editable(p)
            return None
        if nombre == '_elementos_a_mostrar':
            return ops.elementos_a_mostrar(**args)
        if nombre == 'screenshot':
            return self._captura(ops, **args)
        h = mcp_esquemas.POR_NOMBRE[nombre]
        if not h['lee']:
            self._comprobar_libre()
        self._ocupado = True
        cursor = False
        try:
            if not h['lee'] or nombre == 'export_report':
                QApplication.setOverrideCursor(Qt.WaitCursor)
                cursor = True
            try:
                args = dict(args)
                ops.simular = bool(args.pop('dry_run', False))
                res = getattr(ops, nombre)(**args)
            except Exception as e:
                if type(e).__module__ == 'sqlite3' and 'locked' in str(e):
                    raise Ocupado("ocupado: la base de datos está en uso; "
                                  "reintenta en unos segundos") from None
                raise
            if ops.tocados or ops.creados or ops.borrados:
                try:
                    self._refrescar(ops)
                except Exception as e:  # noqa: BLE001 — ya está guardado
                    res = dict(res, view_warning=f"guardado, pero la vista no "
                                                 f"se refrescó: {e}")
            if not h['lee'] and not ops.simular:
                self.actividad.emit(nombre)
            return res
        finally:
            if cursor:
                QApplication.restoreOverrideCursor()
            self._ocupado = False

    # ── ¿El usuario está editando? ───────────────────────────────────────
    def _vistas(self):
        st = self._ventana.stack
        return [st.widget(i) for i in range(st.count())]

    def deshacer_desde_ui(self, forzar: bool):
        """El botón «Deshacer lo último de la IA» (con su ventana delante)."""
        self._comprobar_libre(modal=False)
        ops = self._operaciones()
        res = ops.undo_last(force=forzar)
        self._refrescar(ops)
        self.actividad.emit('undo_last')
        return res

    def _comprobar_libre(self, modal: bool = True):
        if modal and (QApplication.activeModalWidget() is not None
                      or QApplication.activePopupWidget() is not None):
            raise Ocupado("ocupado: el usuario tiene un diálogo o un menú "
                          "abierto; reintenta cuando lo cierre")
        foco = QApplication.focusWidget()
        for v in self._vistas():
            nombre = str(v.property("vista_nombre") or '')
            if nombre.startswith('editar_proyecto_'):
                raise Ocupado("ocupado: el usuario está editando los datos de "
                              "un proyecto")
            if not nombre.startswith('proyecto_'):
                continue
            for tabla in v.findChildren(QAbstractItemView):
                if tabla.state() == QAbstractItemView.EditingState:
                    raise Ocupado("ocupado: el usuario está editando una celda")
            if getattr(v, '_spec_modificada', False):
                raise Ocupado("ocupado: hay especificaciones técnicas sin "
                              "guardar")
            if foco is not None and v.isAncestorOf(foco) \
                    and foco is not getattr(v, 'inp_buscar', None):
                celda = any(isinstance(p, QAbstractItemView)
                            for p in self._ancestros(foco, v))
                if isinstance(foco, QLineEdit) and (celda or foco.isModified()):
                    raise Ocupado("ocupado: el usuario está escribiendo")
                if isinstance(foco, (QTextEdit, QPlainTextEdit)) \
                        and foco is not getattr(v, 'txt_spec', None) \
                        and not foco.isReadOnly() \
                        and foco.document().isModified():
                    raise Ocupado("ocupado: el usuario está escribiendo")

    @staticmethod
    def _ancestros(w, tope):
        w = w.parentWidget()
        while w is not None and w is not tope:
            yield w
            w = w.parentWidget()

    # ── Refrescar lo abierto ─────────────────────────────────────────────
    def _refrescar(self, ops):
        for pid in ops.borrados:
            if any(p['pid'] == pid for p in self._ventana._proyectos_abiertos):
                self._ventana._cerrar_proyecto_tab(pid)
        vistas = self._vistas()
        for v in vistas:
            nombre = str(v.property("vista_nombre") or '')
            if nombre == 'dashboard':
                cache = getattr(v, '_tot_cache', None)
                if isinstance(cache, dict):
                    for pid in (*ops.tocados, *ops.borrados):
                        cache.pop(pid, None)
                if v is self._ventana.stack.currentWidget():
                    v.cargar_proyectos()
            for pid in ops.tocados:
                if nombre == f'proyecto_{pid}' and hasattr(v, 'recargar_partidas'):
                    refrescar_proyecto_view(v)
        for pid in ops.creados:
            # Abrirlo cambia de pestaña: solo si no interrumpe nada.
            self._ventana._abrir_proyecto(pid)

    # ── Captura ──────────────────────────────────────────────────────────
    def _captura(self, ops, project_id: int | None = None):
        if project_id is not None:
            from core.database import get_db
            conn = get_db()
            try:
                ops._proyecto(conn, project_id)
            finally:
                conn.close()
            w = next((v for v in self._vistas() if v.property("vista_nombre")
                      == f'proyecto_{project_id}'), None)
            if w is None:
                raise ErrorMCP("ese proyecto no está abierto en una pestaña")
        else:
            w = self._ventana.stack.currentWidget()
        nombre = str(w.property("vista_nombre") or '') if w is not None else ''
        if not (nombre in VISTAS_CAPTURABLES or nombre.startswith('proyecto_')):
            raise ErrorMCP("esta pantalla no se captura (puede mostrar claves o "
                           "usuarios); pide al usuario que abra un proyecto")
        pm = w.grab()
        if pm.width() > 1600:
            pm = pm.scaledToWidth(1600, Qt.SmoothTransformation)
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        if pm.isNull() or not pm.save(buf, "PNG"):
            raise ErrorMCP("no se pudo capturar")
        return {"view": nombre, "width": pm.width(), "height": pm.height(),
                "mimeType": "image/png",
                "data": base64.b64encode(bytes(buf.data())).decode()}


def refrescar_proyecto_view(v):
    """Vuelve a leer TODO lo que la vista de un proyecto tiene en memoria. No
    basta el árbol: la planilla y el cronograma guardan copias propias y las
    reescribirían encima."""
    from core.database import get_db
    conn = get_db()
    try:
        vivas = {r[0] for r in conn.execute(
            # sub-partidas: incluidas
            "SELECT id FROM partidas WHERE proyecto_id=?", (v.pid,))}
    finally:
        conn.close()
    actual = getattr(v, '_partida_actual_id', None)
    if getattr(v, '_met_panel_pid', None) not in vivas:
        v._met_panel_pid = None
        for nombre, flag in (('tbl_met', '_met_loading'),
                             ('tbl_acero', '_acero_loading')):
            t = getattr(v, nombre, None)
            if t is not None:
                setattr(v, flag, True)
                t.setRowCount(0)
                setattr(v, flag, False)
    v.recargar_tras_edicion()
    if hasattr(v, 'tbl_acu'):
        if actual in vivas:
            v.cargar_acu(actual)
        elif actual is not None:
            v._acu_en_blanco()
        panel = getattr(v, '_met_panel_pid', None)
        if panel in vivas:
            v._cargar_metrados_auto(panel)
    if hasattr(v, 'tbl_ins'):
        est = getattr(v, '_ins_estado', None)
        if isinstance(est, list):
            est = [i for i in est if i in vivas] or None
        elif est not in vivas:
            est = None
        v.cargar_insumos(est)
    for nombre in ('_metrados_view', '_cron_view', '_control_view'):
        sub = getattr(v, nombre, None)
        if sub is not None and hasattr(sub, 'cargar'):
            if nombre == '_cron_view':
                sub._proy = v._proy
            sub.cargar()
    try:
        if v._root_stack.currentIndex() == 1:
            v.cargar_pie()
    except AttributeError:
        pass


# ── Acceso desde la ventana ──────────────────────────────────────────────────

def puente_de(ventana) -> PuenteMCP:
    p = getattr(ventana, '_puente_mcp', None)
    if p is None:
        p = ventana._puente_mcp = PuenteMCP(ventana)
    return p


def arrancar_si_corresponde(ventana):
    """Al iniciar sesión: enciende el puente si el usuario lo dejó encendido.
    Nunca estorba el arranque."""
    try:
        from core.database import get_config
        if get_config(CLAVE_ACTIVO, '0') == '1':
            puente_de(ventana).encender()
    except Exception:
        pass
