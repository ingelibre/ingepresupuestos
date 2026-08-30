# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""formula_view — Editor de Fórmula Polinómica.

Vista anclada al ``_root_stack`` de ProyectoView, con el mismo armado que
Cronograma y Control de Obra: topbar slate, barra fina de acciones, contenido
a sangre repartido en splitters y una pista en el pie.

    - Topbar:      ← Presupuesto · Fórmula Polinómica · chip Σk
    - Barra:       Auto-calcular · Agregar · Guardar · Excel · PDF · Σ
    - Tira:        la expresión K = … y su validación normativa
    - Cuerpo:      [ Monomios ↔ Composición del monomio ]
                   [ Cálculo de Reajuste K              ]
    - Pie:         ayuda breve + costo directo, nº de índices y cuánto va
                   sin índice propio

Hasta la 3.0.4 era la única pantalla del programa con lenguaje de dashboard
—cuatro tarjetas redondeadas de cabecera oscura, apiladas, más una columna
lateral de tarjetas—; además de desentonar, no entraba: en 1366×768 la tabla
de monomios quedaba en 70 px, fila y media visible.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox, QSizePolicy, QSpinBox, QComboBox, QSplitter,
)

from core.database import get_db
from core.formula_polinomica import (
    cargar_monomios, guardar_monomios,
    cargar_periodos, guardar_periodos, calcular_reajuste_k,
    calcular_por_iu, cargar_componentes, recalcular_coeficientes,
    aplica_formula,
)
from core.indices_inei import listar_areas
from utils.formatting import fmt, parse_num
from utils.icons import icon


# ── Paleta — aliases de tokens centralizados (utils/theme.py) ────────────────
from utils.theme import C

ORANGE       = C.brand
ORANGE_DARK  = C.brand_hover
ORANGE_SOFT  = C.brand_soft
SLATE_700    = C.text
SLATE_500    = C.text_secondary
SLATE_400    = "#5C6B7A"
SLATE_300    = C.text_muted
SLATE_100    = C.text_faint
SILVER_50    = C.bg_alt
SILVER_100   = C.bg
SILVER_200   = C.surface_subtle
SILVER_300   = C.border
WHITE        = C.surface
GREEN_700    = C.success
GREEN_SOFT   = C.success_soft
GREEN_DARK   = C.success_dark
RED_500      = C.error
RED_SOFT     = C.error_soft
RED_DARK     = C.error_dark
BLUE_700     = C.info
PAGE_BG      = "#EEF2F7"   # se ve en los tiradores de los splitters


class FormulaView(QWidget):
    """Editor de fórmula polinómica para un proyecto."""

    def __init__(self, proyecto_id: int, proyecto_nombre: str = "",
                 on_back=None, parent=None):
        super().__init__(parent)
        self.pid = proyecto_id
        self.proyecto_nombre = proyecto_nombre
        self._on_back = on_back
        self._monomios: list[dict] = []
        self._proyecto_meta: dict = {}
        self._totales_acu: dict | None = None
        self._cd: float = 0.0          # costo directo con que se armó la fórmula
        self._aplica: bool = True      # falso en administración directa
        self._ius: list[dict] = []     # incidencia de cada índice unificado
        self._build()

    # ── construcción UI ─────────────────────────────────────────────────────
    def _build(self):
        """Mismo armado que Cronograma y Control de Obra.

        Antes esta pantalla era la única del programa con lenguaje de dashboard
        —cuatro tarjetas redondeadas con cabecera oscura apiladas, más una
        columna lateral de tarjetas—, y encima no entraba: en 1366×768 la tabla
        de monomios quedaba en 70 px, fila y media. El resto del programa va a
        sangre, con splitters y una pista en el pie; ahora esta también.
        """
        self.setObjectName("formulaRoot")
        self.setStyleSheet(f"QWidget#formulaRoot {{ background:{PAGE_BG}; }}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())
        root.addWidget(self._build_barra_acciones())
        root.addWidget(self._build_tira_expresion())

        # Cuerpo: monomios ↔ composición arriba, reajuste abajo. Todo
        # arrastrable, que es como se reparte el alto en el resto del programa.
        self.split_arriba = QSplitter(Qt.Horizontal)
        self.split_arriba.setChildrenCollapsible(False)
        self.split_arriba.addWidget(self._build_panel_monomios())
        self.card_composicion = self._build_panel_composicion()
        self.split_arriba.addWidget(self.card_composicion)
        self.split_arriba.setStretchFactor(0, 5)
        self.split_arriba.setStretchFactor(1, 4)

        self.split_cuerpo = QSplitter(Qt.Vertical)
        self.split_cuerpo.setChildrenCollapsible(False)
        self.split_cuerpo.addWidget(self.split_arriba)
        self.split_cuerpo.addWidget(self._build_panel_reajuste())
        self.split_cuerpo.setStretchFactor(0, 3)
        self.split_cuerpo.setStretchFactor(1, 2)
        root.addWidget(self.split_cuerpo, 1)

        root.addWidget(self._build_pie())

    def _build_topbar(self) -> QFrame:
        hdr = QFrame()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(f"background:{SLATE_500}; border:none;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 4, 10, 4)
        hl.setSpacing(6)

        btn_back = QPushButton("← Presupuesto")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet(
            f"QPushButton {{ background:rgba(255,255,255,0.12); color:white;"
            f" border:1px solid rgba(255,255,255,0.25); border-radius:6px;"
            f" font-size:11px; padding:3px 10px; }}"
            f"QPushButton:hover {{ background:rgba(255,255,255,0.22); }}"
        )
        btn_back.clicked.connect(
            lambda: self._on_back() if self._on_back else None)
        hl.addWidget(btn_back)
        hl.addSpacing(8)

        lbl_title = QLabel("Fórmula Polinómica")
        lbl_title.setStyleSheet(
            "color:white; font-size:12px; font-weight:700;"
            " background:transparent; border:none;")
        hl.addWidget(lbl_title)
        hl.addStretch(1)

        # Chip de estado a la derecha, como el «Plazo: 60 días» del Gantt.
        self.lbl_suma_badge = QLabel("Σk = 0.0000")
        self.lbl_suma_badge.setStyleSheet(
            "color:white; font-size:11px; font-weight:700;"
            " background:rgba(255,255,255,0.12); border-radius:4px;"
            " padding:3px 10px;"
        )
        hl.addWidget(self.lbl_suma_badge)
        return hdr

    def _build_barra_acciones(self) -> QFrame:
        """Barra fina de controles, el patrón de Cronograma y Metrados."""
        barra = QFrame()
        barra.setStyleSheet(
            f"QFrame {{ background:{SILVER_50};"
            f" border-bottom:1px solid {SILVER_300}; }}"
        )
        fl = QHBoxLayout(barra)
        fl.setContentsMargins(12, 6, 12, 6)
        fl.setSpacing(8)

        self.btn_calcular = self._btn_barra("Auto-calcular desde ACU",
                                            "rep-acus", primary=True)
        self.btn_calcular.clicked.connect(self._calcular_desde_acu)
        fl.addWidget(self.btn_calcular)

        btn_add = self._btn_barra("Agregar monomio", "add")
        btn_add.clicked.connect(self._agregar_monomio)
        fl.addWidget(btn_add)

        self.btn_guardar = self._btn_barra("Guardar", "guardar")
        self.btn_guardar.clicked.connect(self._guardar)
        fl.addWidget(self.btn_guardar)

        self.btn_export = self._btn_barra("Exportar Excel", "exportar")
        self.btn_export.clicked.connect(self._exportar_excel)
        fl.addWidget(self.btn_export)

        self.btn_export_pdf = self._btn_barra("Exportar PDF", "exportar")
        self.btn_export_pdf.clicked.connect(self._exportar_pdf)
        fl.addWidget(self.btn_export_pdf)

        # Aviso de las fórmulas sin composición (a mano o previas a la 3.0.4).
        self.lbl_sin_composicion = QLabel(
            "Sin composición: auto-calcula para ver de qué índices sale cada "
            "monomio."
        )
        self.lbl_sin_composicion.setStyleSheet(
            f"color:{SLATE_300}; font-size:11px; padding-left:10px;"
            f" background:transparent; border:none;"
        )
        self.lbl_sin_composicion.setVisible(False)
        fl.addWidget(self.lbl_sin_composicion)

        fl.addStretch(1)

        self.lbl_suma_foot = QLabel("Σ = 0.0000  ·  0.00%")
        self.lbl_suma_foot.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px; font-weight:600;"
            f" background:transparent; border:none;"
        )
        fl.addWidget(self.lbl_suma_foot)
        return barra

    def _btn_barra(self, texto: str, ico: str | None = None,
                   primary: bool = False) -> QPushButton:
        b = QPushButton(texto)
        b.setCursor(Qt.PointingHandCursor)
        if ico:
            b.setIcon(icon(ico))
            b.setIconSize(QSize(15, 15))
        if primary:
            b.setStyleSheet(
                f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
                f" border-radius:6px; padding:4px 12px; font-weight:600;"
                f" font-size:11px; }}"
                f"QPushButton:hover {{ background:{ORANGE_DARK}; }}"
            )
        else:
            b.setStyleSheet(
                f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
                f" border:1px solid {SILVER_300}; border-radius:6px;"
                f" padding:4px 12px; font-size:11px; }}"
                f"QPushButton:hover {{ background:{ORANGE_SOFT};"
                f" border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
            )
        return b

    def _build_tira_expresion(self) -> QFrame:
        """La fórmula, en una tira propia: es lo que se viene a ver."""
        fr = QFrame()
        fr.setStyleSheet(
            f"QFrame {{ background:{WHITE};"
            f" border-bottom:1px solid {SILVER_300}; }}"
        )
        v = QVBoxLayout(fr)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(2)

        self.lbl_expr = QLabel("K = …")
        self.lbl_expr.setWordWrap(True)
        self.lbl_expr.setTextFormat(Qt.RichText)
        f_mono = QFont("monospace"); f_mono.setPointSize(11)
        self.lbl_expr.setFont(f_mono)
        self.lbl_expr.setStyleSheet(
            "color:#1E2635; background:transparent; border:none;")
        v.addWidget(self.lbl_expr)

        # Validación normativa (D.S. 011-79-VC): suma=1, incidencia ≥5%, máx 8.
        self.lbl_validacion = QLabel("")
        self.lbl_validacion.setWordWrap(True)
        self.lbl_validacion.setTextFormat(Qt.RichText)
        self.lbl_validacion.setStyleSheet(
            "font-size:11px; background:transparent; border:none;")
        self.lbl_validacion.setVisible(False)
        v.addWidget(self.lbl_validacion)
        return fr

    def _panel(self, titulo: str):
        """Panel a sangre con título fino, como «Insumos del proyecto» de
        Control de Obra. Devuelve (frame, layout_vertical, layout_del_título)."""
        fr = QFrame()
        fr.setStyleSheet(f"QFrame {{ background:{WHITE}; border:none; }}")
        v = QVBoxLayout(fr)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        cab = QFrame()
        cab.setStyleSheet(
            f"QFrame {{ background:{WHITE};"
            f" border-bottom:1px solid {SILVER_300}; }}"
        )
        hl = QHBoxLayout(cab)
        hl.setContentsMargins(12, 7, 10, 7)
        hl.setSpacing(8)
        lbl = QLabel(titulo)
        lbl.setStyleSheet(
            f"color:{SLATE_700}; font-size:12px; font-weight:700;"
            f" background:transparent; border:none;"
        )
        hl.addWidget(lbl)
        hl.addStretch(1)
        v.addWidget(cab)
        return fr, v, hl, lbl

    def _build_pie(self) -> QFrame:
        """Pista del pie, como la del Gantt: ayuda breve y estado del cálculo."""
        fr = QFrame()
        fr.setStyleSheet(
            f"QFrame {{ background:{SILVER_50};"
            f" border-top:1px solid {SILVER_300}; }}"
        )
        hl = QHBoxLayout(fr)
        hl.setContentsMargins(12, 5, 12, 5)
        hl.setSpacing(10)

        self.lbl_pie_ayuda = QLabel(
            "💡 La fórmula reajusta el monto de obra según los índices "
            "unificados del INEI: <b>K = Σ k·(Ir/Io)</b>. Los coeficientes "
            "deben sumar 1.000 y ninguno bajar del 5%."
        )
        self.lbl_pie_ayuda.setTextFormat(Qt.RichText)
        self.lbl_pie_ayuda.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px;"
            f" background:transparent; border:none;"
        )
        hl.addWidget(self.lbl_pie_ayuda)
        hl.addStretch(1)

        # Resumen del reparto: reemplaza a la tarjeta «Costos ACU» del lateral.
        self.lbl_pie_info = QLabel("")
        self.lbl_pie_info.setTextFormat(Qt.RichText)
        self.lbl_pie_info.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px;"
            f" background:transparent; border:none;"
        )
        hl.addWidget(self.lbl_pie_info)
        return fr

    def _build_panel_monomios(self) -> QFrame:
        """La tabla de monomios, a sangre. Los botones viven en la barra."""
        fr, v, hl, _ = self._panel("Monomios")

        self.tbl = QTableWidget(0, 7)
        self.tbl.setHorizontalHeaderLabels(
            ["#", "Símbolo", "Descripción", "Índice INEI", "Coef. k",
             "% Partic.", ""]
        )
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setShowGrid(False)
        self.tbl.setStyleSheet(
            "QTableWidget { background:white; border:none; font-size:12px; }"
            "QTableWidget::item { padding:4px 6px; }"
            f"QHeaderView::section {{ background:{SILVER_100};"
            f"  color:{SLATE_500}; padding:6px 8px; border:none;"
            f"  border-bottom:1px solid {SILVER_300};"
            f"  font-size:11px; font-weight:700; }}"
        )
        self.tbl.itemChanged.connect(self._on_item_changed)
        self.tbl.itemSelectionChanged.connect(self._render_composicion)

        h = self.tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed); h.resizeSection(0, 36)
        h.setSectionResizeMode(1, QHeaderView.Fixed); h.resizeSection(1, 76)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Fixed); h.resizeSection(3, 100)
        h.setSectionResizeMode(4, QHeaderView.Fixed); h.resizeSection(4, 90)
        h.setSectionResizeMode(5, QHeaderView.Fixed); h.resizeSection(5, 80)
        h.setSectionResizeMode(6, QHeaderView.Fixed); h.resizeSection(6, 34)
        v.addWidget(self.tbl, 1)
        return fr

    # ── panel "Composición del monomio" ─────────────────────────────────────
    def _build_panel_composicion(self) -> QFrame:
        """Qué índices unificados forman el monomio seleccionado.

        Es lo que el usuario pedía ver: hasta ahora el monomio era una fila con
        un código y un coeficiente, sin manera de saber de dónde salía. Y la
        columna «Monomio» permite mover un índice a otro, que es la otra mitad
        del pedido.
        """
        fr, v, hl, lbl = self._panel("Composición del monomio")
        self.lbl_comp_titulo = lbl

        self.lbl_comp_badge = QLabel("")
        self.lbl_comp_badge.setStyleSheet(
            f"background:{SILVER_100}; color:{SLATE_500}; padding:2px 8px;"
            f" border-radius:4px; font-weight:600; font-size:11px;"
        )
        # Vacío no se pinta: dejaba un rectángulo suelto en la cabecera.
        self.lbl_comp_badge.setVisible(False)
        hl.addWidget(self.lbl_comp_badge)

        self.tbl_comp = QTableWidget(0, 5)
        self.tbl_comp.setHorizontalHeaderLabels(
            ["Índice", "Descripción", "Monto", "Incidencia", "Monomio"])
        self.tbl_comp.verticalHeader().setVisible(False)
        self.tbl_comp.setAlternatingRowColors(True)
        self.tbl_comp.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_comp.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_comp.setShowGrid(False)
        self.tbl_comp.setStyleSheet(
            "QTableWidget { background:white; border:none; font-size:12px; }"
            "QTableWidget::item { padding:4px 6px; }"
            f"QHeaderView::section {{ background:{SILVER_100};"
            f"  color:{SLATE_500}; padding:6px 8px; border:none;"
            f"  border-bottom:1px solid {SILVER_300};"
            f"  font-size:11px; font-weight:700; }}"
        )
        h = self.tbl_comp.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed); h.resizeSection(0, 62)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        for c, w in ((2, 120), (3, 90), (4, 110)):
            h.setSectionResizeMode(c, QHeaderView.Fixed)
            h.resizeSection(c, w)
        v.addWidget(self.tbl_comp, 1)

        self.lbl_comp_pie = QLabel("")
        self.lbl_comp_pie.setWordWrap(True)
        self.lbl_comp_pie.setStyleSheet(
            f"color:{SLATE_300}; font-size:11px; padding:6px 12px;"
            f" background:{SILVER_50}; border:none;"
            f" border-top:1px solid {SILVER_300};"
        )
        v.addWidget(self.lbl_comp_pie)
        return fr

    def _render_composicion(self):
        """Pinta la composición del monomio seleccionado en la tabla.

        Si la fórmula no tiene composición —escrita a mano, o guardada antes de
        la 3.0.4— la tarjeta se OCULTA en vez de quedarse como una caja vacía
        ocupando el alto que necesita la tabla de monomios. El aviso de que se
        puede derivar va en el pie de los monomios, que sí se ve siempre.
        """
        hay_composicion = any(m.get('componentes') for m in self._monomios)
        self.card_composicion.setVisible(hay_composicion)
        self.lbl_sin_composicion.setVisible(
            bool(self._monomios) and not hay_composicion)
        if not hay_composicion:
            return

        self.tbl_comp.setRowCount(0)
        fila = self.tbl.currentRow()
        if fila < 0 or fila >= len(self._monomios):
            self.lbl_comp_titulo.setText("Composición del monomio")
            self.lbl_comp_badge.setText("")
            self.lbl_comp_pie.setText(
                "Selecciona un monomio para ver los índices unificados que lo "
                "forman."
            )
            return

        m = self._monomios[fila]
        comps = m.get('componentes') or []
        simbolo = m.get('simbolo') or '?'
        self.lbl_comp_titulo.setText(
            f"Composición de {simbolo} — {m.get('descripcion') or ''}"
        )
        self.lbl_comp_badge.setText(
            f"{len(comps)} índice" + ("s" if len(comps) != 1 else "")
        )
        self.lbl_comp_badge.setVisible(True)

        if not comps:
            self.lbl_comp_pie.setText(
                "Este monomio no tiene composición guardada: se escribió a mano "
                "o viene de una versión anterior. Usa «Auto-calcular desde ACU» "
                "para derivarla del presupuesto."
            )
            return

        moneda = self._proyecto_meta.get('moneda', 'Soles')
        cd = self._cd or sum(
            float(c.get('monto') or 0)
            for mm in self._monomios for c in (mm.get('componentes') or [])
        )
        for c in comps:
            r = self.tbl_comp.rowCount()
            self.tbl_comp.insertRow(r)

            it_c = QTableWidgetItem(c.get('codigo', ''))
            it_c.setTextAlignment(Qt.AlignCenter)
            f_mono = QFont("monospace"); f_mono.setBold(True)
            it_c.setFont(f_mono)
            self.tbl_comp.setItem(r, 0, it_c)

            self.tbl_comp.setItem(r, 1, QTableWidgetItem(c.get('nombre', '')))

            monto = float(c.get('monto') or 0)
            it_m = QTableWidgetItem(fmt(monto, moneda))
            it_m.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_comp.setItem(r, 2, it_m)

            inc = (monto / cd) if cd else 0
            it_i = QTableWidgetItem(f"{inc * 100:.2f}%")
            it_i.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_i.setForeground(QColor(SLATE_500))
            self.tbl_comp.setItem(r, 3, it_i)

            cmb = QComboBox()
            for j, mm in enumerate(self._monomios):
                cmb.addItem(f"{mm.get('simbolo') or '?'}", j)
            cmb.setCurrentIndex(fila)
            cmb.setToolTip("Mover este índice a otro monomio")
            cmb.currentIndexChanged.connect(
                lambda idx, cod=c.get('codigo'), orig=fila:
                self._mover_componente(cod, orig, idx)
            )
            self.tbl_comp.setCellWidget(r, 4, cmb)

        self.lbl_comp_pie.setText(
            f"El índice del monomio es el de mayor peso; al calcular K los "
            f"demás entran promediados por su monto. Cambia la columna "
            f"«Monomio» para mover un índice."
        )

    def _mover_componente(self, codigo: str, origen: int, destino: int):
        """Mueve un índice unificado de un monomio a otro y recalcula.

        Los coeficientes se rehacen desde los montos —no se reparten a ojo—,
        así que la fórmula sigue sumando 1.000 y ningún costo se pierde.
        """
        if destino == origen or not codigo:
            self._render_composicion()
            return
        if not (0 <= origen < len(self._monomios)
                and 0 <= destino < len(self._monomios)):
            return
        m_orig = self._monomios[origen]
        comps = m_orig.get('componentes') or []
        mov = next((c for c in comps if c.get('codigo') == codigo), None)
        if mov is None:
            return
        if len(comps) == 1:
            QMessageBox.information(
                self, "Composición",
                f"«{mov.get('nombre')}» es el único índice de este monomio.\n"
                "Mover el último dejaría el monomio vacío: elimínalo con la "
                "papelera si ya no lo quieres."
            )
            self._render_composicion()
            return

        comps.remove(mov)
        self._monomios[destino].setdefault('componentes', []).append(mov)
        for m in self._monomios:
            cs = m.get('componentes') or []
            cs.sort(key=lambda x: -float(x.get('monto') or 0))
            if cs:
                principal = cs[0]
                m['indice_inei'] = principal.get('codigo', '')
                m['descripcion'] = (
                    principal.get('nombre', '') if len(cs) == 1
                    else f"{principal.get('nombre', '')} y {len(cs) - 1} más"
                )
        recalcular_coeficientes(self._monomios, self._cd)
        self._render_tabla()
        self.tbl.selectRow(destino)
        self._render_composicion()

    # ── panel "Cálculo de Reajuste K" ───────────────────────────────────────
    def _build_panel_reajuste(self) -> QFrame:
        fr, v, hl, _ = self._panel("Cálculo de Reajuste K (con valores INEI)")

        self.lbl_k_badge = QLabel("K = —")
        self.lbl_k_badge.setStyleSheet(
            f"background:{SILVER_100}; color:{SLATE_500}; padding:2px 10px;"
            f" border-radius:4px; font-weight:700; font-size:12px;"
            f" font-family: monospace;"
        )
        hl.addWidget(self.lbl_k_badge)

        # Fila de períodos + área
        per_row = QFrame()
        per_row.setStyleSheet(f"QFrame {{ background:{SILVER_50};"
                               f"  border-bottom:1px solid {SILVER_300}; }}")
        pl = QHBoxLayout(per_row)
        pl.setContentsMargins(12, 8, 12, 8)
        pl.setSpacing(10)

        # Oferta
        lbl_o = QLabel("Oferta:")
        lbl_o.setStyleSheet(
            f"color:{SLATE_500}; font-weight:600; font-size:12px;"
            f" background:transparent; border:none;"
        )
        pl.addWidget(lbl_o)
        self.cmb_oferta_mes = QComboBox()
        for i in range(1, 13):
            self.cmb_oferta_mes.addItem(
                ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre",
                 "Diciembre"][i - 1], i
            )
        self.cmb_oferta_mes.setFixedWidth(110)
        pl.addWidget(self.cmb_oferta_mes)

        self.inp_oferta_anio = QSpinBox()
        self.inp_oferta_anio.setRange(1990, 2100)
        self.inp_oferta_anio.setFixedWidth(80)
        pl.addWidget(self.inp_oferta_anio)

        # Separador visual con flecha
        from utils.theme import accent_color as _acc
        flecha = QLabel("→")
        flecha.setStyleSheet(
            f"color:{_acc()}; font-weight:700; font-size:16px;"
            f"  padding:0 8px; background:transparent; border:none;"
        )
        pl.addWidget(flecha)

        # Reajuste
        lbl_r = QLabel("Reajuste:")
        lbl_r.setStyleSheet(
            f"color:{SLATE_500}; font-weight:600; font-size:12px;"
            f" background:transparent; border:none;"
        )
        pl.addWidget(lbl_r)
        self.cmb_reajuste_mes = QComboBox()
        for i in range(1, 13):
            self.cmb_reajuste_mes.addItem(
                ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre",
                 "Diciembre"][i - 1], i
            )
        self.cmb_reajuste_mes.setFixedWidth(110)
        pl.addWidget(self.cmb_reajuste_mes)

        self.inp_reajuste_anio = QSpinBox()
        self.inp_reajuste_anio.setRange(1990, 2100)
        self.inp_reajuste_anio.setFixedWidth(80)
        pl.addWidget(self.inp_reajuste_anio)

        pl.addSpacing(14)

        # Área
        lbl_a = QLabel("Área:")
        lbl_a.setStyleSheet(
            f"color:{SLATE_500}; font-weight:600; font-size:12px;"
            f" background:transparent; border:none;"
        )
        pl.addWidget(lbl_a)
        self.cmb_area = QComboBox()
        self.cmb_area.setMinimumWidth(180)
        for a in listar_areas():
            txt = f"{a['codigo']} — {a['nombre'][:36]}"
            self.cmb_area.addItem(txt, a['codigo'])
        pl.addWidget(self.cmb_area)

        pl.addStretch(1)

        self.btn_recalcular_k = QPushButton("Recalcular")
        self.btn_recalcular_k.setIcon(icon("rep-acus"))
        self.btn_recalcular_k.setIconSize(QSize(16, 16))
        self.btn_recalcular_k.setCursor(Qt.PointingHandCursor)
        self.btn_recalcular_k.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f"  border-radius:6px; padding:5px 12px; font-weight:600;"
            f"  font-size:11px; }}"
            f"QPushButton:hover {{ background:{ORANGE_DARK}; }}"
        )
        self.btn_recalcular_k.clicked.connect(self._calcular_k)
        pl.addWidget(self.btn_recalcular_k)

        # Auto-recálculo al cambiar período/área
        self.cmb_oferta_mes.currentIndexChanged.connect(self._calcular_k)
        self.inp_oferta_anio.valueChanged.connect(self._calcular_k)
        self.cmb_reajuste_mes.currentIndexChanged.connect(self._calcular_k)
        self.inp_reajuste_anio.valueChanged.connect(self._calcular_k)
        self.cmb_area.currentIndexChanged.connect(self._calcular_k)

        v.addWidget(per_row)

        # Tabla de detalle
        self.tbl_k = QTableWidget(0, 7)
        self.tbl_k.setHorizontalHeaderLabels([
            "Símbolo", "INEI", "Coef. k", "Io (oferta)", "Ir (reajuste)",
            "Ir / Io", "k × (Ir/Io)"
        ])
        self.tbl_k.verticalHeader().setVisible(False)
        self.tbl_k.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_k.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_k.setShowGrid(False)
        self.tbl_k.setStyleSheet(
            "QTableWidget { background:white; border:none; font-size:12px; }"
            "QTableWidget::item { padding:5px 8px; }"
            f"QHeaderView::section {{ background:{SILVER_100};"
            f"  color:{SLATE_500}; padding:5px 8px; border:none;"
            f"  border-bottom:1px solid {SILVER_300};"
            f"  font-size:11px; font-weight:700; }}"
        )
        h2 = self.tbl_k.horizontalHeader()
        h2.setSectionResizeMode(0, QHeaderView.Fixed); h2.resizeSection(0, 70)
        h2.setSectionResizeMode(1, QHeaderView.Fixed); h2.resizeSection(1, 60)
        h2.setSectionResizeMode(2, QHeaderView.Fixed); h2.resizeSection(2, 90)
        h2.setSectionResizeMode(3, QHeaderView.Stretch)
        h2.setSectionResizeMode(4, QHeaderView.Stretch)
        h2.setSectionResizeMode(5, QHeaderView.Fixed); h2.resizeSection(5, 90)
        h2.setSectionResizeMode(6, QHeaderView.Fixed); h2.resizeSection(6, 110)
        v.addWidget(self.tbl_k, 1)

        # Footer
        foot = QFrame()
        foot.setStyleSheet(
            f"QFrame {{ background:{SILVER_50};"
            f"  border-top:1px solid {SILVER_300}; }}"
        )
        fl = QHBoxLayout(foot); fl.setContentsMargins(12, 6, 12, 6); fl.setSpacing(8)

        self.lbl_alerta_k = QLabel("")
        self.lbl_alerta_k.setStyleSheet(
            f"color:{RED_500}; font-size:11px; font-weight:600;"
        )
        self.lbl_alerta_k.setWordWrap(True)
        fl.addWidget(self.lbl_alerta_k, 1)

        from utils.theme import accent_hover as _acc_h
        self.lbl_k_grande = QLabel("K = —")
        f_k = QFont("monospace"); f_k.setPointSize(14); f_k.setBold(True)
        self.lbl_k_grande.setFont(f_k)
        self.lbl_k_grande.setStyleSheet(f"color:{_acc_h()}; padding:0 12px;")
        fl.addWidget(self.lbl_k_grande)

        btn_ir_inei = QPushButton("Cargar valores INEI →")
        btn_ir_inei.setCursor(Qt.PointingHandCursor)
        btn_ir_inei.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{BLUE_700};"
            f"  border:none; padding:5px 10px; font-size:11px;"
            f"  font-weight:600; text-decoration:underline; }}"
            f"QPushButton:hover {{ color:{ORANGE_DARK}; }}"
        )
        btn_ir_inei.clicked.connect(self._ir_a_indices_inei)
        fl.addWidget(btn_ir_inei)
        v.addWidget(foot)

        return fr

    def _ir_a_indices_inei(self):
        """Navega al editor de Índices INEI a través de MainWindow."""
        w = self
        while w is not None:
            if hasattr(w, "_ir_a_indices_inei"):
                w._ir_a_indices_inei()
                return
            w = w.parent()
        QMessageBox.information(
            self, "Índices INEI",
            "Para abrir el editor: sidebar → INEI"
        )

    # ── columna lateral: info / costos / ayuda ──────────────────────────────
    def cargar(self):
        """Carga proyecto + monomios persistidos. Llamar al mostrar la vista."""
        conn = get_db()
        proy = conn.execute(
            "SELECT id, nombre, cliente, ubicacion, moneda "
            "FROM proyectos WHERE id=?", (self.pid,)
        ).fetchone()
        conn.close()
        self._proyecto_meta = dict(proy) if proy else {}

        # El nombre del proyecto ya está en las pestañas; la tarjeta lateral
        # que lo repetía se fue con el resto de la columna.

        # Si la obra es por administración directa la fórmula no corresponde;
        # se dice y no se calcula nada.
        ok, motivo = aplica_formula(self.pid)
        self._aplica = ok
        for w in (self.btn_calcular, self.btn_guardar, self.btn_recalcular_k):
            w.setEnabled(ok)
        if not ok:
            self.lbl_pie_ayuda.setText(f"⚠ {motivo}")
            self.lbl_expr.setText("K = —")
            self.lbl_validacion.setVisible(False)
            self._monomios = []
            self._render_tabla()
            return

        self._monomios = cargar_monomios(self.pid)
        # La composición vive en su propia tabla, enlazada por `orden`. Los
        # monomios escritos a mano (o de versiones anteriores) no tienen, y la
        # tarjeta lo dice en vez de fingir un desglose.
        comps = cargar_componentes(self.pid)
        for m in self._monomios:
            m['componentes'] = [dict(c) for c in comps.get(m.get('orden'), [])]
        self._cd = sum(float(c.get('monto') or 0)
                       for m in self._monomios
                       for c in (m.get('componentes') or []))
        self._render_tabla()
        self._cargar_periodos_ui()
        self._calcular_k()

    def _render_tabla(self):
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        for i, m in enumerate(self._monomios):
            self._add_row(i, m)
        self.tbl.blockSignals(False)
        self._actualizar_totales()
        self._render_expr()
        self._render_composicion()

    def _add_row(self, i: int, m: dict):
        row = self.tbl.rowCount()
        self.tbl.insertRow(row)

        # # de fila (no editable)
        it_n = QTableWidgetItem(str(i + 1))
        it_n.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it_n.setForeground(QColor(SLATE_300))
        it_n.setTextAlignment(Qt.AlignCenter)
        self.tbl.setItem(row, 0, it_n)

        it_s = QTableWidgetItem(m.get('simbolo', ''))
        f = QFont(); f.setBold(True); f.setPointSize(11)
        it_s.setFont(f)
        it_s.setTextAlignment(Qt.AlignCenter)
        it_s.setForeground(QColor(SLATE_700))
        self.tbl.setItem(row, 1, it_s)

        it_d = QTableWidgetItem(m.get('descripcion', ''))
        self.tbl.setItem(row, 2, it_d)

        it_i = QTableWidgetItem(m.get('indice_inei', ''))
        it_i.setTextAlignment(Qt.AlignCenter)
        f_mono = QFont("monospace"); f_mono.setBold(True)
        it_i.setFont(f_mono)
        self.tbl.setItem(row, 3, it_i)

        coef = float(m.get('coeficiente') or 0)
        it_k = QTableWidgetItem(f"{coef:.4f}")
        it_k.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f2 = QFont(); f2.setBold(True)
        it_k.setFont(f2)
        self.tbl.setItem(row, 4, it_k)

        it_p = QTableWidgetItem(f"{coef * 100:.2f}%")
        it_p.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it_p.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it_p.setForeground(QColor(SLATE_500))
        self.tbl.setItem(row, 5, it_p)

        # Resaltar en rojo si la incidencia está por debajo del 5% (mínimo legal).
        self._resaltar_incidencia(it_k, it_p, coef)

        # botón eliminar
        btn_del = QPushButton()
        btn_del.setIcon(icon("eliminar"))
        btn_del.setIconSize(QSize(14, 14))
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setFixedWidth(28)
        btn_del.setToolTip("Eliminar monomio")
        btn_del.setStyleSheet(
            "QPushButton { background:transparent; border:none; }"
            f"QPushButton:hover {{ background:{RED_SOFT}; border-radius:4px; }}"
        )
        btn_del.clicked.connect(lambda _=False, r=row: self._eliminar_fila(r))
        self.tbl.setCellWidget(row, 6, btn_del)

    def _resaltar_incidencia(self, it_k, it_p, coef: float):
        """Pinta de rojo el coeficiente (y su %) si la incidencia está por
        debajo del 5% (mínimo legal D.S. 011-79-VC); lo limpia si cumple."""
        bajo = 0 < coef < 0.050
        tip = "Incidencia menor al 5% (mínimo legal 0.050)" if bajo else ""
        for it, fg_normal in ((it_k, None), (it_p, QColor(SLATE_500))):
            if it is None:
                continue
            if bajo:
                it.setBackground(QColor(RED_SOFT))
                it.setForeground(QColor(RED_DARK))
            else:
                it.setData(Qt.BackgroundRole, None)   # respeta el zebra
                if fg_normal is None:
                    it.setData(Qt.ForegroundRole, None)
                else:
                    it.setForeground(fg_normal)
            it.setToolTip(tip)

    def _on_item_changed(self, item: QTableWidgetItem):
        row = item.row()
        col = item.column()
        if row >= len(self._monomios):
            return
        m = self._monomios[row]
        if col == 1:
            m['simbolo'] = item.text().strip()
        elif col == 2:
            m['descripcion'] = item.text().strip()
        elif col == 3:
            m['indice_inei'] = item.text().strip()
        elif col == 4:
            m['coeficiente'] = max(0.0, parse_num(item.text()))
            self.tbl.blockSignals(True)
            item.setText(f"{m['coeficiente']:.4f}")
            it_p = self.tbl.item(row, 5)
            if it_p:
                it_p.setText(f"{m['coeficiente'] * 100:.2f}%")
            self._resaltar_incidencia(item, it_p, m['coeficiente'])
            self.tbl.blockSignals(False)

        self._actualizar_totales()
        self._render_expr()

    def _eliminar_fila(self, row: int):
        """Elimina un monomio. Sus índices se pasan al mayor de los que quedan.

        Descartarlos perdería esa parte del costo directo y la fórmula dejaría
        de sumar 1.000; el usuario los puede repartir después desde la columna
        «Monomio» de la composición.
        """
        if not (0 <= row < len(self._monomios)):
            return
        muerto = self._monomios[row]
        huerfanos = muerto.get('componentes') or []
        del self._monomios[row]

        if huerfanos and self._monomios:
            destino = max(
                self._monomios,
                key=lambda m: sum(float(c.get('monto') or 0)
                                  for c in (m.get('componentes') or []))
            )
            destino.setdefault('componentes', []).extend(huerfanos)
            destino['componentes'].sort(
                key=lambda x: -float(x.get('monto') or 0))
            principal = destino['componentes'][0]
            destino['indice_inei'] = principal.get('codigo', '')
            destino['descripcion'] = (
                principal.get('nombre', '')
                if len(destino['componentes']) == 1
                else f"{principal.get('nombre', '')} y "
                     f"{len(destino['componentes']) - 1} más"
            )
            QMessageBox.information(
                self, "Monomio eliminado",
                f"Sus {len(huerfanos)} índice(s) pasaron a "
                f"«{destino.get('simbolo')}» para no perder costo directo. "
                f"Puedes repartirlos desde la composición."
            )
            recalcular_coeficientes(self._monomios, self._cd)
        self._render_tabla()

    def _agregar_monomio(self):
        # Primer símbolo libre comenzando por A
        usados = {m.get('simbolo', '').upper() for m in self._monomios}
        simbolo = next(
            (chr(c) for c in range(ord('A'), ord('Z') + 1) if chr(c) not in usados),
            'X'
        )
        self._monomios.append({
            'simbolo': simbolo, 'descripcion': '',
            'indice_inei': '', 'coeficiente': 0.0,
        })
        self._render_tabla()
        # Foco en la celda de descripción del último
        last = self.tbl.rowCount() - 1
        if last >= 0:
            self.tbl.setCurrentCell(last, 2)
            self.tbl.editItem(self.tbl.item(last, 2))

    def _validar_formula(self) -> list:
        """Validaciones del D.S. 011-79-VC para la fórmula polinómica:
          - suma de coeficientes = 1.000,
          - incidencia (coeficiente) mínima 0.050 (5%) por monomio,
          - máximo 8 monomios por fórmula.
        Devuelve la lista de mensajes de incumplimiento (vacía = válida)."""
        monos = self._monomios
        n = len(monos)
        issues = []
        if n == 0:
            return issues
        suma = sum(float(m.get('coeficiente') or 0) for m in monos)
        if abs(suma - 1.0) >= 0.001:
            issues.append(
                f"La suma de coeficientes debe ser 1.000 (actual: {suma:.4f}).")
        if n > 8:
            issues.append(f"Máximo 8 monomios por fórmula (tienes {n}).")
        bajos = [(m.get('simbolo') or '?') for m in monos
                 if 0 < float(m.get('coeficiente') or 0) < 0.050]
        if bajos:
            issues.append(
                "Incidencia menor al 5% (mínimo legal 0.050): "
                + ", ".join(bajos) + ".")
        return issues

    def _actualizar_totales(self):
        suma = sum(float(m.get('coeficiente') or 0) for m in self._monomios)
        ok = abs(suma - 1.0) < 0.001
        bg = GREEN_SOFT if ok else RED_SOFT
        fg = GREEN_DARK if ok else RED_DARK
        self.lbl_suma_badge.setText(f"Σk = {suma:.4f}")
        self.lbl_suma_badge.setStyleSheet(
            f"background:{bg}; color:{fg}; padding:3px 10px;"
            f"  border-radius:4px; font-weight:600; font-size:11px;"
        )
        col_suma = GREEN_DARK if ok else RED_500
        self.lbl_suma_foot.setText(f"Σ = {suma:.4f}  ·  {suma * 100:.2f}%")
        self.lbl_suma_foot.setStyleSheet(
            f"color:{col_suma}; font-size:11px; font-weight:600; padding:0 8px;"
        )

        # ── Validación normativa (D.S. 011-79-VC) ──────────────────────────
        from html import escape as _esc
        issues = self._validar_formula()
        if not self._monomios:
            self.lbl_validacion.setVisible(False)
        elif issues:
            self.lbl_validacion.setText(
                "⚠ " + "<br>⚠ ".join(_esc(i) for i in issues))
            self.lbl_validacion.setStyleSheet(
                f"padding:0 16px 12px 16px; font-size:11px; color:{RED_DARK};"
                f" background:transparent; border:none; font-weight:600;")
            self.lbl_validacion.setVisible(True)
        else:
            self.lbl_validacion.setText("✓ Fórmula válida (D.S. 011-79-VC)")
            self.lbl_validacion.setStyleSheet(
                f"padding:0 16px 12px 16px; font-size:11px; color:{GREEN_DARK};"
                f" background:transparent; border:none; font-weight:600;")
            self.lbl_validacion.setVisible(True)

    def _render_expr(self):
        partes = []
        for m in self._monomios:
            k = float(m.get('coeficiente') or 0)
            if k <= 0:
                continue
            s = m.get('simbolo') or '?'
            partes.append(
                f"<span style='color:{ORANGE_DARK}'>{k:.4f}</span>"
                f"·(<b>{s}</b>r/<b>{s}</b>o)"
            )
        if not partes:
            self.lbl_expr.setText("<span style='color:#95A3AB'>K = …</span>")
        else:
            self.lbl_expr.setText("<b>K</b> = " + " + ".join(partes))

    # ── Acciones ───────────────────────────────────────────────────────────
    def _calcular_desde_acu(self):
        self.btn_calcular.setEnabled(False)
        self.btn_calcular.setText("Calculando…")
        try:
            r = calcular_por_iu(self.pid)
        finally:
            self.btn_calcular.setEnabled(True)
            self.btn_calcular.setText("Auto-calcular desde ACU")

        if not r.get('ok'):
            QMessageBox.warning(self, "Auto-calcular",
                                r.get('msg') or "No se pudo calcular.")
            return

        n = len(r['monomios'])
        if self._monomios:
            res = QMessageBox.question(
                self, "Auto-calcular",
                f"Esto reemplazará los monomios actuales por {n} monomio(s) "
                f"derivados del ACU, agrupando los insumos por su índice "
                f"unificado.\n\n¿Continuar?",
                QMessageBox.Yes | QMessageBox.No
            )
            if res != QMessageBox.Yes:
                return

        self._monomios = [dict(m) for m in r['monomios']]
        self._cd = r['cd']
        self._ius = r['ius']
        self._monto_sin_indice = r.get('monto_sin_indice', 0.0)
        self._render_tabla()
        self._actualizar_panel_acu()
        if self._monomios:
            self.tbl.selectRow(0)

    def _actualizar_panel_acu(self):
        """Resumen del reparto, en una línea del pie.

        Antes era una tarjeta lateral con los tres porcentajes MO/MAT/EQ, que
        era todo lo que la fórmula sabía. Ahora que agrupa por índice unificado
        lo que hace falta decir es cuántos índices salieron, cuál es el costo
        directo y —sobre todo— cuánto se apoya en insumos SIN índice asignado,
        que es un supuesto y conviene que se vea antes de presentar.
        """
        if not self._ius or not self._cd:
            self.lbl_pie_info.setText("")
            return
        moneda = self._proyecto_meta.get('moneda', 'Soles')
        txt = (f"C.D. <b>{fmt(self._cd, moneda)}</b> · "
               f"<b>{len(self._ius)}</b> índices")
        sin = getattr(self, '_monto_sin_indice', 0.0)
        if sin:
            txt += (f" · <span style='color:{ORANGE_DARK}'>"
                    f"{fmt(sin, moneda)} ({sin / self._cd * 100:.0f}%) sin "
                    f"índice propio</span>")
        self.lbl_pie_info.setText(txt)

    def _guardar(self):
        suma = sum(float(m.get('coeficiente') or 0) for m in self._monomios)
        if self._monomios and abs(suma - 1.0) > 0.005:
            res = QMessageBox.question(
                self, "Confirmar",
                f"Los coeficientes suman {suma:.4f} (debería ser 1.000).\n"
                f"¿Guardar de todas formas?",
                QMessageBox.Yes | QMessageBox.No
            )
            if res != QMessageBox.Yes:
                return
        try:
            guardar_monomios(self.pid, self._monomios)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{e}")
            return
        QMessageBox.information(
            self, "Guardado",
            f"Fórmula polinómica guardada ({len(self._monomios)} monomios)."
        )

    def _exportar_excel(self):
        """Exporta la fórmula a Excel usando exporter.exportar_formula_polinomica."""
        nombre = self._proyecto_meta.get('nombre', '') or "proyecto"
        import re
        slug = re.sub(r'[^\w\s-]', '', nombre)[:40].strip()
        slug = re.sub(r'\s+', '_', slug) or "proyecto"
        from datetime import datetime
        fecha = datetime.now().strftime("%Y%m%d_%H%M")
        sugerido = f"{slug}_formula_{fecha}.xlsx"

        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar Fórmula Polinómica", sugerido, "Excel (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        try:
            # Asegurar que esté guardada antes de exportar
            guardar_monomios(self.pid, self._monomios)
            from core.exporter import exportar_formula_polinomica
            buf = exportar_formula_polinomica(self.pid)
            with open(path, "wb") as f:
                f.write(buf.getvalue())
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Error",
                                 f"No se pudo exportar:\n{e}")
            return
        QMessageBox.information(self, "Exportado",
                                f"Archivo guardado:\n{path}")

    def _exportar_pdf(self):
        """Exporta la fórmula polinómica a PDF (mismo pipeline/estilo que los
        demás reportes: portada, encabezado y pie compartidos)."""
        nombre = self._proyecto_meta.get('nombre', '') or "proyecto"
        import re
        slug = re.sub(r'[^\w\s-]', '', nombre)[:40].strip()
        slug = re.sub(r'\s+', '_', slug) or "proyecto"
        from datetime import datetime
        fecha = datetime.now().strftime("%Y%m%d_%H%M")
        sugerido = f"{slug}_formula_{fecha}.pdf"

        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar Fórmula Polinómica a PDF", sugerido, "PDF (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        try:
            # Asegurar que esté guardada antes de exportar
            guardar_monomios(self.pid, self._monomios)
            from core.pdf_reports import generar_pdf_archivo
            generar_pdf_archivo('formula_polinomica', self.pid, path)
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Error",
                                 f"No se pudo exportar:\n{e}")
            return
        QMessageBox.information(self, "Exportado",
                                f"Archivo guardado:\n{path}")

    # ── Períodos y cálculo de K (con valores INEI) ──────────────────────────
    def _cargar_periodos_ui(self):
        """Lee los períodos persistidos y los aplica a los widgets."""
        per = cargar_periodos(self.pid)
        self.cmb_oferta_mes.blockSignals(True)
        self.inp_oferta_anio.blockSignals(True)
        self.cmb_reajuste_mes.blockSignals(True)
        self.inp_reajuste_anio.blockSignals(True)
        self.cmb_area.blockSignals(True)
        try:
            for i in range(self.cmb_oferta_mes.count()):
                if self.cmb_oferta_mes.itemData(i) == per['oferta_mes']:
                    self.cmb_oferta_mes.setCurrentIndex(i); break
            self.inp_oferta_anio.setValue(int(per['oferta_anio']))
            for i in range(self.cmb_reajuste_mes.count()):
                if self.cmb_reajuste_mes.itemData(i) == per['reajuste_mes']:
                    self.cmb_reajuste_mes.setCurrentIndex(i); break
            self.inp_reajuste_anio.setValue(int(per['reajuste_anio']))
            for i in range(self.cmb_area.count()):
                if self.cmb_area.itemData(i) == per['area_inei']:
                    self.cmb_area.setCurrentIndex(i); break
        finally:
            self.cmb_oferta_mes.blockSignals(False)
            self.inp_oferta_anio.blockSignals(False)
            self.cmb_reajuste_mes.blockSignals(False)
            self.inp_reajuste_anio.blockSignals(False)
            self.cmb_area.blockSignals(False)

    def _calcular_k(self):
        """Calcula K con los períodos/área actuales y los monomios guardados.
        Persiste los períodos para preservarlos entre sesiones."""
        if not self._monomios:
            self.tbl_k.setRowCount(0)
            self.lbl_k_badge.setText("K = —")
            self.lbl_k_grande.setText("K = —")
            self.lbl_alerta_k.setText(
                "No hay monomios definidos. Crea o auto-calcula la fórmula primero."
            )
            return

        oa = self.inp_oferta_anio.value()
        om = self.cmb_oferta_mes.currentData()
        ra = self.inp_reajuste_anio.value()
        rm = self.cmb_reajuste_mes.currentData()
        area = self.cmb_area.currentData() or '01'

        # Persistir períodos
        try:
            guardar_periodos(self.pid, oa, om, ra, rm, area)
        except Exception:
            pass

        # Calcular
        r = calcular_reajuste_k(
            self.pid,
            oferta_anio=oa, oferta_mes=om,
            reajuste_anio=ra, reajuste_mes=rm,
            area_inei=area,
        )

        # Renderear tabla
        self.tbl_k.setRowCount(0)
        flag = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        for d in r['detalle']:
            row = self.tbl_k.rowCount()
            self.tbl_k.insertRow(row)

            # Símbolo (bold + naranja)
            it_s = QTableWidgetItem(d.get('simbolo') or '?')
            it_s.setFlags(flag)
            f = QFont(); f.setBold(True); f.setPointSize(11)
            it_s.setFont(f)
            it_s.setTextAlignment(Qt.AlignCenter)
            it_s.setForeground(QColor(ORANGE_DARK))
            self.tbl_k.setItem(row, 0, it_s)

            # INEI
            it_i = QTableWidgetItem(d.get('indice_inei') or '—')
            it_i.setFlags(flag)
            it_i.setTextAlignment(Qt.AlignCenter)
            fmono = QFont("monospace"); fmono.setBold(True)
            it_i.setFont(fmono)
            self.tbl_k.setItem(row, 1, it_i)

            # k
            it_k = QTableWidgetItem(f"{d['coeficiente']:.4f}")
            it_k.setFlags(flag)
            it_k.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_k.setItem(row, 2, it_k)

            # Io
            vo = d.get('valor_o')
            txt_o = f"{vo:.4f}".rstrip('0').rstrip('.') if vo else "— sin dato"
            it_o = QTableWidgetItem(txt_o)
            it_o.setFlags(flag)
            it_o.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if not vo:
                it_o.setForeground(QColor(RED_500))
            self.tbl_k.setItem(row, 3, it_o)

            # Ir
            vr = d.get('valor_r')
            txt_r = f"{vr:.4f}".rstrip('0').rstrip('.') if vr else "— sin dato"
            it_r = QTableWidgetItem(txt_r)
            it_r.setFlags(flag)
            it_r.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if not vr:
                it_r.setForeground(QColor(RED_500))
            self.tbl_k.setItem(row, 4, it_r)

            # Ir/Io
            rt = d.get('ratio')
            txt_rt = f"{rt:.4f}" if rt is not None else "—"
            it_rt = QTableWidgetItem(txt_rt)
            it_rt.setFlags(flag)
            it_rt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            fr_b = QFont(); fr_b.setBold(True)
            it_rt.setFont(fr_b)
            if rt is not None:
                # Verde si ratio > 1, rojo si < 1
                it_rt.setForeground(
                    QColor(GREEN_700 if rt > 1 else (RED_500 if rt < 1 else SLATE_500))
                )
            self.tbl_k.setItem(row, 5, it_rt)

            # k * ratio
            ap = d.get('aporte')
            txt_ap = f"{ap:.4f}" if ap is not None else "—"
            it_a = QTableWidgetItem(txt_ap)
            it_a.setFlags(flag)
            it_a.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            fa = QFont(); fa.setBold(True)
            it_a.setFont(fa)
            it_a.setForeground(QColor(SLATE_700) if ap is not None
                               else QColor(SLATE_300))
            self.tbl_k.setItem(row, 6, it_a)

        # Actualizar badges
        kt = r['k_total']
        sin = r['monomios_sin_datos']
        if sin > 0:
            self.lbl_k_badge.setText(f"K parcial = {kt:.4f}")
            self.lbl_k_badge.setStyleSheet(
                f"background:{RED_SOFT}; color:{RED_DARK}; padding:4px 12px;"
                f"  border-radius:4px; font-weight:700; font-size:12px;"
                f"  font-family:monospace;"
            )
            self.lbl_k_grande.setText(f"K = {kt:.4f}*")
            self.lbl_k_grande.setStyleSheet(
                f"color:{RED_500}; padding:0 12px;"
            )
            self.lbl_alerta_k.setText(
                f"⚠  Faltan valores INEI para {sin} monomio(s). "
                f"El K mostrado es parcial. "
                f"Carga valores en el editor de INEI."
            )
        else:
            self.lbl_k_badge.setText(f"K = {kt:.4f}")
            color_b = GREEN_SOFT
            color_t = GREEN_DARK
            self.lbl_k_badge.setStyleSheet(
                f"background:{color_b}; color:{color_t}; padding:4px 12px;"
                f"  border-radius:4px; font-weight:700; font-size:12px;"
                f"  font-family:monospace;"
            )
            from utils.theme import accent_hover as _acc_h
            self.lbl_k_grande.setText(f"K = {kt:.4f}")
            self.lbl_k_grande.setStyleSheet(
                f"color:{_acc_h()}; padding:0 12px;"
            )
            pct = (kt - 1.0) * 100
            if abs(pct) < 0.001:
                self.lbl_alerta_k.setText(
                    "K = 1.0000 → sin reajuste (oferta = reajuste)."
                )
            else:
                signo = "incremento" if pct > 0 else "decremento"
                self.lbl_alerta_k.setText(
                    f"Reajuste resultante: {signo} de {abs(pct):.2f}% sobre el monto contractual."
                )
