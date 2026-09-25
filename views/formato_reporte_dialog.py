# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Editor de formato de reportes — empresa, logo, color, página, encabezado y pie.

Persiste en la tabla `configuracion` mediante core.pdf_reports.set_formato().

Es un diálogo apaisado con un menú de secciones a la izquierda y una página
por sección a la derecha, como las «Preferencias» de cualquier programa.
Antes era una sola columna con las cinco secciones apiladas: en una laptop
de 768 px desbordaba la pantalla y el botón «Guardar» quedaba fuera (David
Ramos, 5 sep 2026); el 7 sep pidió justamente «una ventana más horizontal
con ítems laterales para configurar».
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from core import pdf_reports

ORANGE      = "#F37329"
ORANGE_DARK = "#C0621A"
ORANGE_SOFT = "#FEF5EB"
SLATE_700   = "#2E3C52"
SLATE_500   = "#485A6C"
SLATE_300   = "#94A3B8"
SLATE_100   = "#E2E8F0"
SILVER_50   = "#FAFBFC"
SILVER_100  = "#F8F9FA"
WHITE       = "#FFFFFF"

ANCHO_MENU = 176


class FormatoReporteDialog(QDialog):
    """Diálogo para editar la configuración de formato de reportes."""

    # Sección abierta la última vez en esta sesión: si el usuario está
    # ajustando los márgenes y abre el diálogo tres veces, no tiene que
    # volver a buscar la pestaña cada vez.
    _ultima_seccion = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar formato de reportes")
        self.setMinimumWidth(640)
        self.setMinimumHeight(380)
        self._dimensionar()
        self.setStyleSheet(f"QDialog {{ background:{SILVER_100}; }}")

        self._formato = pdf_reports.get_formato()
        self._build_ui()
        self._load_values()

    def _dimensionar(self):
        """780×580 apaisado, pero NUNCA más grande que la pantalla.

        El alto era fijo: en una laptop de 768 px la barra de «Guardar»
        quedaba por debajo del borde y el diálogo no se podía cerrar más que
        con Escape (reporte de David Ramos, 5 sep 2026). Con las secciones
        repartidas a lo ancho, 580 px de alto sobran incluso para la más
        larga; el tope por pantalla queda como red de seguridad.
        """
        ancho, alto = 780, 580
        pantalla = self.screen() or QApplication.primaryScreen()
        if pantalla is not None:
            geo = pantalla.availableGeometry()
            # Margen para la barra de título y la de tareas.
            alto = min(alto, max(380, geo.height() - 80))
            ancho = min(ancho, max(640, geo.width() - 40))
        self.resize(ancho, alto)

    # ─── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{SLATE_700};")
        hdr_l = QHBoxLayout(hdr)
        hdr_l.setContentsMargins(18, 0, 18, 0)
        ico = QLabel("🎨")
        ico.setStyleSheet(
            "color:white; font-size:18px;"
            " background:transparent; border:none;"
        )
        hdr_l.addWidget(ico)
        t = QLabel("Configurar formato de reportes")
        t.setStyleSheet(
            "color:white; font-size:14px; font-weight:700;"
            " background:transparent; border:none;"
        )
        hdr_l.addWidget(t)
        hdr_l.addStretch(1)
        outer.addWidget(hdr)

        # Cuerpo: menú lateral + página de la sección elegida
        medio = QFrame()
        medio.setStyleSheet(f"background:{SILVER_100};")
        medio_l = QHBoxLayout(medio)
        medio_l.setContentsMargins(0, 0, 0, 0)
        medio_l.setSpacing(0)

        self._menu = QListWidget()
        self._menu.setFixedWidth(ANCHO_MENU)
        self._menu.setFocusPolicy(Qt.NoFocus)
        self._menu.setCursor(Qt.PointingHandCursor)
        self._menu.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._menu.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._menu.setStyleSheet(self._menu_ss())
        medio_l.addWidget(self._menu)

        self._paginas = QStackedWidget()
        self._paginas.setStyleSheet(f"background:{SILVER_100};")
        medio_l.addWidget(self._paginas, 1)
        outer.addWidget(medio, stretch=1)

        self._seccion("🏢", "Empresa", self._pagina_empresa())
        self._seccion("🖼️", "Logo", self._pagina_logo())
        self._seccion("🎨", "Color de marca", self._pagina_color())
        self._seccion("🔤", "Colores de títulos", self._pagina_titulos())
        self._seccion("📄", "Página y texto", self._pagina_pagina())
        self._seccion("📝", "Encabezado y pie", self._pagina_encabezado_pie())

        self._menu.currentRowChanged.connect(self._paginas.setCurrentIndex)
        self._menu.currentRowChanged.connect(self._recordar_seccion)
        fila = min(max(0, FormatoReporteDialog._ultima_seccion),
                   self._menu.count() - 1)
        self._menu.setCurrentRow(fila)

        # Botones
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"background:{WHITE}; border-top:1px solid {SLATE_100};")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(18, 8, 18, 8)
        bar_l.setSpacing(10)

        btn_reset = QPushButton("Restaurar valores por defecto")
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.setStyleSheet(self._btn_ss())
        btn_reset.clicked.connect(self._reset_defaults)
        bar_l.addWidget(btn_reset)
        bar_l.addStretch(1)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet(self._btn_ss())
        btn_cancel.clicked.connect(self.reject)
        bar_l.addWidget(btn_cancel)

        btn_ok = QPushButton("Guardar")
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setStyleSheet(self._btn_ss(primary=True))
        btn_ok.clicked.connect(self._save_and_accept)
        bar_l.addWidget(btn_ok)

        outer.addWidget(bar)

    def _seccion(self, icono: str, titulo: str, pagina: QWidget):
        """Un ítem del menú lateral y su página, envuelta en scroll.

        El scroll es por página: ninguna lo necesita en un monitor normal,
        pero si la ventana se achica la barra de botones sigue fija abajo y
        «Guardar» se ve siempre."""
        item = QListWidgetItem(f"{icono}  {titulo}")
        item.setSizeHint(QSize(ANCHO_MENU - 8, 40))
        self._menu.addItem(item)

        scroll = QScrollArea()
        scroll.setWidget(pagina)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background:{SILVER_100}; border:none; }}")
        self._paginas.addWidget(scroll)

    @staticmethod
    def _recordar_seccion(fila: int):
        FormatoReporteDialog._ultima_seccion = int(fila)

    def _pagina_base(self, titulo: str, subtitulo: str):
        """Lienzo de una sección: título, una línea que dice para qué sirve,
        y el layout donde va el contenido."""
        pagina = QFrame()
        pagina.setStyleSheet(f"background:{SILVER_100};")
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(12)
        t = QLabel(titulo)
        t.setStyleSheet(f"color:{SLATE_700}; font-size:15px; font-weight:700;")
        lay.addWidget(t)
        sub = QLabel(subtitulo)
        sub.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SLATE_100}; background:{SLATE_100}; max-height:1px;")
        lay.addWidget(sep)
        return pagina, lay

    # ── Sección: Empresa ──
    def _pagina_empresa(self) -> QWidget:
        pagina, lay = self._pagina_base(
            "Empresa",
            "Razón social y datos de contacto. Van en el encabezado de cada "
            "página y en la portada; son los mismos de Configuración → Datos "
            "de empresa.")
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.inp_empresa = QLineEdit()
        self.inp_empresa.setPlaceholderText("ingePresupuestos")
        self.inp_empresa.setStyleSheet(self._le_ss())
        form.addRow("Nombre de empresa:", self.inp_empresa)

        self.inp_subtitulo = QLineEdit()
        self.inp_subtitulo.setPlaceholderText("Sistema de Presupuestos de Obra Pública")
        self.inp_subtitulo.setStyleSheet(self._le_ss())
        form.addRow("Subtítulo / lema:", self.inp_subtitulo)

        # Datos fiscales — van al pie de la portada del PDF.
        self.inp_ruc = QLineEdit()
        from core.paises import etiqueta_tributaria
        self.inp_ruc.setPlaceholderText(etiqueta_tributaria())
        self.inp_ruc.setStyleSheet(self._le_ss())
        form.addRow(f"{etiqueta_tributaria()}:", self.inp_ruc)

        self.inp_direccion = QLineEdit()
        self.inp_direccion.setPlaceholderText("Dirección")
        self.inp_direccion.setStyleSheet(self._le_ss())
        form.addRow("Dirección:", self.inp_direccion)

        self.inp_telefono = QLineEdit()
        self.inp_telefono.setPlaceholderText("Teléfono / celular")
        self.inp_telefono.setStyleSheet(self._le_ss())
        form.addRow("Teléfono:", self.inp_telefono)

        lay.addLayout(form)
        lay.addStretch(1)
        return pagina

    # ── Sección: Logo ──
    def _pagina_logo(self) -> QWidget:
        pagina, lay = self._pagina_base(
            "Logo",
            "Imagen que va a la izquierda del encabezado, junto a la razón social.")
        logo_row = QHBoxLayout()
        self._lbl_logo = QLabel()
        self._lbl_logo.setFixedSize(180, 60)
        self._lbl_logo.setAlignment(Qt.AlignCenter)
        self._lbl_logo.setStyleSheet(
            f"background:{WHITE}; border:1px dashed {SLATE_100};"
            f" border-radius:6px; color:{SLATE_300}; font-size:11px;"
        )
        logo_row.addWidget(self._lbl_logo)

        logo_btns = QVBoxLayout()
        logo_btns.setSpacing(6)
        btn_logo = QPushButton("Elegir imagen…")
        btn_logo.setCursor(Qt.PointingHandCursor)
        btn_logo.setStyleSheet(self._btn_ss())
        btn_logo.clicked.connect(self._choose_logo)
        logo_btns.addWidget(btn_logo)

        self.btn_clear_logo = QPushButton("Quitar logo")
        self.btn_clear_logo.setCursor(Qt.PointingHandCursor)
        self.btn_clear_logo.setStyleSheet(self._btn_ss(danger=True))
        self.btn_clear_logo.clicked.connect(self._clear_logo)
        logo_btns.addWidget(self.btn_clear_logo)
        logo_btns.addStretch(1)
        logo_row.addLayout(logo_btns)
        logo_row.addStretch(1)
        lay.addLayout(logo_row)

        # Tamaño del logo — el encabezado ya escala solo con el papel
        # (A3/A1/A0); esto es el ajuste fino sobre ese tamaño base.
        esc_row = QHBoxLayout()
        esc_row.setSpacing(10)
        esc_row.addWidget(QLabel("Tamaño del logo:"))
        self.sld_logo = QSlider(Qt.Horizontal)
        self.sld_logo.setRange(50, 200)
        self.sld_logo.setSingleStep(5)
        self.sld_logo.setPageStep(10)
        self.sld_logo.setFixedWidth(180)
        self.sld_logo.valueChanged.connect(self._on_logo_escala)
        esc_row.addWidget(self.sld_logo)
        self.lbl_logo_esc = QLabel("100 %")
        self.lbl_logo_esc.setFixedWidth(48)
        esc_row.addWidget(self.lbl_logo_esc)
        self.btn_logo_reset = QToolButton()
        self.btn_logo_reset.setText("Restablecer")
        self.btn_logo_reset.setCursor(Qt.PointingHandCursor)
        self.btn_logo_reset.clicked.connect(lambda: self.sld_logo.setValue(100))
        esc_row.addWidget(self.btn_logo_reset)
        esc_row.addStretch(1)
        lay.addLayout(esc_row)

        lay.addWidget(self._hint(
            "Recomendado: PNG con fondo transparente, máx. ~240×60 px. "
            "En A3/A1/A0 el encabezado se agranda solo — el tamaño del logo "
            "es solo para ajustarlo a gusto."
        ))
        lay.addStretch(1)
        return pagina

    # ── Sección: Color de marca ──
    def _pagina_color(self) -> QWidget:
        pagina, lay = self._pagina_base(
            "Color de marca",
            "Color principal usado en bandas, títulos y barras del Gantt. "
            "El tono oscuro se calcula solo.")
        col_row = QHBoxLayout()
        col_row.setSpacing(10)
        self._color_swatch = QFrame()
        self._color_swatch.setFixedSize(60, 28)
        self._color_swatch.setStyleSheet(
            f"background:{ORANGE}; border:1px solid {SLATE_100}; border-radius:6px;"
        )
        col_row.addWidget(self._color_swatch)

        self.inp_color = QLineEdit()
        self.inp_color.setPlaceholderText("#F37329")
        self.inp_color.setMaxLength(7)
        self.inp_color.setStyleSheet(self._le_ss())
        self.inp_color.setFixedWidth(120)
        self.inp_color.textChanged.connect(self._on_color_text)
        col_row.addWidget(self.inp_color)

        btn_pick = QPushButton("Elegir…")
        btn_pick.setCursor(Qt.PointingHandCursor)
        btn_pick.setStyleSheet(self._btn_ss())
        btn_pick.clicked.connect(self._pick_color)
        col_row.addWidget(btn_pick)
        col_row.addStretch(1)
        lay.addLayout(col_row)
        lay.addWidget(self._hint(
            "Escribe un color HEX (por ejemplo #F37329) o elígelo de la paleta."))
        lay.addStretch(1)
        return pagina

    # ── Sección: Colores de títulos ──
    # Sub-presupuesto + los nueve niveles de título (`pdf_reports.N_NIVELES`).
    NIVEL_EJEMPLO = ("SUB-PRESUPUESTO: ESTRUCTURAS",
                     "01  OBRAS PROVISIONALES", "01.01  Trabajos preliminares",
                     "01.01.01  Movilización", "01.01.01.01  Equipos",
                     "01.01.01.01.01  Detalle", "01.01.01.01.01.01  Nivel 6",
                     "01.01.01.01.01.01.01  Nivel 7", "…01.01  Nivel 8",
                     "…01.01.01  Nivel 9")
    NIVEL_ROTULO = ("Sub-presupuesto:",) + tuple(
        f"Nivel {n}:" for n in range(1, pdf_reports.N_NIVELES + 1))

    def _pagina_titulos(self) -> QWidget:
        """Esquemas de colores para los nueve niveles de título de los
        reportes. Los de fábrica no se editan: tocar un color crea (o
        actualiza) el esquema «Personalizado»; «Guardar como…» lo guarda
        con nombre propio. Solo afecta al PDF y al Excel; en pantalla el
        árbol sigue con los colores del tema (pedido de David Ramos, 5 sep
        2026; diseño de Marco, 8 sep: «varios estilos personalizables y
        guardables»)."""
        pagina, lay = self._pagina_base(
            "Colores de títulos",
            "El color de la cabecera de sub-presupuesto y de cada nivel de título en los reportes PDF y Excel. "
            "Elige un esquema o arma el tuyo y guárdalo con nombre.")

        fila = QHBoxLayout()
        fila.setSpacing(10)
        fila.addWidget(QLabel("Esquema:"))
        self.cmb_esquema = QComboBox()
        self.cmb_esquema.setCursor(Qt.PointingHandCursor)
        self.cmb_esquema.setMinimumWidth(240)
        self.cmb_esquema.currentIndexChanged.connect(self._on_esquema_elegido)
        fila.addWidget(self.cmb_esquema)
        self.btn_esq_guardar = QPushButton("Guardar como…")
        self.btn_esq_guardar.setCursor(Qt.PointingHandCursor)
        self.btn_esq_guardar.setStyleSheet(self._btn_ss())
        self.btn_esq_guardar.clicked.connect(self._esquema_guardar_como)
        fila.addWidget(self.btn_esq_guardar)
        self.btn_esq_eliminar = QPushButton("Eliminar")
        self.btn_esq_eliminar.setCursor(Qt.PointingHandCursor)
        self.btn_esq_eliminar.setStyleSheet(self._btn_ss(danger=True))
        self.btn_esq_eliminar.clicked.connect(self._esquema_eliminar)
        fila.addWidget(self.btn_esq_eliminar)
        fila.addStretch(1)
        lay.addLayout(fila)

        cuerpo = QVBoxLayout()
        cuerpo.setSpacing(10)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self._sw_nivel, self._inp_nivel = [], []
        # 0 = sub-presupuesto, 1..N = niveles. Diez filas no caben en la
        # altura del diálogo: van en dos columnas de cinco.
        n_filas = (len(self.NIVEL_ROTULO) + 1) // 2
        for i in range(len(self.NIVEL_ROTULO)):
            fila, col0 = i % n_filas, (i // n_filas) * 5
            grid.addWidget(QLabel(self.NIVEL_ROTULO[i]), fila, col0)
            sw = QFrame()
            sw.setFixedSize(28, 22)
            grid.addWidget(sw, fila, col0 + 1)
            inp = QLineEdit()
            inp.setMaxLength(7)
            inp.setFixedWidth(76)
            inp.setStyleSheet(self._le_ss())
            inp.editingFinished.connect(lambda i=i: self._on_nivel_texto(i))
            grid.addWidget(inp, fila, col0 + 2)
            b = QPushButton("Elegir…")
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(self._btn_ss())
            b.clicked.connect(lambda _=False, i=i: self._on_nivel_elegir(i))
            grid.addWidget(b, fila, col0 + 3)
            if col0 == 0:
                grid.setColumnMinimumWidth(4, 14)   # aire entre columnas
            self._sw_nivel.append(sw)
            self._inp_nivel.append(inp)
        cuerpo.addLayout(grid)

        # Vista previa: cómo se ven los niveles con el esquema. Va DEBAJO de
        # la grilla (con nueve niveles, a la derecha no cabía en 780 px).
        self.lbl_previa = QLabel()
        self.lbl_previa.setTextFormat(Qt.RichText)
        self.lbl_previa.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.lbl_previa.setStyleSheet(
            f"background:{WHITE}; border:1px solid {SLATE_100}; border-radius:6px;"
            " padding:6px 12px; font-size:10px;")
        cuerpo.addWidget(self.lbl_previa)
        lay.addLayout(cuerpo)

        lay.addWidget(self._hint(
            "«Clásico» son los colores de siempre. Los esquemas de fábrica no "
            "se modifican: al cambiar un color se crea el esquema "
            "«Personalizado», que puedes guardar con otro nombre. En pantalla, "
            "el árbol del presupuesto y el Gantt conservan sus colores; el "
            "esquema aplica al PDF y al Excel. Word no usa colores de nivel."
        ))
        lay.addStretch(1)
        return pagina

    # ── Lógica de esquemas ──
    # Estado de trabajo: `self._esquemas` (todos, con 'fabrica') y
    # `self._esq_activo` (clave). Se vuelca a las dos claves al Guardar.

    def _esquemas_cargar(self):
        self._esquemas = pdf_reports.esquemas_titulos(self._formato)
        clave = str(self._formato.get('rep_esquema_titulos') or pdf_reports.ESQUEMA_DEFECTO)
        self._esq_activo = clave if clave in self._esquemas else pdf_reports.ESQUEMA_DEFECTO
        self._esquemas_refrescar_combo()

    def _esquemas_refrescar_combo(self):
        self.cmb_esquema.blockSignals(True)
        self.cmb_esquema.clear()
        for k, v in self._esquemas.items():
            self.cmb_esquema.addItem(
                v['nombre'] if v['fabrica'] else f"{v['nombre']}  (propio)", k)
        self.cmb_esquema.setCurrentIndex(max(0, self.cmb_esquema.findData(self._esq_activo)))
        self.cmb_esquema.blockSignals(False)
        self._esquemas_pintar()

    def _esquemas_pintar(self):
        esq = self._esquemas[self._esq_activo]
        for i, c in enumerate([esq['sub']] + list(esq['colores'])):
            self._sw_nivel[i].setStyleSheet(
                f"background:{c}; border:1px solid {SLATE_100}; border-radius:4px;")
            self._inp_nivel[i].blockSignals(True)
            self._inp_nivel[i].setText(c.upper())
            self._inp_nivel[i].blockSignals(False)
        tam = (11, 12, 11, 10, 10, 10, 10, 10, 10, 10)
        cols = [esq['sub']] + list(esq['colores'])
        lineas = []
        for i, txt in enumerate(self.NIVEL_EJEMPLO):
            estilo = "font-style:italic;" if i >= 5 else ""     # como el PDF
            sub = "text-decoration:underline;" if i in (0, 1) else ""
            lineas.append(
                f'<div style="color:{cols[i]};font-weight:700;'
                f'font-size:{tam[i]}px;margin-left:{max(0, i - 1) * 8}px;'
                f'margin-bottom:{4 if i == 0 else 0}px;{estilo}{sub}">{txt}</div>')
        self.lbl_previa.setText("".join(lineas))
        self.btn_esq_eliminar.setEnabled(not esq['fabrica'])

    def _on_esquema_elegido(self, idx: int):
        clave = self.cmb_esquema.itemData(idx)
        if clave in self._esquemas:
            self._esq_activo = clave
            self._esquemas_pintar()

    def _esquema_editable(self) -> dict:
        """El esquema donde cae la edición: el activo si es propio; si es de
        fábrica, «Personalizado» (creado a partir de él)."""
        esq = self._esquemas[self._esq_activo]
        if not esq['fabrica']:
            return esq
        self._esquemas['personalizado'] = {
            'nombre': 'Personalizado', 'colores': list(esq['colores']),
            'sub': esq['sub'], 'fabrica': False}
        self._esq_activo = 'personalizado'
        self._esquemas_refrescar_combo()
        return self._esquemas['personalizado']

    def _poner_color_nivel(self, i: int, color: str):
        c = QColor(color)
        if not c.isValid():
            self._esquemas_pintar()      # revierte el texto inválido
            return
        esq = self._esquema_editable()
        if i == 0:
            esq['sub'] = c.name().upper()
        else:
            esq['colores'][i - 1] = c.name().upper()
        self._esquemas_pintar()

    def _on_nivel_texto(self, i: int):
        self._poner_color_nivel(i, self._inp_nivel[i].text().strip())

    def _on_nivel_elegir(self, i: int):
        esq = self._esquemas[self._esq_activo]
        actual = QColor(esq['sub'] if i == 0 else esq['colores'][i - 1])
        c = QColorDialog.getColor(actual, self, "Color de " + self.NIVEL_ROTULO[i].rstrip(':').lower())
        if c.isValid():
            self._poner_color_nivel(i, c.name())

    def _esquema_guardar_como(self):
        from PySide6.QtWidgets import QInputDialog
        nombre, ok = QInputDialog.getText(
            self, "Guardar esquema", "Nombre del esquema:",
            text=self._esquemas[self._esq_activo]['nombre'] if not
            self._esquemas[self._esq_activo]['fabrica'] else "")
        nombre = (nombre or '').strip()
        if not ok or not nombre:
            return
        clave = ''.join(ch if ch.isalnum() else '_' for ch in nombre.lower()).strip('_') or 'esquema'
        if clave in pdf_reports.ESQUEMAS_FABRICA:
            clave = f"{clave}_propio"
        self._esquemas[clave] = {
            'nombre': nombre,
            'colores': list(self._esquemas[self._esq_activo]['colores']),
            'sub': self._esquemas[self._esq_activo]['sub'],
            'fabrica': False}
        self._esq_activo = clave
        self._esquemas_refrescar_combo()

    def _esquema_eliminar(self):
        esq = self._esquemas[self._esq_activo]
        if esq['fabrica']:
            return
        if QMessageBox.question(
                self, "Eliminar esquema",
                f"¿Eliminar el esquema «{esq['nombre']}»?") != QMessageBox.Yes:
            return
        del self._esquemas[self._esq_activo]
        self._esq_activo = pdf_reports.ESQUEMA_DEFECTO
        self._esquemas_refrescar_combo()

    def _esquemas_a_formato(self):
        propios = {k: {'nombre': v['nombre'], 'colores': v['colores'], 'sub': v['sub']}
                   for k, v in self._esquemas.items() if not v['fabrica']}
        self._formato['rep_esquema_titulos'] = self._esq_activo
        self._formato['rep_esquemas_titulos'] = json.dumps(propios, ensure_ascii=False) if propios else ''

    # ── Sección: Página y texto ──
    def _pagina_pagina(self) -> QWidget:
        pagina, lay = self._pagina_base(
            "Página y texto",
            "Cuánto texto entra en cada hoja del PDF: el tamaño del cuerpo y "
            "los márgenes del papel.")

        # Tamaño del texto del cuerpo — pasos fijos
        # (pdf_reports.ESCALAS_TEXTO), no un slider: cada paso está verificado
        # en los 13 tipos de reporte.
        lay.addWidget(self._section_title("Tamaño del texto"))
        txt_row = QHBoxLayout()
        txt_row.setSpacing(10)
        txt_row.addWidget(QLabel("Tamaño del texto:"))
        self.cmb_escala_texto = QComboBox()
        self.cmb_escala_texto.setCursor(Qt.PointingHandCursor)
        self.cmb_escala_texto.setFixedWidth(220)
        _rotulos = {100: "Normal", 90: "Compacto", 80: "Muy compacto"}
        for pct in pdf_reports.ESCALAS_TEXTO:
            self.cmb_escala_texto.addItem(
                f"{_rotulos.get(pct, 'Escala')} ({pct} %)", pct)
        txt_row.addWidget(self.cmb_escala_texto)
        txt_row.addStretch(1)
        lay.addLayout(txt_row)
        lay.addWidget(self._hint(
            "Reduce el texto del cuerpo para que entren más filas por página "
            "y el reporte ocupe menos hojas. Encabezado, pie y portada no "
            "cambian. Solo afecta al PDF: en Word y Excel el tamaño se cambia "
            "en el propio programa."
        ))

        # Márgenes — en milímetros, dispuestos como en la hoja: arriba,
        # izquierda/derecha, abajo.
        lay.addWidget(self._section_title("Márgenes del papel"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        self.spn_margen_sup = self._spin_margen()
        self.spn_margen_inf = self._spin_margen()
        self.spn_margen_izq = self._spin_margen()
        self.spn_margen_der = self._spin_margen()
        grid.addWidget(self._etiqueta_margen("Superior"), 0, 1, Qt.AlignHCenter)
        grid.addWidget(self.spn_margen_sup, 1, 1, Qt.AlignHCenter)
        grid.addWidget(self._etiqueta_margen("Izquierdo"), 2, 0, Qt.AlignHCenter)
        grid.addWidget(self.spn_margen_izq, 3, 0, Qt.AlignHCenter)
        hoja = QLabel("cuerpo del\nreporte")
        hoja.setAlignment(Qt.AlignCenter)
        hoja.setFixedSize(96, 56)
        hoja.setStyleSheet(
            f"background:{WHITE}; border:1px dashed {SLATE_300};"
            f" border-radius:4px; color:{SLATE_300}; font-size:10px;"
            f" font-style:italic;"
        )
        grid.addWidget(hoja, 2, 1, 2, 1, Qt.AlignCenter)
        grid.addWidget(self._etiqueta_margen("Derecho"), 2, 2, Qt.AlignHCenter)
        grid.addWidget(self.spn_margen_der, 3, 2, Qt.AlignHCenter)
        grid.addWidget(self._etiqueta_margen("Inferior"), 4, 1, Qt.AlignHCenter)
        grid.addWidget(self.spn_margen_inf, 5, 1, Qt.AlignHCenter)
        grid_wrap = QHBoxLayout()
        grid_wrap.addLayout(grid)
        self.btn_margenes_reset = QToolButton()
        self.btn_margenes_reset.setText("Restablecer márgenes")
        self.btn_margenes_reset.setCursor(Qt.PointingHandCursor)
        self.btn_margenes_reset.clicked.connect(self._reset_margenes)
        grid_wrap.addSpacing(18)
        grid_wrap.addWidget(self.btn_margenes_reset, 0, Qt.AlignVCenter)
        grid_wrap.addStretch(1)
        lay.addLayout(grid_wrap)
        for spn in (self.spn_margen_sup, self.spn_margen_inf,
                    self.spn_margen_izq, self.spn_margen_der):
            spn.valueChanged.connect(self._on_margen)
        _d = {k: pdf_reports.FORMATO_CLAVES[k] for k in pdf_reports.MARGENES_CLAVES}
        lay.addWidget(self._hint(
            f"En milímetros, de {pdf_reports.MARGEN_MIN_MM} a "
            f"{pdf_reports.MARGEN_MAX_MM}. Los de siempre son "
            f"{_d['rep_margen_sup']} arriba, {_d['rep_margen_inf']} abajo y "
            f"{_d['rep_margen_izq']} a cada lado. El superior mueve el "
            "encabezado junto con el cuerpo y el inferior mueve el pie; la "
            "portada no cambia. Solo afecta al PDF de los reportes — el "
            "cronograma Gantt tiene sus propios márgenes."
        ))
        lay.addStretch(1)
        return pagina

    def _spin_margen(self) -> QSpinBox:
        s = QSpinBox()
        s.setRange(pdf_reports.MARGEN_MIN_MM, pdf_reports.MARGEN_MAX_MM)
        s.setSuffix(" mm")
        s.setFixedWidth(92)
        s.setAlignment(Qt.AlignRight)
        s.setStyleSheet(
            f"QSpinBox {{ background:{WHITE}; border:1px solid {SLATE_100};"
            f" border-radius:6px; padding:4px 6px; font-size:12px; }}"
            f"QSpinBox:focus {{ border-color:{ORANGE}; }}"
        )
        return s

    @staticmethod
    def _etiqueta_margen(texto: str) -> QLabel:
        l = QLabel(texto)
        l.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
        return l

    # ── Sección: Encabezado y pie ──
    def _pagina_encabezado_pie(self) -> QWidget:
        pagina, lay = self._pagina_base(
            "Encabezado y pie",
            "Qué se imprime arriba y abajo de cada página. La portada no lleva "
            "ninguno de los dos.")

        lay.addWidget(self._section_title("Encabezado de las páginas"))
        self.chk_encabezado = QCheckBox(
            "Imprimir el encabezado en cada página")
        self.chk_encabezado.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.chk_encabezado)
        lay.addWidget(self._hint(
            "Es la franja con el logo, la razón social y el título del reporte. "
            "Al quitarla el cuerpo sube y entran más filas por hoja."
        ))

        lay.addWidget(self._section_title("Pie de página"))
        self.chk_pie = QCheckBox("Imprimir el pie en cada página")
        self.chk_pie.setCursor(Qt.PointingHandCursor)
        self.chk_pie.toggled.connect(self._on_pie_toggled)
        lay.addWidget(self.chk_pie)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.inp_pie_izq, self.chk_pie_izq = self._fila_pie(
            form, "Texto izquierdo:", "Por defecto: Cliente del proyecto")
        self.inp_pie_cen, self.chk_pie_cen = self._fila_pie(
            form, "Texto central:", "Por defecto: fecha de generación")
        self.inp_pie_der, self.chk_pie_der = self._fila_pie(
            form, "Texto derecho:", "Por defecto: Página X de N")
        lay.addLayout(form)
        self.chk_pie_linea = QCheckBox("Imprimir la línea que separa el pie del cuerpo")
        self.chk_pie_linea.setCursor(Qt.PointingHandCursor)
        self.chk_pie_linea.setToolTip(
            "Quítala si necesitas ese espacio limpio para sellos y firmas; "
            "los textos del pie se imprimen igual.")
        lay.addWidget(self.chk_pie_linea)
        lay.addWidget(self._hint(
            "Dejar el texto en blanco usa el valor por defecto. Marca «Vacío» "
            "para que ese hueco no se imprima — por ejemplo, vacío a la "
            "izquierda y al centro deja solo el número de página. Con el pie "
            "apagado no se imprime nada abajo, ni la línea."
        ))
        lay.addWidget(self._section_title("Diagrama de Gantt"))
        self.chk_gantt_leyenda = QCheckBox(
            "Imprimir la leyenda del Gantt al pie (Tarea, Crítica, Hito, Dependencia, Hoy, Fin plazo)")
        self.chk_gantt_leyenda.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.chk_gantt_leyenda)
        lay.addWidget(self._hint(
            "El encabezado y el pie del Gantt siguen las casillas de arriba, "
            "como el resto de reportes. La leyenda va aparte: quítala si ya "
            "conoces los colores y quieres ganar espacio."
        ))
        lay.addStretch(1)
        return pagina

    def _on_pie_toggled(self, on: bool):
        for w in (self.inp_pie_izq, self.chk_pie_izq, self.inp_pie_cen,
                  self.chk_pie_cen, self.inp_pie_der, self.chk_pie_der,
                  self.chk_pie_linea):
            w.setEnabled(on)
        if on:
            for casilla, campo in ((self.chk_pie_izq, self.inp_pie_izq),
                                   (self.chk_pie_cen, self.inp_pie_cen),
                                   (self.chk_pie_der, self.inp_pie_der)):
                campo.setEnabled(not casilla.isChecked())

    def _fila_pie(self, form, etiqueta: str, placeholder: str):
        """Una ranura del pie: el texto + la casilla «Vacío» que la anula.

        Sin la casilla, un texto en blanco significaba «usa el valor por
        defecto» y no había manera de pedir que el hueco quedara vacío de
        verdad (reporte de David Ramos, 5 sep 2026).
        """
        fila = QWidget()
        h = QHBoxLayout(fila)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        campo = QLineEdit()
        campo.setPlaceholderText(placeholder)
        campo.setStyleSheet(self._le_ss())
        h.addWidget(campo, 1)
        casilla = QCheckBox("Vacío")
        casilla.setCursor(Qt.PointingHandCursor)
        casilla.setToolTip("No imprimir nada en esta parte del pie.")
        casilla.toggled.connect(lambda on, c=campo: c.setEnabled(not on))
        h.addWidget(casilla)
        form.addRow(etiqueta, fila)
        return campo, casilla

    # ─── Estilos ─────────────────────────────────────────────────────────────

    def _section_title(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{SLATE_700}; font-size:11px; font-weight:700;"
            f" letter-spacing:1px; text-transform:uppercase;"
            f" padding:4px 0; border-bottom:1px solid {SLATE_100};"
        )
        return l

    def _hint(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(f"color:{SLATE_300}; font-size:10px; font-style:italic;")
        l.setWordWrap(True)
        return l

    def _le_ss(self) -> str:
        return (
            f"QLineEdit {{ background:{WHITE}; border:1px solid {SLATE_100};"
            f" border-radius:6px; padding:6px 8px; font-size:12px; }}"
            f"QLineEdit:focus {{ border-color:{ORANGE}; }}"
        )

    def _menu_ss(self) -> str:
        return (
            f"QListWidget {{ background:{SILVER_50}; border:none;"
            f" border-right:1px solid {SLATE_100}; outline:none;"
            f" padding:8px 0; font-size:12px; color:{SLATE_700}; }}"
            f"QListWidget::item {{ padding:0 14px; border-left:3px solid transparent; }}"
            f"QListWidget::item:hover {{ background:{SILVER_100}; }}"
            f"QListWidget::item:selected {{ background:{WHITE}; color:{ORANGE_DARK};"
            f" font-weight:700; border-left:3px solid {ORANGE}; }}"
        )

    def _btn_ss(self, primary: bool = False, danger: bool = False) -> str:
        if primary:
            from utils.theme import BTN_PRIMARY_SS
            return BTN_PRIMARY_SS
        if danger:
            return (
                f"QPushButton {{ background:{WHITE}; color:#C6262E;"
                f" border:1px solid {SLATE_100}; border-radius:6px;"
                f" padding:6px 12px; font-size:11px; }}"
                f"QPushButton:hover {{ background:#FFEDED; border-color:#C6262E; }}"
            )
        return (
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f" border:1px solid {SLATE_100}; border-radius:6px;"
            f" padding:6px 12px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{SILVER_100}; border-color:{ORANGE};"
            f" color:{ORANGE_DARK}; }}"
        )

    # ─── Carga de valores ────────────────────────────────────────────────────

    def _load_values(self):
        f = self._formato
        self.inp_empresa.setText(f.get('rep_empresa_nombre') or '')
        self.inp_subtitulo.setText(f.get('rep_empresa_subtitulo') or '')
        self.inp_color.setText(f.get('rep_color_marca') or '#F37329')
        self.inp_pie_izq.setText(f.get('rep_pie_izquierdo') or '')
        self.inp_pie_cen.setText(f.get('rep_pie_central') or '')
        self.inp_pie_der.setText(f.get('rep_pie_derecho') or '')
        self.chk_encabezado.setChecked(
            str(f.get('rep_encabezado_oculto') or '0') != '1')
        self.chk_pie.setChecked(str(f.get('rep_pie_oculto') or '0') != '1')
        self.chk_pie_linea.setChecked(
            str(f.get('rep_pie_linea_oculta') or '0') != '1')
        self.chk_gantt_leyenda.setChecked(
            str(f.get('rep_gantt_leyenda_oculta') or '0') != '1')
        self._on_pie_toggled(self.chk_pie.isChecked())
        for casilla, clave in ((self.chk_pie_izq, 'rep_pie_izq_oculto'),
                               (self.chk_pie_cen, 'rep_pie_cen_oculto'),
                               (self.chk_pie_der, 'rep_pie_der_oculto')):
            casilla.setChecked(str(f.get(clave) or '0') == '1')
        self.inp_ruc.setText(f.get('rep_empresa_ruc') or '')
        self.inp_direccion.setText(f.get('rep_empresa_direccion') or '')
        self.inp_telefono.setText(f.get('rep_empresa_telefono') or '')
        self._update_color_swatch(self.inp_color.text())
        try:
            _esc = int(float(str(f.get('rep_logo_escala') or 100)))
        except (TypeError, ValueError):
            _esc = 100
        self.sld_logo.setValue(max(50, min(200, _esc)))
        self._on_logo_escala(self.sld_logo.value())
        _pct = int(round(pdf_reports.texto_escala(f) * 100))
        self.cmb_escala_texto.setCurrentIndex(
            max(0, self.cmb_escala_texto.findData(_pct)))
        self._esquemas_cargar()
        mm = pdf_reports.margenes_mm(f)
        self.spn_margen_sup.setValue(int(round(mm['sup'])))
        self.spn_margen_inf.setValue(int(round(mm['inf'])))
        self.spn_margen_izq.setValue(int(round(mm['izq'])))
        self.spn_margen_der.setValue(int(round(mm['der'])))
        self._on_margen()
        self._update_logo_preview(f.get('rep_logo_b64') or '')

    # ─── Logo ────────────────────────────────────────────────────────────────

    def _choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar logo",
            os.path.expanduser("~"),
            "Imágenes (*.png *.jpg *.jpeg *.svg *.bmp)"
        )
        if not path:
            return
        try:
            img = QImage(path)
            if img.isNull():
                raise ValueError("No se pudo leer la imagen")
            # Escalar a tamaño razonable (max 480 ancho)
            if img.width() > 480:
                img = img.scaledToWidth(480, Qt.SmoothTransformation)
            ba = QByteArray()
            from PySide6.QtCore import QBuffer, QIODevice
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            b64 = bytes(ba.toBase64()).decode('ascii')
            self._formato['rep_logo_b64'] = b64
            self._update_logo_preview(b64)
        except Exception as e:
            QMessageBox.critical(self, "Logo", f"No se pudo cargar la imagen:\n{e}")

    def _on_logo_escala(self, val: int):
        self.lbl_logo_esc.setText(f"{int(val)} %")
        self.btn_logo_reset.setEnabled(int(val) != 100)

    def _clear_logo(self):
        self._formato['rep_logo_b64'] = ''
        self._update_logo_preview('')

    def _update_logo_preview(self, b64: str):
        if not b64:
            self._lbl_logo.setPixmap(QPixmap())
            self._lbl_logo.setText("Sin logo")
            self.btn_clear_logo.setEnabled(False)
            return
        try:
            ba = QByteArray.fromBase64(b64.encode('ascii'))
            img = QImage()
            if img.loadFromData(ba):
                pm = QPixmap.fromImage(img.scaled(
                    178, 58, Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
                self._lbl_logo.setPixmap(pm)
                self._lbl_logo.setText("")
                self.btn_clear_logo.setEnabled(True)
                return
        except Exception:
            pass
        self._lbl_logo.setPixmap(QPixmap())
        self._lbl_logo.setText("Logo inválido")

    # ─── Márgenes ────────────────────────────────────────────────────────────

    def _margenes_actuales(self) -> dict:
        return {
            'rep_margen_sup': str(self.spn_margen_sup.value()),
            'rep_margen_inf': str(self.spn_margen_inf.value()),
            'rep_margen_izq': str(self.spn_margen_izq.value()),
            'rep_margen_der': str(self.spn_margen_der.value()),
        }

    def _on_margen(self, *_):
        """«Restablecer márgenes» solo se enciende cuando hay algo que restablecer."""
        por_defecto = all(
            self._margenes_actuales()[k] == pdf_reports.FORMATO_CLAVES[k]
            for k in pdf_reports.MARGENES_CLAVES)
        self.btn_margenes_reset.setEnabled(not por_defecto)

    def _reset_margenes(self):
        for spn, clave in ((self.spn_margen_sup, 'rep_margen_sup'),
                           (self.spn_margen_inf, 'rep_margen_inf'),
                           (self.spn_margen_izq, 'rep_margen_izq'),
                           (self.spn_margen_der, 'rep_margen_der')):
            spn.setValue(int(pdf_reports.FORMATO_CLAVES[clave]))

    # ─── Color ───────────────────────────────────────────────────────────────

    def _pick_color(self):
        actual = QColor(self.inp_color.text() or ORANGE)
        c = QColorDialog.getColor(actual, self, "Color de marca")
        if c.isValid():
            self.inp_color.setText(c.name().upper())

    def _on_color_text(self, txt: str):
        self._update_color_swatch(txt)

    def _update_color_swatch(self, txt: str):
        c = QColor(txt or ORANGE)
        if not c.isValid():
            c = QColor(ORANGE)
        self._color_swatch.setStyleSheet(
            f"background:{c.name()}; border:1px solid {SLATE_100}; border-radius:6px;"
        )

    # ─── Restaurar / Guardar ─────────────────────────────────────────────────

    def _reset_defaults(self):
        for k, default in pdf_reports.FORMATO_CLAVES.items():
            self._formato[k] = default
        self._load_values()

    def _save_and_accept(self):
        # Recoger valores actuales
        color = (self.inp_color.text() or '').strip().upper()
        if color and not (color.startswith('#') and len(color) == 7):
            self._menu.setCurrentRow(2)
            QMessageBox.warning(self, "Color",
                                "Ingresa un color HEX válido (ej. #F37329).")
            return

        self._formato['rep_empresa_nombre']    = self.inp_empresa.text().strip()
        self._formato['rep_empresa_subtitulo'] = self.inp_subtitulo.text().strip()
        self._formato['rep_color_marca']       = color or '#F37329'
        self._formato['rep_color_marca_dk']    = self._darken(color or '#F37329')
        self._formato['rep_pie_izquierdo']     = self.inp_pie_izq.text().strip()
        self._formato['rep_pie_central']       = self.inp_pie_cen.text().strip()
        self._formato['rep_pie_derecho']       = self.inp_pie_der.text().strip()
        self._formato['rep_encabezado_oculto'] = '0' if self.chk_encabezado.isChecked() else '1'
        self._formato['rep_pie_oculto']        = '0' if self.chk_pie.isChecked() else '1'
        self._formato['rep_pie_linea_oculta']  = '0' if self.chk_pie_linea.isChecked() else '1'
        self._formato['rep_gantt_leyenda_oculta'] = '0' if self.chk_gantt_leyenda.isChecked() else '1'
        self._formato['rep_pie_izq_oculto']    = '1' if self.chk_pie_izq.isChecked() else '0'
        self._formato['rep_pie_cen_oculto']    = '1' if self.chk_pie_cen.isChecked() else '0'
        self._formato['rep_pie_der_oculto']    = '1' if self.chk_pie_der.isChecked() else '0'
        self._formato['rep_logo_escala']       = str(self.sld_logo.value())
        self._formato['rep_escala_texto']      = str(self.cmb_escala_texto.currentData())
        self._formato.update(self._margenes_actuales())
        self._esquemas_a_formato()
        self._formato['rep_empresa_ruc']       = self.inp_ruc.text().strip()
        self._formato['rep_empresa_direccion'] = self.inp_direccion.text().strip()
        self._formato['rep_empresa_telefono']  = self.inp_telefono.text().strip()

        pdf_reports.set_formato(self._formato)
        self.accept()

    @staticmethod
    def _darken(hex_color: str, factor: float = 0.78) -> str:
        c = QColor(hex_color)
        if not c.isValid():
            return ORANGE_DARK
        h, s, v, a = c.getHsv()
        v = int(max(0, min(255, v * factor)))
        c.setHsv(h, s, v, a)
        return c.name().upper()
