# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Gestor de complementos (Configuración ▸ Complementos)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from core.complementos import cargador, esquema, gestor
from core.complementos.paquete import ErrorPaquete
from utils.i18n import N_, tr
from utils.theme import BTN_PRIMARY_SS, SLATE_500, btn_secondary

_ESTADOS = {
    'activo': N_("Activo"), 'apagado': N_("Apagado"),
    'cambiado': N_("Cambió: hay que volver a activarlo"),
    'error': N_("Apagado por un error"), 'dañado': N_("Dañado"),
}
_SECCIONES = {
    'paises': N_("Países"), 'monedas': N_("Monedas"),
    'vocabulario': N_("Vocabulario"),
    'importadores_excel': N_("Formatos de Excel"), 'indices': N_("Índices"),
    'titulos': N_("Títulos"), 'unidades': N_("Unidades"),
}


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
    L = [f"{m['nombre']}  {m['version']}",
         f"{tr('Estado')}: {tr(_ESTADOS[i.estado])}"]
    if i.error:
        L.append(i.error)
    L += ["", m['descripcion'], "",
          f"{tr('Autor')}: {m['autor']}", f"{tr('Licencia')}: {m['licencia']}"]
    if m['web']:
        L.append(f"Web: {m['web']}")
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
        cuerpo = QHBoxLayout()
        self.lst = QListWidget()
        self.lst.setMaximumWidth(220)
        self.lst.addItem(tr("Resumen"))
        for r in sorted(info.paquete.archivos):
            it = QListWidgetItem(r)
            it.setData(Qt.UserRole, r)
            self.lst.addItem(it)
        cuerpo.addWidget(self.lst)
        self.ver = QPlainTextEdit()
        self.ver.setReadOnly(True)
        cuerpo.addWidget(self.ver, 1)
        vl.addLayout(cuerpo, 1)
        self.lst.currentItemChanged.connect(self._mostrar)
        self.lst.setCurrentRow(0)
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

    def _listo(self, *_):
        self.btn.setEnabled(all(c.isChecked() for c in self.chks))


class ComplementosDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Complementos"))
        self.setWindowModality(Qt.WindowModal)
        self.resize(820, 560)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(20, 18, 20, 16)
        vl.setSpacing(10)
        nota = QLabel(tr(
            "Nada se descarga de internet y nada se activa solo. Un complemento "
            "con código solo debería instalarse si confías en quien lo hizo."))
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color:{SLATE_500};")
        vl.addWidget(nota)

        arriba = QHBoxLayout()
        self.btn_zip = self._boton(arriba, tr("Instalar .zip…"), self._de_zip, True)
        self.btn_carpeta = self._boton(arriba, tr("Instalar carpeta…"),
                                       self._de_carpeta)
        self.btn_incl = self._boton(arriba, tr("Incluidos"), None)
        menu = QMenu(self.btn_incl)
        menu.aboutToShow.connect(lambda: self._llenar_incluidos(menu))
        self.btn_incl.setMenu(menu)
        self.btn_crear = self._boton(arriba, tr("Crear complemento…"), self._crear)
        arriba.addStretch()
        self._boton(arriba, tr("Abrir carpeta"), self._abrir_carpeta)
        vl.addLayout(arriba)

        cuerpo = QHBoxLayout()
        self.lst = QListWidget()
        self.lst.setMinimumWidth(250)
        self.lst.currentItemChanged.connect(lambda *_: self._mostrar())
        cuerpo.addWidget(self.lst, 1)
        der = QVBoxLayout()
        self.txt = QPlainTextEdit()
        self.txt.setReadOnly(True)
        der.addWidget(self.txt, 1)
        fila = QHBoxLayout()
        self.btn_act = self._boton(fila, tr("Activar…"), self._activar, True)
        self.btn_des = self._boton(fila, tr("Desactivar"), self._desactivar)
        self.btn_rec = self._boton(fila, tr("Recargar"), self._recargar)
        self.btn_rec.setToolTip(tr("Vuelve a copiar los archivos desde la carpeta "
                                   "de origen (para quien lo está escribiendo)"))
        self.btn_ind = self._boton(fila, tr("Importar índice…"), self._indice)
        fila.addStretch()
        self.btn_qui = self._boton(fila, tr("Desinstalar"), self._desinstalar)
        der.addLayout(fila)
        cuerpo.addLayout(der, 2)
        vl.addLayout(cuerpo, 1)

        self.lbl = QLabel('')
        self.lbl.setTextFormat(Qt.PlainText)
        self.lbl.setWordWrap(True)
        vl.addWidget(self.lbl)
        hl = QHBoxLayout()
        hl.addStretch()
        self._boton(hl, tr("Cerrar"), self.accept)
        vl.addLayout(hl)
        self._puede = gestor.puede_gestionar()
        if gestor.modo_seguro():
            self.lbl.setText(tr("Modo seguro: en esta sesión no se carga ningún "
                                "complemento."))
        elif not self._puede:
            self.lbl.setText(tr("Solo un administrador puede gestionar "
                                "complementos."))
        for b in (self.btn_zip, self.btn_carpeta, self.btn_incl):
            b.setEnabled(self._puede)
        self._cargar()

    @staticmethod
    def _boton(layout, texto, fn, primario=False) -> QPushButton:
        b = QPushButton(texto)
        b.setStyleSheet(BTN_PRIMARY_SS if primario else btn_secondary())
        b.setAutoDefault(False)
        if fn is not None:
            b.clicked.connect(lambda _=False: fn())
        layout.addWidget(b)
        return b

    # ── Lista ────────────────────────────────────────────────────────────
    def _cargar(self, elegir: str | None = None):
        gestor.invalidar()
        elegir = elegir or (self.actual().id if self.actual() else None)
        self._infos = {i.id: i for i in gestor.instalados()}
        self.lst.blockSignals(True)
        self.lst.clear()
        for i in self._infos.values():
            it = QListWidgetItem(f"{'●' if i.activo else '○'}  {i.nombre}\n"
                                 f"     {tr(_ESTADOS[i.estado])}")
            it.setData(Qt.UserRole, i.id)
            self.lst.addItem(it)
            if i.id == elegir:
                self.lst.setCurrentItem(it)
        if self.lst.currentItem() is None and self.lst.count():
            self.lst.setCurrentRow(0)
        self.lst.blockSignals(False)
        self._mostrar()

    def actual(self) -> gestor.Info | None:
        it = self.lst.currentItem()
        return self._infos.get(it.data(Qt.UserRole)) if it is not None else None

    def _mostrar(self):
        i = self.actual()
        self.txt.setPlainText(ficha(i) if i else tr(
            "No hay complementos instalados. Prueba con «Incluidos»."))
        ok = self._puede and i is not None
        self.btn_act.setEnabled(bool(ok and i.paquete and not i.activo))
        self.btn_des.setEnabled(bool(ok and i.activo))
        self.btn_rec.setEnabled(bool(ok and i.origen))
        self.btn_qui.setEnabled(bool(ok))
        self.btn_ind.setVisible(bool(i and i.paquete
                                     and i.paquete.manifiesto['indices']))
        self.btn_ind.setEnabled(bool(ok))

    def _hacer(self, fn, elegir=None):
        """Operación con sus errores explicados y la lista al día."""
        try:
            r = fn()
        except (gestor.ErrorGestor, ErrorPaquete, OSError) as e:
            _aviso(self, str(e))
            r = None
        self._cargar(elegir or getattr(r, 'id', None))
        return r

    # ── Acciones ─────────────────────────────────────────────────────────
    def _de_zip(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, tr("Instalar complemento"), '', "ZIP (*.zip)")
        if ruta:
            self._instalar(ruta)

    def _de_carpeta(self):
        ruta = QFileDialog.getExistingDirectory(self, tr("Instalar complemento"))
        if ruta:
            self._instalar(ruta)

    def _llenar_incluidos(self, menu):
        menu.clear()
        for d in gestor.incluidos():
            try:
                m = esquema.leer((d / esquema.ARCHIVO).read_bytes())
            except (OSError, esquema.ErrorEsquema):
                continue
            a = menu.addAction(m['nombre'].replace('&', '&&'))
            a.triggered.connect(lambda _=False, d=d: self._instalar(d))

    def _instalar(self, ruta):
        i = self._hacer(lambda: gestor.instalar(ruta))
        if i is not None:
            self.lbl.setText(tr("«{nombre}» quedó instalado y apagado.").format(
                nombre=i.nombre))

    def _activar(self):
        i = self.actual()
        if i is None or i.paquete is None:
            return
        if ConsentimientoDialog(i, self).exec() != QDialog.Accepted:
            return
        r = self._hacer(lambda: gestor.activar(i.id, i.paquete.huella))
        if r is None:
            return
        if not gestor.modo_seguro():
            fallos = [t for id_, t in cargador.cargar_activos() if id_ == i.id]
            cargador.fallos[:] = []
            if fallos:
                self._cargar(i.id)
                _aviso(self, tr("No se pudo cargar y quedó apagado:")
                       + "\n\n" + "\n".join(fallos))
                return
        self.lbl.setText(tr("«{nombre}» está activo. Cierra y vuelve a abrir las "
                            "ventanas abiertas para ver sus cambios.").format(
                                nombre=i.nombre))

    def _desactivar(self):
        i = self.actual()
        if i is not None:
            self._hacer(lambda: gestor.desactivar(i.id), i.id)

    def _recargar(self):
        i = self.actual()
        if i is None:
            return
        estaba = i.activo
        r = self._hacer(lambda: gestor.recargar(i.id), i.id)
        if r is None:
            return
        if r.activo:
            cargador.cargar_activos()
            self._cargar(i.id)
        elif estaba:
            self._activar()         # cambió: se vuelve a pedir

    def _desinstalar(self):
        i = self.actual()
        if i is None:
            return
        box = QMessageBox(QMessageBox.Question, tr("Desinstalar"), '',
                          QMessageBox.Yes | QMessageBox.No, self)
        box.setTextFormat(Qt.PlainText)
        box.setText(tr("¿Desinstalar «{nombre}»? Los proyectos que lo usaron "
                       "siguen abriendo e imprimiendo.").format(nombre=i.nombre))
        box.setDefaultButton(QMessageBox.No)
        if box.exec() == QMessageBox.Yes:
            self._hacer(lambda: gestor.desinstalar(i.id))

    def _indice(self):
        i = self.actual()
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
        n = self._hacer(lambda: gestor.importar_indice(i.id, clave, ruta), i.id)
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
        if self._puede:
            self._instalar(d)
        self.lbl.setText(tr("Creado en {ruta}. Edítalo y pulsa «Recargar».").format(
            ruta=d))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _abrir_carpeta(self):
        d = gestor.raiz()
        i = self.actual()
        if i is not None and Path(gestor.carpeta_de(i.id)).is_dir():
            d = gestor.carpeta_de(i.id)
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
