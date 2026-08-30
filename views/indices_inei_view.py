# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""indices_inei_view — Histórico de Índices Unificados de Precios INEI.

Layout:
    - Topbar:        ← Inicio · Índices INEI · selector de área · botones
    - Split H:
        · Izquierda (sidebar): lista de 80 índices con búsqueda + KPIs
        · Derecha (centro):    tabla pivot año × meses del índice seleccionado
    - Acciones:      Importar Excel INEI · Exportar JSON · Importar JSON

Equivalente conceptual al módulo "Importación de Índices de Precios INEI 2026"
de Delphin Express.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QFont, QColor, QShortcut, QKeySequence, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QLineEdit, QComboBox,
    QPushButton, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSplitter, QFileDialog, QMessageBox,
    QSizePolicy, QApplication, QDialog, QDialogButtonBox, QFormLayout, QMenu,
)

from core.database import get_db
from core.indices_inei import (
    asegurar_seed, listar_indices, listar_areas,
    SERIE_ACTUAL, series_disponibles, serie_nombre, serie_de,
    buscar_resoluciones_gobpe, descargar_resolucion_gobpe,
    descargar_indices_publicados,
    crear_indice, actualizar_indice, eliminar_indice, contar_usos,
    asegurar_codigos, codigos_huerfanos,
    obtener_matriz, guardar_valor, guardar_valores, eliminar_valor,
    importar_excel_inei, exportar_json, importar_json,
    descargar_desde_url, importar_desde_texto,
    buscar_ultimo_excel_inei, descargar_ultimo_inei,
)
from views._catalogo_base import EditorPlenoDelegate
from utils.icons import icon
from utils.formatting import parse_num, parse_num_opt


# ── Paleta ────────────────────────────────────────────────────────────────────
ORANGE       = "#F37329"
ORANGE_DARK  = "#C0621A"
ORANGE_SOFT  = "#FEF5EB"
SLATE_700    = "#273445"
SLATE_500    = "#485A6C"
SLATE_300    = "#667885"
SILVER_50    = "#FBFBFC"
SILVER_100   = "#F8F9FA"
SILVER_200   = "#F0F1F2"
SILVER_300   = "#D4D4D4"
WHITE        = "#FFFFFF"
BLUE_700     = "#0D52BF"
GREEN_700    = "#16A34A"
GREEN_SOFT   = "#D1FAE5"

MESES_LARGOS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


class DialogoIndice(QDialog):
    """Alta y edición de un índice unificado.

    En edición el código queda fijo: es la clave con la que lo referencian los
    insumos y los monomios ya guardados, y cambiarlo los dejaría colgando.
    """

    def __init__(self, parent=None, codigo: str = "", nombre: str = ""):
        super().__init__(parent)
        self._edicion = bool(codigo)
        self.setWindowTitle("Editar índice unificado" if self._edicion
                            else "Nuevo índice unificado")
        self.setMinimumWidth(420)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        self.inp_codigo = QLineEdit(codigo)
        self.inp_codigo.setPlaceholderText("Dos dígitos, ej. 85")
        self.inp_codigo.setMaxLength(2)
        self.inp_codigo.setEnabled(not self._edicion)
        form.addRow("Código *:", self.inp_codigo)

        self.inp_nombre = QLineEdit(nombre)
        self.inp_nombre.setPlaceholderText("Descripción del índice unificado")
        form.addRow("Nombre *:", self.inp_nombre)
        v.addLayout(form)

        ayuda = QLabel(
            "El código es el que publica el INEI. Los insumos y los monomios "
            "de la fórmula polinómica lo referencian por ese número."
        )
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet(f"color:{SLATE_300}; font-size:11px;")
        v.addWidget(ayuda)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Guardar")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self._guardar)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        (self.inp_nombre if self._edicion else self.inp_codigo).setFocus()

    def datos(self) -> tuple[str, str]:
        return self.inp_codigo.text().strip(), self.inp_nombre.text().strip()

    def _guardar(self):
        codigo, nombre = self.datos()
        if not codigo.isdigit():
            QMessageBox.warning(self, "Código inválido",
                                "El código debe ser numérico (01 a 99).")
            return
        if not nombre:
            QMessageBox.warning(self, "Falta el nombre",
                                "Escribe la descripción del índice.")
            return
        self.accept()


class IndicesINEIView(QWidget):
    """Histórico de Índices Unificados de Precios INEI."""

    volver = Signal()

    def __init__(self, proyecto_id: int | None = None,
                 proyecto_nombre: str = '', *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty("vista_nombre", "indices_inei")
        # Contexto: si se llegó desde un proyecto, el diccionario puede
        # ceñirse a los insumos que ESE proyecto usa.
        self._pid_contexto = proyecto_id
        self._nombre_contexto = proyecto_nombre
        asegurar_seed()
        self._codigo_actual: str | None = None
        self._area_actual: str = '01'
        # Las dos bases del INEI conviven: la de 1992 (6 áreas) para los
        # presupuestos anteriores a diciembre de 2025 y la de 2025 (13 áreas)
        # desde entonces. No se mezclan.
        self._serie_actual: str = SERIE_ACTUAL
        self._indices_cache: list[tuple[str, str]] = []
        self._huerfanos: list[dict] = []
        self._build()
        self._cargar_todo()

    # ── construcción UI ─────────────────────────────────────────────────────
    def _build(self):
        """Mismo armado que el Catálogo de Insumos, su vista hermana.

        Antes esta barra metía el título, dos selectores y OCHO botones en una
        sola fila: pedía 1872 px de ancho mínimo, así que en un portátil de
        1366 el combo de la base salía cortado. Ahora las importaciones van en
        un menú «Importar ▾» —como en Insumos— y los selectores bajan a la
        barra de filtros, que es donde el programa pone los filtros.
        """
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        # ── Cabecera ──
        top = QHBoxLayout()
        top.setSpacing(10)

        ico_t = QLabel()
        ico_t.setPixmap(icon("rep-resumen").pixmap(28, 28))
        ico_t.setFixedSize(28, 28)
        top.addWidget(ico_t)

        title = QLabel("Índices Unificados de Precios INEI")
        f = QFont(); f.setPointSize(15); f.setWeight(QFont.DemiBold)
        title.setFont(f)
        title.setStyleSheet(f"color:{SLATE_700};")
        top.addWidget(title)

        self.lbl_subt = QLabel("")
        self.lbl_subt.setStyleSheet(f"color:{SLATE_300}; padding-left:6px;")
        top.addWidget(self.lbl_subt)
        top.addStretch(1)

        self.btn_auto = self._mk_btn("Sincronizar con INEI",
                                      icon_name="importar", primary=True)
        self.btn_auto.setToolTip(
            "Detecta y descarga el último archivo oficial del INEI"
            " automáticamente")
        self.btn_auto.clicked.connect(self._sincronizar_inei)
        top.addWidget(self.btn_auto)

        # Todo lo que es traer datos, en un solo menú.
        self.btn_import = self._mk_btn("Importar ▾", icon_name="importar")
        menu = QMenu(self.btn_import)
        self.btn_imp_excel = menu.addAction(icon("folder"),
                                            "Archivo del INEI (.xlsx)")
        self.btn_imp_excel.triggered.connect(self._importar_excel)
        self.btn_url = menu.addAction(icon("importar"), "Desde una URL…")
        self.btn_url.triggered.connect(self._descargar_url)
        self.btn_pegar = menu.addAction(icon("copiar"),
                                        "Pegar datos del portapapeles")
        self.btn_pegar.triggered.connect(self._pegar_datos)
        menu.addSeparator()
        self.btn_imp_delphin = menu.addAction(icon("sqlite"),
                                              "Base de Delphin Express")
        self.btn_imp_delphin.triggered.connect(self._importar_delphin_sqlite)
        self.btn_imp_json = menu.addAction(icon("importar"), "Desde JSON")
        self.btn_imp_json.triggered.connect(self._importar_json)
        self.btn_import.setMenu(menu)
        top.addWidget(self.btn_import)

        self.btn_exp_json = self._mk_btn("Exportar", icon_name="exportar")
        self.btn_exp_json.setToolTip("Exportar el histórico a JSON")
        self.btn_exp_json.clicked.connect(self._exportar_json)
        top.addWidget(self.btn_exp_json)

        self.btn_diccionario = self._mk_btn("Diccionario",
                                            icon_name="rep-insumos")
        self.btn_diccionario.setToolTip(
            "Qué índice unificado le corresponde a cada insumo — es lo que usa "
            "la fórmula polinómica para agrupar el costo")
        self.btn_diccionario.clicked.connect(self._abrir_diccionario)
        top.addWidget(self.btn_diccionario)

        root.addLayout(top)

        # ── KPIs ──
        kpis = QHBoxLayout()
        kpis.setSpacing(10)
        self.kpi_indices = self._mk_kpi("Índices catálogo", "0", SLATE_500)
        self.kpi_con_datos = self._mk_kpi("Con valores cargados", "0", GREEN_700)
        self.kpi_valores = self._mk_kpi("Valores totales", "0", BLUE_700)
        from utils.theme import accent_color as _acc
        self.kpi_ultimo = self._mk_kpi("Último período cargado", "—", _acc())
        for k in (self.kpi_indices, self.kpi_con_datos,
                  self.kpi_valores, self.kpi_ultimo):
            kpis.addWidget(k, 1)
        root.addLayout(kpis)

        # ── Filtros ──
        filtros = QFrame()
        filtros.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:1px solid {SILVER_300};"
            f"  border-radius:6px; }}"
        )
        fl = QHBoxLayout(filtros)
        fl.setContentsMargins(10, 8, 10, 8)
        fl.setSpacing(8)

        ico_s = QLabel(); ico_s.setPixmap(icon("buscar").pixmap(16, 16))
        ico_s.setStyleSheet("background:transparent; border:none;")
        fl.addWidget(ico_s)
        self.inp_q = QLineEdit()
        self.inp_q.setPlaceholderText("Buscar por código o nombre…")
        self.inp_q.setClearButtonEnabled(True)
        self._timer_q = QTimer(self)
        self._timer_q.setSingleShot(True)
        self._timer_q.timeout.connect(self._refrescar_lista)
        self.inp_q.textChanged.connect(lambda _: self._timer_q.start(220))
        fl.addWidget(self.inp_q, 2)

        lbl_s = QLabel("Base:")
        lbl_s.setStyleSheet(f"color:{SLATE_500}; font-weight:600;"
                            f" background:transparent; border:none;")
        fl.addWidget(lbl_s)
        self.cmb_serie = QComboBox()
        self.cmb_serie.setMinimumWidth(210)
        self.cmb_serie.setToolTip(
            "El INEI cambió la base en diciembre de 2025 (RJ 016-2026-INEI). "
            "Los índices de una base no se mezclan con los de la otra."
        )
        for clave, nombre in series_disponibles():
            self.cmb_serie.addItem(nombre, clave)
        self.cmb_serie.currentIndexChanged.connect(self._on_serie_change)
        fl.addWidget(self.cmb_serie)

        lbl_a = QLabel("Área:")
        lbl_a.setStyleSheet(f"color:{SLATE_500}; font-weight:600;"
                            f" background:transparent; border:none;")
        fl.addWidget(lbl_a)
        self.cmb_area = QComboBox()
        self.cmb_area.setMinimumWidth(230)
        self.cmb_area.currentIndexChanged.connect(self._on_area_change)
        fl.addWidget(self.cmb_area, 1)

        # Aviso de códigos usados que el catálogo no define. Solo aparece
        # cuando los hay: la biblioteca semilla trae varios.
        self.btn_huerfanos = QPushButton("")
        self.btn_huerfanos.setCursor(Qt.PointingHandCursor)
        self.btn_huerfanos.setStyleSheet(
            "QPushButton { background:#FDE8D0; color:#7A3800;"
            " border:1px solid #F9A65C; border-radius:4px;"
            " padding:5px 10px; font-size:11px; font-weight:700; }"
            "QPushButton:hover { background:#F9A65C; color:white; }"
        )
        self.btn_huerfanos.clicked.connect(self._revisar_huerfanos)
        self.btn_huerfanos.setVisible(False)
        fl.addWidget(self.btn_huerfanos)

        self.btn_nuevo = self._mk_btn("Nuevo índice", icon_name="add")
        self.btn_nuevo.setToolTip("Dar de alta un índice unificado")
        self.btn_nuevo.clicked.connect(self._nuevo_indice)
        fl.addWidget(self.btn_nuevo)

        root.addWidget(filtros)

        # ── Cuerpo: lista de índices ↔ matriz año × mes ──
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_panel_izq())
        split.addWidget(self._build_panel_der())
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        split.setSizes([300, 760])
        root.addWidget(split, 1)

    def _panel(self, titulo: str):
        """Panel a sangre con título fino, el mismo de las demás vistas."""
        fr = QFrame()
        fr.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:1px solid {SILVER_300};"
            f"  border-radius:6px; }}"
        )
        v = QVBoxLayout(fr)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        cab = QFrame()
        cab.setStyleSheet(
            f"QFrame {{ background:{WHITE};"
            f" border:none; border-bottom:1px solid {SILVER_300};"
            f" border-radius:6px 6px 0 0; }}"
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

    def _build_panel_izq(self) -> QWidget:
        fr, v, hl, _ = self._panel("Índices")

        self.lst = QListWidget()
        self.lst.setStyleSheet(
            "QListWidget { border:none; background:white; }"
            "QListWidget::item { padding:6px 10px;"
            " border-bottom:1px solid #F0F1F2; }"
        )
        # Los nombres largos no deben sacar una barra horizontal: se recortan
        # con puntos suspensivos, como en el resto de las listas del programa.
        self.lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lst.setTextElideMode(Qt.ElideRight)
        self.lst.setWordWrap(False)
        self.lst.itemSelectionChanged.connect(self._on_lst_change)
        self.lst.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lst.customContextMenuRequested.connect(self._menu_indices)
        self.lst.itemDoubleClicked.connect(
            lambda it: self._editar_indice(it.data(Qt.UserRole))
        )
        v.addWidget(self.lst, 1)
        return fr

    def _build_panel_der(self) -> QWidget:
        fr, v, hl, lbl = self._panel("Selecciona un índice")
        self.lbl_titulo_matriz = lbl

        btn_add_anio = QPushButton("Agregar año")
        btn_add_anio.setIcon(icon("add"))
        btn_add_anio.setIconSize(QSize(13, 13))
        btn_add_anio.setCursor(Qt.PointingHandCursor)
        btn_add_anio.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:4px;"
            f" padding:4px 10px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f" border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        btn_add_anio.clicked.connect(self._agregar_anio)
        hl.addWidget(btn_add_anio)

        # Tabla pivot: filas = años, cols = Ene..Dic + Promedio
        self.tbl = QTableWidget(0, 13)
        self.tbl.setHorizontalHeaderLabels(MESES_LARGOS + ["Promedio"])
        self.tbl.verticalHeader().setVisible(True)
        self.tbl.verticalHeader().setDefaultSectionSize(28)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.tbl.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setShowGrid(True)
        self.tbl.setStyleSheet(
            "QTableWidget { background:white; border:none;"
            " gridline-color: #ECECEC; font-size:12px; }"
            "QTableWidget::item { padding:4px 6px; }"
            f"QHeaderView::section {{ background:{SILVER_100};"
            f"  color:{SLATE_500}; padding:6px 8px; border:none;"
            f"  border-right:1px solid {SILVER_300};"
            f"  border-bottom:1px solid {SILVER_300};"
            f"  font-size:11px; font-weight:700; }}"
        )
        h = self.tbl.horizontalHeader()
        for c in range(12):
            h.setSectionResizeMode(c, QHeaderView.Stretch)
        h.setSectionResizeMode(12, QHeaderView.Fixed)
        h.resizeSection(12, 90)
        self.tbl.setItemDelegate(EditorPlenoDelegate(self.tbl))
        self.tbl.itemChanged.connect(self._on_celda_cambiada)

        QShortcut(QKeySequence("Delete"), self.tbl,
                  activated=self._eliminar_valor_seleccionado)
        v.addWidget(self.tbl, 1)
        return fr

    def _mk_btn(self, text: str, icon_name: str | None = None,
                primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(32)
        if icon_name:
            b.setIcon(icon(icon_name))
            b.setIconSize(QSize(16, 16))
        if primary:
            from utils.theme import BTN_PRIMARY_SS
            b.setStyleSheet(BTN_PRIMARY_SS)
        else:
            b.setStyleSheet(
                f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
                f"  border:1px solid {SILVER_300}; border-radius:6px;"
                f"  padding:6px 12px; font-size:12px; }}"
                f"QPushButton:hover {{ background:{ORANGE_SOFT};"
                f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
            )
        return b

    def _mk_kpi(self, etiqueta: str, valor: str, color: str) -> QFrame:
        """Card KPI del sistema de diseño, un punto más apretada que la de
        los catálogos: esta fila lleva cuatro KPIs y una barra de filtros."""
        from utils.theme import crear_kpi_card
        return crear_kpi_card(etiqueta, valor, color,
                              margenes=(14, 8, 14, 8), espaciado=0)

    # ── Carga inicial ───────────────────────────────────────────────────────
    def _cargar_todo(self):
        # Áreas
        self.cmb_area.blockSignals(True)
        self.cmb_area.clear()
        for a in listar_areas(serie=self._serie_actual):
            self.cmb_area.addItem(f"{a['codigo']} — {a['nombre']}", a['codigo'])
        self.cmb_area.blockSignals(False)
        self._area_actual = self.cmb_area.itemData(0) or '01'

        self._refrescar_lista()
        self._actualizar_kpis()

    def _refrescar_lista(self):
        q = self.inp_q.text().strip().lower() if hasattr(self, 'inp_q') else ''
        indices = listar_indices(serie=self._serie_actual)
        self._indices_cache = [(i['codigo'], i['nombre']) for i in indices]
        anterior = self._codigo_actual

        self.lst.blockSignals(True)
        self.lst.clear()
        cnt = 0
        for ind in indices:
            txt = f"{ind['codigo']}  ·  {ind['nombre']}"
            if q and q not in ind['codigo'].lower() and q not in ind['nombre'].lower():
                continue
            cnt += 1
            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, ind['codigo'])
            # Badge con último período si existe
            if ind['ultimo_periodo']:
                it.setToolTip(
                    f"{ind['nombre']}\n"
                    f"{ind['n_valores']} valores · último: "
                    f"{ind['ultimo_periodo']} = {ind['ultimo_valor']:.2f}"
                )
            self.lst.addItem(it)
        self.lst.blockSignals(False)

        if anterior:
            # Re-seleccionar el código actual si existe
            for i in range(self.lst.count()):
                if self.lst.item(i).data(Qt.UserRole) == anterior:
                    self.lst.setCurrentRow(i)
                    break
        if self.lst.count() and self.lst.currentRow() < 0:
            self.lst.setCurrentRow(0)
        self.lbl_subt.setText(f"  ·  {cnt} índices")
        self._actualizar_huerfanos()

    def _actualizar_kpis(self):
        from core.database import get_db
        conn = get_db()
        n_indices = conn.execute(
            "SELECT COUNT(*) FROM indices_inei WHERE serie=?",
            (self._serie_actual,)).fetchone()[0]
        n_con_datos = conn.execute(
            "SELECT COUNT(DISTINCT codigo) FROM indices_inei_valores "
            "WHERE area=? AND serie=?", (self._area_actual, self._serie_actual)
        ).fetchone()[0]
        n_valores = conn.execute(
            "SELECT COUNT(*) FROM indices_inei_valores WHERE area=? AND serie=?",
            (self._area_actual, self._serie_actual)
        ).fetchone()[0]
        ult = conn.execute(
            "SELECT anio, mes FROM indices_inei_valores WHERE area=? AND serie=? "
            "ORDER BY anio DESC, mes DESC LIMIT 1",
            (self._area_actual, self._serie_actual)
        ).fetchone()
        conn.close()
        self.kpi_indices.lbl_valor.setText(str(n_indices))
        self.kpi_con_datos.lbl_valor.setText(str(n_con_datos))
        self.kpi_valores.lbl_valor.setText(str(n_valores))
        self.kpi_ultimo.lbl_valor.setText(
            f"{ult['anio']}-{ult['mes']:02d}" if ult else "—"
        )

    # ── Catálogo: alta, edición y baja ──────────────────────────────────────
    def _menu_indices(self, pos):
        """Editar · Eliminar sobre el índice bajo el cursor."""
        it = self.lst.itemAt(pos)
        if it is None:
            return
        codigo = it.data(Qt.UserRole)
        m = QMenu(self)
        a_edit = QAction(icon("editar"), "Editar", self)
        a_edit.triggered.connect(lambda: self._editar_indice(codigo))
        m.addAction(a_edit)
        a_new = QAction(icon("add"), "Nuevo índice", self)
        a_new.triggered.connect(self._nuevo_indice)
        m.addAction(a_new)
        m.addSeparator()
        a_del = QAction(icon("eliminar"), "Eliminar", self)
        a_del.triggered.connect(lambda: self._eliminar_indice_ui(codigo))
        m.addAction(a_del)
        m.exec(self.lst.viewport().mapToGlobal(pos))

    def _nuevo_indice(self):
        dlg = DialogoIndice(self)
        if dlg.exec() != QDialog.Accepted:
            return
        codigo, nombre = dlg.datos()
        try:
            codigo = crear_indice(codigo, nombre, serie=self._serie_actual)
        except ValueError as e:
            QMessageBox.warning(self, "No se pudo crear", str(e))
            return
        self._codigo_actual = codigo
        self._refrescar_lista()
        self._actualizar_kpis()

    def _editar_indice(self, codigo: str):
        if not codigo:
            return
        nombre = dict(self._indices_cache).get(codigo, "")
        dlg = DialogoIndice(self, codigo=codigo, nombre=nombre)
        if dlg.exec() != QDialog.Accepted:
            return
        _, nombre_nuevo = dlg.datos()
        actualizar_indice(codigo, nombre=nombre_nuevo, serie=self._serie_actual)
        self._refrescar_lista()

    def _eliminar_indice_ui(self, codigo: str):
        """Baja del catálogo, avisando qué queda apuntando al código.

        No hay clave foránea: borrar no rompe el SQL, pero deja insumos con un
        índice que ya no existe. Por eso se enumera antes y los insumos NO se
        tocan — reasignarlos es decisión del usuario.
        """
        if not codigo:
            return
        nombre = dict(self._indices_cache).get(codigo, "")
        usos = contar_usos(codigo, serie=self._serie_actual)
        detalle = []
        if usos['recursos']:
            detalle.append(f"{usos['recursos']} insumo(s) lo tienen asignado")
        if usos['valores']:
            detalle.append(f"{usos['valores']} valor(es) del histórico")
        if usos['monomios']:
            detalle.append(f"{usos['monomios']} monomio(s) de fórmulas guardadas")

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Eliminar índice unificado")
        msg.setText(f"¿Eliminar el índice {codigo} — {nombre}?")
        if detalle:
            msg.setInformativeText(
                "Quedarán apuntando a un código que ya no existe:\n· "
                + "\n· ".join(detalle)
                + "\n\nLos insumos no se modifican."
            )
        else:
            msg.setInformativeText("No lo usa nadie.")
        btn_si = msg.addButton("Eliminar", QMessageBox.DestructiveRole)
        msg.addButton("Cancelar", QMessageBox.RejectRole)
        msg.exec()
        if msg.clickedButton() is not btn_si:
            return

        borrar_valores = False
        if usos['valores']:
            r = QMessageBox.question(
                self, "Histórico del índice",
                f"¿Borrar también sus {usos['valores']} valores del histórico?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            borrar_valores = (r == QMessageBox.Yes)

        eliminar_indice(codigo, borrar_valores=borrar_valores,
                        serie=self._serie_actual)
        if self._codigo_actual == codigo:
            self._codigo_actual = None
            self._limpiar_matriz()
        self._refrescar_lista()
        self._actualizar_kpis()

    def _actualizar_huerfanos(self):
        """Refresca el aviso de códigos usados que el catálogo no define."""
        try:
            self._huerfanos = codigos_huerfanos(serie=self._serie_actual)
        except Exception:
            self._huerfanos = []
        n = len(self._huerfanos)
        self.btn_huerfanos.setVisible(bool(n))
        if n:
            desc = sum(1 for h in self._huerfanos if h['descontinuado'])
            self.btn_huerfanos.setText(f"{n} códigos inválidos")
            self.btn_huerfanos.setToolTip(
                f"{n} códigos usados por insumos no están en el catálogo de "
                f"esta base"
                + (f" — {desc} los descontinuó el INEI al reagruparlos"
                   if desc else "")
                + ". Clic para ver qué hacer."
            )

    def _revisar_huerfanos(self):
        """Qué hacer con los códigos que el catálogo de la serie no define.

        Antes esto ofrecía «darlos de alta» con un nombre provisional, y era un
        mal consejo: la mayoría son códigos que el INEI RETIRÓ al reagruparlos
        —el 22 y el 23, «Cemento Portland Tipo II» y «Tipo V», los absorbió el
        21— o que nunca fueron suyos, como el 99 de las bibliotecas importadas,
        que acá son 319 subcontratos. Crearlos inventaría índices que el INEI no
        publica y que NUNCA tendrán valores, así que el reajuste de esa parte
        del costo quedaría sin poder calcularse.

        Lo que corresponde es reasignar esos insumos a códigos vigentes, que es
        justo lo que hace el diccionario.
        """
        if not getattr(self, '_huerfanos', None):
            return
        desc = [h for h in self._huerfanos if h['descontinuado']]
        desc_n = sum(h['n_recursos'] for h in desc)
        otros = [h for h in self._huerfanos if not h['descontinuado']]
        otros_n = sum(h['n_recursos'] for h in otros)

        def _lista(hs, con_nombre):
            return "\n".join(
                f"· {h['codigo']} — {h['n_recursos']} insumo(s)"
                + (f"   ({h['nombre_anterior']})" if con_nombre
                   and h['nombre_anterior'] else "")
                for h in hs
            )

        partes = [
            f"{len(self._huerfanos)} código(s) están en uso pero NO figuran en "
            f"el catálogo de la base vigente."
        ]
        if desc:
            partes.append(
                f"\nDESCONTINUADOS por el INEI — existían en la base anterior "
                f"y se reagruparon ({desc_n} insumos):\n" + _lista(desc, True))
        if otros:
            partes.append(
                f"\nSIN ORIGEN OFICIAL — no figuran en ninguna relación del "
                f"INEI; suelen venir de bibliotecas importadas ({otros_n} "
                f"insumos):\n" + _lista(otros, False))
        partes.append(
            "\nLo recomendable es REASIGNAR esos insumos a códigos vigentes "
            "con el diccionario del INEI. Darlos de alta crearía índices que el "
            "INEI no publica: nunca tendrán valores y su parte del reajuste no "
            "se podrá calcular."
        )

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Códigos que el catálogo no define")
        msg.setText("\n".join(partes))
        b_dicc = msg.addButton("Abrir el diccionario", QMessageBox.AcceptRole)
        b_alta = msg.addButton("Darlos de alta igual", QMessageBox.DestructiveRole)
        msg.addButton("Cerrar", QMessageBox.RejectRole)
        msg.setDefaultButton(b_dicc)
        msg.exec()

        if msg.clickedButton() is b_dicc:
            self._abrir_diccionario()
        elif msg.clickedButton() is b_alta:
            n = asegurar_codigos([h['codigo'] for h in self._huerfanos],
                                 serie=self._serie_actual)
            self._refrescar_lista()
            self._actualizar_kpis()
            QMessageBox.information(
                self, "Listo",
                f"{n} índice(s) dados de alta con nombre provisional. "
                f"Edítalos con doble clic; recuerda que el INEI no publica "
                f"valores para ellos."
            )

    def _abrir_diccionario(self):
        """El diccionario insumo → índice unificado.

        Vive acá y no en la vista de Insumos porque es lo que hace utilizable
        el catálogo: sin la asignación, los índices son una lista de precios
        sin nada que agrupar.
        """
        from views.diccionario_iu_dialog import DiccionarioIUDialog
        dlg = DiccionarioIUDialog(self, self._pid_contexto,
                                  self._nombre_contexto)
        dlg.exec()
        self._refrescar_lista()
        self._actualizar_kpis()

    def _on_serie_change(self):
        """Cambiar de base recarga áreas e índices: son catálogos distintos."""
        self._serie_actual = self.cmb_serie.currentData() or SERIE_ACTUAL
        self._codigo_actual = None
        self._limpiar_matriz()
        self.cmb_area.blockSignals(True)
        self.cmb_area.clear()
        for a in listar_areas(serie=self._serie_actual):
            self.cmb_area.addItem(f"{a['codigo']} — {a['nombre']}", a['codigo'])
        self.cmb_area.blockSignals(False)
        self._area_actual = self.cmb_area.itemData(0) or '01'
        self._refrescar_lista()
        self._actualizar_kpis()

    # ── Eventos ─────────────────────────────────────────────────────────────
    def _on_area_change(self):
        self._area_actual = self.cmb_area.currentData() or '01'
        self._actualizar_kpis()
        if self._codigo_actual:
            self._cargar_matriz(self._codigo_actual)

    def _on_lst_change(self):
        items = self.lst.selectedItems()
        if not items:
            self._codigo_actual = None
            self._limpiar_matriz()
            return
        cod = items[0].data(Qt.UserRole)
        self._codigo_actual = cod
        self._cargar_matriz(cod)

    def _limpiar_matriz(self):
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        self.tbl.blockSignals(False)
        self.lbl_titulo_matriz.setText("Selecciona un índice")

    def _cargar_matriz(self, codigo: str):
        # Recuperar nombre del índice
        ind = next((x for x in listar_indices() if x['codigo'] == codigo), None)
        nombre = ind['nombre'] if ind else codigo
        self.lbl_titulo_matriz.setText(f"{codigo}  ·  {nombre}")

        m = obtener_matriz(codigo, self._area_actual, serie=self._serie_actual)
        # Años a mostrar: rango completo desde el mín hasta el actual, o solo el actual
        hoy = datetime.now().year
        if m:
            anio_min = min(m.keys())
            anio_max = max(max(m.keys()), hoy)
        else:
            anio_min = hoy
            anio_max = hoy

        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        for anio in range(anio_min, anio_max + 1):
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            self.tbl.setVerticalHeaderItem(row, QTableWidgetItem(str(anio)))
            data_anio = m.get(anio, {})
            for mes in range(1, 13):
                v = data_anio.get(mes)
                txt = f"{v:.4f}".rstrip('0').rstrip('.') if v is not None else ""
                it = QTableWidgetItem(txt)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it.setData(Qt.UserRole, anio)
                it.setData(Qt.UserRole + 1, mes)
                if v is not None:
                    f = QFont(); f.setWeight(QFont.DemiBold)
                    it.setFont(f)
                    it.setForeground(QColor(SLATE_700))
                else:
                    it.setForeground(QColor(SLATE_300))
                self.tbl.setItem(row, mes - 1, it)
            # Promedio (solo lectura)
            valores = [v for v in data_anio.values() if v is not None]
            avg = sum(valores) / len(valores) if valores else 0
            it_avg = QTableWidgetItem(f"{avg:.4f}".rstrip('0').rstrip('.')
                                      if valores else "—")
            it_avg.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_avg.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            it_avg.setForeground(QColor(ORANGE_DARK) if valores else QColor(SLATE_300))
            f = QFont(); f.setBold(True)
            it_avg.setFont(f)
            self.tbl.setItem(row, 12, it_avg)
        self.tbl.blockSignals(False)

    def _agregar_anio(self):
        if not self._codigo_actual:
            return
        # Agregar fila al año siguiente del más alto actualmente mostrado
        if self.tbl.rowCount() == 0:
            anio = datetime.now().year
        else:
            ultimo = int(self.tbl.verticalHeaderItem(
                self.tbl.rowCount() - 1
            ).text())
            anio = ultimo + 1
        self.tbl.blockSignals(True)
        row = self.tbl.rowCount()
        self.tbl.insertRow(row)
        self.tbl.setVerticalHeaderItem(row, QTableWidgetItem(str(anio)))
        for mes in range(1, 13):
            it = QTableWidgetItem("")
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it.setData(Qt.UserRole, anio)
            it.setData(Qt.UserRole + 1, mes)
            it.setForeground(QColor(SLATE_300))
            self.tbl.setItem(row, mes - 1, it)
        it_avg = QTableWidgetItem("—")
        it_avg.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it_avg.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it_avg.setForeground(QColor(SLATE_300))
        self.tbl.setItem(row, 12, it_avg)
        self.tbl.blockSignals(False)
        self.tbl.scrollToBottom()
        # Foco en enero del nuevo año
        self.tbl.setCurrentCell(row, 0)
        self.tbl.editItem(self.tbl.item(row, 0))

    def _on_celda_cambiada(self, item: QTableWidgetItem):
        if not self._codigo_actual or item.column() >= 12:
            return
        anio = item.data(Qt.UserRole)
        mes = item.data(Qt.UserRole + 1)
        if anio is None or mes is None:
            return
        txt = item.text().strip()
        if not txt:
            eliminar_valor(self._codigo_actual, anio, mes, self._area_actual,
                           serie=self._serie_actual)
            self.tbl.blockSignals(True)
            item.setForeground(QColor(SLATE_300))
            self.tbl.blockSignals(False)
        else:
            valor = parse_num(txt)
            if valor <= 0:
                return
            guardar_valor(self._codigo_actual, anio, mes, valor,
                          self._area_actual, serie=self._serie_actual)
            self.tbl.blockSignals(True)
            item.setText(f"{valor:.4f}".rstrip('0').rstrip('.'))
            f = QFont(); f.setWeight(QFont.DemiBold)
            item.setFont(f)
            item.setForeground(QColor(SLATE_700))
            self.tbl.blockSignals(False)
        # Recalcular promedio + KPIs + tooltip de la lista
        self._recalcular_promedio_fila(item.row())
        self._actualizar_kpis()
        self._refrescar_lista()

    def _recalcular_promedio_fila(self, row: int):
        valores: list[float] = []
        for c in range(12):
            it = self.tbl.item(row, c)
            if it and it.text().strip():
                v = parse_num_opt(it.text())
                if v is not None:
                    valores.append(v)
        it_avg = self.tbl.item(row, 12)
        if not it_avg:
            return
        self.tbl.blockSignals(True)
        if valores:
            avg = sum(valores) / len(valores)
            it_avg.setText(f"{avg:.4f}".rstrip('0').rstrip('.'))
            it_avg.setForeground(QColor(ORANGE_DARK))
        else:
            it_avg.setText("—")
            it_avg.setForeground(QColor(SLATE_300))
        self.tbl.blockSignals(False)

    def _eliminar_valor_seleccionado(self):
        sel = self.tbl.selectedItems()
        if not sel or not self._codigo_actual:
            return
        for it in sel:
            if it.column() >= 12:
                continue
            self.tbl.blockSignals(True)
            it.setText("")
            self.tbl.blockSignals(False)
            self._on_celda_cambiada(it)

    # ── Sincronizar automáticamente con INEI ────────────────────────────────
    def _sincronizar_inei(self):
        """Trae del INEI todo lo publicado para la base que se está viendo.

        Son DOS fuentes oficiales y hacen falta las dos:

        * el **Excel** de la base — un archivo acumulativo, pero el INEI lo
          actualiza cuando quiere: a agosto de 2026 seguía con datos hasta
          marzo;
        * las **resoluciones jefaturales mensuales**, que sí salen puntuales
          (la de julio se publicó el 19 de agosto) y gob.pe enlaza en PDF.

        Antes solo se pedía el Excel y por eso la app se quedaba clavada en el
        último mes que al INEI se le hubiera ocurrido subir.
        """
        self.btn_auto.setEnabled(False)
        QApplication.processEvents()
        filas: list[dict] = []
        fuentes: list[str] = []
        problemas: list[str] = []

        try:
            # ── 0) el histórico publicado ──
            # Es el más completo y el más barato: un solo archivo con las dos
            # bases, ya reconciliado, que una Action mantiene al día dos veces
            # al mes. Las otras fuentes siguen detrás por si no responde o por
            # si el INEI publicó antes de que la Action corriera.
            self.btn_auto.setText("Buscando el histórico publicado…")
            QApplication.processEvents()
            pub = descargar_indices_publicados()
            if pub.get('ok') and pub.get('rows'):
                propias = [r for r in pub['rows']
                           if r.get('serie') == self._serie_actual]
                if propias:
                    filas += propias
                    fuentes.append(
                        f"Histórico publicado del {pub.get('generado', '?')} "
                        f"({pub.get('tamano_kb', 0)} KB) — "
                        f"{self._rango_de(propias)}")
            else:
                problemas.append(pub.get('msg') or "No se pudo leer el histórico.")

            # ── 1) el Excel de la base ──
            self.btn_auto.setText("Buscando el archivo del INEI…")
            QApplication.processEvents()
            busq = buscar_ultimo_excel_inei(self._serie_actual)
            url_excel = busq.get('url')
            if busq['ok']:
                self.btn_auto.setText("Descargando el archivo…")
                QApplication.processEvents()
                res = descargar_desde_url(
                    busq['url'], area=self._area_actual,
                    anio_override=busq['anio_detectado'],
                    serie=busq.get('serie', self._serie_actual))
                if res.get('ok') and res.get('rows'):
                    filas += res['rows']
                    fuentes.append(
                        f"Archivo del INEI ({res.get('tamano_kb', 0)} KB) — "
                        f"{self._rango_de(res['rows'])}")
                else:
                    problemas.append(res.get('msg') or "El archivo no trajo datos.")
            else:
                problemas.append(busq.get('msg') or "No se encontró el archivo.")

            # ── 2) las resoluciones mensuales ──
            self.btn_auto.setText("Buscando resoluciones del mes…")
            QApplication.processEvents()
            try:
                resoluciones = buscar_resoluciones_gobpe()
            except Exception as e:
                resoluciones = []
                problemas.append(f"No se pudo consultar gob.pe: {e}")
            for r in resoluciones:
                if serie_de(r['anio'], r['mes']) != self._serie_actual:
                    continue
                self.btn_auto.setText(
                    f"Descargando R.J. {r['resolucion']}…")
                QApplication.processEvents()
                dr = descargar_resolucion_gobpe(r['url'],
                                                serie=self._serie_actual)
                if dr.get('ok') and dr.get('rows'):
                    filas += dr['rows']
                    fuentes.append(
                        f"R.J. {r['resolucion']} — {r['titulo'].title()} "
                        f"({dr.get('tamano_kb', 0)} KB)")
                else:
                    problemas.append(
                        f"R.J. {r['resolucion']}: {dr.get('msg', '')}")

            if not filas:
                QMessageBox.warning(
                    self, "Sincronizar con INEI",
                    "\n".join(problemas) or "No se encontró nada que importar.")
                return

            res_total = {
                'ok': True, 'rows': filas, 'ignorados': 0,
                'serie': self._serie_actual,
                'codigos_encontrados': {r['codigo'] for r in filas},
                'url': pub.get('url') if pub.get('ok') else url_excel,
            }
            fuente = "<br>".join("• " + f for f in fuentes)
            if problemas:
                fuente += "<br><i>" + "<br>".join(problemas[:2]) + "</i>"
            self._procesar_resultado_import(res_total, fuente=fuente)
        finally:
            self.btn_auto.setEnabled(True)
            self.btn_auto.setText("Sincronizar con INEI")

    def _meses_faltantes(self, filas: list[dict]) -> list[tuple[int, int]]:
        """Meses sin ningún índice entre el primero y el último que se tendría.

        Importa saberlo antes de calcular un reajuste: si falta el mes de la
        valorización no hay K que valga. Y pasa de verdad — el INEI publica el
        Excel acumulado cuando quiere (a agosto de 2026 iba por marzo) y en
        gob.pe solo deja el PDF del mes vigente, así que en medio quedan huecos
        que hay que cargar a mano desde El Peruano.
        """
        per = {(r['anio'], r['mes']) for r in filas
               if r.get('anio') and r.get('mes')}
        try:
            with get_db() as conn:
                per |= {(a, m) for a, m in conn.execute(
                    "SELECT DISTINCT anio, mes FROM indices_inei_valores "
                    "WHERE serie=?", (self._serie_actual,))}
        except Exception:
            pass
        if len(per) < 2:
            return []
        ords = sorted(a * 12 + (m - 1) for a, m in per)
        return [(o // 12, o % 12 + 1)
                for o in range(ords[0], ords[-1]) if o not in set(ords)]

    @staticmethod
    def _rango_de(filas: list[dict]) -> str:
        """«2026-01 a 2026-03 (3 meses)» a partir de las filas importadas."""
        per = sorted({(f.get('anio'), f.get('mes')) for f in filas
                      if f.get('anio') and f.get('mes')})
        if not per:
            return "sin períodos"
        if len(per) == 1:
            return f"{per[0][0]}-{per[0][1]:02d}"
        return (f"{per[0][0]}-{per[0][1]:02d} a {per[-1][0]}-{per[-1][1]:02d} "
                f"({len(per)} meses)")

    # ── Descargar desde URL ─────────────────────────────────────────────────
    def _descargar_url(self):
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QLineEdit, QFormLayout, QSpinBox,
            QLabel as _QLabel, QVBoxLayout as _QV
        )

        # Diálogo personalizado: URL + año override opcional
        dlg = QDialog(self)
        dlg.setWindowTitle("Descargar Excel desde URL")
        dlg.setMinimumWidth(520)
        v = _QV(dlg)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        intro = _QLabel(
            "Pega aquí el enlace directo al archivo <b>.xlsx</b> publicado por "
            "el INEI (o cualquier fuente).<br><br>"
            "<b>Tip:</b> usa el botón <i>«Sincronizar con INEI»</i> para "
            "descargar automáticamente el último archivo. Esta opción es "
            "para descargar un mes específico o desde otra fuente.<br><br>"
            "<b>Cómo conseguirlo manualmente:</b><br>"
            "1. Abre:<br>"
            "&nbsp;&nbsp;<a href='https://www.inei.gob.pe/estadisticas/indice-tematico/price-indexes/'>"
            "inei.gob.pe — Índices de Precios</a><br>"
            "2. <b>Clic derecho</b> sobre el enlace del Excel del mes deseado.<br>"
            "3. <b>«Copiar dirección del enlace»</b>.<br>"
            "4. Pega aquí abajo y pulsa <b>Descargar</b>."
        )
        intro.setOpenExternalLinks(True)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        intro.setStyleSheet(f"color:{SLATE_500}; font-size:12px;")
        v.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)
        inp_url = QLineEdit()
        inp_url.setPlaceholderText("https://m.inei.gob.pe/.../iu-XXXxxxx.xlsx")
        # Auto-pegar desde clipboard si tiene un URL
        from PySide6.QtWidgets import QApplication as _QApp
        cb = _QApp.clipboard().text().strip()
        if cb.startswith("http://") or cb.startswith("https://"):
            inp_url.setText(cb)
        form.addRow("URL:", inp_url)

        inp_anio = QSpinBox()
        inp_anio.setRange(0, 2100)
        inp_anio.setSpecialValueText("(detectar automáticamente)")
        inp_anio.setValue(0)
        form.addRow("Año (opcional):", inp_anio)

        info_area = _QLabel(
            f"Los datos se cargarán para el área actual: "
            f"<b>{self.cmb_area.currentText()[:50]}</b>"
        )
        info_area.setStyleSheet(f"color:{SLATE_300}; font-size:11px;")
        info_area.setTextFormat(Qt.RichText)
        info_area.setWordWrap(True)
        v.addLayout(form)
        v.addWidget(info_area)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Descargar e importar")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return
        url = inp_url.text().strip()
        if not url:
            return
        anio_ovr = inp_anio.value() if inp_anio.value() > 1990 else None

        # Indicador visual de progreso (cambiar texto del botón)
        self.btn_url.setEnabled(False)
        self.btn_url.setText("Descargando…")
        QApplication.processEvents()
        try:
            res = descargar_desde_url(url, area=self._area_actual,
                                       anio_override=anio_ovr)
        finally:
            self.btn_url.setEnabled(True)
            self.btn_url.setText("Descargar desde URL")

        self._procesar_resultado_import(res, fuente=f"URL ({url[:60]}…)")

    # ── Pegar desde portapapeles ────────────────────────────────────────────
    def _pegar_datos(self):
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QTextEdit as _QText, QSpinBox,
            QLabel as _QLabel, QVBoxLayout as _QV
        )
        from PySide6.QtWidgets import QApplication as _QApp

        dlg = QDialog(self)
        dlg.setWindowTitle("Pegar datos INEI desde portapapeles")
        dlg.setMinimumSize(720, 480)
        v = _QV(dlg)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        intro = _QLabel(
            "Pega aquí una tabla de cualquier fuente (Excel, página web, PDF, "
            "etc.).<br>"
            "<b>Formato esperado:</b> primera columna = código INEI, "
            "siguientes columnas = meses (Ene–Dic o 1–12).<br>"
            "El parser detecta automáticamente el separador (tab, coma, "
            "punto y coma)."
        )
        intro.setTextFormat(Qt.RichText)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{SLATE_500}; font-size:12px;")
        v.addWidget(intro)

        txt = _QText()
        txt.setPlaceholderText(
            "Ejemplo:\n"
            "Código\tEne\tFeb\tMar\tAbr\tMay\tJun\tJul\tAgo\tSep\tOct\tNov\tDic\n"
            "47\t1245.32\t1267.81\t1290.55\t1310.20\t1325.40\t...\n"
            "39\t1124.10\t1135.50\t1145.20\t..."
        )
        f_mono = QFont("monospace"); f_mono.setPointSize(10)
        txt.setFont(f_mono)
        # Auto-poblar con el clipboard si tiene texto
        clip = _QApp.clipboard().text()
        if clip.strip() and (',' in clip or '\t' in clip or ';' in clip):
            txt.setPlainText(clip)
        v.addWidget(txt, 1)

        # Fila inferior: año override
        from PySide6.QtWidgets import QHBoxLayout as _QH
        bottom = _QH()
        bottom.addWidget(_QLabel("Año:"))
        inp_anio = QSpinBox()
        inp_anio.setRange(0, 2100)
        inp_anio.setSpecialValueText("(detectar automáticamente)")
        inp_anio.setValue(0)
        bottom.addWidget(inp_anio)
        bottom.addStretch(1)

        info_area = _QLabel(
            f"Área destino: <b>{self.cmb_area.currentText()[:50]}</b>"
        )
        info_area.setStyleSheet(f"color:{SLATE_300}; font-size:11px;")
        info_area.setTextFormat(Qt.RichText)
        bottom.addWidget(info_area)
        v.addLayout(bottom)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Procesar datos")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return
        texto = txt.toPlainText()
        if not texto.strip():
            return
        anio_ovr = inp_anio.value() if inp_anio.value() > 1990 else None

        res = importar_desde_texto(texto, area=self._area_actual,
                                    anio_override=anio_ovr)
        self._procesar_resultado_import(res, fuente="Portapapeles")

    def _procesar_resultado_import(self, res: dict, fuente: str = ""):
        """Aplica el resultado de un importador: confirma y persiste."""
        if not res.get('ok'):
            QMessageBox.warning(
                self, "Importar",
                res.get('msg') or "No se pudo procesar."
            )
            return

        if not res['rows']:
            QMessageBox.information(
                self, "Importar",
                "No se detectaron valores nuevos."
            )
            return

        codigos = sorted(res.get('codigos_encontrados') or set())
        cod_preview = ", ".join(codigos[:8])
        if len(codigos) > 8:
            cod_preview += f"… (+{len(codigos) - 8} más)"

        # Qué períodos trae el archivo, para poder contrastarlo con el INEI sin
        # tener que abrirlo: es la pregunta que uno se hace al sincronizar.
        periodos = sorted({(r.get('anio'), r.get('mes')) for r in res['rows']
                           if r.get('anio') and r.get('mes')})
        if periodos:
            rango = (f"{periodos[0][0]}-{periodos[0][1]:02d}"
                     if len(periodos) == 1 else
                     f"{periodos[0][0]}-{periodos[0][1]:02d} a "
                     f"{periodos[-1][0]}-{periodos[-1][1]:02d}"
                     f"  ({len(periodos)} meses)")
        else:
            rango = "(no detectados)"

        areas = sorted({r.get('area') for r in res['rows'] if r.get('area')})
        destino = (f"{len(areas)} áreas del archivo" if len(areas) > 1
                   else f"área {self._area_actual}")

        msg = (f"<b>Fuente:</b> {fuente}<br>"
               f"<b>Períodos en el archivo:</b> {rango}<br>"
               f"<b>Base:</b> {serie_nombre(res.get('serie', ''))}<br>"
               f"<b>Destino:</b> {destino}<br>"
               f"<b>Índices encontrados:</b> {len(codigos)} ({cod_preview})<br>"
               f"<b>Valores a importar:</b> {len(res['rows'])}<br>"
               f"<b>Ignorados:</b> {res.get('ignorados', 0)}<br>")
        if res.get('url'):
            msg += (f"<b>Archivo:</b> <a href='{res['url']}'>"
                    f"{res['url'].rsplit('/', 1)[-1]}</a><br>")
        faltan = self._meses_faltantes(res['rows'])
        if faltan:
            lista = ", ".join(f"{a}-{m:02d}" for a, m in faltan[:8])
            if len(faltan) > 8:
                lista += f"… (+{len(faltan) - 8} más)"
            msg += (f"<b>Quedarían sin datos:</b> {lista}<br>"
                    f"<span style='color:#6B7280'>El INEI deja en gob.pe solo "
                    f"el PDF del mes vigente; esos meses se cargan con "
                    f"«Importar ▾ → Pegar datos del portapapeles» desde El "
                    f"Peruano.</span><br>")
        msg += "<br>¿Importar? (los valores existentes se reemplazarán.)"

        caja = QMessageBox(self)
        caja.setIcon(QMessageBox.Question)
        caja.setWindowTitle("Confirmar importación")
        caja.setTextFormat(Qt.RichText)
        caja.setText(msg)
        # El enlace abre el archivo en el navegador, para verificar la fuente.
        lbl = caja.findChild(QLabel, "qt_msgbox_label")
        if lbl is not None:
            lbl.setOpenExternalLinks(True)
        caja.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        caja.setDefaultButton(QMessageBox.Yes)
        if caja.exec() != QMessageBox.Yes:
            return

        ok_n, err_n = guardar_valores(res['rows'])
        self._actualizar_kpis()
        self._refrescar_lista()
        if self._codigo_actual:
            self._cargar_matriz(self._codigo_actual)
        QMessageBox.information(
            self, "Importación completa",
            f"{ok_n} valores importados, {err_n} ignorados."
        )

    # ── Importar Excel INEI ─────────────────────────────────────────────────
    def _importar_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar Excel INEI", "", "Excel (*.xlsx *.xls)"
        )
        if not path:
            return
        res = importar_excel_inei(path, area=self._area_actual)
        self._procesar_resultado_import(res, fuente=Path(path).name)

    def _importar_delphin_sqlite(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar histórico INEI desde Delphin Express",
            "", "Bases de datos Delphin (*.sqlite *.db)"
        )
        if not path:
            return

        # Pre-confirmación
        msg = (
            "Se va a importar el histórico completo de índices INEI desde la "
            "base de datos de Delphin Express.\n\n"
            "Mapeo de regiones Delphin → áreas INEI ingePresupuestos:\n"
            "  • Región 1 (Costa Norte)   → 02 Norte\n"
            "  • Región 2 (Lima/Centro)   → 01 Lima Metropolitana\n"
            "  • Región 3 (Sierra Centro) → 03 Centro\n"
            "  • Región 4 (Sur Costa)     → 05 Sur\n"
            "  • Región 5 (Loreto/Selva)  → 04 Sur Medio y Selva\n"
            "  • Región 6 (Sierra Sur)    → 06 Nacional\n\n"
            "Los valores existentes con la misma combinación "
            "(código, año, mes, área) serán reemplazados.\n\n"
            "¿Continuar?"
        )
        r = QMessageBox.question(
            self, "Importar histórico INEI desde Delphin", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if r != QMessageBox.Yes:
            return

        try:
            from core.delphin_sqlite_importer import import_inei_delphin_sqlite
            res = import_inei_delphin_sqlite(path)
        except Exception as e:
            QMessageBox.critical(
                self, "Importar histórico INEI desde Delphin",
                f"No se pudo leer la base de datos:\n\n{e}"
            )
            return

        anios = res['anios']
        rango_anios = (f"{anios[0]} – {anios[-1]} ({len(anios)} años)"
                       if anios else "—")
        resumen = (
            f"Importación completada.\n\n"
            f"  Filas leídas:      {res['n_filas_origen']:,}\n"
            f"  Valores guardados: {res['n_insertadas']:,}\n"
            f"  Filas ignoradas:   {res['n_ignoradas']:,}\n\n"
            f"  Años:              {rango_anios}\n"
            f"  Códigos INEI:      {len(res['codigos'])}\n"
            f"  Regiones Delphin:  {len(res['regiones_origen'])}\n"
            f"  Áreas pobladas:    {', '.join(res['areas_destino'])}"
        )
        self._actualizar_kpis()
        self._refrescar_lista()
        if self._codigo_actual:
            self._cargar_matriz(self._codigo_actual)
        QMessageBox.information(
            self, "Importar histórico INEI desde Delphin", resumen
        )

    def _importar_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar JSON de índices INEI", "", "JSON (*.json)"
        )
        if not path:
            return
        res = importar_json(path)
        if not res['ok']:
            QMessageBox.warning(self, "Importar JSON", res.get('msg'))
            return
        self._actualizar_kpis()
        self._refrescar_lista()
        if self._codigo_actual:
            self._cargar_matriz(self._codigo_actual)
        QMessageBox.information(self, "Importar JSON", res['msg'])

    def _exportar_json(self):
        from datetime import datetime as _dt
        fecha = _dt.now().strftime("%Y%m%d_%H%M")
        sugerido = f"indices_inei_{self._area_actual}_{fecha}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar JSON de índices INEI", sugerido, "JSON (*.json)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            n = exportar_json(path, area=self._area_actual)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar:\n{e}")
            return
        QMessageBox.information(
            self, "Exportado",
            f"{n} valores exportados a:\n{path}"
        )


