# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Gestor de complementos: Complementos ▸ Administrar complementos…

Todo lo que sale de un paquete es ajeno: los textos van en PlainText y la imagen
se comprueba en los bytes antes de decodificarla.
"""
from __future__ import annotations

import unicodedata

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import (
    QColor, QDesktopServices, QImage, QImageReader, QKeySequence, QPainter,
    QPainterPath, QShortcut,
)
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTabWidget,
    QVBoxLayout, QWidget,
)

from core.complementos import cargador, esquema, gestor
from core.complementos.paquete import ErrorPaquete
from utils.i18n import N_, tr
from utils.theme import (
    BLUE_700, BTN_PRIMARY_SS, GREEN_700, ORANGE_700, PURPLE_500, RED_700,
    SILVER_100, SILVER_300, SLATE_400, SLATE_500, SLATE_700, WHITE, btn_primary, btn_secondary,
    input_default, tinte,
)
from widgets.flow_layout import FlowLayout

_ESTADOS = {
    'disponible': N_("No instalado"),
    'activo': N_("Activo"), 'apagado': N_("Apagado"),
    'cambiado': N_("Cambió: hay que volver a activarlo"),
    'error': N_("Apagado por un error"), 'dañado': N_("Dañado"),
}
_SECCIONES = {
    'paises': N_("Países"), 'monedas': N_("Monedas"),
    'vocabulario': N_("Vocabulario"),
    'importadores_excel': N_("Formatos de Excel"), 'indices': N_("Índices"),
    'titulos': N_("Títulos"), 'unidades': N_("Unidades"),
    'temas': N_("Temas de reportes"),
}
_CATEGORIAS = {
    'reportes': N_("Reportes"), 'paises': N_("Países"), 'precios': N_("Precios"),
    'metrados': N_("Metrados"), 'importar': N_("Importar"),
    'revision': N_("Revisión"), 'temas': N_("Temas"), 'otros': N_("Otros"),
}
assert tuple(_CATEGORIAS) == esquema.CATEGORIAS


def _aviso(padre, texto, icono=QMessageBox.Warning):
    box = QMessageBox(icono, tr("Complementos"), '', QMessageBox.Ok, padre)
    box.setTextFormat(Qt.PlainText)      # el texto puede venir del paquete
    box.setText(texto[:4000])
    box.setWindowModality(Qt.WindowModal)
    box.exec()


def avisar_fallos_de_arranque(ventana) -> None:
    """Una vez: qué complementos se apagaron al arrancar y por qué."""
    if not cargador.fallos:
        return
    fallos, cargador.fallos[:] = list(cargador.fallos), []
    _aviso(ventana, tr("Se apagaron estos complementos porque fallaron al "
                       "cargar. El resto del programa funciona normalmente.")
           + "\n\n" + "\n".join(f"• {i or '—'}: {t}" for i, t in fallos))


def ficha(i: gestor.Info) -> str:
    """Todo lo que hay que saber antes de activar, en texto plano."""
    if i.paquete is None:
        return f"{i.id}\n\n{i.error}"
    m = i.paquete.manifiesto
    L = [f"{i.nombre}  {m['version']}",
         f"{tr('Estado')}: {tr(_ESTADOS[i.estado])}"]
    if i.error:
        L.append(i.error)
    L += ["", i.descripcion, "",
          f"{tr('Autor')}: {m['autor']}", f"{tr('Licencia')}: {m['licencia']}"]
    if m['web']:
        L.append(f"Web: {m['web']}")
    if m['categorias']:
        L.append(f"{tr('Categoría')}: "
                 + ", ".join(tr(_CATEGORIAS[c]) for c in m['categorias']))
    L.append(f"{tr('Identificador')}: {m['id']}")
    L.append(f"{tr('Tipo')}: " + (
        tr("con código Python (API {n})").format(n=m['api_version'])
        if m['codigo'] else tr("solo datos, no ejecuta nada")))
    for k in esquema.tiene_datos(m):
        detalle = [str(x.get('nombre') or x.get('idioma')) if isinstance(x, dict)
                   else x for x in m[k]][:6]
        L.append(f"  {tr(_SECCIONES[k])}: {len(m[k])} ({', '.join(detalle)}"
                 + ("…)" if len(m[k]) > 6 else ")"))
    cs = gestor.conflictos(i.paquete)
    if cs:
        L += ["", tr("Cambia datos que ya existen:")] + [f"  ! {c}" for c in cs]
    L += ["", f"{tr('Archivos')}: {len(i.paquete.archivos)}"]
    L += [f"  {r}  ({len(b):,} B)" for r, b in sorted(i.paquete.archivos.items())]
    L += ["", f"SHA-256: {i.paquete.huella}"]
    if i.origen:
        L.append(f"{tr('Carpeta de origen')}: {i.origen}")
    return "\n".join(L)


class _Visor(QWidget):
    """El resumen y, uno a uno, los archivos del paquete."""

    def __init__(self, info: gestor.Info):
        super().__init__()
        self.info = info
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        self.lst = QListWidget()
        self.lst.setMaximumWidth(220)
        self.lst.addItem(tr("Resumen"))
        for r in sorted(info.paquete.archivos if info.paquete else ()):
            it = QListWidgetItem(r)
            it.setData(Qt.UserRole, r)
            self.lst.addItem(it)
        hl.addWidget(self.lst)
        self.ver = QPlainTextEdit()
        self.ver.setReadOnly(True)
        hl.addWidget(self.ver, 1)
        self.lst.currentItemChanged.connect(self._mostrar)
        self.lst.setCurrentRow(0)

    def _mostrar(self, item, _antes=None):
        ruta = item.data(Qt.UserRole) if item is not None else None
        if not ruta:
            self.ver.setPlainText(ficha(self.info))
            return
        try:
            self.ver.setPlainText(
                self.info.paquete.archivos[ruta].decode('utf-8')[:300_000])
        except UnicodeDecodeError:
            self.ver.setPlainText(tr("(archivo binario)"))


class DetallesDialog(QDialog):
    def __init__(self, info: gestor.Info, parent=None):
        super().__init__(parent)
        self.setWindowTitle(info.nombre)
        self.setWindowModality(Qt.WindowModal)
        self.resize(720, 520)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(20, 18, 20, 16)
        self.visor = _Visor(info)
        vl.addWidget(self.visor, 1)
        hl = QHBoxLayout()
        hl.addStretch()
        b = QPushButton(tr("Cerrar"))
        b.setStyleSheet(btn_secondary())
        b.clicked.connect(self.accept)
        hl.addWidget(b)
        vl.addLayout(hl)


class ConsentimientoDialog(QDialog):
    """Antes de activar: quién lo hizo, qué trae y qué puede hacer."""

    def __init__(self, info: gestor.Info, parent=None):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle(tr("Activar «{nombre}»").format(nombre=info.nombre))
        self.setWindowModality(Qt.WindowModal)
        self.resize(720, 560)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(20, 18, 20, 16)
        vl.setSpacing(10)
        con_codigo = info.paquete.con_codigo
        txt = QLabel(
            tr("Este complemento contiene código. Al activarlo puede hacer lo "
               "mismo que el programa: leer y cambiar todos tus proyectos, tus "
               "archivos y conectarse a internet. Actívalo solo si confías en "
               "su autor. IngePresupuestos no lo ha revisado.")
            if con_codigo else
            tr("Este complemento solo trae datos: no ejecuta nada."))
        txt.setTextFormat(Qt.PlainText)
        txt.setWordWrap(True)
        txt.setStyleSheet("font-weight:600;" + ("color:#A10705;" if con_codigo else ""))
        vl.addWidget(txt)
        self.visor = _Visor(info)
        self.lst, self.ver = self.visor.lst, self.visor.ver
        vl.addWidget(self.visor, 1)
        conf = gestor.conflictos(info.paquete)
        self.chks = []
        if conf:
            lbl = QLabel(tr("Cambia datos que ya existen:") + "\n"
                         + "\n".join(f"• {c}" for c in conf))
            lbl.setTextFormat(Qt.PlainText)
            lbl.setWordWrap(True)
            vl.addWidget(lbl)
            self.chks.append(QCheckBox(tr("Acepto que cambie esos datos")))
        if con_codigo:
            self.chks.append(QCheckBox(tr(
                "Confío en «{autor}» y entiendo que puede hacer lo mismo que "
                "el programa").format(
                    autor=info.paquete.manifiesto['autor'].replace('&', '&&'))))
        for c in self.chks:
            vl.addWidget(c)
            c.toggled.connect(self._listo)
        hl = QHBoxLayout()
        hl.addStretch()
        b = QPushButton(tr("Cancelar"))
        b.setStyleSheet(btn_secondary())
        b.clicked.connect(self.reject)
        b.setDefault(True)
        hl.addWidget(b)
        self.btn = QPushButton(tr("Activar"))
        self.btn.setStyleSheet(BTN_PRIMARY_SS)
        self.btn.setAutoDefault(False)
        self.btn.clicked.connect(self.accept)
        hl.addWidget(self.btn)
        vl.addLayout(hl)
        self._listo()

    def _listo(self, *_):
        self.btn.setEnabled(all(c.isChecked() for c in self.chks))


# ── Tarjetas ─────────────────────────────────────────────────────────────────

ANCHO_COLUMNA = 350
ALTO_IMAGEN = 140
_COLORES = (BLUE_700, GREEN_700, ORANGE_700, PURPLE_500, "#00695C", "#AD1457")
#: Imágenes ya reducidas, por contenido: el gestor se abre muchas veces.
_IMAGENES: dict[tuple, QImage] = {}
_MAX_IMAGENES = 150

# Una sola hoja para toda la rejilla: ponerla tarjeta a tarjeta es lo lento.
_HOJA = f"""
QWidget#rejilla {{ background:{SILVER_100}; }}
QFrame#tarjeta {{ background:{WHITE}; border:1px solid {SILVER_300};
    border-radius:8px; }}
QFrame#tarjeta QLabel {{ background:transparent; border:none; color:{SLATE_700}; }}
QFrame#tarjeta QLabel#nombre {{ font-size:15px; font-weight:700; }}
QFrame#tarjeta QLabel#pie {{ color:{SLATE_400}; font-size:11px; }}
QFrame#tarjeta QLabel#error {{ color:{RED_700}; font-size:11px; }}
QFrame#tarjeta QLabel#insignia {{ color:{SLATE_500}; background:{SILVER_100};
    border:1px solid {SILVER_300}; border-radius:4px; padding:1px 5px;
    font-size:10px; font-weight:700; }}
QFrame#tarjeta QLabel#insignia[clase="incluido"] {{ color:{GREEN_700};
    border-color:{GREEN_700}; }}
QFrame#tarjeta QLabel#insignia[clase="codigo"] {{ color:{ORANGE_700};
    border-color:{ORANGE_700}; }}
QFrame#tarjeta QLabel#estado[clase="activo"] {{ color:{GREEN_700}; font-weight:700; }}
QFrame#tarjeta QLabel#estado[clase="mal"] {{ color:{RED_700}; font-weight:700; }}
"""
_PILDORA = (
    f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
    f" border:1px solid {SILVER_300}; border-radius:12px; padding:3px 12px; }}"
    f"QPushButton:hover, QPushButton:focus {{ border-color:{ORANGE_700}; }}"
    f"QPushButton:checked {{ background:{ORANGE_700}; color:{WHITE};"
    f" border-color:{ORANGE_700}; font-weight:700; }}")


def sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize('NFKD', t.casefold())
                   if not unicodedata.combining(c))


def imagen_de(paquete) -> QImage | None:
    """La imagen del paquete, reducida; None si no trae o no vale."""
    if paquete is None or not paquete.manifiesto['imagen']:
        return None
    clave = (paquete.huella, paquete.manifiesto['imagen'])
    if clave not in _IMAGENES:
        while len(_IMAGENES) >= _MAX_IMAGENES:
            _IMAGENES.pop(next(iter(_IMAGENES)))
        _IMAGENES[clave] = _decodificar(
            paquete.archivos.get(paquete.manifiesto['imagen'], b''))
    img = _IMAGENES[clave]
    return None if img.isNull() else img


def _decodificar(b: bytes) -> QImage:
    tipo = esquema.imagen_tarjeta(b)         # tamaño y lados, antes de abrirla
    if tipo is None:
        return QImage()
    datos = QByteArray(b)
    buf = QBuffer(datos)
    buf.open(QIODevice.ReadOnly)
    r = QImageReader(buf, QByteArray(tipo.encode()))
    r.setAutoDetectImageFormat(False)        # solo ese decodificador
    t = r.size()
    if not t.isValid() or max(t.width(), t.height()) > esquema.MAX_LADO_TARJETA:
        return QImage()
    if t.width() > 760:
        r.setScaledSize(QSize(760, max(1, round(t.height() * 760 / t.width()))))
    return r.read()


class _Imagen(QWidget):
    """La imagen o, si no hay, iniciales sobre un color. Se decodifica al
    pintarse: solo las tarjetas que se ven."""

    def __init__(self, info: gestor.Info):
        super().__init__()
        self.info = info
        self.setFixedHeight(ALTO_IMAGEN)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        borde = QPainterPath()
        borde.addRoundedRect(r.adjusted(0, 0, 0, 10), 7, 7)
        p.setClipPath(borde)
        img = imagen_de(self.info.paquete)
        if img is not None:
            # Llena el ancho y enseña la parte de arriba.
            p.fillRect(r, QColor(WHITE))
            alto = img.width() * r.height() / r.width()
            if alto <= img.height():
                p.drawImage(r, img, QRectF(0, 0, img.width(), alto))
            else:
                ancho = img.height() * r.width() / r.height()
                p.drawImage(r, img, QRectF((img.width() - ancho) / 2, 0,
                                           ancho, img.height()))
            p.fillRect(QRectF(0, r.height() - 1, r.width(), 1), QColor(SILVER_300))
            return
        color = _COLORES[sum(self.info.id.encode()) % len(_COLORES)]
        p.fillRect(r, QColor(tinte(color, 0.16)))
        f = p.font()
        f.setPixelSize(44)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(r, Qt.AlignCenter, iniciales(self.info.nombre))


def iniciales(t: str) -> str:
    pals = [x for x in t.split() if x[0].isalnum()] or [t or '?']
    return (pals[0][0] + pals[1][0] if len(pals) > 1 else pals[0][:2]).upper()


def corto(t: str, n: int = 150) -> str:
    t = " ".join(t.split())
    if len(t) <= n:
        return t
    return t[:n].rsplit(' ', 1)[0].rstrip(' ,.;:') + "…"


def _etiqueta(texto, nombre, clase='', envuelve=False) -> QLabel:
    w = QLabel(texto)
    w.setTextFormat(Qt.PlainText)
    w.setObjectName(nombre)
    if clase:
        w.setProperty('clase', clase)
    w.setWordWrap(envuelve)
    return w


class Tarjeta(QFrame):
    """`info` es lo que se enseña; `puesto`, lo instalado con ese id (o None);
    `nueva`, la versión incluida si es posterior a la instalada."""

    def __init__(self, dlg, info: gestor.Info, puesto, incluido: bool, nueva: str):
        super().__init__()
        self.setObjectName('tarjeta')
        self.id, self.botones = info.id, {}
        m = info.paquete.manifiesto if info.paquete else None
        estado = puesto.estado if puesto else info.estado
        vl = QVBoxLayout(self)
        vl.setContentsMargins(1, 1, 1, 10)
        vl.setSpacing(6)
        vl.addWidget(_Imagen(info))
        c = QVBoxLayout()
        c.setContentsMargins(12, 2, 12, 0)
        c.setSpacing(5)
        vl.addLayout(c, 1)
        c.addWidget(_etiqueta(info.nombre, 'nombre', envuelve=True))
        if m:
            version = (puesto.paquete.manifiesto['version']
                       if puesto and puesto.paquete else m['version'])
            if nueva:
                version += f" → {nueva}"
            c.addWidget(_etiqueta(f"{version} · {m['autor']} · {m['licencia']}",
                                  'pie', envuelve=True))
            c.addWidget(_etiqueta(corto(info.descripcion), 'descripcion',
                                  envuelve=True))
        fila = QWidget()
        ins = FlowLayout(fila)
        if incluido:
            ins.addWidget(_etiqueta(tr("INCLUIDO"), 'insignia', 'incluido'))
        if m:
            ins.addWidget(_etiqueta(tr("CÓDIGO"), 'insignia', 'codigo') if m['codigo']
                          else _etiqueta(tr("SOLO DATOS"), 'insignia'))
            for k in m['categorias']:
                ins.addWidget(_etiqueta(tr(_CATEGORIAS[k]), 'insignia'))
        c.addWidget(fila)
        self.lbl_estado = _etiqueta(
            ("● " if estado == 'activo' else "○ ") + tr(_ESTADOS[estado]), 'estado',
            'activo' if estado == 'activo' else
            'mal' if estado in ('error', 'dañado', 'cambiado') else '')
        c.addWidget(self.lbl_estado)
        error = (puesto.error if puesto else info.error) or ''
        if error:
            c.addWidget(_etiqueta(corto(error, 180), 'error', envuelve=True))
        c.addStretch(1)
        fila = QWidget()
        self._fila = FlowLayout(fila)
        c.addWidget(fila)
        i = puesto or info
        if puesto is None:
            if info.paquete is not None:
                self._boton(dlg, 'instalar', tr("Instalar"),
                            lambda: dlg.instalar_incluido(info.id), True)
        else:
            if nueva:
                self._boton(dlg, 'actualizar', tr("Actualizar"),
                            lambda: dlg.actualizar(info.id), True)
            if puesto.activo:
                self._boton(dlg, 'desactivar', tr("Desactivar"),
                            lambda: dlg.desactivar(info.id))
            elif puesto.paquete is not None:
                self._boton(dlg, 'activar', tr("Activar…"),
                            lambda: dlg.activar(info.id), not nueva)
        self._boton(dlg, 'detalles', tr("Detalles"), lambda: dlg.detalles(i),
                    libre=True)
        if puesto is not None:
            self._boton(dlg, 'mas', "⋯", None, libre=True)
            b = self.botones['mas']
            b.setToolTip(tr("Más acciones"))
            b.setMenu(dlg.menu_de(puesto, b))
        for b in self.botones.values():
            b.setAccessibleName(f"{b.text()}: {info.nombre}")

    def _boton(self, dlg, clave, texto, fn, primario=False, libre=False):
        b = QPushButton(texto)
        b.setStyleSheet(dlg.estilos[bool(primario)])
        b.setAutoDefault(False)
        b.setProperty('clave', clave)
        if not libre and not dlg.puede:
            b.setEnabled(False)
            b.setToolTip(tr("Solo un administrador puede gestionar complementos."))
        if fn is not None:
            b.clicked.connect(lambda _=False: fn())
        self.botones[clave] = b
        self._fila.addWidget(b)


class _Pagina(QWidget):
    """Buscador, categorías, orden y la rejilla de una pestaña."""

    def __init__(self, dlg, vacio: str):
        super().__init__()
        self._dlg, self._vacio = dlg, vacio
        self._datos: list[dict] = []
        self.tarjetas: dict[str, Tarjeta] = {}
        self.visibles: list[str] = []
        self._columnas = 0
        vl = QVBoxLayout(self)
        vl.setContentsMargins(8, 10, 8, 4)
        vl.setSpacing(8)
        fila = QHBoxLayout()
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText(tr("Buscar complementos…"))
        self.buscar.setClearButtonEnabled(True)
        self.buscar.setStyleSheet(input_default())
        self.buscar.textChanged.connect(lambda *_: self.filtrar())
        fila.addWidget(self.buscar, 1)
        self.orden = QComboBox()
        self.orden.addItem(tr("Por nombre"), 'nombre')
        self.orden.addItem(tr("Instalados primero"), 'instalados')
        self.orden.setAccessibleName(tr("Orden"))
        self.orden.currentIndexChanged.connect(lambda *_: self.filtrar())
        fila.addWidget(self.orden)
        self.contador = QLabel('')
        self.contador.setStyleSheet(f"color:{SLATE_500};")
        fila.addWidget(self.contador)
        vl.addLayout(fila)
        cats = QWidget()
        flujo = FlowLayout(cats)
        self.grupo = QButtonGroup(self)
        self.categorias = {}
        for k, t in (('', tr("Todos")), *((k, tr(t)) for k, t in _CATEGORIAS.items())):
            b = QPushButton(t)
            b.setCheckable(True)
            b.setAutoDefault(False)
            b.setStyleSheet(_PILDORA)
            b.clicked.connect(lambda *_: self.filtrar())
            self.grupo.addButton(b)
            self.categorias[k] = b
            flujo.addWidget(b)
        self.categorias[''].setChecked(True)
        vl.addWidget(cats)
        self.sc = QScrollArea()
        self.sc.setWidgetResizable(True)
        self.sc.setFrameShape(QFrame.NoFrame)
        self.sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sc.setFocusPolicy(Qt.NoFocus)
        rej = QWidget()
        rej.setObjectName('rejilla')
        rej.setStyleSheet(_HOJA)
        self.grid = QGridLayout(rej)
        self.grid.setContentsMargins(4, 4, 4, 8)
        self.grid.setSpacing(12)
        self.sin_nada = QLabel('')
        self.sin_nada.setAlignment(Qt.AlignCenter)
        self.sin_nada.setWordWrap(True)
        self.sin_nada.setStyleSheet(f"color:{SLATE_500}; padding:40px;")
        self.sc.setWidget(rej)
        self.sc.viewport().installEventFilter(self)
        vl.addWidget(self.sc, 1)
        vl.addWidget(self.sin_nada, 1)

    def eventFilter(self, o, e):
        if e.type() == QEvent.Resize and self._n_columnas() != self._columnas:
            self._colocar()
        return False

    def _n_columnas(self):
        return max(1, self.sc.viewport().width() // ANCHO_COLUMNA)

    def poner(self, datos: list[dict]):
        """[{info, puesto, incluido, nueva}]. Las tarjetas se hacen de nuevo."""
        foco = self._foco()
        arriba = self.sc.verticalScrollBar().value()
        for t in self.tarjetas.values():
            self.grid.removeWidget(t)
            t.hide()
            t.deleteLater()
        self.tarjetas = {}
        self._datos = datos
        self.filtrar()
        self.grid.activate()
        self.sc.verticalScrollBar().setValue(arriba)
        if foco and foco[0] in self.tarjetas:
            bs = self.tarjetas[foco[0]].botones
            b = bs.get(foco[1])
            if b is None or not b.isEnabled():
                b = next((x for x in bs.values() if x.isEnabled()), None)
            if b is not None:
                b.setFocus()

    def _foco(self):
        w = self._dlg.focusWidget()
        for id_, t in self.tarjetas.items():
            if w is not None and t.isAncestorOf(w):
                return id_, w.property('clave')
        return None

    @staticmethod
    def _texto(i: gestor.Info) -> str:
        m = i.paquete.manifiesto if i.paquete else None
        if m is None:
            return sin_tildes(i.id)
        return sin_tildes(" ".join([
            i.id, m['nombre'], m['descripcion'], m['autor'],
            *(x for t in m['traducciones'].values() for x in t.values())]))

    def filtrar(self):
        pals = sin_tildes(self.buscar.text()).split()
        cat = next(k for k, b in self.categorias.items() if b.isChecked())

        def pasa(d):
            m = d['info'].paquete.manifiesto if d['info'].paquete else None
            cats = (m['categorias'] if m else []) or ['otros']
            t = d.setdefault('texto', self._texto(d['info']))
            return (not cat or cat in cats) and all(p in t for p in pals)
        hay = [d for d in self._datos if pasa(d)]
        primero = self.orden.currentData() == 'instalados'
        hay.sort(key=lambda d: (primero and d['puesto'] is None,
                                sin_tildes(d['info'].nombre), d['info'].id))
        self.visibles = [d['info'].id for d in hay]
        for d in hay:
            if d['info'].id not in self.tarjetas:
                t = self.tarjetas[d['info'].id] = Tarjeta(
                    self._dlg, d['info'], d['puesto'], d['incluido'], d['nueva'])
                t.setParent(self.grid.parentWidget())
        self.contador.setText(tr("{n} de {m}").format(n=len(hay), m=len(self._datos)))
        self.sin_nada.setText(
            self._vacio if not self._datos else
            tr("Ningún complemento coincide con lo que buscas."))
        self.sc.setVisible(bool(hay))
        self.sin_nada.setVisible(not hay)
        self._colocar()

    def _colocar(self):
        n = self._columnas = self._n_columnas()
        while self.grid.count():
            self.grid.takeAt(0)
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 1 if c < n else 0)
        for r in range(self.grid.rowCount()):
            self.grid.setRowStretch(r, 0)
        for c in range(n):
            self.grid.setColumnStretch(c, 1)
        ver = set(self.visibles)
        for k, t in self.tarjetas.items():
            if k not in ver:
                t.hide()
        antes = None
        for k, id_ in enumerate(self.visibles):
            t = self.tarjetas[id_]
            self.grid.addWidget(t, k // n, k % n)
            t.show()
            for b in t.botones.values():          # el tabulador sigue la rejilla
                if antes is not None:
                    QWidget.setTabOrder(antes, b)
                antes = b
        self.grid.setRowStretch(len(self.visibles) // n + 1, 1)


class ComplementosDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Complementos"))
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumSize(440, 420)
        disp = self.screen().availableGeometry()
        self.resize(min(1180, disp.width() - 60), min(760, disp.height() - 80))
        self.estilos = {True: btn_primary(height=30), False: btn_secondary(height=28)}
        self.puede = gestor.puede_gestionar()
        vl = QVBoxLayout(self)
        vl.setContentsMargins(16, 14, 16, 12)
        vl.setSpacing(8)
        arriba = QWidget()
        fl = FlowLayout(arriba, h_spacing=8)
        self.btn_zip = self._boton(fl, tr("Instalar .zip…"), self._de_zip, True)
        self.btn_carpeta = self._boton(fl, tr("Instalar carpeta…"), self._de_carpeta)
        self.btn_crear = self._boton(fl, tr("Crear complemento…"), self._crear)
        self._boton(fl, tr("Abrir carpeta"), self._abrir_carpeta)
        for b in (self.btn_zip, self.btn_carpeta):
            b.setEnabled(self.puede)
        vl.addWidget(arriba)
        nota = QLabel(tr(
            "Nada se descarga de internet y nada se activa solo. Un complemento "
            "con código solo debería instalarse si confías en quien lo hizo."))
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color:{SLATE_500};")
        vl.addWidget(nota)
        self.tabs = QTabWidget()
        self.explorar = _Pagina(self, tr("No hay complementos para explorar."))
        self.instalados = _Pagina(self, tr(
            "No hay complementos instalados. Mira los de «Explorar»."))
        self.tabs.addTab(self.explorar, tr("Explorar"))
        self.tabs.addTab(self.instalados, tr("Instalados"))
        self.tabs.currentChanged.connect(lambda *_: self._mostrar())
        vl.addWidget(self.tabs, 1)
        hl = QHBoxLayout()
        self.lbl = QLabel('')
        self.lbl.setTextFormat(Qt.PlainText)
        self.lbl.setWordWrap(True)
        hl.addWidget(self.lbl, 1)
        self._boton(hl, tr("Cerrar"), self.accept)
        vl.addLayout(hl)
        if gestor.modo_seguro():
            self.lbl.setText(tr("Modo seguro: en esta sesión no se carga ningún "
                                "complemento."))
        elif not self.puede:
            self.lbl.setText(tr("Solo un administrador puede gestionar "
                                "complementos."))
        QShortcut(QKeySequence.Find, self, lambda: self._pagina().buscar.setFocus())
        self._pendiente = set()
        self._ofrecidos = {i.id: (d, i) for d, i in gestor.explorar()}
        self._cargar()

    @staticmethod
    def _boton(layout, texto, fn, primario=False) -> QPushButton:
        b = QPushButton(texto)
        b.setStyleSheet(btn_primary(height=34) if primario else btn_secondary())
        b.setAutoDefault(False)
        b.clicked.connect(lambda _=False: fn())
        layout.addWidget(b)
        return b

    def _pagina(self) -> _Pagina:
        return self.tabs.currentWidget()

    # ── Qué se enseña ────────────────────────────────────────────────────
    def _cargar(self):
        gestor.invalidar()
        self.infos = {i.id: i for i in gestor.instalados()}
        self._pendiente = {self.explorar, self.instalados}
        self.tabs.setTabText(1, f"{tr('Instalados')} ({len(self.infos)})")
        self._mostrar()

    def _mostrar(self):
        """Solo la pestaña a la vista; la otra se llena al abrirla."""
        p = self._pagina()
        if p not in self._pendiente:
            return
        self._pendiente.discard(p)
        infos = ([i for _d, i in self._ofrecidos.values()] if p is self.explorar
                 else list(self.infos.values()))
        p.poner([{'info': i, 'puesto': self.infos.get(i.id),
                  'incluido': self._es_incluido(i), 'nueva': self._nueva(i.id)}
                 for i in infos])

    def _es_incluido(self, i) -> bool:
        """Por CONTENIDO: uno ajeno con el mismo id no lleva la insignia."""
        o = self._ofrecidos.get(i.id)
        return bool(o and (o[1] is i or (
            o[1].paquete and i.paquete and o[1].paquete.huella == i.paquete.huella)))

    def _nueva(self, id_) -> str:
        o, i = self._ofrecidos.get(id_), self.infos.get(id_)
        if not (o and i and o[1].paquete):
            return ''
        v = o[1].paquete.manifiesto['version']
        if i.paquete is None or gestor.es_mas_nueva(
                v, i.paquete.manifiesto['version']):
            return v
        return ''

    def menu_de(self, i, padre) -> QMenu:
        m = QMenu(padre)
        m.setToolTipsVisible(True)

        def entrada(texto, fn, ayuda='', puede=True):
            a = m.addAction(texto)
            a.setToolTip(ayuda)
            a.setEnabled(puede)
            a.triggered.connect(lambda *_: fn())
        if i.paquete and i.paquete.manifiesto['indices']:
            entrada(tr("Importar índice…"), lambda: self.importar_indice(i.id),
                    puede=self.puede)
        if i.origen and Path(i.origen).is_dir():
            entrada(tr("Recargar"), lambda: self.recargar(i.id), tr(
                "Vuelve a copiar los archivos desde la carpeta de origen (para "
                "quien lo está escribiendo)"), self.puede)
        entrada(tr("Abrir carpeta"), lambda: self._abrir_carpeta(i.id))
        m.addSeparator()
        entrada(tr("Desinstalar"), lambda: self.desinstalar(i.id), puede=self.puede)
        return m

    def _hacer(self, fn):
        """Operación con sus errores explicados y las tarjetas al día."""
        try:
            r = fn()
        except (gestor.ErrorGestor, ErrorPaquete, OSError) as e:
            _aviso(self, str(e))
            r = None
        self._cargar()
        return r

    # ── Acciones ─────────────────────────────────────────────────────────
    def detalles(self, i):
        DetallesDialog(i, self).exec()

    def _de_zip(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, tr("Instalar complemento"), '', "ZIP (*.zip)")
        if ruta:
            self.instalar(ruta)

    def _de_carpeta(self):
        ruta = QFileDialog.getExistingDirectory(self, tr("Instalar complemento"))
        if ruta:
            self.instalar(ruta)

    def instalar(self, ruta):
        """De un archivo del usuario: se enseña en «Instalados»."""
        i = self._instalar(ruta)
        if i is not None and i.id not in self.explorar.visibles:
            self.tabs.setCurrentWidget(self.instalados)

    def instalar_incluido(self, id_):
        self._instalar(self._ofrecidos[id_][0])

    def _instalar(self, ruta):
        i = self._hacer(lambda: gestor.instalar(ruta))
        if i is not None:
            self.lbl.setText(tr("«{nombre}» quedó instalado y apagado.").format(
                nombre=i.nombre))
        return i

    def actualizar(self, id_):
        estaba = id_ in self.infos and self.infos[id_].activo
        if self._instalar(self._ofrecidos[id_][0]) is not None and estaba:
            self.activar(id_)           # otro contenido: se vuelve a pedir

    def activar(self, id_):
        i = self.infos.get(id_)
        if i is None or i.paquete is None:
            return
        if ConsentimientoDialog(i, self).exec() != QDialog.Accepted:
            return
        r = self._hacer(lambda: gestor.activar(i.id, i.paquete.huella))
        if r is None:
            return
        if not gestor.modo_seguro():
            fallos = [t for x, t in cargador.cargar_activos() if x == i.id]
            cargador.fallos[:] = []
            if fallos:
                self._cargar()
                _aviso(self, tr("No se pudo cargar y quedó apagado:")
                       + "\n\n" + "\n".join(fallos))
                return
        self.lbl.setText(tr("«{nombre}» está activo. Cierra y vuelve a abrir las "
                            "ventanas abiertas para ver sus cambios.").format(
                                nombre=i.nombre))

    def desactivar(self, id_):
        self._hacer(lambda: gestor.desactivar(id_))
        self.lbl.setText('')

    def recargar(self, id_):
        i = self.infos.get(id_)
        if i is None:
            return
        r = self._hacer(lambda: gestor.recargar(id_))
        if r is None:
            return
        if r.activo:
            cargador.cargar_activos()
            self._cargar()
        elif i.activo:
            self.activar(id_)           # cambió: se vuelve a pedir

    def desinstalar(self, id_):
        i = self.infos.get(id_)
        if i is None:
            return
        box = QMessageBox(QMessageBox.Question, tr("Desinstalar"), '',
                          QMessageBox.Yes | QMessageBox.No, self)
        box.setTextFormat(Qt.PlainText)
        box.setText(tr("¿Desinstalar «{nombre}»? Los proyectos que lo usaron "
                       "siguen abriendo e imprimiendo.").format(nombre=i.nombre))
        box.setDefaultButton(QMessageBox.No)
        if box.exec() == QMessageBox.Yes:
            self._hacer(lambda: gestor.desinstalar(id_))
            self.lbl.setText('')

    def importar_indice(self, id_):
        i = self.infos.get(id_)
        xs = i.paquete.manifiesto['indices'] if i and i.paquete else []
        if not xs:
            return
        clave = xs[0]['clave']
        if len(xs) > 1:
            nombres = [x['nombre'] for x in xs]
            n, ok = QInputDialog.getItem(self, tr("Importar índice"), tr("Índice"),
                                         nombres, 0, False)
            if not ok:
                return
            clave = xs[nombres.index(n)]['clave']
        ruta, _ = QFileDialog.getOpenFileName(
            self, tr("Importar índice"), '', "CSV (*.csv *.txt)")
        if not ruta:
            return
        n = self._hacer(lambda: gestor.importar_indice(id_, clave, ruta))
        if n:
            self.lbl.setText(tr("Se importaron {n} valores.").format(n=n))

    def _crear(self):
        from core.complementos import plantilla
        nombre, ok = QInputDialog.getText(self, tr("Crear complemento"),
                                          tr("Nombre del complemento"))
        if not ok or not nombre.strip():
            return
        donde = QFileDialog.getExistingDirectory(
            self, tr("Carpeta donde crearlo"))
        if not donde:
            return
        try:
            d = plantilla.crear(nombre, donde)
        except FileExistsError as e:
            _aviso(self, tr("Ya existe: {ruta}").format(ruta=e))
            return
        except OSError as e:
            _aviso(self, str(e))
            return
        if self.puede:
            self.instalar(d)
        self.lbl.setText(tr("Creado en {ruta}. Edítalo y pulsa «Recargar».").format(
            ruta=d))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _abrir_carpeta(self, id_=None):
        d = gestor.raiz()
        if id_ and gestor.carpeta_de(id_).is_dir():
            d = gestor.carpeta_de(id_)
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
