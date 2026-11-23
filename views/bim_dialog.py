# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Diálogos BIM: vista previa de un modelo, vínculos con partidas y
actualización. Toda la lógica está en `core.bim_modelo`.

Puertas de entrada:
- `ImportarBimDialog` — importar un modelo (proyecto nuevo o existente).
- `ModeloBimDialog`   — «Modelo BIM…» dentro del proyecto. Con
  `recibir_takeoff(dict)` acepta directamente lo que manda IngeTrazo.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core import bim_modelo as bim
from core.config import puede_editar
from core.database import get_db, get_decimales_metrado
from utils.formatting import norm_busqueda, parse_num
from utils.auth import usuario_actual
from utils.i18n import N_, tr
from utils.theme import BTN_PRIMARY_SS, btn_secondary
from views.aviso_precios_dialog import moneda_de_proyecto

SLATE_700, SLATE_500, SLATE_100 = "#2E3C52", "#485A6C", "#E2E8F0"
SILVER_100, WHITE, ROJO = "#F8F9FA", "#FFFFFF", "#B71C1C"
FILTRO = "IFC / IngeTrazo (*.ifc *.json)"

_AVISOS = {bim.SIN_CANTIDAD: N_("sin cantidad"), bim.BRUTA: N_("cantidad bruta (sin descontar vanos)")}


def leer_archivo(ruta) -> bim.ModeloBim:
    if str(ruta).lower().endswith('.json'):
        try:
            datos = json.loads(Path(ruta).read_text(encoding='utf-8-sig'))
        except ValueError as e:
            raise ValueError(tr("El archivo no es un JSON válido.")) from e
        return bim.leer_takeoff(datos)
    return bim.leer_ifc(ruta)


class LectorBim(QThread):
    """Lee el archivo fuera del hilo de la interfaz."""
    listo = Signal(object)
    fallo = Signal(str)

    def __init__(self, ruta, parent=None):
        super().__init__(parent)
        self._ruta = ruta

    def run(self):
        try:
            self.listo.emit(leer_archivo(self._ruta))
        except Exception as e:                        # noqa: BLE001 — al usuario
            self.fallo.emit(str(e) or type(e).__name__)


def _num(v) -> str:
    return f"{v:,.{get_decimales_metrado()}f}"


def _boton(texto, accion, primario=False) -> QPushButton:
    b = QPushButton(texto)
    b.setCursor(Qt.PointingHandCursor)
    b.setAutoDefault(False)
    b.setStyleSheet(BTN_PRIMARY_SS if primario else btn_secondary())
    b.clicked.connect(lambda: accion())
    return b


def _nota(texto='', color=SLATE_500) -> QLabel:
    lb = QLabel(texto)
    lb.setWordWrap(True)
    lb.setTextFormat(Qt.PlainText)
    lb.setStyleSheet(f"color:{color}; font-size:11px; border:none;")
    return lb


def _arbol(cabeceras, ancho0=300) -> QTreeWidget:
    t = QTreeWidget()
    t.setHeaderLabels(cabeceras)
    t.setUniformRowHeights(True)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setStyleSheet(f"QTreeWidget {{ background:{WHITE}; border:1px solid {SLATE_100};"
                    f" border-radius:6px; font-size:11px; }}"
                    f"QHeaderView::section {{ background:{SILVER_100}; color:{SLATE_700};"
                    f" font-weight:700; font-size:10px; border:none; padding:4px; }}")
    t.header().setStretchLastSection(True)
    t.setColumnWidth(0, ancho0)
    return t


def _avisos(e) -> str:
    out = [tr(_AVISOS.get(a, a)) for a in e.avisos]
    if e.parte_de:
        out.append(tr("parte de otro elemento"))
    return ", ".join(out)


class ArbolElementos(QTreeWidget):
    """Clase ▸ tipo ▸ piso ▸ elemento, con casillas. Los elementos se crean al
    desplegar su piso: con 50 000 no se puede poblar todo de entrada."""

    marcados_cambian = Signal()

    def __init__(self, extra_cab='', parent=None):
        super().__init__(parent)
        base = _arbol([])
        self.setStyleSheet(base.styleSheet())
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        cab = [tr("Elemento"), tr("N.º"), tr("Metrado"), tr("Aviso")]
        self._con_extra = bool(extra_cab)
        self.setHeaderLabels(cab + ([extra_cab] if extra_cab else []))
        self.setColumnWidth(0, 230 if extra_cab else 330)
        self.setColumnWidth(1, 50)
        self.setColumnWidth(2, 110)
        self.setColumnWidth(3, 110)
        self._grupos: dict = {}
        self._extra: dict = {}
        self.itemExpanded.connect(self._poblar)
        self.itemChanged.connect(self._cambio)

    def cargar(self, elementos, marcados=None, extra=None):
        """`marcados(e)`: estado inicial; `extra`: {global_id: texto}."""
        marcados = marcados or (lambda e: False)
        self._extra = extra or {}
        self.blockSignals(True)
        self.clear()
        self._grupos, jer = {}, {}
        for e in elementos:
            jer.setdefault(e.clase, {}).setdefault(e.tipo, {}).setdefault(e.piso, []).append(e)
        for clase in sorted(jer, key=bim.nombre_clase):
            nc = self._nodo(self, f"{bim.nombre_clase(clase)}  ({clase})",
                            [e for t in jer[clase].values() for p in t.values() for e in p])
            for tipo in sorted(jer[clase]):
                nt = self._nodo(nc, tipo or tr("(sin tipo)"),
                                [e for p in jer[clase][tipo].values() for e in p])
                for piso, els in sorted(jer[clase][tipo].items()):
                    np = self._nodo(nt, piso or tr("(sin piso)"), els)
                    np.setData(0, Qt.UserRole, len(self._grupos))
                    self._grupos[len(self._grupos)] = {'els': els, 'nodo': np, 'hechos': False,
                                                       'marca': {e.global_id for e in els if marcados(e)}}
                    np.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
                    self._pintar_piso(np)
                self._pintar_padre(nt)
            self._pintar_padre(nc)
        self.blockSignals(False)
        self.marcados_cambian.emit()

    def _nodo(self, padre, texto, els):
        it = QTreeWidgetItem(padre, [texto, str(len(els))])
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        sumas, avisos = {}, {}
        for e in els:
            if e.metrado and e.se_presupuesta:
                sumas[e.metrado[1]] = sumas.get(e.metrado[1], 0) + e.metrado[0]
            for a in e.avisos:
                avisos[a] = avisos.get(a, 0) + 1
        it.setText(2, " + ".join(f"{_num(v)} {u}" for u, v in sumas.items()))
        it.setText(3, ", ".join(f"{n} {tr(_AVISOS.get(a, a))}" for a, n in avisos.items()))
        if avisos:
            it.setForeground(3, Qt.darkRed)
        return it

    def _poblar(self, np):
        g = self._grupos.get(np.data(0, Qt.UserRole))
        if g is None or np.parent() is None or g['hechos']:
            return
        g['hechos'] = True
        self.blockSignals(True)
        hijos = []
        for e in g['els']:
            h = QTreeWidgetItem([e.nombre or e.global_id, '',
                                 f"{_num(e.metrado[0])} {e.metrado[1]}" if e.metrado else '—',
                                 _avisos(e), self._extra.get(e.global_id, '')])
            h.setFlags(h.flags() | Qt.ItemIsUserCheckable)
            h.setData(0, Qt.UserRole + 1, e.global_id)
            h.setCheckState(0, Qt.Checked if e.global_id in g['marca'] else Qt.Unchecked)
            h.setToolTip(0, "\n".join([e.global_id] + [f"{k}: {v:g} {u}" for k, (v, u) in
                                                       e.cantidades.items()]
                                      + ([e.material] if e.material else [])))
            if e.avisos:
                h.setForeground(3, Qt.darkRed)
            hijos.append(h)
        np.addChildren(hijos)
        self.blockSignals(False)

    def _pintar_piso(self, np):
        g = self._grupos[np.data(0, Qt.UserRole)]
        n = len(g['marca'])
        np.setCheckState(0, Qt.Unchecked if not n else
                         Qt.Checked if n == len(g['els']) else Qt.PartiallyChecked)

    def _pintar_padre(self, it):
        est = {it.child(i).checkState(0) for i in range(it.childCount())}
        it.setCheckState(0, est.pop() if len(est) == 1 else Qt.PartiallyChecked)

    def _cambio(self, it, col):
        if col != 0:
            return
        self.blockSignals(True)
        marca = it.checkState(0) == Qt.Checked
        gid = it.data(0, Qt.UserRole + 1)
        if gid is not None:
            g = self._grupos[it.parent().data(0, Qt.UserRole)]
            g['marca'].add(gid) if marca else g['marca'].discard(gid)
            self._pintar_piso(it.parent())
            arriba = it.parent().parent()
        else:
            self._marcar_rama(it, marca)
            arriba = it.parent()
        while arriba is not None:
            self._pintar_padre(arriba)
            arriba = arriba.parent()
        self.blockSignals(False)
        self.marcados_cambian.emit()

    def marcar(self, gids):
        """Deja marcados exactamente esos elementos."""
        gids = set(gids)
        self.blockSignals(True)
        for g in self._grupos.values():
            g['marca'] = {e.global_id for e in g['els'] if e.global_id in gids}
            np = g['nodo']
            for i in range(np.childCount()):
                h = np.child(i)
                h.setCheckState(0, Qt.Checked if h.data(0, Qt.UserRole + 1) in g['marca']
                                else Qt.Unchecked)
            self._pintar_piso(np)
        for i in range(self.topLevelItemCount()):
            nc = self.topLevelItem(i)
            for j in range(nc.childCount()):
                self._pintar_padre(nc.child(j))
            self._pintar_padre(nc)
        self.blockSignals(False)
        self.marcados_cambian.emit()

    def _marcar_rama(self, it, marca):
        g = self._grupos.get(it.data(0, Qt.UserRole))
        it.setCheckState(0, Qt.Checked if marca else Qt.Unchecked)
        if g is not None:
            g['marca'] = {e.global_id for e in g['els']} if marca else set()
        for i in range(it.childCount()):
            h = it.child(i)
            if h.data(0, Qt.UserRole + 1) is not None:
                h.setCheckState(0, it.checkState(0))
            else:
                self._marcar_rama(h, marca)

    def marcar_todo(self, marca: bool):
        self.blockSignals(True)
        for i in range(self.topLevelItemCount()):
            self._marcar_rama(self.topLevelItem(i), marca)
        self.blockSignals(False)
        self.marcados_cambian.emit()

    def marcados(self) -> list:
        return [e for g in self._grupos.values() for e in g['els'] if e.global_id in g['marca']]


class _Base(QDialog):
    def __init__(self, titulo, parent=None, w=980, h=640):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setWindowModality(Qt.WindowModal)
        self.resize(w, h)
        self.setMinimumSize(720, 460)
        self.setStyleSheet(f"QDialog {{ background:{SILVER_100}; }}")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(18, 14, 18, 14)
        self.v.setSpacing(8)
        self._lector = None

    # Lectura en segundo plano ------------------------------------------------
    def _leer(self, ruta, al_listo):
        if self._lector is not None:
            return
        self._lector = LectorBim(ruta, self)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.setEnabled(False)
        # Método de QObject y no lambda: así la señal llega encolada al hilo
        # de la interfaz.
        self._al_listo = (al_listo, ruta)
        self._lector.listo.connect(self._leido)
        self._lector.fallo.connect(self._mal)
        self._lector.start()

    def _soltar(self):
        QApplication.restoreOverrideCursor()
        self.setEnabled(True)
        lector, self._lector = self._lector, None
        if lector is not None:
            lector.wait()
            lector.deleteLater()

    def _leido(self, modelo):
        al_listo, ruta = self._al_listo
        self._soltar()
        al_listo(modelo, ruta)

    def _mal(self, msg):
        self._soltar()
        QMessageBox.critical(self, tr("Modelo BIM"), tr("No se pudo leer el archivo:\n\n{e}").format(e=msg))

    def _error(self, e):
        QMessageBox.critical(self, tr("Modelo BIM"), str(e) or type(e).__name__)

    def done(self, r):
        if self._lector is not None:
            for s in (self._lector.listo, self._lector.fallo):
                s.disconnect()
            self._soltar()
        super().done(r)


def _subs(pid):
    c = get_db()
    try:
        return [(r['id'], r['nombre']) for r in c.execute(
            "SELECT id, nombre FROM sub_presupuestos WHERE proyecto_id=? ORDER BY orden, id", (pid,))]
    finally:
        c.close()


class ImportarBimDialog(_Base):
    """Vista previa del modelo y destino. Al aceptar deja `proyecto_id`.

    Con `pid` el destino es ese proyecto (se llega desde «Modelo BIM…»)."""

    def __init__(self, modelo, ruta='', pid=None, sub_id=None, parent=None):
        super().__init__(tr("Importar modelo BIM"), parent)
        self.modelo, self.ruta, self._pid, self._sub = modelo, str(ruta or ''), pid, sub_id
        self.proyecto_id = None
        self.creadas = 0
        tit = QLabel(modelo.nombre or Path(self.ruta).name)
        tit.setTextFormat(Qt.PlainText)
        tit.setStyleSheet(f"color:{SLATE_700}; font-size:14px; font-weight:700;")
        self.v.addWidget(tit)
        self.v.addWidget(_nota(tr("{n} elementos. Desmarca lo que no quieras presupuestar; cada partida "
                                  "reúne los elementos marcados de la misma clase, tipo y unidad.").format(
                                      n=len(modelo.elementos))))
        self.arbol = ArbolElementos(parent=self)
        self.v.addWidget(self.arbol, 1)
        if modelo.avisos:
            self.v.addWidget(_nota("\n".join(modelo.avisos[:6]), ROJO))
        fila = QHBoxLayout()
        self.cmb = QComboBox()
        self.cmb_sub = QComboBox()
        if pid is None:
            self.cmb.addItem(tr("Crear un proyecto nuevo"), None)
            c = get_db()
            try:
                # Los mismos proyectos que muestra el Inicio a este usuario.
                usuario = usuario_actual()
                cond, par = '', ()
                if usuario is not None and not usuario.es_admin:
                    cond, par = " WHERE usuario_id=? OR usuario_id IS NULL", (usuario.id,)
                for r in c.execute("SELECT id, nombre, estado FROM proyectos" + cond
                                   + " ORDER BY id DESC", par):
                    if not puede_editar(r['estado'] or 'elaboracion', 'presupuesto'):
                        continue
                    self.cmb.addItem(tr("Añadir a: {p}").format(p=r['nombre']), r['id'])
            finally:
                c.close()
            self.cmb.currentIndexChanged.connect(self._destino)
            fila.addWidget(QLabel(tr("Destino")))
            fila.addWidget(self.cmb, 1)
        fila.addWidget(self.cmb_sub, 1)
        self.v.addLayout(fila)
        pie = QHBoxLayout()
        self.lbl = _nota()
        pie.addWidget(self.lbl, 1)
        pie.addWidget(_boton(tr("Cancelar"), self.reject))
        self.b_ok = _boton(tr("Crear partidas"), self._aceptar, True)
        pie.addWidget(self.b_ok)
        self.v.addLayout(pie)
        self.arbol.marcados_cambian.connect(self._resumen)
        self._destino()
        self.arbol.cargar(modelo.elementos, lambda e: e.se_presupuesta)

    def _pid_destino(self):
        return self._pid if self._pid is not None else self.cmb.currentData()

    def _destino(self):
        pid = self._pid_destino()
        self.cmb_sub.clear()
        subs = _subs(pid) if pid else []
        self.cmb_sub.addItem(tr("Presupuesto principal"), None)
        for i, n in subs:
            self.cmb_sub.addItem(n, i)
        self.cmb_sub.setCurrentIndex(max(0, self.cmb_sub.findData(self._sub)))
        self.cmb_sub.setVisible(bool(subs))

    def propuestas(self):
        return bim.proponer_partidas(self.arbol.marcados())

    def _resumen(self):
        ps = self.propuestas()
        self.lbl.setText(tr("{n} partida(s)").format(n=len(ps)))
        self.b_ok.setEnabled(bool(ps))

    def _aceptar(self):
        pid, ps = self._pid_destino(), self.propuestas()
        if pid is not None:
            ya = self._vinculados(pid)
            rep = sum(1 for p in ps for g in p['global_ids'] if g in ya)
            if rep and QMessageBox.question(
                    self, self.windowTitle(),
                    tr("{n} de estos elementos ya están vinculados a partidas del proyecto: se contarían "
                       "dos veces. ¿Seguir?").format(n=rep)) != QMessageBox.Yes:
                return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if pid is None:
                self.proyecto_id = bim.crear_proyecto(self.modelo, self.ruta, ps)
            else:
                bim.anadir_partidas(pid, self.modelo, self.ruta, ps, sub_id=self.cmb_sub.currentData())
                self.proyecto_id = pid
            self.creadas = len(ps)
        except Exception as e:                        # noqa: BLE001 — al usuario
            QApplication.restoreOverrideCursor()
            return self._error(e)
        QApplication.restoreOverrideCursor()
        self.accept()

    @staticmethod
    def _vinculados(pid):
        c = get_db()
        try:
            return {r[0] for r in c.execute(
                "SELECT v.global_id FROM bim_vinculos v JOIN bim_modelos m ON m.id=v.modelo_id "
                "WHERE m.proyecto_id=?", (pid,))}
        finally:
            c.close()


class DiferenciasDialog(_Base):
    """Qué cambió en el modelo y qué metrados moverá. Solo se aplica lo marcado."""

    def __init__(self, modelo_id, nuevo, ruta='', parent=None):
        super().__init__(tr("Actualizar modelo BIM"), parent)
        self.modelo_id, self.nuevo, self.ruta = modelo_id, nuevo, str(ruta or '')
        self.resultado = None
        d = self.dif = bim.diferencias(modelo_id, nuevo)
        self.v.addWidget(_nota(tr("{n} nuevos · {b} borrados · {c} cambiados · {i} iguales").format(
            n=len(d['nuevos']), b=len(d['borrados']), c=len(d['cambiados']), i=len(d['iguales']))))
        comunes = len(d['iguales']) + len(d['cambiados'])
        self.ajeno = not comunes and bool(d['borrados'])
        if self.ajeno:
            self.v.addWidget(_nota(tr("Ningún elemento coincide con el modelo guardado: parece otro modelo."),
                                   ROJO))
        self.t = _arbol([tr("Cambio"), tr("Antes"), tr("Después"), tr("Detalle")], 400)
        self.t.setColumnWidth(1, 110)
        self.t.setColumnWidth(2, 110)
        self.v.addWidget(self.t, 1)
        self._partidas()
        self._nuevos()
        self._lista(tr("Elementos cambiados"), [
            (c['despues'].nombre or c['global_id'], self._m(c['antes']), self._m(c['despues']),
             ", ".join(c['campos'])) for c in d['cambiados']])
        self._lista(tr("Elementos borrados"), [
            (e.nombre or e.global_id, self._m(e), '—', bim.nombre_clase(e.clase)) for e in d['borrados']])
        if nuevo.avisos:
            self.v.addWidget(_nota("\n".join(nuevo.avisos[:6]), ROJO))
        self.v.addWidget(_nota(tr("Las filas escritas o editadas a mano no se tocan. Lo que no marques sigue "
                                  "como está y vuelve a salir la próxima vez.")))
        pie = QHBoxLayout()
        pie.addStretch(1)
        pie.addWidget(_boton(tr("Cancelar"), self.reject))
        pie.addWidget(_boton(tr("Aplicar lo marcado"), self._aplicar, True))
        self.v.addLayout(pie)

    @staticmethod
    def _m(e):
        return f"{_num(e.metrado[0])} {e.metrado[1]}" if e.metrado else '—'

    def _raiz(self, texto, n, abierta=True):
        r = QTreeWidgetItem(self.t, [f"{texto} ({n})"])
        f = r.font(0)
        f.setBold(True)
        r.setFont(0, f)
        r.setExpanded(abierta)
        return r

    def _partidas(self):
        self.it_partidas = []
        if not self.dif['partidas']:
            return
        raiz = self._raiz(tr("Metrados que cambian"), len(self.dif['partidas']))
        for p in self.dif['partidas']:
            det = []
            for k, t in (('actualizar', tr("{n} fila(s) cambian")), ('borrar', tr("{n} fila(s) se quitan")),
                         ('editadas', tr("{n} editada(s) a mano: no se tocan")),
                         ('sin_medida', tr("{n} sin la cantidad en el modelo nuevo: se conservan"))):
                if p[k]:
                    det.append(t.format(n=p[k]))
            it = QTreeWidgetItem(raiz, [f"{p['item']}  {p['descripcion']}", f"{_num(p['antes'])} {p['unidad'] or ''}",
                                        f"{_num(p['despues'])} {p['unidad'] or ''}", "; ".join(det)])
            it.setData(0, Qt.UserRole, p['partida_id'])
            if p['actualizar'] or p['borrar']:
                it.setCheckState(0, Qt.Unchecked if self.ajeno else Qt.Checked)
                self.it_partidas.append(it)

    def _nuevos(self):
        self.it_nuevos = []
        els = self.dif['nuevos']
        if not els:
            return
        c = get_db()
        try:
            nom = {r['id']: f"{r['item']}  {r['descripcion']}" for r in c.execute(
                "SELECT p.id, p.item, p.descripcion FROM partidas_ppto p JOIN bim_modelos m "
                "ON m.proyecto_id=p.proyecto_id WHERE m.id=?", (self.modelo_id,))}
        finally:
            c.close()
        raiz = self._raiz(tr("Elementos nuevos"), len(els))
        filas = []
        for e in els:
            pid = self.dif['sugerencias'].get(e.global_id)
            it = QTreeWidgetItem([e.nombre or e.global_id, '—', self._m(e),
                                  tr("Vincular a {p}").format(p=nom[pid]) if pid in nom
                                  else tr("Sin partida: vincúlalo después")])
            if pid in nom:
                it.setData(0, Qt.UserRole, (e.global_id, pid))
                it.setCheckState(0, Qt.Unchecked)
                self.it_nuevos.append(it)
            filas.append(it)
        raiz.addChildren(filas)

    def _lista(self, titulo, filas):
        if filas:
            raiz = self._raiz(titulo, len(filas), False)
            raiz.addChildren([QTreeWidgetItem(list(f)) for f in filas])

    def _aplicar(self):
        if self.ajeno and QMessageBox.question(
                self, self.windowTitle(),
                tr("Este archivo no tiene ningún elemento del modelo guardado. ¿Reemplazarlo de todos "
                   "modos?")) != QMessageBox.Yes:
            return
        partidas = [i.data(0, Qt.UserRole) for i in self.it_partidas if i.checkState(0) == Qt.Checked]
        nuevos = dict(i.data(0, Qt.UserRole) for i in self.it_nuevos if i.checkState(0) == Qt.Checked)
        try:
            self.resultado = bim.aplicar(self.modelo_id, self.nuevo, partidas, nuevos=nuevos,
                                         ruta=self.ruta or None)
        except Exception as e:                        # noqa: BLE001 — al usuario
            return self._error(e)
        self.accept()


class ModeloBimDialog(_Base):
    """Modelos del proyecto y vínculos elemento ↔ partida. `cambio` queda en
    True si se escribió algo (para refrescar el presupuesto al cerrar)."""

    def __init__(self, pid, partida_id=None, editable=True, sub_id=None, parent=None):
        super().__init__(tr("Modelo BIM"), parent, 1180, 720)
        self.pid, self.sub_id, self.editable = pid, sub_id, editable
        self.cambio = False
        self._partidas_rows = []
        arriba = QHBoxLayout()
        arriba.addWidget(QLabel(tr("Modelo")))
        self.cmb_modelo = QComboBox()
        self.cmb_modelo.currentIndexChanged.connect(lambda *_: self._cargar_modelo())
        arriba.addWidget(self.cmb_modelo, 1)
        self.b_agregar = _boton(tr("Agregar modelo…"), self._agregar)
        self.b_actualizar = _boton(tr("Actualizar desde archivo…"), self._actualizar)
        self.b_quitar = _boton(tr("Quitar"), self._quitar)
        self.b_3d = _boton(tr("Vista 3D"), self._alternar_3d)
        self.b_3d.setCheckable(True)
        self.visor = None
        self._desde_visor = False
        for b in (self.b_agregar, self.b_actualizar, self.b_quitar, self.b_3d):
            arriba.addWidget(b)
        self.v.addLayout(arriba)

        sp = self._sp = QSplitter(Qt.Horizontal)
        izq = QWidget()
        li = QVBoxLayout(izq)
        li.setContentsMargins(0, 0, 0, 0)
        ff = QHBoxLayout()
        self.ed_filtro = QLineEdit()
        self.ed_filtro.setPlaceholderText(tr("Buscar por nombre, clase, tipo, piso, capa o material"))
        self.ed_filtro.returnPressed.connect(self._cargar_arbol)
        ff.addWidget(self.ed_filtro, 1)
        self.chk_sueltos = QCheckBox(tr("Solo sin vincular"))
        self.chk_sueltos.toggled.connect(lambda *_: self._cargar_arbol())
        ff.addWidget(self.chk_sueltos)
        li.addLayout(ff)
        self.arbol = ArbolElementos(tr("Partidas"), self)
        self.arbol.marcados_cambian.connect(self._estado)
        li.addWidget(self.arbol, 1)
        self.lbl_marcados = _nota()
        li.addWidget(self.lbl_marcados)
        sp.addWidget(izq)

        der = QFrame()
        ld = QVBoxLayout(der)
        ld.setContentsMargins(8, 0, 0, 0)
        self.ed_partida = QLineEdit()
        self.ed_partida.setPlaceholderText(tr("Buscar partida"))
        self.ed_partida.textChanged.connect(lambda *_: self._filtrar_partidas())
        ld.addWidget(self.ed_partida)
        self.tp = _arbol([tr("Partida"), tr("Und"), tr("Metrado")], 280)
        self.tp.setRootIsDecorated(False)
        self.tp.setColumnWidth(1, 45)
        self.tp.currentItemChanged.connect(lambda *_: self._cargar_vinculos())
        ld.addWidget(self.tp, 1)
        fm = QHBoxLayout()
        fm.addWidget(QLabel(tr("Medida")))
        self.cmb_medida = QComboBox()
        fm.addWidget(self.cmb_medida, 1)
        fm.addWidget(QLabel(tr("Factor")))
        self.ed_factor = QLineEdit("1")
        self.ed_factor.setFixedWidth(64)
        self.ed_factor.setToolTip(tr("Multiplica la cantidad del modelo. Ej.: 2 para tarrajear las dos caras."))
        fm.addWidget(self.ed_factor)
        self.b_vincular = _boton(tr("Vincular lo marcado"), self._vincular, True)
        fm.addWidget(self.b_vincular)
        ld.addLayout(fm)
        self.tv = _arbol([tr("Vínculos de la partida"), tr("Medida"), tr("Metrado"), tr("Aviso")], 200)
        self.tv.setRootIsDecorated(False)
        self.tv.setSelectionMode(QAbstractItemView.ExtendedSelection)
        ld.addWidget(self.tv, 1)
        fv = QHBoxLayout()
        self.b_desvincular = _boton(tr("Desvincular seleccionados"), self._desvincular)
        self.b_acu = _boton(tr("ACU de la biblioteca…"), self._acu)
        fv.addWidget(self.b_desvincular)
        fv.addWidget(self.b_acu)
        self.b_mostrar = _boton(tr("Mostrar en IngeTrazo"), self._mostrar)
        fv.addWidget(self.b_mostrar)
        fv.addStretch(1)
        ld.addLayout(fv)
        sp.addWidget(der)
        sp.setSizes([620, 520])
        self.v.addWidget(sp, 1)

        pie = QHBoxLayout()
        self.b_crear = _boton(tr("Crear partidas con lo marcado"), self._crear)
        pie.addWidget(self.b_crear)
        pie.addStretch(1)
        pie.addWidget(_boton(tr("Cerrar"), self.accept))
        self.v.addLayout(pie)
        self._cargar_partidas(partida_id)
        self._cargar_modelos()

    # ── Modelos ──────────────────────────────────────────────────────────────
    @property
    def modelo_id(self):
        return self.cmb_modelo.currentData()

    @property
    def partida_id(self):
        it = self.tp.currentItem()
        return it.data(0, Qt.UserRole) if it is not None else None

    def _cargar_modelos(self, mid=None):
        mid = mid or self.modelo_id
        self.cmb_modelo.blockSignals(True)
        self.cmb_modelo.clear()
        for m in bim.modelos(self.pid):
            self.cmb_modelo.addItem(tr("{nombre} — {n} elementos").format(
                nombre=m['nombre'] or Path(m['ruta'] or '').name, n=m['n_elementos']), m['id'])
        i = self.cmb_modelo.findData(mid)
        self.cmb_modelo.setCurrentIndex(i if i >= 0 else self.cmb_modelo.count() - 1)
        self.cmb_modelo.blockSignals(False)
        self._cargar_modelo()

    def _cargar_modelo(self):
        self._els = bim.elementos(self.modelo_id) if self.modelo_id else []
        ant = self.cmb_medida.currentData()
        self.cmb_medida.clear()
        self.cmb_medida.addItem(tr("Automática (según la unidad)"), None)
        self.cmb_medida.addItem(tr("Metrado del modelo"), 'metrado')
        self.cmb_medida.addItem(tr("Contar (und)"), 'und')
        for k, u in sorted({(k, u) for e in self._els for k, (_v, u) in e.cantidades.items()}):
            self.cmb_medida.addItem(f"{k} ({u})", k)
        self.cmb_medida.setCurrentIndex(max(0, self.cmb_medida.findData(ant) if ant else 0))
        self._cargar_arbol()
        self._cargar_vinculos()
        if self.visor is not None and self.b_3d.isChecked():
            self._abrir_3d()

    def _cargar_arbol(self):
        extra = {}
        if self.modelo_id:
            c = get_db()
            try:
                for r in c.execute("SELECT v.global_id, p.item FROM bim_vinculos v JOIN partidas p "
                                   "ON p.id=v.partida_id WHERE v.modelo_id=? ORDER BY p.item", (self.modelo_id,)):
                    extra[r[0]] = f"{extra[r[0]]}, {r[1]}" if r[0] in extra else str(r[1])
            finally:
                c.close()
        self._extra = extra
        q = norm_busqueda(self.ed_filtro.text()).split()
        sueltos = self.chk_sueltos.isChecked()
        els = []
        for e in self._els:
            if sueltos and e.global_id in extra:
                continue
            if q:
                t = norm_busqueda(" ".join((e.nombre, e.clase, bim.nombre_clase(e.clase), e.tipo, e.piso,
                                            e.capa, e.material)))
                if not all(x in t for x in q):
                    continue
            els.append(e)
        self.arbol.cargar(els, extra=extra)

    def _estado(self):
        n = len(self.arbol.marcados())
        self.lbl_marcados.setText(tr("{m} marcados · {v} de {n} vinculados").format(
            m=n, v=len(getattr(self, '_extra', {})), n=len(getattr(self, '_els', []))))
        hay = self.modelo_id is not None
        e = self.editable
        self.b_agregar.setEnabled(e)
        self.b_actualizar.setEnabled(e and hay)
        self.b_quitar.setEnabled(e and hay)
        self.b_3d.setEnabled(hay or self.b_3d.isChecked())
        self.b_crear.setEnabled(e and hay and n > 0)
        self.b_vincular.setEnabled(e and hay and n > 0 and self.partida_id is not None)
        self.b_desvincular.setEnabled(e and self.tv.topLevelItemCount() > 0)
        self.b_mostrar.setEnabled(n > 0 or self.tv.topLevelItemCount() > 0)
        self.b_acu.setEnabled(e and self.partida_id is not None)

    # ── Vista 3D ─────────────────────────────────────────────────────────────
    def _alternar_3d(self):
        if not self.b_3d.isChecked():
            if self.visor is not None:
                self.visor.cerrar()
                self.visor.hide()
                self._ruta_3d = None
            return
        if self.visor is None:
            from views.bim_visor import BimVisor
            self.visor = BimVisor(self)
            self.visor.seleccion_cambiada.connect(self._elegido_en_3d)
            self.visor.cargado.connect(self._cargar_vinculos)
            self._sp.addWidget(self.visor)
            self._sp.setSizes([340, 320, 520])
            self._sp.setStretchFactor(2, 1)
            for i in range(3):
                self._sp.setCollapsible(i, False)
            for i in (0, 1):
                self._sp.widget(i).setMinimumWidth(300)
            self.resize(max(self.width(), 1320), self.height())
        self.visor.show()
        self._abrir_3d()

    def _estados_3d(self):
        return {e.global_id: 'vinculado' if e.global_id in self._extra else 'sin'
                for e in self._els}

    def _abrir_3d(self):
        """El modelo elegido, en 3D. Lo traído de IngeTrazo no trae archivo: se
        pide su IFC (comparte los GlobalId)."""
        mid = self.modelo_id
        if mid is None:
            self._ruta_3d = None
            return self.visor.cerrar()
        m = next(x for x in bim.modelos(self.pid) if x['id'] == mid)
        rutas = self.__dict__.setdefault('_rutas_3d', {})
        ruta = rutas.get(mid) or m['ruta'] or ''
        if not (ruta.lower().endswith('.ifc') and Path(ruta).is_file()):
            from views.bim_visor import motivo_no_disponible
            ruta = '' if motivo_no_disponible() else QFileDialog.getOpenFileName(
                self, tr("Elige el IFC de este modelo para verlo en 3D"), "",
                tr("Modelos IFC") + " (*.ifc *.IFC)")[0]
            if not ruta and not motivo_no_disponible():
                self.b_3d.setChecked(False)
                return self._alternar_3d()
            rutas[mid] = ruta
        # Mismo archivo ya abierto: solo cambian los colores. Un IFC
        # reescrito tiene otra fecha y sí se vuelve a leer.
        clave = (ruta, Path(ruta).stat().st_mtime_ns if ruta else 0)
        if clave == getattr(self, '_ruta_3d', None):
            return self.visor.set_estados(self._estados_3d())
        self._ruta_3d = clave
        self.visor.abrir(ruta, self._estados_3d())

    def _elegido_en_3d(self, gids):
        """Clic en el modelo: marca los elementos y va a su partida."""
        if any(g not in {e.global_id for g2 in self.arbol._grupos.values() for e in g2['els']}
               for g in gids) and (self.ed_filtro.text() or self.chk_sueltos.isChecked()):
            self.ed_filtro.clear()
            self.chk_sueltos.blockSignals(True)
            self.chk_sueltos.setChecked(False)
            self.chk_sueltos.blockSignals(False)
            self._cargar_arbol()
        self.arbol.marcar(gids)
        if not gids:
            return
        suyas = bim.partidas_de(self.modelo_id, gids[0])
        if not suyas or self.partida_id in suyas:
            return
        self._desde_visor = True
        try:
            for i in range(self.tp.topLevelItemCount()):
                it = self.tp.topLevelItem(i)
                if it.data(0, Qt.UserRole) == suyas[0]:
                    self.ed_partida.clear()
                    self.tp.setCurrentItem(it)
                    self.tp.scrollToItem(it)
                    break
        finally:
            self._desde_visor = False

    def done(self, r):
        if self.visor is not None:
            self.visor.cerrar()
        super().done(r)

    def _pedir_archivo(self):
        ruta, _f = QFileDialog.getOpenFileName(self, tr("Elegir modelo"), "", FILTRO)
        return ruta

    def _agregar(self):
        ruta = self._pedir_archivo()
        if ruta:
            self._leer(ruta, self.recibir_modelo)

    def _actualizar(self):
        ruta = self._pedir_archivo()
        if ruta:
            self._leer(ruta, lambda m, r: self._comparar(self.modelo_id, m, r))

    def recibir_takeoff(self, takeoff: dict, ruta: str = ''):
        """Entrada para «Traer de IngeTrazo»: el takeoff ya leído."""
        try:
            m = bim.leer_takeoff(takeoff)
        except ValueError as e:
            return self._error(e)
        self.recibir_modelo(m, ruta)

    def recibir_modelo(self, modelo, ruta=''):
        """Modelo conocido (comparte elementos con uno del proyecto) → se
        compara; si no, se agrega para vincularlo."""
        mid = self.modelo_parecido(modelo)
        if mid is not None:
            return self._comparar(mid, modelo, ruta)
        try:
            mid = bim.registrar_modelo(self.pid, modelo, ruta)
        except Exception as e:                        # noqa: BLE001 — al usuario
            return self._error(e)
        self.cambio = True
        self._cargar_modelos(mid)
        if modelo.avisos:
            QMessageBox.warning(self, tr("Modelo BIM"), "\n".join(modelo.avisos[:12]))

    def modelo_parecido(self, modelo):
        gids = {e.global_id for e in modelo.elementos}
        mejor, n = None, 0
        for m in bim.modelos(self.pid):
            c = sum(1 for e in bim.elementos(m['id']) if e.global_id in gids)
            if c > n:
                mejor, n = m['id'], c
        return mejor

    def _comparar(self, mid, modelo, ruta):
        dlg = DiferenciasDialog(mid, modelo, ruta, self)
        if dlg.exec() == QDialog.Accepted:
            self.cambio = True
            self._refrescar(mid)
            r = dlg.resultado
            txt = [tr("{a} fila(s) actualizadas, {b} quitadas, {c} nuevas.").format(
                a=r['actualizadas'], b=r['borradas'], c=r['vinculados'])]
            if r['editadas']:
                txt.append(tr("{n} fila(s) editadas a mano no se tocaron.").format(n=r['editadas']))
            txt += self._motivos(r['omitidos'])
            QMessageBox.information(self, tr("Modelo BIM"), "\n".join(txt))

    def _quitar(self):
        if QMessageBox.question(
                self, tr("Modelo BIM"),
                tr("¿Quitar el modelo y sus vínculos? Los metrados que ya escribió se quedan en la "
                   "planilla.")) == QMessageBox.Yes:
            bim.eliminar_modelo(self.modelo_id)
            self.cambio = True
            self._refrescar()

    def _refrescar(self, mid=None):
        self._cargar_partidas(self.partida_id)
        self._cargar_modelos(mid)

    # ── Partidas y vínculos ──────────────────────────────────────────────────
    def _cargar_partidas(self, sel=None):
        c = get_db()
        try:
            rows = c.execute(
                "SELECT p.id, p.item, p.descripcion, p.unidad, p.metrado, p.sub_presupuesto_id, s.nombre AS sub "
                "FROM partidas_ppto p LEFT JOIN sub_presupuestos s ON s.id=p.sub_presupuesto_id "
                "WHERE p.proyecto_id=? AND COALESCE(p.es_titulo,0)=0 "
                "ORDER BY (p.sub_presupuesto_id IS NOT ?), s.orden, p.item", (self.pid, self.sub_id)).fetchall()
        finally:
            c.close()
        self.tp.blockSignals(True)
        self.tp.clear()
        for r in rows:
            it = QTreeWidgetItem(self.tp, [f"{r['item']}  {r['descripcion']}", r['unidad'] or '',
                                           _num(r['metrado'] or 0)])
            it.setData(0, Qt.UserRole, r['id'])
            it.setToolTip(0, r['sub'] or '')
            if r['id'] == sel:
                self.tp.setCurrentItem(it)
        self.tp.blockSignals(False)
        self._filtrar_partidas()
        if self.tp.currentItem() is not None:
            self.tp.scrollToItem(self.tp.currentItem())

    def _filtrar_partidas(self):
        q = norm_busqueda(self.ed_partida.text()).split()
        for i in range(self.tp.topLevelItemCount()):
            it = self.tp.topLevelItem(i)
            t = norm_busqueda(it.text(0))
            it.setHidden(not all(x in t for x in q))

    def _cargar_vinculos(self):
        self.tv.clear()
        filas = bim.vinculos_partida(self.partida_id) if self.partida_id else []
        for v in filas:
            e = v['elemento']
            med = tr("Metrado del modelo") if v['medida'] == 'metrado' else v['medida']
            it = QTreeWidgetItem([(e.nombre or e.global_id) if e else v['global_id'],
                                  med + (f" × {v['factor']:g}" if v['factor'] != 1 else ''),
                                  _num(v['parcial'] or 0),
                                  tr("ya no está en el modelo") if e is None else
                                  tr("editada a mano") if v['editada'] else ''])
            it.setData(0, Qt.UserRole, (v['modelo_id'], v['global_id']))
            self.tv.addTopLevelItem(it)
        self._estado()
        if self.visor is not None and not self._desde_visor:
            self.visor.resaltar([v['global_id'] for v in filas
                                 if v['modelo_id'] == self.modelo_id])

    def _motivos(self, omitidos):
        cuenta: dict = {}
        for _g, m in omitidos:
            cuenta[m] = cuenta.get(m, 0) + 1
        return [tr("{n} omitido(s): {motivo}.").format(n=n, motivo=m) for m, n in cuenta.items()]

    def _vincular(self):
        gids = [e.global_id for e in self.arbol.marcados()]
        args = (self.partida_id, self.modelo_id, gids, self.cmb_medida.currentData(),
                parse_num(self.ed_factor.text(), moneda_de_proyecto(self.pid)))
        try:
            try:
                r = bim.vincular(*args)
            except bim.MetradoManual as e:
                c = get_db()
                try:
                    acero = c.execute("SELECT 1 FROM acero_detalle WHERE partida_id=? LIMIT 1",
                                      (self.partida_id,)).fetchone()
                finally:
                    c.close()
                if acero:
                    QMessageBox.warning(self, tr("Modelo BIM"), str(e))
                    return
                if QMessageBox.question(self, tr("Modelo BIM"), str(e) + "\n\n" + tr(
                        "¿Reemplazarlo por el del modelo?")) != QMessageBox.Yes:
                    return
                r = bim.vincular(*args, reemplazar_manual=True)
        except Exception as e:                        # noqa: BLE001 — al usuario
            return self._error(e)
        self.cambio = self.cambio or bool(r['vinculados'])
        self._refrescar()
        if r['omitidos']:
            QMessageBox.information(self, tr("Modelo BIM"), "\n".join(
                [tr("{n} vinculado(s).").format(n=r['vinculados'])] + self._motivos(r['omitidos'])))

    def _desvincular(self):
        por: dict = {}
        for it in self.tv.selectedItems():
            m, g = it.data(0, Qt.UserRole)
            por.setdefault(m, []).append(g)
        for m, gs in por.items():
            bim.desvincular(self.partida_id, m, gs)
            self.cambio = True
        if por:
            self._refrescar()

    def _crear(self):
        els = self.arbol.marcados()
        m = next(x for x in bim.modelos(self.pid) if x['id'] == self.modelo_id)
        # Mismo modelo (misma huella): registrar_modelo devuelve el que ya está.
        modelo = bim.ModeloBim(nombre=m['nombre'], origen=m['origen'], elementos=els, huella=m['huella'])
        ya = sum(1 for e in els if e.global_id in self._extra)
        if ya and QMessageBox.question(
                self, tr("Modelo BIM"),
                tr("{n} de estos elementos ya están vinculados a partidas del proyecto: se contarían "
                   "dos veces. ¿Seguir?").format(n=ya)) != QMessageBox.Yes:
            return
        try:
            _mid, ids = bim.anadir_partidas(self.pid, modelo, '', sub_id=self.sub_id)
        except Exception as e:                        # noqa: BLE001 — al usuario
            return self._error(e)
        self.cambio = True
        self._cargar_partidas(ids[0] if ids else None)
        self._cargar_modelos()

    def _mostrar(self):
        """Ilumina en IngeTrazo los vínculos elegidos; si no hay, lo marcado;
        si no, todos los de la partida."""
        items = self.tv.selectedItems()
        gids = [i.data(0, Qt.UserRole)[1] for i in items] or [e.global_id for e in self.arbol.marcados()]
        if not gids and self.partida_id:
            gids = [v['global_id'] for v in bim.vinculos_partida(self.partida_id)]
        if not gids:
            return
        try:
            from views.ingetrazo_traer import mostrar_en_ingetrazo
        except ImportError:
            QMessageBox.information(self, tr("Modelo BIM"),
                                    tr("Esta versión no trae la conexión con IngeTrazo."))
            return
        mostrar_en_ingetrazo(self, gids)

    def _acu(self):
        c = get_db()
        try:
            p = c.execute("SELECT descripcion, unidad, (SELECT COUNT(*) FROM acu_items a WHERE "
                          "a.partida_id=p.id) AS n FROM partidas p WHERE id=?", (self.partida_id,)).fetchone()
        finally:
            c.close()
        if p['n']:
            QMessageBox.information(self, tr("Modelo BIM"), tr("La partida ya tiene su ACU."))
            return
        sug = bim.sugerir_biblioteca(p['descripcion'], p['unidad'], 10)
        if not sug:
            QMessageBox.information(self, tr("Modelo BIM"),
                                    tr("No hay en la biblioteca partidas parecidas con esa unidad."))
            return
        textos = [f"{i + 1}. {s['descripcion']} ({s['unidad']}) — {s['puntaje']:.0f} %"
                  for i, s in enumerate(sug)]
        t, ok = QInputDialog.getItem(self, tr("ACU de la biblioteca…"), tr("Partida parecida:"), textos, 0, False)
        if ok:
            s = sug[textos.index(t)]
            try:
                if bim.poner_acu(self.partida_id, s['origen'], s['ref_id']):
                    self.cambio = True
            except Exception as e:                    # noqa: BLE001 — al usuario
                self._error(e)


def abrir_takeoff(parent, pid, takeoff: dict):
    """Entrada de «Traer de IngeTrazo»: abre «Modelo BIM…» con el takeoff ya
    leído. Desde la vista del proyecto pasa por ella, para que se refresque."""
    if getattr(parent, 'pid', None) == pid and hasattr(parent, '_abrir_modelo_bim'):
        return parent._abrir_modelo_bim(takeoff=takeoff)
    dlg = ModeloBimDialog(pid, parent=parent)
    QTimer.singleShot(0, lambda: dlg.recibir_takeoff(takeoff))
    dlg.exec()
    cambio = dlg.cambio
    dlg.deleteLater()
    return cambio
