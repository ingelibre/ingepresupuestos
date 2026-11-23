# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Importar insumos desde un Excel cualquiera — con asignación de columnas.

Reemplaza el camino de «Importar ▸ Desde Excel» del Catálogo de Insumos, que
solo aceptaba el formato propio en la primera fila. La lógica (detectar la
cabecera, asignar columnas, «100 Kg», quitar el IVA, escribir en la BD) vive
en `core/importar_excel_insumos.py`; aquí solo se muestra y se deja corregir.

La vista previa enseña los insumos COMO VAN A QUEDAR —unidad partida, precio
dividido y sin impuesto—, con lo que traía el archivo al lado: es lo que deja
ver de un vistazo que «100 Kg a 26 222,59» entró como «Kg a 214,94».

La asignación que se usó se recuerda por la firma de la cabecera (QSettings):
la Lista del MTOP del mes siguiente es un clic.
"""
from __future__ import annotations

import os
from html import escape

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core import importar_excel_insumos as imp
from utils.icons import icon
from utils.theme import BTN_PRIMARY_SS, C, F_PX, R, W, btn_secondary

# Filas de la vista previa. Las suficientes para ver el patrón sin que el
# diálogo crezca: el resumen de abajo da el total.
FILAS_PREVIA = 12

_QS_ORG, _QS_APP = 'ingePresupuestos', 'importar_excel_insumos'

_TIPO_FG = {'MO': C.mo_fg, 'MAT': C.mat_fg, 'EQ': C.eq_fg, 'SC': C.sc_fg}


def _letra(i: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    s = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _corto(v, n: int = 28) -> str:
    s = imp._texto(v).replace('\n', ' ')
    return s if len(s) <= n else s[:n - 1] + '…'


class ImportarExcelDialog(QDialog):
    """`exec()` devuelve Accepted cuando ya importó; `resultado` y
    `texto_resumen` cuentan qué pasó (la vista lo muestra y recarga)."""

    def __init__(self, libro: imp.Libro, parent=None, *,
                 impuesto_pct: float | None = None, settings: QSettings | None = None):
        super().__init__(parent)
        from utils.i18n import tr
        self.libro = libro
        self.resultado: dict | None = None
        self.texto_resumen = ''
        self.op = imp.Opciones()
        self._insumos: list[imp.Insumo] = []
        self._omitidos: list[tuple[int, str]] = []
        self._cargando = False
        self._memoria = False
        self._qs = settings or QSettings(_QS_ORG, _QS_APP)
        if impuesto_pct is None:
            try:
                from core.paises import impuesto
                impuesto_pct = impuesto()[1]
            except Exception:
                impuesto_pct = 18.0
        self._imp_pct_pais = float(impuesto_pct)
        try:
            from core.paises import es_peru
            self._es_peru = es_peru()
        except Exception:
            self._es_peru = True

        self.setWindowTitle(tr("Importar insumos desde Excel"))
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumSize(860, 600)
        self.resize(1000, 700)
        self.setStyleSheet(f"QDialog {{ background:{C.bg}; }}")
        self._build()
        self._cargar_hoja(imp.hoja_inicial(libro))

    # ── Construcción ────────────────────────────────────────────────────
    def _lbl(self, txt: str, *, color=None, size=None, bold=False) -> QLabel:
        l = QLabel(txt)
        l.setStyleSheet(
            f"color:{color or C.text}; font-size:{size or F_PX.body}px;"
            f" font-weight:{W.semibold if bold else W.normal};"
            " background:transparent; border:none;")
        return l

    def _build(self):
        from utils.i18n import tr
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{C.headerbar_dark};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18, 0, 18, 0)
        ic = QLabel()
        ic.setPixmap(icon("xlsx").pixmap(20, 20))
        ic.setStyleSheet("background:transparent; border:none;")
        hl.addWidget(ic)
        t = QLabel(tr("Importar insumos desde Excel"))
        t.setStyleSheet(f"color:{C.text_inverse}; font-size:14px; font-weight:{W.bold};"
                        " background:transparent; border:none;")
        hl.addWidget(t)
        hl.addStretch(1)
        arch = QLabel(os.path.basename(self.libro.ruta))
        arch.setToolTip(self.libro.ruta)
        arch.setStyleSheet(f"color:{C.sidebar_text_muted}; font-size:{F_PX.label}px;"
                           " background:transparent; border:none;")
        hl.addWidget(arch)
        v.addWidget(hdr)

        cuerpo = QFrame()
        cuerpo.setStyleSheet(f"background:{C.bg};")
        cl = QVBoxLayout(cuerpo)
        cl.setContentsMargins(18, 12, 18, 10)
        cl.setSpacing(10)

        # Aviso: formato reconocido / asignación recordada.
        self.lbl_aviso = QLabel()
        self.lbl_aviso.setWordWrap(True)
        self.lbl_aviso.setStyleSheet(
            f"background:{C.info_soft}; color:{C.text}; border:1px solid {C.border};"
            f" border-radius:{R.md}px; padding:6px 10px; font-size:{F_PX.body}px;")
        cl.addWidget(self.lbl_aviso)

        # Hoja + fila de títulos.
        fila = QHBoxLayout()
        fila.setSpacing(8)
        fila.addWidget(self._lbl(tr("Hoja"), bold=True))
        self.cmb_hoja = QComboBox()
        self.cmb_hoja.addItems(self.libro.hojas)
        self.cmb_hoja.setMinimumWidth(180)
        self.cmb_hoja.currentTextChanged.connect(self._cargar_hoja)
        fila.addWidget(self.cmb_hoja)
        fila.addSpacing(14)
        fila.addWidget(self._lbl(tr("Fila de títulos"), bold=True))
        self.spin_cab = QSpinBox()
        self.spin_cab.setMinimum(1)
        self.spin_cab.setFixedWidth(70)
        self.spin_cab.setToolTip(tr("Fila del Excel donde están los títulos de las "
                                    "columnas. Se detecta sola; cámbiela si no acertó."))
        self.spin_cab.valueChanged.connect(self._cambio_cabecera)
        fila.addWidget(self.spin_cab)
        self.lbl_cab = self._lbl('', color=C.text_secondary, size=F_PX.label)
        fila.addWidget(self.lbl_cab, 1)
        cl.addLayout(fila)

        # Columnas.
        caja = QFrame()
        caja.setObjectName("cajaCols")
        caja.setStyleSheet(f"QFrame#cajaCols {{ background:{C.surface};"
                           f" border:1px solid {C.border}; border-radius:{R.lg}px; }}")
        g = QGridLayout(caja)
        g.setContentsMargins(14, 10, 14, 10)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        g.addWidget(self._lbl(tr("Columnas del archivo"), bold=True), 0, 0, 1, 6)
        self.cmb_col: dict[str, QComboBox] = {}
        self._lbl_col: dict[str, QLabel] = {}
        etiquetas = {
            'codigo': tr("Código"), 'descripcion': tr("Descripción *"),
            'unidad': tr("Unidad"), 'precio': tr("Precio *"),
            'tipo': tr("Tipo"), 'inei': tr("Índice INEI"),
        }
        pos = {'codigo': (1, 0), 'descripcion': (1, 2), 'unidad': (1, 4),
               'precio': (2, 0), 'tipo': (2, 2), 'inei': (2, 4)}
        for campo in imp.CAMPOS:
            r, c = pos[campo]
            lab = self._lbl(etiquetas[campo], color=C.text_secondary, size=F_PX.label)
            cb = QComboBox()
            cb.setMinimumWidth(190)
            cb.currentIndexChanged.connect(self._recalcular)
            g.addWidget(lab, r, c)
            g.addWidget(cb, r, c + 1)
            self.cmb_col[campo] = cb
            self._lbl_col[campo] = lab
        for c in (1, 3, 5):
            g.setColumnStretch(c, 1)

        # Opciones.
        self.chk_cant = QCheckBox(tr("La unidad trae la cantidad («100 Kg» → unidad Kg, "
                                     "precio ÷ 100)"))
        self.chk_imp = QCheckBox(tr("Los precios incluyen impuesto: quitar"))
        self.spin_pct = QDoubleSpinBox()
        self.spin_pct.setRange(0, 60)
        self.spin_pct.setDecimals(2)
        self.spin_pct.setSuffix(" %")
        self.spin_pct.setFixedWidth(90)
        self.chk_omitir = QCheckBox(tr("Omitir filas sin precio (0); al actualizar, un 0 "
                                       "nunca pisa un precio existente"))
        self.inp_pref = QLineEdit()
        self.inp_pref.setPlaceholderText(tr("p. ej. MTOP-"))
        self.inp_pref.setFixedWidth(120)
        self.inp_pref.setToolTip(tr("Se antepone a cada código del archivo, para que no "
                                    "choque con códigos de otros catálogos."))
        for w in (self.chk_cant, self.chk_imp, self.chk_omitir):
            # Sin esto el fondo del QDialog asoma como una franja gris
            # dentro de la caja blanca.
            w.setStyleSheet("QCheckBox { background:transparent; }")
            w.toggled.connect(self._recalcular)
        self.spin_pct.valueChanged.connect(self._recalcular)
        self.inp_pref.textChanged.connect(self._recalcular)

        g.addWidget(self.chk_cant, 3, 0, 1, 6)
        fimp = QHBoxLayout()
        fimp.setSpacing(6)
        fimp.addWidget(self.chk_imp)
        fimp.addWidget(self.spin_pct)
        fimp.addStretch(1)
        fimp.addWidget(self._lbl(tr("Prefijo de código"), color=C.text_secondary,
                                 size=F_PX.label))
        fimp.addWidget(self.inp_pref)
        g.addLayout(fimp, 4, 0, 1, 6)
        g.addWidget(self.chk_omitir, 5, 0, 1, 6)
        self.lbl_motivos = self._lbl('', color=C.text_secondary, size=F_PX.label)
        self.lbl_motivos.setWordWrap(True)
        g.addWidget(self.lbl_motivos, 6, 0, 1, 6)
        cl.addWidget(caja)

        # Vista previa.
        cl.addWidget(self._lbl(tr("Vista previa — así quedarán en el catálogo"), bold=True))
        self.tbl = QTableWidget(0, 7)
        self.tbl.setHorizontalHeaderLabels([
            tr("Fila"), tr("Código"), tr("Tipo"), tr("Descripción"), tr("Unidad"),
            tr("Precio"), tr("En el archivo")])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setShowGrid(False)
        self.tbl.setWordWrap(False)
        self.tbl.setStyleSheet(
            f"QTableWidget {{ background:{C.surface}; border:1px solid {C.border};"
            f" border-radius:{R.md}px; font-size:{F_PX.label}px;"
            f" alternate-background-color:{C.bg_alt}; }}"
            f"QHeaderView::section {{ background:{C.surface_subtle}; color:{C.text};"
            f" font-weight:{W.bold}; font-size:{F_PX.meta}px; border:none;"
            f" border-bottom:1px solid {C.border}; padding:4px; }}")
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        cl.addWidget(self.tbl, 1)

        self.lbl_resumen = self._lbl('', size=F_PX.body)
        self.lbl_resumen.setWordWrap(True)
        cl.addWidget(self.lbl_resumen)
        v.addWidget(cuerpo, 1)

        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"background:{C.surface}; border-top:1px solid {C.border};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(18, 8, 18, 8)
        bl.setSpacing(10)
        bl.addStretch(1)
        b_cancel = QPushButton(tr("Cancelar"))
        b_cancel.setCursor(Qt.PointingHandCursor)
        b_cancel.setStyleSheet(btn_secondary())
        b_cancel.clicked.connect(self.reject)
        bl.addWidget(b_cancel)
        self.b_ok = QPushButton(tr("Importar"))
        self.b_ok.setCursor(Qt.PointingHandCursor)
        self.b_ok.setStyleSheet(BTN_PRIMARY_SS)
        self.b_ok.clicked.connect(self._aceptar)
        bl.addWidget(self.b_ok)
        v.addWidget(bar)

    # ── Carga de hoja / cabecera ────────────────────────────────────────
    def _filas(self) -> list[list]:
        return self.libro.filas.get(self.op.hoja) or []

    def _cargar_hoja(self, hoja: str, fila_cabecera: int | None = None):
        if not hoja:
            return
        filas = self.libro.filas.get(hoja) or []
        op = imp.configuracion_inicial(filas, hoja, impuesto_pct=self._imp_pct_pais,
                                       fila_cabecera=fila_cabecera)
        cab = filas[op.fila_cabecera] if op.fila_cabecera < len(filas) else []
        guardada = self._qs.value(f"formatos/{imp.clave_firma(cab)}")
        self._memoria = bool(guardada) and op.aplicar_json(guardada)
        self.op = op
        self._cargando = True
        try:
            if self.cmb_hoja.currentText() != hoja:
                self.cmb_hoja.blockSignals(True)
                self.cmb_hoja.setCurrentText(hoja)
                self.cmb_hoja.blockSignals(False)
            self.spin_cab.setMaximum(max(1, len(filas)))
            self.spin_cab.setValue(op.fila_cabecera + 1)
            self._llenar_combos(cab, imp.datos_de(filas, op.fila_cabecera))
            self.chk_cant.setChecked(op.cantidad_en_unidad)
            self.chk_imp.setChecked(op.quitar_impuesto)
            self.spin_pct.setValue(op.impuesto_pct)
            self.chk_omitir.setChecked(op.omitir_sin_precio)
            self.inp_pref.setText(op.prefijo)
            ver_inei = self._es_peru or op.columnas.get('inei') is not None
            self.cmb_col['inei'].setVisible(ver_inei)
            self._lbl_col['inei'].setVisible(ver_inei)
            self.lbl_cab.setText(" · ".join(_corto(h, 18) for h in cab if imp._texto(h)))
        finally:
            self._cargando = False
        self._pintar_aviso()
        self._recalcular()

    def _cambio_cabecera(self, valor: int):
        if not self._cargando:
            self._cargar_hoja(self.op.hoja, fila_cabecera=valor - 1)

    def _llenar_combos(self, cab: list, datos: list[list]):
        from utils.i18n import tr
        ncols = max([len(cab)] + [len(f) for f in datos[:50]] + [0])
        ejemplo = {}
        for i in range(ncols):
            for f in datos[:30]:
                if i < len(f) and imp._texto(f[i]):
                    ejemplo[i] = imp._texto(f[i])
                    break
        for campo, cb in self.cmb_col.items():
            cb.blockSignals(True)
            cb.clear()
            if campo == 'tipo':
                for t, largo in (('MAT', tr("Material")), ('MO', tr("Mano de obra")),
                                 ('EQ', tr("Equipo")), ('SC', tr("Subcontrato"))):
                    cb.addItem(tr("Todas: {t} ({c})").format(t=largo, c=t), f'fijo:{t}')
                cb.insertSeparator(cb.count())
            else:
                cb.addItem(tr("— (ninguna)"), None)
            for i in range(ncols):
                titulo = imp._texto(cab[i]) if i < len(cab) else ''
                txt = f"{_letra(i)} · {_corto(titulo) or tr('(sin título)')}"
                cb.addItem(txt, f'col:{i}' if campo == 'tipo' else i)
                if i in ejemplo:
                    cb.setItemData(cb.count() - 1,
                                   tr("Ej.: {v}").format(v=_corto(ejemplo[i], 60)),
                                   Qt.ToolTipRole)
            # Selección actual.
            if campo == 'tipo':
                dato = (f"col:{self.op.columnas['tipo']}"
                        if self.op.columnas.get('tipo') is not None and not self.op.tipo_fijo
                        else f"fijo:{self.op.tipo_fijo or 'MAT'}")
            else:
                dato = self.op.columnas.get(campo)
            idx = cb.findData(dato)
            cb.setCurrentIndex(idx if idx >= 0 else 0)
            cb.blockSignals(False)

    def _pintar_aviso(self):
        from utils.i18n import tr
        partes = []
        if self.op.motivos.get('mtop'):
            partes.append(tr("Se reconoció la <b>Lista Oficial de Precios del MTOP</b> "
                             "(Uruguay): quedó configurada sola — materiales, cantidad en "
                             "la unidad e IVA. La hoja «NUEVOS MATERIALES» se importa "
                             "eligiéndola arriba."))
        if self.op.motivos.get('formato'):
            partes.append(tr("Se reconoció el formato <b>{nombre}</b> (de un "
                             "complemento).").format(
                                 nombre=escape(self.op.motivos['formato'])))
            if self.op.motivos.get('formato_aviso'):
                partes.append(escape(self.op.motivos['formato_aviso']))
        if self._memoria:
            partes.append(tr("Se usó la asignación de la última importación de este "
                             "formato."))
        if not partes:
            partes.append(tr("Revise qué columna es cada dato. Se asignaron por el "
                             "título; Descripción y Precio son obligatorias."))
        self.lbl_aviso.setText(" ".join(partes))

    # ── Recalcular vista previa ─────────────────────────────────────────
    def _leer_widgets(self):
        op = self.op
        for campo, cb in self.cmb_col.items():
            dato = cb.currentData()
            if campo == 'tipo':
                # «fijo:MAT» = un tipo para todas las filas; «col:3» = columna D.
                clase, _, valor = str(dato or '').partition(':')
                if clase == 'fijo':
                    op.tipo_fijo, op.columnas['tipo'] = valor, None
                elif clase == 'col':
                    op.tipo_fijo, op.columnas['tipo'] = None, int(valor)
            elif campo == 'inei' and cb.isHidden():
                op.columnas['inei'] = None
            else:
                op.columnas[campo] = dato
        op.cantidad_en_unidad = self.chk_cant.isChecked()
        op.quitar_impuesto = self.chk_imp.isChecked()
        op.impuesto_pct = self.spin_pct.value()
        op.omitir_sin_precio = self.chk_omitir.isChecked()
        op.prefijo = self.inp_pref.text().strip()

    def _recalcular(self, *_):
        if self._cargando:
            return
        from utils.i18n import tr
        self._leer_widgets()
        self.spin_pct.setEnabled(self.chk_imp.isChecked())
        motivos = [m for k, m in self.op.motivos.items()
                   if k in ('cantidad', 'impuesto') and isinstance(m, str)]
        self.lbl_motivos.setText(" ".join(motivos))
        self.lbl_motivos.setVisible(bool(motivos))

        falta = imp.faltantes(self.op)
        if falta:
            self._insumos, self._omitidos = [], []
        else:
            self._insumos, self._omitidos = imp.preparar_insumos(self._filas(), self.op)
        self._pintar_tabla()

        if falta:
            nombres = {'descripcion': tr("Descripción"), 'precio': tr("Precio")}
            self.lbl_resumen.setText(
                tr("Falta asignar: {c}.").format(c=", ".join(nombres[c] for c in falta)))
            self.lbl_resumen.setStyleSheet(
                f"color:{C.error}; font-size:{F_PX.body}px; font-weight:{W.semibold};"
                " background:transparent; border:none;")
        else:
            txt = tr("Se importarán <b>{n}</b> insumos.").format(n=len(self._insumos))
            if self._omitidos:
                cuenta: dict[str, int] = {}
                for _, m in self._omitidos:
                    cuenta[m] = cuenta.get(m, 0) + 1
                det = ", ".join(f"{n} {tr(imp.MOTIVOS.get(m, m))}" for m, n in cuenta.items())
                txt += " " + tr("Se omiten {n} filas: {d}.").format(
                    n=len(self._omitidos), d=det)
            self.lbl_resumen.setText(txt)
            self.lbl_resumen.setStyleSheet(
                f"color:{C.text}; font-size:{F_PX.body}px;"
                " background:transparent; border:none;")
        n = len(self._insumos)
        self.b_ok.setEnabled(n > 0)
        self.b_ok.setText(tr("Importar {n} insumos").format(n=n) if n else tr("Importar"))

    def _pintar_tabla(self):
        t = self.tbl
        t.setRowCount(0)
        for ins in self._insumos[:FILAS_PREVIA]:
            r = t.rowCount()
            t.insertRow(r)
            vals = [str(ins.fila), ins.codigo or '—', ins.tipo, ins.descripcion,
                    ins.unidad, f"{ins.precio:,.2f}", ins.original]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c in (0, 2, 4):
                    it.setTextAlignment(Qt.AlignCenter)
                elif c == 5:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 2:
                    it.setForeground(QColor(_TIPO_FG.get(ins.tipo, C.text)))
                if c in (0, 6):
                    it.setForeground(QColor(C.text_secondary))
                if c == 3:
                    it.setToolTip(ins.descripcion)
                t.setItem(r, c, it)

    # ── Importar ────────────────────────────────────────────────────────
    def _aceptar(self):
        from utils.i18n import tr
        self._recalcular()
        if not self._insumos:
            return
        try:
            self.resultado = imp.importar_insumos(self._insumos)
        except Exception as e:
            QMessageBox.critical(self, tr("Error"),
                                 tr("No se pudo importar:\n{e}").format(e=e))
            return
        filas = self._filas()
        cab = filas[self.op.fila_cabecera] if self.op.fila_cabecera < len(filas) else []
        self._qs.setValue(f"formatos/{imp.clave_firma(cab)}", self.op.a_json())
        self._qs.sync()
        self.texto_resumen = imp.resumen(self.resultado, self._omitidos)
        self.accept()
