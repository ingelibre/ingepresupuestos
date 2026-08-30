# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""diccionario_iu_dialog — el diccionario insumo → índice unificado.

Tres cosas en una ventana, que son las que pidió el usuario:

* ver cuántos insumos están sin clasificar (y cuánto pesan);
* clasificarlos en tanda, con propuestas por parecido de descripción que él
  acepta o descarta — nunca automáticas, porque asignar mal un índice mueve
  plata de un monomio a otro de la fórmula polinómica;
* llevarse el diccionario a otra instalación (exportar / importar JSON).

Las propuestas ambiguas —las que tienen un rival cercano de OTRO índice, como
«CEMENTO PORTLAND TIPO V» contra «TIPO I»— vienen desmarcadas y en ámbar.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QComboBox, QMessageBox,
    QFileDialog, QSpinBox, QFrame, QCheckBox,
)

from core import diccionario_iu as DIC
from core.indices_inei import catalogo
from utils.icons import icon

SLATE_700 = "#273445"
SLATE_500 = "#485A6C"
SLATE_300 = "#667885"
SILVER_100 = "#F8F9FA"
SILVER_300 = "#D4D4D4"
AMBAR_SOFT = "#FEF3C7"
AMBAR_DARK = "#92400E"
WHITE = "#FFFFFF"


class DiccionarioIUDialog(QDialog):
    """Clasificación en tanda de los insumos sin índice unificado."""

    def __init__(self, parent=None, proyecto_id: int | None = None,
                 proyecto_nombre: str = ''):
        super().__init__(parent)
        self.setWindowTitle("Diccionario de índices unificados")
        self.resize(1000, 620)
        # Cuando se llega desde un proyecto, lo que interesa son SUS insumos:
        # la biblioteca global trae miles que no tienen que ver con la obra.
        self._pid = proyecto_id
        self._proyecto_nombre = proyecto_nombre
        self._sugerencias: list[dict] = []
        self._catalogo = catalogo()
        self._build()
        self._refrescar_cabecera()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        tit = QLabel("Diccionario de índices unificados")
        f = QFont(); f.setPointSize(14); f.setWeight(QFont.DemiBold)
        tit.setFont(f)
        tit.setStyleSheet(f"color:{SLATE_700};")
        v.addWidget(tit)

        self.lbl_estado = QLabel("")
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setStyleSheet(f"color:{SLATE_500}; font-size:12px;")
        v.addWidget(self.lbl_estado)

        # ── Barra de acciones ──
        barra = QHBoxLayout()
        barra.setSpacing(8)

        self.chk_proyecto = QCheckBox("Solo los insumos de este proyecto")
        self.chk_proyecto.setChecked(bool(self._pid))
        self.chk_proyecto.setVisible(bool(self._pid))
        self.chk_proyecto.setToolTip(
            "Acota la lista a los insumos que el proyecto usa en sus análisis "
            "de costos" + (f": {self._proyecto_nombre}"
                           if self._proyecto_nombre else ""))
        self.chk_proyecto.toggled.connect(self._refrescar_cabecera)
        barra.addWidget(self.chk_proyecto)

        barra.addWidget(QLabel("Parecido mínimo:"))
        self.spin_umbral = QSpinBox()
        self.spin_umbral.setRange(60, 100)
        self.spin_umbral.setValue(85)
        self.spin_umbral.setSuffix(" %")
        self.spin_umbral.setToolTip(
            "Cuánto se debe parecer la descripción a la de un insumo ya "
            "clasificado para proponerle su índice"
        )
        barra.addWidget(self.spin_umbral)

        self.btn_sugerir = self._btn("Buscar propuestas", "buscar", primary=True)
        self.btn_sugerir.clicked.connect(self._buscar)
        barra.addWidget(self.btn_sugerir)

        self.btn_seguras = self._btn("Marcar solo las seguras")
        self.btn_seguras.clicked.connect(lambda: self._marcar(solo_seguras=True))
        barra.addWidget(self.btn_seguras)

        self.btn_ninguna = self._btn("Desmarcar todas")
        self.btn_ninguna.clicked.connect(lambda: self._marcar(ninguna=True))
        barra.addWidget(self.btn_ninguna)

        barra.addStretch(1)

        self.btn_exp = self._btn("Exportar", "exportar")
        self.btn_exp.setToolTip("Guardar el diccionario como JSON")
        self.btn_exp.clicked.connect(self._exportar)
        barra.addWidget(self.btn_exp)

        self.btn_imp = self._btn("Importar", "importar")
        self.btn_imp.setToolTip("Aplicar un diccionario JSON")
        self.btn_imp.clicked.connect(self._importar)
        barra.addWidget(self.btn_imp)
        v.addLayout(barra)

        # ── Tabla de propuestas ──
        self.tbl = QTableWidget(0, 7)
        self.tbl.setHorizontalHeaderLabels(
            ["", "Insumo", "Tipo", "Índice propuesto", "Parecido", "Fuente",
             "Se parece a"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setStyleSheet(
            "QTableWidget { background:white; border:1px solid #D4D4D4;"
            " font-size:12px; }"
            "QTableWidget::item { padding:3px 6px; }"
            f"QHeaderView::section {{ background:{SILVER_100};"
            f" color:{SLATE_500}; padding:6px 8px; border:none;"
            f" border-bottom:1px solid {SILVER_300};"
            f" font-size:11px; font-weight:700; }}"
        )
        h = self.tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed); h.resizeSection(0, 34)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Fixed); h.resizeSection(2, 54)
        h.setSectionResizeMode(3, QHeaderView.Fixed); h.resizeSection(3, 230)
        h.setSectionResizeMode(4, QHeaderView.Fixed); h.resizeSection(4, 80)
        h.setSectionResizeMode(5, QHeaderView.Fixed); h.resizeSection(5, 90)
        h.setSectionResizeMode(6, QHeaderView.Stretch)
        v.addWidget(self.tbl, 1)

        self.lbl_pie = QLabel(
            "Las propuestas en ámbar tienen otro índice casi igual de parecido: "
            "revísalas una por una. Puedes cambiar el índice de cualquier fila "
            "antes de aplicar."
        )
        self.lbl_pie.setWordWrap(True)
        self.lbl_pie.setStyleSheet(f"color:{SLATE_300}; font-size:11px;")
        v.addWidget(self.lbl_pie)

        # ── Pie de botones ──
        pie = QHBoxLayout()
        pie.addStretch(1)
        self.btn_aplicar = self._btn("Aplicar seleccionadas", "guardar",
                                     primary=True)
        self.btn_aplicar.clicked.connect(self._aplicar)
        pie.addWidget(self.btn_aplicar)
        btn_cerrar = self._btn("Cerrar")
        btn_cerrar.clicked.connect(self.accept)
        pie.addWidget(btn_cerrar)
        v.addLayout(pie)

    def _btn(self, texto, icono=None, primary=False) -> QPushButton:
        b = QPushButton(texto)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(30)
        if icono:
            try:
                b.setIcon(icon(icono))
                b.setIconSize(QSize(15, 15))
            except Exception:
                pass
        if primary:
            from utils.theme import BTN_PRIMARY_SS
            b.setStyleSheet(BTN_PRIMARY_SS)
        return b

    # ── Datos ───────────────────────────────────────────────────────────────
    def _pid_filtro(self):
        return self._pid if (self._pid and self.chk_proyecto.isChecked()) else None

    def _refrescar_cabecera(self):
        pendientes = DIC.insumos_sin_indice(proyecto_id=self._pid_filtro())
        total = len(pendientes)
        if total:
            from core.indices_inei import diccionario_oficial
            self.lbl_estado.setText(
                f"<b>{total}</b> insumo(s) "
                + ("del proyecto " if self._pid_filtro() else "")
                + "sin índice unificado válido. "
                f"La fórmula polinómica los reparte por el índice de su tipo, "
                f"que es un supuesto — clasificarlos la vuelve exacta.<br>"
                f"Las propuestas se apoyan primero en el <b>Diccionario de "
                f"Elementos de la Construcción</b> del INEI "
                f"({len(diccionario_oficial())} elementos, Anexo 2 de la "
                f"RJ 016-2026-INEI) y después en tu propia biblioteca."
            )
        else:
            self.lbl_estado.setText(
                "Todos los insumos tienen índice unificado asignado."
            )

    def _buscar(self):
        self.btn_sugerir.setEnabled(False)
        self.btn_sugerir.setText("Buscando…")
        try:
            self._sugerencias = DIC.sugerencias(
                umbral=self.spin_umbral.value(),
                proyecto_id=self._pid_filtro())
        finally:
            self.btn_sugerir.setEnabled(True)
            self.btn_sugerir.setText("Buscar propuestas")
        self._render()
        if not self._sugerencias:
            QMessageBox.information(
                self, "Sin propuestas",
                "No hay insumos sin clasificar que se parezcan lo suficiente "
                "a uno ya clasificado. Prueba bajando el parecido mínimo."
            )

    def _render(self):
        self.tbl.setRowCount(0)
        ambiguas = 0
        for s in self._sugerencias:
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)

            it_chk = QTableWidgetItem()
            it_chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                            | Qt.ItemIsSelectable)
            # Las ambiguas nacen desmarcadas: son las que hay que mirar.
            it_chk.setCheckState(Qt.Unchecked if s['ambiguo'] else Qt.Checked)
            self.tbl.setItem(r, 0, it_chk)

            it_d = QTableWidgetItem(s['descripcion'])
            self.tbl.setItem(r, 1, it_d)

            it_t = QTableWidgetItem(s['tipo'] or '')
            it_t.setTextAlignment(Qt.AlignCenter)
            self.tbl.setItem(r, 2, it_t)

            cmb = QComboBox()
            for cod, nom in self._catalogo:
                cmb.addItem(f"{cod} — {nom}", cod)
            ix = cmb.findData(s['codigo'])
            if ix < 0:
                cmb.insertItem(0, f"{s['codigo']} — (fuera del catálogo)",
                               s['codigo'])
                ix = 0
            cmb.setCurrentIndex(ix)
            cmb.currentIndexChanged.connect(
                lambda _i, fila=r, c=cmb: self._cambiar_codigo(fila, c))
            self.tbl.setCellWidget(r, 3, cmb)

            it_p = QTableWidgetItem(f"{s['puntaje']:.0f} %")
            it_p.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl.setItem(r, 4, it_p)

            es_oficial = s.get('fuente') == 'oficial'
            it_f = QTableWidgetItem("INEI" if es_oficial else "biblioteca")
            it_f.setTextAlignment(Qt.AlignCenter)
            it_f.setToolTip(
                "Diccionario de Elementos de la Construcción del INEI "
                "(Anexo 2 de la RJ 016-2026-INEI)" if es_oficial else
                "Parecido con un insumo de tu biblioteca que ya tiene índice"
            )
            if es_oficial:
                f_b = QFont(); f_b.setBold(True)
                it_f.setFont(f_b)
            else:
                it_f.setForeground(QColor(SLATE_300))
            self.tbl.setItem(r, 5, it_f)

            it_o = QTableWidgetItem(s['parecido_a'])
            it_o.setForeground(QColor(SLATE_300))
            self.tbl.setItem(r, 6, it_o)

            if s['ambiguo']:
                ambiguas += 1
                tip = (f"El índice {s['rival']} se parece casi igual. "
                       f"Asignar mal el índice mueve costo de un monomio a "
                       f"otro de la fórmula: confirma este a mano.")
                for c in range(7):
                    it = self.tbl.item(r, c)
                    if it:
                        it.setBackground(QColor(AMBAR_SOFT))
                        it.setForeground(QColor(AMBAR_DARK))
                        it.setToolTip(tip)

        n = len(self._sugerencias)
        n_of = sum(1 for s in self._sugerencias if s.get('fuente') == 'oficial')
        self.lbl_pie.setText(
            f"{n} propuesta(s): {n_of} salen del diccionario del INEI y "
            f"{n - n_of} del parecido con tu biblioteca. {n - ambiguas} sin "
            f"rival cercano (marcadas) y {ambiguas} ambigua(s) en ámbar, "
            f"desmarcadas para que las revises. Puedes cambiar el índice de "
            f"cualquier fila antes de aplicar."
        )

    def _cambiar_codigo(self, fila: int, cmb: QComboBox):
        if 0 <= fila < len(self._sugerencias):
            self._sugerencias[fila]['codigo'] = cmb.currentData()

    def _marcar(self, solo_seguras: bool = False, ninguna: bool = False):
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            if it is None:
                continue
            if ninguna:
                it.setCheckState(Qt.Unchecked)
            elif solo_seguras:
                amb = self._sugerencias[r]['ambiguo'] if r < len(self._sugerencias) else True
                it.setCheckState(Qt.Unchecked if amb else Qt.Checked)

    def _seleccionadas(self) -> list[dict]:
        out = []
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            if it and it.checkState() == Qt.Checked and r < len(self._sugerencias):
                out.append(self._sugerencias[r])
        return out

    # ── Acciones ────────────────────────────────────────────────────────────
    def _aplicar(self):
        sel = self._seleccionadas()
        if not sel:
            QMessageBox.information(self, "Nada seleccionado",
                                    "Marca al menos una propuesta.")
            return
        ambiguas = sum(1 for s in sel if s['ambiguo'])
        aviso = (f"\n\n{ambiguas} de ellas están marcadas como ambiguas."
                 if ambiguas else "")
        r = QMessageBox.question(
            self, "Aplicar",
            f"Se asignará el índice unificado a {len(sel)} insumo(s).{aviso}\n\n"
            f"¿Continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if r != QMessageBox.Yes:
            return
        n = DIC.aplicar_sugerencias(sel)
        self._sugerencias = []
        self._render()
        self._refrescar_cabecera()
        QMessageBox.information(
            self, "Listo",
            f"{n} insumo(s) clasificados. Vuelve a auto-calcular la fórmula "
            f"polinómica de tus proyectos para que lo tome."
        )

    def _exportar(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar diccionario", "diccionario-iu.json",
            "JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        try:
            n = DIC.exportar(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar:\n{e}")
            return
        QMessageBox.information(self, "Exportado",
                                f"{n} entradas guardadas en:\n{path}")

    def _importar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar diccionario", "", "JSON (*.json)")
        if not path:
            return
        r = QMessageBox.question(
            self, "Importar diccionario",
            "¿Completar solo los insumos SIN índice?\n\n"
            "Sí — no toca lo que ya clasificaste (recomendado).\n"
            "No — el archivo pisa también las asignaciones existentes.",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes
        )
        if r == QMessageBox.Cancel:
            return
        try:
            res = DIC.importar(path, solo_sin_indice=(r == QMessageBox.Yes))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo importar:\n{e}")
            return
        self._catalogo = catalogo()
        self._sugerencias = []
        self._render()
        self._refrescar_cabecera()
        QMessageBox.information(self, "Importado", res['msg'])
