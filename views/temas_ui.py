# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Temas de reportes: el botón del Centro de Reportes y su editor."""
from __future__ import annotations

import os
import tempfile
from functools import partial

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFontComboBox, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from core import temas
from core.complementos import gestor
from core.complementos.paquete import ErrorPaquete
from utils.i18n import N_, tr

_COLORES = (
    ('marca', N_("Marca (encabezado y portada)")),
    ('marca_oscuro', N_("Marca, nombre de la empresa")),
    ('acento', N_("Líneas de cabecera")), ('acento_oscuro', N_("Totales")),
    ('suave', N_("Fondo de cabeceras")), ('borde', N_("Bordes de tablas")),
    ('cebra', N_("Filas alternas")), ('subpresupuesto', N_("Sub-presupuesto")))
_BORDES = (('ninguno', N_("Sin bordes")), ('finos', N_("Finos")),
           ('normales', N_("Normales")), ('gruesos', N_("Gruesos")))
_TEXTOS = {
    'encabezado': (('titulo', N_("Título")), ('linea', N_("Segunda línea")),
                   ('subtitulo', N_("Bajo el nombre de la empresa")),
                   ('derecha', N_("Derecha, arriba")),
                   ('derecha2', N_("Derecha, abajo"))),
    'pie': (('izquierda', N_("Izquierda")), ('centro', N_("Centro")),
            ('derecha', N_("Derecha"))),
}
_CAMPOS = {'codigo': N_("Código"), 'descripcion': N_("Descripción"),
           'unidad': N_("Unidad"), 'cantidad': N_("Cantidad"),
           'desglose': N_("Desglose del precio"), 'precio': N_("Precio"),
           'parcial': N_("Parcial")}


def _aviso(padre, texto):
    box = QMessageBox(QMessageBox.Warning, tr("Temas de reportes"), '',
                      QMessageBox.Ok, padre)
    box.setTextFormat(Qt.PlainText)
    box.setText(texto[:3000])
    box.setWindowModality(Qt.WindowModal)
    box.exec()


def texto_aviso(pid) -> str:
    """Por qué el reporte no lleva el tema elegido; '' si todo va bien."""
    ref = temas.aviso(pid)
    if ref:
        return tr("El tema «{ref}» no está disponible: se usa el de fábrica.").format(
            ref=ref)
    t = temas.activo(pid)
    tip = (t.datos.get('tipografia') or {}) if t else {}
    quiere = tip.get('familia')
    if quiere and temas.familia(t.datos).lower() != quiere.lower():
        return tr("La tipografía «{f}» no está instalada: se usa {otra}.").format(
            f=quiere, otra=temas.familia(t.datos))
    return ''


def llenar_menu(menu: QMenu, padre, pid, al_cambiar, invitado=False) -> None:
    """El menú «Tema»: para todos, para este proyecto, crear, editar, exportar."""
    menu.clear()
    hay = temas.disponibles()
    glob, propio = temas.global_(), temas.del_proyecto(pid)

    def grupo(m, opciones, actual, elegir):
        g = QActionGroup(m)
        for ref, nombre in opciones:
            a = QAction(nombre.replace('&', '&&'), m, checkable=True)
            a.setChecked(ref == actual)
            a.triggered.connect(partial(_elegir, elegir, ref))
            g.addAction(a)
            m.addAction(a)
        if actual not in dict(opciones):
            a = m.addAction(tr("No disponible: {ref}").format(
                ref=actual.replace('&', '&&')))
            a.setEnabled(False)

    def _elegir(elegir, ref, *_a):
        elegir(ref)
        al_cambiar()
    lista = [(t.ref, t.nombre) for t in hay.values()]
    m1 = menu.addMenu(tr("Para todos los proyectos"))
    grupo(m1, [('', tr("De fábrica"))] + lista, glob, temas.elegir_global)
    m1.setEnabled(gestor.puede_gestionar())
    m2 = menu.addMenu(tr("Para este proyecto"))
    grupo(m2, [('', tr("El de todos los proyectos")),
               (temas.DE_FABRICA, tr("De fábrica"))] + lista, propio,
          partial(temas.elegir_proyecto, pid))
    m2.setEnabled(not invitado)
    menu.addSeparator()
    puede = gestor.puede_gestionar()
    a = menu.addAction(tr("Crear tema a partir del actual…"))
    a.setEnabled(puede)
    a.triggered.connect(lambda: crear(padre, pid, al_cambiar))
    activo = temas.activo(pid)
    if activo is not None:
        a = menu.addAction(tr("Editar «{t}»…").format(t=activo.nombre.replace('&', '&&')))
        a.setEnabled(puede and activo.propio)
        if not activo.propio:
            a.setToolTip(tr("Viene en un complemento: crea una copia para cambiarlo."))
        a.triggered.connect(lambda: editar(padre, pid, activo, al_cambiar))
        a = menu.addAction(tr("Exportar «{t}»…").format(t=activo.nombre.replace('&', '&&')))
        a.triggered.connect(lambda: exportar(padre, activo))
    a = menu.addAction(tr("Gestionar complementos…"))
    a.triggered.connect(lambda: _gestionar(padre, al_cambiar))


def _gestionar(padre, al_cambiar):
    from views.complementos_dialog import ComplementosDialog
    ComplementosDialog(padre).exec()
    al_cambiar()


def crear(padre, pid, al_cambiar):
    nombre, ok = QInputDialog.getText(padre, tr("Crear tema"), tr("Nombre del tema:"))
    if not ok or not nombre.strip():
        return
    datos, logo = temas.desde_actual(pid)
    dlg = TemaDialog(nombre.strip()[:60], datos, logo, pid, padre)
    if dlg.exec() == QDialog.Accepted:
        try:
            ref = temas.guardar(dlg.nombre(), dlg.datos(), dlg.logo)
            temas.elegir_proyecto(pid, ref)
        except (ErrorPaquete, gestor.ErrorGestor, ValueError, OSError) as e:
            _aviso(padre, str(e))
        al_cambiar()


def editar(padre, pid, tema, al_cambiar):
    dlg = TemaDialog(tema.nombre, tema.datos, tema.logo, pid, padre)
    if dlg.exec() == QDialog.Accepted:
        try:
            temas.guardar(dlg.nombre(), dlg.datos(), dlg.logo, tema.ref)
        except (ErrorPaquete, gestor.ErrorGestor, ValueError, OSError) as e:
            _aviso(padre, str(e))
        al_cambiar()


def exportar(padre, tema, ruta=None):
    if ruta is None:
        ruta, _f = QFileDialog.getSaveFileName(
            padre, tr("Exportar tema"), f"{tema.ref.split('/')[0]}.zip", "ZIP (*.zip)")
    if not ruta:
        return None
    try:
        return temas.exportar(tema.ref, ruta)
    except (ErrorPaquete, OSError, KeyError) as e:
        _aviso(padre, str(e))
        return None


class _BotonColor(QPushButton):
    """Un color #RRGGBB o ninguno (el de fábrica)."""

    def __init__(self, valor, parent=None):
        super().__init__(parent)
        self.setFixedSize(QSize(92, 26))
        self.poner(valor)
        self.clicked.connect(self._elegir)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _p: self.poner(None))
        self.setToolTip(tr("Clic derecho: quitar (usar el de fábrica)"))

    def poner(self, valor):
        self.valor = valor
        self.setText(valor or "—")
        c = QColor(valor or '#FFFFFF')
        self.setStyleSheet(f"background:{c.name()}; color:"
                           f"{'#FFFFFF' if c.lightness() < 140 else '#1F2A38'};"
                           "border:1px solid #94A3B8; border-radius:5px;")

    def _elegir(self):
        c = QColorDialog.getColor(QColor(self.valor or '#FFFFFF'), self)
        if c.isValid():
            self.poner(c.name().upper())


class TemaDialog(QDialog):
    """Formulario de un tema, con vista previa."""

    def __init__(self, nombre, datos, logo, pid, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Tema de reportes"))
        self.pid, self.logo = pid, logo
        self._d = {k: v for k, v in datos.items() if k not in ('clave', 'nombre')}
        hl = QHBoxLayout(self)
        izq = QVBoxLayout()
        hl.addLayout(izq)
        f = QFormLayout()
        self.inp_nombre = QLineEdit(nombre)
        self.inp_nombre.setMaxLength(60)
        f.addRow(tr("Nombre:"), self.inp_nombre)
        izq.addLayout(f)
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(430)
        izq.addWidget(self.tabs, 1)
        self._pag_colores()
        self._pag_pagina()
        self._pag_textos()
        self._pag_columnas()
        self._pag_firmas()
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText(tr("Guardar"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Cancelar"))
        btn = bb.addButton(tr("Vista previa"), QDialogButtonBox.ActionRole)
        btn.clicked.connect(self.previsualizar)
        bb.accepted.connect(self._aceptar)
        bb.rejected.connect(self.reject)
        izq.addWidget(bb)
        self.lbl = QLabel(tr("Pulsa «Vista previa» para ver la primera página."))
        self.lbl.setAlignment(Qt.AlignCenter)
        self.lbl.setWordWrap(True)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.lbl)
        sc.setMinimumWidth(420)
        hl.addWidget(sc, 1)
        self.resize(1000, 680)

    def _pagina(self, titulo):
        w = QWidget()
        lay = QFormLayout(w)
        self.tabs.addTab(w, titulo)
        return lay

    def _pag_colores(self):
        lay, c = self._pagina(tr("Colores")), self._d.get('colores') or {}
        self._col = {}
        for k, n in _COLORES:
            self._col[k] = _BotonColor(c.get(k))
            lay.addRow(tr(n) + ":", self._col[k])
        g = QGridLayout()
        self._niveles = []
        tit = c.get('titulos') or []
        for n in range(9):
            b = _BotonColor(tit[n] if n < len(tit) else None)
            self._niveles.append(b)
            g.addWidget(QLabel(str(n + 1)), n // 3, (n % 3) * 2)
            g.addWidget(b, n // 3, (n % 3) * 2 + 1)
        lay.addRow(tr("Títulos por nivel:"), g)

    def _pag_pagina(self):
        lay, d = self._pagina(tr("Página")), self._d
        tip = d.get('tipografia') or {}
        self.cmb_fuente = QFontComboBox()
        self.cmb_fuente.setCurrentText(tip.get('familia') or 'Inter')
        lay.addRow(tr("Tipografía:"), self.cmb_fuente)
        self.inp_sustituta = QLineEdit(tip.get('sustituta') or '')
        self.inp_sustituta.setPlaceholderText(tr("Si falta la anterior"))
        lay.addRow(tr("Sustituta:"), self.inp_sustituta)
        self.cmb_escala = QComboBox()
        for e in (100, 90, 80, 75):
            self.cmb_escala.addItem(f"{e} %", e)
        self.cmb_escala.setCurrentIndex(
            max(0, self.cmb_escala.findData(tip.get('escala', 100))))
        lay.addRow(tr("Tamaño del texto:"), self.cmb_escala)
        self._margen = {}
        for k, n, base in (('superior', tr("Margen superior"), 15),
                           ('inferior', tr("Margen inferior"), 18),
                           ('izquierdo', tr("Margen izquierdo"), 15),
                           ('derecho', tr("Margen derecho"), 15)):
            s = QDoubleSpinBox()
            s.setRange(5, 40)
            s.setDecimals(0)
            s.setSuffix(" mm")
            s.setValue((d.get('margenes') or {}).get(k, base))
            self._margen[k] = s
            lay.addRow(n + ":", s)
        self.cmb_bordes = QComboBox()
        for k, n in _BORDES:
            self.cmb_bordes.addItem(tr(n), k)
        self.cmb_bordes.setCurrentIndex(
            max(0, self.cmb_bordes.findData(d.get('bordes', 'ninguno'))))
        lay.addRow(tr("Bordes de tablas:"), self.cmb_bordes)
        fila = QHBoxLayout()
        self.lbl_logo = QLabel(tr("Con logo") if self.logo else tr("Sin logo propio"))
        b1, b2 = QPushButton(tr("Elegir…")), QPushButton(tr("Quitar"))
        b1.clicked.connect(lambda: self._elegir_logo())
        b2.clicked.connect(lambda: self._poner_logo(None))
        for w in (self.lbl_logo, b1, b2):
            fila.addWidget(w)
        lay.addRow(tr("Logo:"), fila)
        self.spn_logo = QDoubleSpinBox()
        self.spn_logo.setRange(50, 200)
        self.spn_logo.setDecimals(0)
        self.spn_logo.setSuffix(" %")
        self.spn_logo.setValue((d.get('logo') or {}).get('escala', 100))
        lay.addRow(tr("Tamaño del logo:"), self.spn_logo)

    def _elegir_logo(self):
        ruta, _f = QFileDialog.getOpenFileName(self, tr("Logo"), '',
                                               "PNG, JPG (*.png *.jpg *.jpeg)")
        if ruta:
            self._poner_logo(ruta)

    def _poner_logo(self, ruta):
        from core.complementos import esquema
        if ruta is None:
            self.logo = None
        else:
            try:
                with open(ruta, 'rb') as fh:
                    b = fh.read(esquema.MAX_IMAGEN + 1)
            except OSError as e:
                return _aviso(self, str(e))
            if esquema.tipo_imagen(b) is None:
                return _aviso(self, tr("El logo debe ser PNG o JPG, de hasta 1 MB y "
                                       "4000 píxeles de lado."))
            self.logo = b
        self.lbl_logo.setText(tr("Con logo") if self.logo else tr("Sin logo propio"))

    def _pag_textos(self):
        lay = self._pagina(tr("Encabezado y pie"))
        nota = QLabel(tr("Vacío = no sale. Sin marcar = como de fábrica. Marcadores: ")
                      + " ".join('{%s}' % m for m in temas.MARCADORES))
        nota.setWordWrap(True)
        lay.addRow(nota)
        self._textos, self._mostrar = {}, {}
        for sec, campos in _TEXTOS.items():
            s = self._d.get(sec) or {}
            chk = QCheckBox(tr("Imprimir el encabezado") if sec == 'encabezado'
                            else tr("Imprimir el pie"))
            chk.setChecked(s.get('mostrar', True))
            self._mostrar[sec] = chk
            lay.addRow(chk)
            if sec == 'pie':
                self.chk_linea = QCheckBox(tr("Línea sobre el pie"))
                self.chk_linea.setChecked(s.get('linea', True))
                lay.addRow(self.chk_linea)
            for k, n in campos:
                usa = QCheckBox(tr(n))
                inp = QLineEdit(s.get(k, ''))
                inp.setMaxLength(200)
                usa.setChecked(k in s)
                inp.setEnabled(k in s)
                usa.toggled.connect(inp.setEnabled)
                self._textos[sec, k] = (usa, inp)
                lay.addRow(usa, inp)

    def _pag_columnas(self):
        lay = self._pagina(tr("Columnas"))
        lay.addRow(QLabel(tr("Marca las que salen y arrástralas para ordenarlas.")))
        self._cols = {}
        for rep, nombre in (('presupuesto', tr("Presupuesto")), ('insumos', tr("Insumos"))):
            lst = QListWidget()
            lst.setDragDropMode(QListWidget.InternalMove)
            lst.setMaximumHeight(190)
            de_tema = (self._d.get('columnas') or {}).get(rep)
            usadas = [c['campo'] for c in de_tema] if de_tema else list(temas.COLUMNAS[rep])
            self._extra_col = getattr(self, '_extra_col', {})
            self._extra_col[rep] = {c['campo']: c for c in de_tema or []}
            for c in usadas + [c for c in temas.COLUMNAS[rep] if c not in usadas]:
                it = QListWidgetItem(tr(_CAMPOS[c]))
                it.setData(Qt.UserRole, c)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if c in usadas else Qt.Unchecked)
                lst.addItem(it)
            self._cols[rep] = lst
            lay.addRow(nombre + ":", lst)
        self.inp_titulo_ppto = QLineEdit((self._d.get('nombres') or {}).get(
            'presupuesto', ''))
        self.inp_titulo_ppto.setMaxLength(80)
        lay.addRow(tr("Título del presupuesto:"), self.inp_titulo_ppto)

    def _pag_firmas(self):
        lay = self._pagina(tr("Firmas"))
        lay.addRow(QLabel(tr("Salen al final del presupuesto.")))
        self._firmas = []
        hay = self._d.get('firmas') or []
        for n in range(4):
            f = hay[n] if n < len(hay) else {}
            a, b = QLineEdit(f.get('nombre', '')), QLineEdit(f.get('cargo', ''))
            a.setPlaceholderText(tr("Nombre"))
            b.setPlaceholderText(tr("Cargo"))
            for i in (a, b):
                i.setMaxLength(80)
            fila = QHBoxLayout()
            fila.addWidget(a)
            fila.addWidget(b)
            self._firmas.append((a, b))
            lay.addRow(f"{n + 1}:", fila)

    # ── Resultado ────────────────────────────────────────────────────────
    def nombre(self) -> str:
        return self.inp_nombre.text().strip()

    def datos(self) -> dict:
        d = {k: v for k, v in self._d.items()
             if k in ('nombres',)}
        col = {k: b.valor for k, b in self._col.items() if b.valor}
        niveles = []
        for b in self._niveles:          # los que siguen al primer hueco, de fábrica
            if not b.valor:
                break
            niveles.append(b.valor)
        if niveles:
            col['titulos'] = niveles
        d['colores'] = col
        d['tipografia'] = {'familia': self.cmb_fuente.currentText().strip() or 'Inter',
                           'escala': self.cmb_escala.currentData()}
        if self.inp_sustituta.text().strip():
            d['tipografia']['sustituta'] = self.inp_sustituta.text().strip()
        d['margenes'] = {k: s.value() for k, s in self._margen.items()}
        d['bordes'] = self.cmb_bordes.currentData()
        d['logo'] = {'escala': int(self.spn_logo.value())}
        for sec in _TEXTOS:
            d[sec] = {'mostrar': self._mostrar[sec].isChecked()}
            for (s, k), (usa, inp) in self._textos.items():
                if s == sec and usa.isChecked():
                    d[sec][k] = inp.text().strip()
        d['pie']['linea'] = self.chk_linea.isChecked()
        d['columnas'] = {}
        for rep, lst in self._cols.items():
            cs = [lst.item(i).data(Qt.UserRole) for i in range(lst.count())
                  if lst.item(i).checkState() == Qt.Checked]
            if cs != list(temas.COLUMNAS[rep]) or self._extra_col[rep]:
                d['columnas'][rep] = [
                    dict(self._extra_col[rep].get(c) or {}, campo=c) for c in cs]
        nombres = dict(d.get('nombres') or {})
        nombres.pop('presupuesto', None)
        if self.inp_titulo_ppto.text().strip():
            nombres['presupuesto'] = self.inp_titulo_ppto.text().strip()
        d['nombres'] = nombres
        d['firmas'] = [{'nombre': a.text().strip(), 'cargo': b.text().strip()}
                       for a, b in self._firmas if a.text().strip() or b.text().strip()]
        return {k: v for k, v in d.items() if v not in ({}, [])}

    def _tema(self):
        try:
            return temas.revisar(self.nombre(), self.datos(), self.logo)
        except (ErrorPaquete, ValueError) as e:
            _aviso(self, str(e))
            return None

    def _aceptar(self):
        if self._tema() is not None:
            self.accept()

    def previsualizar(self):
        from PySide6.QtPdf import QPdfDocument
        from core import pdf_reports
        tema = self._tema()
        if tema is None:
            return
        fd, ruta = tempfile.mkstemp(suffix='.pdf')
        os.close(fd)
        doc = QPdfDocument(self)
        try:
            with temas.usando(tema):
                pdf_reports.generar_pdf_archivo('presupuesto', self.pid, ruta,
                                                with_cover=False)
            doc.load(ruta)
            tam = doc.pagePointSize(0).toSize() * 1.3
            self.lbl.setPixmap(QPixmap.fromImage(doc.render(0, tam)))
        except Exception as e:  # noqa: BLE001
            self.lbl.setText(str(e))
        finally:
            doc.close()
            try:
                os.unlink(ruta)
            except OSError:
                pass
