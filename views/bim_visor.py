# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Visor 3D de un modelo IFC (solo ver y seleccionar: modelar es IngeTrazo).

    v = BimVisor()
    v.abrir(ruta_ifc, {global_id: 'vinculado' | 'cambio' | 'sin'})
    v.seleccion_cambiada.connect(...)     # lo que el usuario toca
    v.resaltar([global_id, ...])          # desde una partida; no emite

No conoce la base de datos ni el presupuesto. Sin IfcOpenShell o sin una
tarjeta gráfica que sirva muestra el motivo y el resto de la app sigue igual.
"""
from __future__ import annotations

import shutil

from PySide6.QtCore import QByteArray, QProcess, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QVector3D
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from core import bim_geometria as bg
from core.config import BASE_DIR
from utils.i18n import N_, tr
from utils.theme import C, btn_secondary

# Estados que entiende `set_estados`. Lo que no venga en el dict es 'sin'.
ESTADOS = ('sin', 'vinculado', 'cambio')
COLOR_ESTADO = {
    'sin':       (170, 178, 186),     # gris: sin partida
    'vinculado': (104, 183, 35),      # verde: ya está en una partida
    'cambio':    (249, 196, 64),      # amarillo: cambió desde que se metró
}
TEXTO_ESTADO = {
    'sin': N_("Sin partida"),
    'vinculado': N_("Con partida"),
    'cambio': N_("Cambió"),
}
COLOR_SELECCION = (243, 115, 41)
ALFA_RESTO = 34                       # «el resto transparente»

# Mensajes de core/bim_geometria.py (sin Qt ni traducción propia)
_MENSAJES = (
    N_("El archivo no es un IFC válido o está dañado."),
    N_("El archivo no trae geometría 3D."),
    N_("No hay memoria suficiente para este modelo."),
    N_("No se pudo leer la geometría de este archivo."),
    N_("El lector de geometría se cerró al procesar este archivo "
       "(está dañado o es demasiado grande)."),
)


def motivo_no_disponible() -> str:
    """'' si el visor puede usarse; si no, la explicación para el usuario."""
    if not bg.disponible():
        return tr("Esta instalación no incluye IfcOpenShell, el componente que "
                  "lee la geometría de los IFC. Los metrados desde IFC siguen "
                  "funcionando; solo falta la vista 3D.")
    try:
        import PySide6.QtQuick3D     # noqa: F401
        import PySide6.QtQuickWidgets  # noqa: F401
    except Exception:                # ImportError o biblioteca del sistema ausente
        return tr("No se pudo cargar Qt Quick 3D en este equipo, así que el "
                  "modelo no se puede mostrar en 3D.")
    return ''


class BimVisor(QWidget):
    seleccion_cambiada = Signal(list)   # global_ids que eligió el USUARIO
    cargado = Signal()
    fallo = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._geo: bg.Geometria | None = None
        self._ruta = None
        self._tmp = None
        self._proc: QProcess | None = None
        self._estados: dict[str, str] = {}
        self._sel: set[int] = set()         # índices de elemento
        self._ocultos: set[int] = set()
        self._qw = None
        self._root = None
        self._mallas = []
        self._tex = None
        self._sincronizando = False
        self._items: dict[int, QTreeWidgetItem] = {}
        self._armar()

    # ── API ──────────────────────────────────────────────────────────────────

    def abrir(self, ruta, estados: dict | None = None):
        """Carga un IFC. Vuelve enseguida: avisa con `cargado` o `fallo`."""
        self.cerrar()
        self._ruta = str(ruta)
        self._estados = dict(estados or {})
        motivo = motivo_no_disponible()
        if motivo:
            return self._mensaje(motivo, error=True)
        try:
            geo = bg.abrir_cache(self._ruta)
        except OSError:
            return self._mensaje(tr("No se encuentra el archivo del modelo:") +
                                 "\n" + self._ruta, error=True)
        if geo is not None:
            return self._mostrar(geo)
        try:
            self._tmp = bg.preparar(self._ruta)
        except OSError as exc:
            return self._mensaje(str(exc), error=True)
        self._progreso.setRange(0, 0)
        self._paginas.setCurrentWidget(self._pag_carga)
        cmd = bg.comando(self._ruta, self._tmp)
        self._proc = QProcess(self)
        self._proc.setStandardErrorFile(QProcess.nullDevice())
        self._proc.readyReadStandardOutput.connect(self._leer_progreso)
        self._proc.finished.connect(self._termino)
        self._proc.errorOccurred.connect(self._no_arranco)
        self._proc.start(cmd[0], cmd[1:])

    def cerrar(self):
        """Suelta el modelo (y corta la carga si estaba en marcha)."""
        self._matar_proceso()
        self._geo = None
        self._sel.clear()
        self._ocultos.clear()
        self._items.clear()
        self._sincronizando = True
        self._arbol.clear()
        self._sincronizando = False
        if self._root is not None:
            self._root.vaciar()
        for m in self._mallas:
            m.deleteLater()
        self._mallas = []
        self._tex = None
        self._actualizar_botones()
        self._mensaje(tr("Ningún modelo abierto."))

    def set_estados(self, estados: dict):
        """{global_id: 'sin' | 'vinculado' | 'cambio'}"""
        self._estados = dict(estados or {})
        self._pintar()

    def resaltar(self, global_ids, encuadrar: bool = False):
        """Ilumina esos elementos (p. ej. los de una partida). No emite."""
        if self._geo is None:
            return
        por_id = self._geo.por_id
        self._poner_seleccion({por_id[g] for g in global_ids if g in por_id},
                              emitir=False)
        if encuadrar and self._sel:
            self.encuadrar()

    def seleccion(self) -> list[str]:
        if self._geo is None:
            return []
        return [self._geo.elementos[i].global_id for i in sorted(self._sel)]

    def aislar(self, global_ids):
        """Deja a la vista solo esos elementos."""
        if self._geo is None:
            return
        ver = {self._geo.por_id[g] for g in global_ids if g in self._geo.por_id}
        if ver:
            self._ocultos = set(range(len(self._geo.elementos))) - ver
            self._pintar()

    def ocultar(self, global_ids):
        if self._geo is None:
            return
        self._ocultos |= {self._geo.por_id[g] for g in global_ids
                          if g in self._geo.por_id}
        self._pintar()

    def mostrar_todo(self):
        if self._geo is None:
            return
        # los ambientes (IfcSpace) taparían el edificio
        self._ocultos = {i for i, e in enumerate(self._geo.elementos)
                         if e.clase in bg.CLASES_OCULTAS}
        self._pintar()

    def encuadrar(self):
        """Acerca la cámara a lo seleccionado o, si no hay, a lo visible."""
        if self._geo is None or self._root is None:
            return
        n = len(self._geo.elementos)
        cuales = self._sel or (set(range(n)) - self._ocultos) or set(range(n))
        caja = self._geo.caja_de([self._geo.elementos[i].global_id for i in cuales])
        if caja is None:
            return
        a, b = caja
        radio = max(0.25, sum((y - x) ** 2 for x, y in zip(a, b)) ** .5 / 2)
        self._root.encuadrar(QVector3D(*((x + y) / 2 for x, y in zip(a, b))), radio)

    def mascara_visibles(self):
        """Booleano por parte (lo oculto ni se pinta ni se puede tocar)."""
        import numpy as np
        ver = np.ones(len(self._geo.elementos), bool)
        if self._ocultos:
            ver[list(self._ocultos)] = False
        return ver[self._geo.partes[:, 0]]

    def paletas(self):
        """(sólida, transparente) RGBA por parte: lo que se sube a la GPU."""
        import numpy as np
        geo = self._geo
        el = geo.partes[:, 0]
        col = geo.colores.copy()
        if self._combo_color.currentData() == 'estado':
            est = np.array([ESTADOS.index(self._estados.get(e.global_id, 'sin'))
                            if self._estados.get(e.global_id, 'sin') in ESTADOS else 0
                            for e in geo.elementos], np.int64)
            tabla = np.array([COLOR_ESTADO[e] for e in ESTADOS], np.uint8)
            col[:, :3] = tabla[est[el]]
        sel = np.zeros(len(geo.elementos), bool)
        sel[list(self._sel)] = True
        sel = sel[el]
        if self._chk_transp.isChecked() and sel.any():
            col[~sel, 3] = np.minimum(col[~sel, 3], ALFA_RESTO)
        col[sel] = (*COLOR_SELECCION, 255)
        col[~self.mascara_visibles(), 3] = 0
        solida, vidrio = col.copy(), col
        es_solida = col[:, 3] >= 250
        solida[~es_solida, 3] = 0
        solida[es_solida, 3] = 255
        vidrio = col.copy()
        vidrio[es_solida, 3] = 0
        return solida, vidrio

    # ── Interfaz ─────────────────────────────────────────────────────────────

    def _armar(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        barra = QHBoxLayout()
        barra.setSpacing(6)

        def boton(texto, ayuda, fn):
            b = QPushButton(texto)
            b.setToolTip(ayuda)
            b.setStyleSheet(btn_secondary(height=28))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            barra.addWidget(b)
            return b

        self._btn_encuadrar = boton(
            tr("Encuadrar"), tr("Acercar a lo seleccionado, o a todo el modelo"),
            lambda: self.encuadrar())
        self._btn_aislar = boton(
            tr("Aislar"), tr("Dejar a la vista solo lo seleccionado"),
            lambda: self.aislar(self.seleccion()))
        self._btn_ocultar = boton(
            tr("Ocultar"), tr("Ocultar lo seleccionado"), self._ocultar_seleccion)
        self._btn_todo = boton(
            tr("Mostrar todo"), tr("Volver a mostrar lo oculto"),
            lambda: self.mostrar_todo())
        self._chk_transp = QCheckBox(tr("Resto transparente"))
        self._chk_transp.setToolTip(
            tr("Vuelve transparente lo que no está seleccionado"))
        self._chk_transp.toggled.connect(lambda _v: self._pintar())
        barra.addWidget(self._chk_transp)
        barra.addStretch(1)
        self._leyenda = QLabel()
        self._leyenda.setTextFormat(Qt.RichText)
        self._leyenda.setText("&nbsp;&nbsp;".join(
            f'<span style="color:{QColor(*COLOR_ESTADO[e]).name()}">&#9632;</span> '
            f'{tr(TEXTO_ESTADO[e])}' for e in ESTADOS
            if e != 'cambio'))      # nadie lo calcula todavía
        self._leyenda.hide()
        barra.addWidget(self._leyenda)
        self._combo_color = QComboBox()
        self._combo_color.addItem(tr("Color: materiales"), 'material')
        self._combo_color.addItem(tr("Color: por partida"), 'estado')
        self._combo_color.currentIndexChanged.connect(self._cambio_color)
        barra.addWidget(self._combo_color)
        lay.addLayout(barra)

        self._split = QSplitter(Qt.Horizontal)
        lay.addWidget(self._split, 1)

        izq = QWidget()
        li = QVBoxLayout(izq)
        li.setContentsMargins(0, 0, 0, 0)
        self._combo_orden = QComboBox()
        self._combo_orden.addItem(tr("Por piso y clase"), 'piso')
        self._combo_orden.addItem(tr("Por clase y piso"), 'clase')
        self._combo_orden.currentIndexChanged.connect(lambda _i: self._llenar_arbol())
        li.addWidget(self._combo_orden)
        self._buscar = QLineEdit()
        self._buscar.setPlaceholderText(tr("Buscar en el modelo…"))
        self._buscar.setClearButtonEnabled(True)
        self._espera = QTimer(self)
        self._espera.setSingleShot(True)
        self._espera.setInterval(250)
        self._espera.timeout.connect(self._llenar_arbol)
        self._buscar.textChanged.connect(lambda _t: self._espera.start())
        li.addWidget(self._buscar)
        self._arbol = QTreeWidget()
        self._arbol.setHeaderHidden(True)
        self._arbol.setUniformRowHeights(True)
        self._arbol.setSelectionMode(QTreeWidget.ExtendedSelection)
        self._arbol.itemSelectionChanged.connect(self._arbol_cambio)
        self._arbol.itemDoubleClicked.connect(lambda *_a: self.encuadrar())
        li.addWidget(self._arbol, 1)
        self._split.addWidget(izq)

        self._paginas = QStackedWidget()
        self._pag_msj = QLabel()
        self._pag_msj.setWordWrap(True)
        self._pag_msj.setAlignment(Qt.AlignCenter)
        self._pag_msj.setMargin(30)
        self._pag_msj.setStyleSheet(f"color:{C.text_muted}; background:{C.bg};")
        self._paginas.addWidget(self._pag_msj)
        self._pag_carga = QWidget()
        lc = QVBoxLayout(self._pag_carga)
        lc.addStretch(1)
        lbl = QLabel(tr("Preparando el modelo 3D…"))
        lbl.setAlignment(Qt.AlignCenter)
        lc.addWidget(lbl)
        self._progreso = QProgressBar()
        self._progreso.setMaximumWidth(360)
        lc.addWidget(self._progreso, 0, Qt.AlignHCenter)
        cancelar = QPushButton(tr("Cancelar"))
        cancelar.setStyleSheet(btn_secondary(height=28))
        cancelar.clicked.connect(self.cerrar)
        lc.addWidget(cancelar, 0, Qt.AlignHCenter)
        lc.addStretch(1)
        self._paginas.addWidget(self._pag_carga)
        self._split.addWidget(self._paginas)
        self._split.setStretchFactor(1, 1)
        self._split.setSizes([260, 800])

        self._pie = QLabel()
        self._pie.setStyleSheet(f"color:{C.text_muted};")
        lay.addWidget(self._pie)
        self._actualizar_botones()
        self._mensaje(tr("Ningún modelo abierto."))

    def _mensaje(self, texto: str, error: bool = False):
        self._pag_msj.setText(texto)
        self._paginas.setCurrentWidget(self._pag_msj)
        self._pie.clear()
        if error:
            self.fallo.emit(texto)

    def _actualizar_botones(self):
        hay = self._geo is not None
        for b in (self._btn_encuadrar, self._btn_todo, self._chk_transp,
                  self._combo_color, self._combo_orden, self._buscar):
            b.setEnabled(hay)
        for b in (self._btn_aislar, self._btn_ocultar):
            b.setEnabled(hay and bool(self._sel))

    def _cambio_color(self, _i):
        self._leyenda.setVisible(self._combo_color.currentData() == 'estado')
        self._pintar()

    def _ocultar_seleccion(self):
        ids = self.seleccion()
        self._poner_seleccion(set(), emitir=True)
        self.ocultar(ids)

    # ── Carga ────────────────────────────────────────────────────────────────

    def _leer_progreso(self):
        if self._proc is None:
            return
        while self._proc.canReadLine():
            pct = bg.leer_progreso(bytes(self._proc.readLine()).decode('utf-8', 'replace'))
            if pct is not None:
                self._progreso.setRange(0, 100)
                self._progreso.setValue(pct)

    def _matar_proceso(self):
        p, self._proc = self._proc, None
        if p is not None:
            p.blockSignals(True)
            if p.state() != QProcess.NotRunning:
                p.kill()
                p.waitForFinished(3000)
            p.deleteLater()
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None

    def _no_arranco(self, err):
        if err == QProcess.FailedToStart and self._proc is not None:
            self._matar_proceso()
            self._mensaje(tr("No se pudo leer la geometría de este archivo."), error=True)

    def _termino(self, codigo, estado):
        if self._proc is None:
            return
        if estado == QProcess.CrashExit:
            codigo = -1
        if codigo != 0 or not (self._tmp / 'meta.json').exists():
            texto = bg.mensaje_de_salida(codigo, self._tmp)
            self._matar_proceso()
            return self._mensaje(tr(texto), error=True)
        try:
            geo = bg.finalizar(self._ruta, self._tmp)
        except Exception as exc:
            self._matar_proceso()
            return self._mensaje(str(exc), error=True)
        self._tmp = None
        self._matar_proceso()
        self._mostrar(geo)

    def _escena(self) -> str:
        """Crea la ventana 3D la primera vez. Devuelve '' o el problema."""
        if self._qw is not None:
            return ''
        try:
            import sys
            if sys.platform == 'win32':
                # igual que el mapa: bajo MSIX los plugins QML no encuentran
                # sus DLL si la carpeta de PySide6 no está registrada
                import os
                import PySide6
                try:
                    os.add_dll_directory(os.path.dirname(PySide6.__file__))
                except OSError:
                    pass
            from PySide6 import QtQuick3D  # noqa: F401  carga las bibliotecas
            from PySide6.QtQuickWidgets import QQuickWidget
            qw = QQuickWidget()
            qw.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
            qw.setMinimumSize(200, 200)
            qw.sceneGraphError.connect(lambda _e, _m: self._sin_gpu())
            qw.setSource(QUrl.fromLocalFile(str(BASE_DIR / 'resources' / 'bim_visor.qml')))
            if qw.status() != QQuickWidget.Status.Ready:
                detalle = "; ".join(e.toString() for e in qw.errors())
                qw.deleteLater()
                return detalle or 'QML'
        except Exception as exc:
            return str(exc)
        self._qw = qw
        self._root = qw.rootObject()
        self._root.tocado.connect(self._tocado)
        self._root.doble.connect(self.encuadrar)
        self._paginas.addWidget(qw)
        return ''

    def _sin_gpu(self):
        self._mensaje(tr("Este equipo no tiene aceleración gráfica disponible, "
                         "así que el modelo no se puede mostrar en 3D."), error=True)

    def _revisar_gpu(self):
        """Con el dibujado por software de Qt no hay 3D: mejor decirlo."""
        if self._qw is None or self._geo is None:
            return
        from PySide6.QtQuick import QSGRendererInterface as R
        ri = self._qw.quickWindow().rendererInterface()
        if ri is not None and ri.graphicsApi() == R.GraphicsApi.Software:
            self._sin_gpu()

    def _mostrar(self, geo: bg.Geometria):
        problema = self._escena()
        self._geo = geo
        self._sel.clear()
        self._ocultos = {i for i, e in enumerate(geo.elementos)
                         if e.clase in bg.CLASES_OCULTAS}
        if problema:
            self._geo = None
            return self._mensaje(tr("No se pudo iniciar la vista 3D:") + "\n" + problema,
                                 error=True)
        self._subir_mallas()
        a, b = geo.caja
        self._root.setProperty('radio', max(
            0.5, sum((y - x) ** 2 for x, y in zip(a, b)) ** .5 / 2))
        self._llenar_arbol()
        self._pintar()
        self._root.vista(-35.0, 28.0)
        self._paginas.setCurrentWidget(self._qw)
        self.encuadrar()
        self._actualizar_botones()
        self._pie.setText(" · ".join(
            [tr("{n} elementos").format(n=len(geo.elementos))] + geo.avisos))
        QTimer.singleShot(0, self._revisar_gpu)
        QTimer.singleShot(0, self.encuadrar)      # ya con el tamaño real
        self.cargado.emit()

    def _subir_mallas(self):
        from PySide6.QtQuick3D import QQuick3DGeometry, QQuick3DTextureData
        from PySide6.QtQml import QQmlEngine

        def mia(obj):
            # si no, el recolector de QML se la puede llevar
            QQmlEngine.setObjectOwnership(obj, QQmlEngine.ObjectOwnership.CppOwnership)
            self._mallas.append(obj)
            return obj

        A = QQuick3DGeometry.Attribute
        for vert, idx in self._geo.bloques():
            g = mia(QQuick3DGeometry())
            g.setVertexData(QByteArray(vert.tobytes()))
            g.setIndexData(QByteArray(idx.tobytes()))
            g.setStride(32)
            g.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
            f32 = A.ComponentType.F32Type
            g.addAttribute(A.Semantic.PositionSemantic, 0, f32)
            g.addAttribute(A.Semantic.NormalSemantic, 12, f32)
            g.addAttribute(A.Semantic.TexCoord0Semantic, 24, f32)
            g.addAttribute(A.Semantic.IndexSemantic, 0, A.ComponentType.U32Type)
            g.setBounds(QVector3D(*vert[:, :3].min(0).tolist()),
                        QVector3D(*vert[:, :3].max(0).tolist()))
            self._root.agregarBloque(g)
        filas = max(1, -(-self._geo.n_partes // bg.ANCHO_PALETA))
        self._tex = []
        for _ in range(2):
            t = mia(QQuick3DTextureData())
            t.setSize(QSize(bg.ANCHO_PALETA, filas))
            t.setFormat(QQuick3DTextureData.Format.RGBA8)
            self._tex.append(t)

    def _pintar(self):
        """Rehace la paleta: color, transparencia y visibilidad de cada parte."""
        if self._geo is None or self._root is None or not self._tex:
            return
        import numpy as np
        filas = max(1, -(-self._geo.n_partes // bg.ANCHO_PALETA))
        for t, pal in zip(self._tex, self.paletas()):
            buf = np.zeros((filas * bg.ANCHO_PALETA, 4), np.uint8)
            buf[:len(pal)] = pal
            t.setTextureData(QByteArray(buf.tobytes()))
            t.update()
            hay = bool(pal[:, 3].any())       # el último: transparentes
        self._root.setProperty('hayTransparentes', hay)
        self._root.ponerPaletas(*self._tex)

    # ── Selección ────────────────────────────────────────────────────────────

    def _tocado(self, origen, direccion, sumar):
        if self._geo is None:
            return
        i = self._geo.elemento_bajo_rayo(
            (origen.x(), origen.y(), origen.z()),
            (direccion.x(), direccion.y(), direccion.z()), self.mascara_visibles())
        if i is None:
            nueva = set(self._sel) if sumar else set()
        elif sumar:
            nueva = self._sel ^ {i}
        else:
            nueva = {i}
        self._poner_seleccion(nueva, emitir=True)

    def _poner_seleccion(self, nueva: set, emitir: bool, desde_arbol=False):
        cambio = nueva != self._sel
        self._sel = set(nueva)
        if not desde_arbol:
            self._marcar_arbol()
        self._pintar()
        self._actualizar_botones()
        if cambio and emitir:
            self.seleccion_cambiada.emit(self.seleccion())

    def _marcar_arbol(self):
        self._sincronizando = True
        self._arbol.setUpdatesEnabled(False)
        try:
            self._arbol.clearSelection()
            primero = None
            for i in sorted(self._sel):
                it = self._items.get(i)
                if it is not None:
                    it.setSelected(True)
                    primero = primero or it
            if primero is not None:
                self._arbol.scrollToItem(primero)
        finally:
            self._arbol.setUpdatesEnabled(True)
            self._sincronizando = False

    def _arbol_cambio(self):
        if self._sincronizando or self._geo is None:
            return
        nueva = set()
        pila = list(self._arbol.selectedItems())
        while pila:
            it = pila.pop()
            i = it.data(0, Qt.UserRole)
            if i is not None:
                nueva.add(i)
            pila += [it.child(k) for k in range(it.childCount())]
        self._poner_seleccion(nueva, emitir=True, desde_arbol=True)

    def _llenar_arbol(self):
        if self._geo is None:
            return
        geo = self._geo
        texto = self._buscar.text().strip().lower()
        por_piso = self._combo_orden.currentData() == 'piso'
        orden = {p: k for k, p in enumerate(geo.pisos)}
        sin_piso = tr("Sin piso")
        grupos: dict = {}
        for i, e in enumerate(geo.elementos):
            if texto and texto not in f'{e.nombre} {e.clase} {e.piso} {e.global_id}'.lower():
                continue
            piso, clase = e.piso or sin_piso, e.clase
            a, b = (piso, clase) if por_piso else (clase, piso)
            grupos.setdefault(a, {}).setdefault(b, []).append(i)

        def clave(t):
            return (orden.get(t, len(orden)), t)

        self._sincronizando = True
        self._arbol.setUpdatesEnabled(False)
        try:
            self._arbol.clear()
            self._items.clear()
            raices = []
            for a in sorted(grupos, key=clave):
                total = sum(len(v) for v in grupos[a].values())
                na = QTreeWidgetItem([f'{a}  ({total})'])
                for b in sorted(grupos[a], key=clave):
                    nb = QTreeWidgetItem([f'{b}  ({len(grupos[a][b])})'])
                    for i in grupos[a][b]:
                        e = geo.elementos[i]
                        it = QTreeWidgetItem([e.nombre or e.global_id])
                        it.setToolTip(0, f'{e.clase} · {e.global_id}')
                        it.setData(0, Qt.UserRole, i)
                        nb.addChild(it)
                        self._items[i] = it
                    na.addChild(nb)
                raices.append(na)
            self._arbol.addTopLevelItems(raices)
            for na in raices:
                na.setExpanded(bool(texto) or len(raices) <= 12)
        finally:
            self._arbol.setUpdatesEnabled(True)
            self._sincronizando = False
        self._marcar_arbol()

    def closeEvent(self, ev):
        self._matar_proceso()
        super().closeEvent(ev)
