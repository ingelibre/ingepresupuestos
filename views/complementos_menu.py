# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""El menú de los complementos activos: el ÚNICO punto de enganche.

    menu = menu_complementos(padre, ventana, pid)
    if menu is not None:
        barra.addMenu(menu)

`None` = ningún complemento activo añade nada. Todo lo que hace un
complemento se ejecuta protegido: si falla se explica y el programa sigue.
"""
from __future__ import annotations

import os
from dataclasses import replace
from html import escape

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QPlainTextEdit, QProgressDialog, QPushButton, QScrollArea, QSpinBox,
    QTableWidget, QVBoxLayout, QWidget)

from core.complementos import cargador
from core.complementos.contexto import Cancelado
from ingepresupuestos import api
from utils.i18n import tr


class DatosDialog(QDialog):
    """El formulario de `ctx.pedir_datos`. Los límites los impone cada campo."""

    def __init__(self, titulo, campos, texto='', parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo[:80])
        vl = QVBoxLayout(self)
        if texto:
            lbl = QLabel(texto[:2000])
            lbl.setTextFormat(Qt.PlainText)
            lbl.setWordWrap(True)
            vl.addWidget(lbl)
        dentro = QWidget()
        form = QFormLayout(dentro)
        self._w = {}
        for c in campos:
            w = self._w[c.clave] = self._campo(c)
            if c.ayuda:
                w.setToolTip(escape(str(c.ayuda)[:500]))
            if c.tipo == 'tabla':
                rot = QLabel(str(c.titulo)[:120])
                rot.setTextFormat(Qt.PlainText)
                form.addRow(rot)
                form.addRow(w)
            elif c.tipo == 'si_no':
                form.addRow(w)
            else:
                rot = QLabel(str(c.titulo)[:120] + ":")
                rot.setTextFormat(Qt.PlainText)
                form.addRow(rot, w)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.setWidget(dentro)
        tablas = any(c.tipo == 'tabla' for c in campos)
        sc.setMinimumSize(min(940 if tablas else 620, dentro.sizeHint().width() + 30),
                          min(520 if tablas else 460, dentro.sizeHint().height() + 8))
        vl.addWidget(sc, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Aceptar"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Cancelar"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        vl.addWidget(bb)

    def _campo(self, c):
        return _campo(c)

    def valores(self) -> dict:
        return {k: _valor(w) for k, w in self._w.items()}


def _campo(c):
    v = c.valor
    num = isinstance(v, (int, float)) and not isinstance(v, bool)
    if c.tipo == 'entero':
        w = QSpinBox()
        w.setRange(int(max(c.minimo, -2**31)), int(min(c.maximo, 2**31 - 1)))
        w.setValue(int(v) if num else w.minimum())
    elif c.tipo == 'numero':
        w = QDoubleSpinBox()
        w.setDecimals(max(0, min(6, int(c.decimales))))
        w.setRange(c.minimo, c.maximo)
        w.setGroupSeparatorShown(True)
        w.setMinimumWidth(170)
        w.setValue(float(v) if num else c.minimo)
    elif c.tipo == 'opcion':
        w = QComboBox()
        w.addItems([str(o) for o in c.opciones])
        w.setCurrentIndex(max(0, w.findText(str(v))))
    elif c.tipo == 'si_no':
        w = QCheckBox(str(c.titulo).replace('&', '&&')[:120])
        w.setChecked(v is True)
    elif c.tipo == 'tabla':
        return _TablaDatos(c)
    elif c.tipo == 'parrafo':
        w = QPlainTextEdit(str(v or ''))
        w.setMinimumSize(380, 120)
        w.setTabChangesFocus(True)
    else:
        w = QLineEdit(str(v or ''))
        w.setMaxLength(1000)
        w.setMinimumWidth(300)
    if c.tipo in ('entero', 'numero') and c.sufijo:
        w.setSuffix(f" {c.sufijo}"[:12])
    return w


def _valor(w):
    if isinstance(w, _TablaDatos):
        return w.filas()
    if isinstance(w, (QSpinBox, QDoubleSpinBox)):
        return w.value()
    if isinstance(w, QComboBox):
        return w.currentText()
    if isinstance(w, QPlainTextEdit):
        return w.toPlainText().strip()[:5000]
    if isinstance(w, QCheckBox):
        return w.isChecked()
    return w.text().strip()


class _TablaDatos(QWidget):
    """Un `Dato` de tipo «tabla»: filas que se agregan, duplican y quitan."""

    MAX_FILAS = 200

    def __init__(self, c):
        super().__init__()
        self._cols = list(c.columnas)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        self.t = QTableWidget(0, len(self._cols))
        self.t.setHorizontalHeaderLabels([
            str(x.titulo)[:60] + (f" ({x.sufijo})" if x.sufijo else '')
            for x in self._cols])
        for i, x in enumerate(self._cols):
            if x.ayuda:
                self.t.horizontalHeaderItem(i).setToolTip(escape(str(x.ayuda)[:500]))
        self.t.setSelectionBehavior(QTableWidget.SelectRows)
        self.t.setMinimumSize(880, 130)
        vl.addWidget(self.t)
        hl = QHBoxLayout()
        for texto, fn in ((tr("Agregar fila"), lambda: self.poner({})),
                          (tr("Duplicar fila"), self._duplicar),
                          (tr("Quitar fila"), self._quitar)):
            b = QPushButton(texto)
            b.setAutoDefault(False)
            b.clicked.connect(lambda _=False, f=fn: f())
            hl.addWidget(b)
        hl.addStretch(1)
        vl.addLayout(hl)
        for f in c.valor if isinstance(c.valor, (list, tuple)) else ():
            if isinstance(f, dict):
                self.poner(f)
        self.t.resizeColumnsToContents()

    def poner(self, fila):
        if self.t.rowCount() >= self.MAX_FILAS:
            return
        r = self.t.rowCount()
        self.t.insertRow(r)
        for i, c in enumerate(self._cols):
            w = _campo(replace(c, valor=fila.get(c.clave, c.valor), sufijo='',
                               titulo='' if c.tipo == 'si_no' else c.titulo))
            ancho = 70
            if isinstance(w, QLineEdit):
                # Que se lea entero lo escrito; el ejemplo, mientras está vacío.
                w.setPlaceholderText(str(c.ayuda)[:60])
                ancho = max(110, *(min(280, w.fontMetrics().horizontalAdvance(x) + 24)
                                   for x in (w.text(), w.placeholderText())))
                w.setCursorPosition(0)
            w.setMinimumWidth(ancho)
            w.installEventFilter(self)
            self.t.setCellWidget(r, i, w)
        self.t.resizeRowToContents(r)
        self.t.selectRow(r)

    def eventFilter(self, w, e):
        # La fila «actual» es la del campo donde se está escribiendo.
        if e.type() == QEvent.FocusIn:
            for r in range(self.t.rowCount()):
                if any(self.t.cellWidget(r, i) is w for i in range(len(self._cols))):
                    self.t.selectRow(r)
                    break
        return super().eventFilter(w, e)

    def _actual(self):
        s = self.t.selectionModel().selectedRows()
        return s[0].row() if s else self.t.rowCount() - 1

    def _fila(self, r):
        return {c.clave: _valor(self.t.cellWidget(r, i))
                for i, c in enumerate(self._cols)}

    def _duplicar(self):
        if self.t.rowCount():
            self.poner(self._fila(self._actual()))

    def _quitar(self):
        if self.t.rowCount():
            self.t.removeRow(self._actual())

    def filas(self):
        return [self._fila(r) for r in range(self.t.rowCount())]


class VistaDialog(QDialog):
    """Un texto largo con barra, para leerlo entero antes de decidir."""

    def __init__(self, titulo, texto, preguntar, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo[:80])
        vl = QVBoxLayout(self)
        self.txt = QPlainTextEdit(texto)
        self.txt.setReadOnly(True)
        self.txt.setMinimumSize(720, 460)
        vl.addWidget(self.txt)
        b = QDialogButtonBox.Yes | QDialogButtonBox.No if preguntar \
            else QDialogButtonBox.StandardButtons(QDialogButtonBox.Ok)
        bb = QDialogButtonBox(b)
        if preguntar:
            bb.button(QDialogButtonBox.Yes).setText(tr("Sí"))
            bb.button(QDialogButtonBox.No).setText(tr("No"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        vl.addWidget(bb)


class Interfaz:
    """avisar / preguntar / pedir_archivo para `api.Contexto`."""

    def __init__(self, padre, titulo: str):
        self._padre, self._titulo = padre, titulo

    _espera = None

    def trabajando(self):
        """Aviso de «Calculando…» con Cancelar. La ventana queda bloqueada por
        él (modal), pero se sigue pintando."""
        if self._espera is None:
            d = self._espera = QProgressDialog(
                tr("Calculando…"), tr("Cancelar"), 0, 0, self._padre)
            d.setWindowTitle(self._titulo)
            d.setWindowModality(Qt.ApplicationModal)
            d.setMinimumDuration(0)
            d.setAutoClose(False)
            d.setAutoReset(False)
            d.show()
        QApplication.processEvents()
        if self._espera is not None and self._espera.wasCanceled():
            self.fin()
            raise Cancelado

    def fin(self):
        if self._espera is not None:
            d, self._espera = self._espera, None
            d.hide()
            d.deleteLater()

    def _caja(self, icono, texto, botones=QMessageBox.Ok):
        self.fin()
        box = QMessageBox(icono, self._titulo, '', botones, self._padre)
        box.setTextFormat(Qt.PlainText)
        box.setText(texto[:4000])
        box.setWindowModality(Qt.WindowModal)
        return box.exec()

    def _larga(self, texto, preguntar):
        self.fin()
        d = VistaDialog(self._titulo, texto[:60_000], preguntar, self._padre)
        d.setWindowModality(Qt.WindowModal)
        return d.exec() == QDialog.Accepted

    @staticmethod
    def _es_larga(texto):
        return len(texto) > 1500 or texto.count("\n") > 20

    def avisar(self, texto):
        if self._es_larga(texto):
            self._larga(texto, False)
            return
        self._caja(QMessageBox.Information, texto)

    def error(self, texto):
        self._caja(QMessageBox.Warning, texto)

    def preguntar(self, texto):
        if self._es_larga(texto):
            return self._larga(texto, True)
        return self._caja(QMessageBox.Question, texto,
                          QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

    def pedir_datos(self, titulo, campos, texto=''):
        self.fin()
        dlg = DatosDialog(titulo, campos, texto, self._padre)
        dlg.setWindowModality(Qt.WindowModal)
        return dlg.valores() if dlg.exec() == QDialog.Accepted else None

    def pedir_archivo(self, extensiones=()):
        self.fin()
        filtro = " ".join(f"*.{e}" for e in extensiones)
        ruta, _ = QFileDialog.getOpenFileName(
            self._padre, self._titulo, '', filtro and f"({filtro})")
        return ruta or None


def _usuario():
    from utils.auth import usuario_actual
    u = usuario_actual()
    if u is None:
        raise api.ErrorComplemento(tr("Nadie ha iniciado sesión."))
    return u


def _proteger(padre, cargado, registro, fn) -> bool:
    """Ejecuta y traduce cualquier fallo a un aviso legible."""
    try:
        fn()
        return True
    except Cancelado:
        return False
    except (Exception, SystemExit) as e:  # noqa: BLE001
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        Interfaz(padre, cargado.nombre).error(
            tr("El complemento «{nombre}» falló en «{que}»:").format(
                nombre=cargado.nombre, que=registro.titulo)
            + "\n\n" + cargador.texto_error(e, cargado.id))
        return False


def _puente(ventana):
    try:
        from views.mcp_puente import puente_de
        return puente_de(ventana)
    except Exception:  # noqa: BLE001 — sin MainWindow (pruebas)
        return None


def _contexto(padre, ventana, cargado, pid):
    from core.complementos.contexto import ContextoReal
    puente = _puente(ventana)
    return ContextoReal(cargado, pid, _usuario(), Interfaz(padre, cargado.nombre),
                        puente.pila if puente is not None else None)


def _refrescar(ventana, ctx) -> None:
    """Lo que el complemento escribió, a la vista. También si luego falló."""
    puente = _puente(ventana)
    if puente is not None and ctx.operaciones.tocados:
        puente._refrescar(ctx.operaciones)


def ejecutar_accion(padre, ventana, cargado, registro, pid) -> bool:
    def hacer():
        ctx = _contexto(padre, ventana, cargado, pid)
        try:
            registro.funcion(ctx)
        finally:
            ctx._ui.fin()
            _refrescar(ventana, ctx)
    return _proteger(padre, cargado, registro, hacer)


def ejecutar_reporte(padre, cargado, registro, pid, formato, ruta=None) -> bool:
    def hacer():
        nonlocal ruta
        from core.complementos import contexto, reportes
        p = contexto.presupuesto(pid, _usuario(), cargado.id)
        if ruta is None:
            base = "".join(c for c in f"{p.nombre} - {registro.titulo}"
                           if c not in '<>:"/\\|?*' and ord(c) >= 32)[:120]
            from core.database import get_config
            carpeta = get_config('ruta_exportacion', '') or ''
            ruta, _ = QFileDialog.getSaveFileName(
                padre, registro.titulo, os.path.join(carpeta, f"{base}.{formato}"),
                f"(*.{formato})")
            if not ruta:
                return
            if not ruta.lower().endswith('.' + formato):
                ruta += '.' + formato
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            reportes.generar(registro, p, ruta)
        finally:
            QApplication.restoreOverrideCursor()
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if QApplication.platformName() != 'offscreen':
            QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))
    return _proteger(padre, cargado, registro, hacer)


def ejecutar_importador(padre, ventana, cargado, registro, pid, ruta=None) -> bool:
    def hacer():
        ctx = _contexto(padre, ventana, cargado, pid)
        archivo = ruta or ctx.pedir_archivo(registro.extra['extensiones'])
        if not archivo:
            return
        try:
            nuevas = list(registro.funcion(archivo, ctx) or [])
            if not nuevas:
                ctx.avisar(tr("No hay nada que importar."))
                return
            titulos = sum(bool(getattr(x, 'es_titulo', False)) for x in nuevas)
            if not ctx.preguntar(tr(
                    "Se agregarán {t} títulos y {n} partidas al proyecto. "
                    "¿Continuar?").format(t=titulos, n=len(nuevas) - titulos)):
                return
            ctx.editar.agregar(nuevas)
        finally:
            _refrescar(ventana, ctx)
    return _proteger(padre, cargado, registro, hacer)


def ejecutar_validador(padre, cargado, registro, pid) -> bool:
    def hacer():
        from core.complementos import contexto
        p = contexto.presupuesto(pid, _usuario(), cargado.id)
        avisos = list(registro.funcion(p) or [])
        if any(not isinstance(a, api.Aviso) for a in avisos):
            raise api.ErrorComplemento("un validador devuelve una lista de Aviso")
        ui = Interfaz(padre, registro.titulo)
        if not avisos:
            ui.avisar(tr("Sin observaciones."))
            return
        lineas = [("✗ " if a.nivel == 'error' else "• ") + str(a.texto)
                  for a in avisos[:60]]
        if len(avisos) > 60:
            lineas.append(tr("… y {n} más.").format(n=len(avisos) - 60))
        ui.avisar("\n".join(lineas))
    return _proteger(padre, cargado, registro, hacer)


def menu_complementos(padre, ventana, pid: int, menu=None,
                      tipos=('accion', 'reporte', 'importador', 'validador')
                      ) -> QMenu | None:
    """El menú para el proyecto `pid` (o `menu`, ya creado, lleno con él);
    None si no hay nada que mostrar."""
    cs = [c for c in cargador.cargados() if any(c.de(t) for t in tipos)]
    if not cs:
        return None
    menu = menu if menu is not None else QMenu(tr("Complementos"), padre)
    menu.setToolTipsVisible(True)

    def entrada(m, texto, ayuda, fn):
        a = m.addAction(texto.replace('&', '&&'))
        a.setToolTip(ayuda or '')
        a.triggered.connect(lambda _=False: fn())

    for c in cs:
        sub = menu.addMenu(c.nombre.replace('&', '&&')) if len(cs) > 1 else menu
        for r in c.de('accion') if 'accion' in tipos else ():
            entrada(sub, r.titulo, r.extra['ayuda'],
                    lambda c=c, r=r: ejecutar_accion(padre, ventana, c, r, pid))
        for r in c.de('reporte') if 'reporte' in tipos else ():
            for f in r.extra['formatos']:
                entrada(sub, f"{r.titulo} ({'PDF' if f == 'pdf' else 'Excel'})",
                        r.extra['ayuda'],
                        lambda c=c, r=r, f=f: ejecutar_reporte(padre, c, r, pid, f))
        for r in c.de('importador') if 'importador' in tipos else ():
            entrada(sub, tr("Importar: {que}…").format(que=r.titulo),
                    r.extra['ayuda'],
                    lambda c=c, r=r: ejecutar_importador(padre, ventana, c, r, pid))
        for r in c.de('validador') if 'validador' in tipos else ():
            entrada(sub, tr("Revisar: {que}").format(que=r.titulo),
                    r.extra['ayuda'],
                    lambda c=c, r=r: ejecutar_validador(padre, c, r, pid))
    return menu
