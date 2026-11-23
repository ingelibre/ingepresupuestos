# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Pestaña «Sub-partidas» del diálogo de agregar recursos (issue #23): las
del proyecto, con alta (vacía o copiada), edición y baja."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core import subpartidas as SP
from core.database import get_db, get_decimales_ppto
from utils.formatting import fmt_doc, norm_busqueda, parse_num
from utils.i18n import tr


def _botones(dlg, texto_ok) -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText(texto_ok)
    bb.button(QDialogButtonBox.Cancel).setText(tr("Cancelar"))
    bb.rejected.connect(dlg.reject)
    return bb


class FichaSubpartidaDialog(QDialog):
    """Descripción y unidad de una sub-partida, nueva (`sub_id=None`) o no.
    Al aceptar ya está grabada; `sub_id` dice cuál es."""

    def __init__(self, proyecto_id: int, sub_id: int | None = None, parent=None):
        super().__init__(parent)
        self.proyecto_id, self.sub_id = proyecto_id, sub_id
        self.setWindowTitle(tr("Editar sub-partida") if sub_id else tr("Nueva sub-partida"))
        self.setMinimumWidth(420)
        self.inp_desc, self.inp_und = QLineEdit(), QLineEdit()
        self.inp_und.setMaximumWidth(90)
        if sub_id:
            conn = get_db()
            p = conn.execute("SELECT descripcion, unidad FROM partidas WHERE id=?",
                             (sub_id,)).fetchone()
            conn.close()
            self.inp_desc.setText(p['descripcion'])
            self.inp_und.setText(p['unidad'] or '')
        form = QFormLayout(self)
        form.addRow(tr("Descripción:"), self.inp_desc)
        form.addRow(tr("Unidad:"), self.inp_und)
        self.lbl_error = QLabel("")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setStyleSheet("color:#dc3545; font-size:11px;")
        form.addRow(self.lbl_error)
        bb = _botones(self, tr("Guardar"))
        bb.accepted.connect(self._guardar)
        form.addRow(bb)

    def _guardar(self):
        desc, und = self.inp_desc.text().strip(), self.inp_und.text().strip()
        conn = get_db()
        try:
            if self.sub_id:
                SP.validar_datos(conn, self.proyecto_id, desc, und, excluir=self.sub_id)
                conn.execute("UPDATE partidas SET descripcion=?, unidad=? WHERE id=?",
                             (desc, und, self.sub_id))
            else:
                self.sub_id = SP.crear(conn, self.proyecto_id, desc, und)
            conn.commit()
        except ValueError as e:
            self.lbl_error.setText(str(e))
            return
        finally:
            conn.close()
        self.accept()


class CopiarSubpartidaDialog(QDialog):
    """Elegir de dónde copiar: una partida del proyecto o la biblioteca."""

    def __init__(self, proyecto_id: int, parent=None):
        super().__init__(parent)
        self.proyecto_id, self.sub_id = proyecto_id, None
        self.setWindowTitle(tr("Copiar análisis como sub-partida"))
        self.resize(560, 420)
        vl = QVBoxLayout(self)
        hl = QHBoxLayout()
        self.cmb = QComboBox()
        self.cmb.addItem(tr("Partidas de este proyecto"), 'proj')
        self.cmb.addItem(tr("Biblioteca"), 'bib')
        self.cmb.currentIndexChanged.connect(self._buscar)
        hl.addWidget(self.cmb)
        self.inp = QLineEdit()
        self.inp.setPlaceholderText(tr("Buscar por descripción…"))
        self.inp.textChanged.connect(self._buscar)
        hl.addWidget(self.inp, 1)
        vl.addLayout(hl)
        self.lst = QListWidget()
        self.lst.itemDoubleClicked.connect(lambda _it: self._copiar())
        vl.addWidget(self.lst, 1)
        self.chk = QCheckBox(tr("Sin precios (solo rendimientos y cantidades)"))
        vl.addWidget(self.chk)
        bb = _botones(self, tr("Copiar"))
        bb.accepted.connect(self._copiar)
        vl.addWidget(bb)
        self._buscar()

    def _buscar(self):
        origen = self.cmb.currentData()
        self.chk.setVisible(origen == 'bib')
        like = f"%{norm_busqueda(self.inp.text().strip())}%"
        conn = get_db()
        conn.create_function("_norm", 1, norm_busqueda)
        if origen == 'bib':
            rows = conn.execute(
                "SELECT c.id, c.descripcion, c.unidad, c.grupo AS item FROM biblioteca_cu c"
                " WHERE _norm(c.descripcion) LIKE ? AND EXISTS (SELECT 1 FROM"
                " biblioteca_acu_items i WHERE i.cu_id=c.id)"
                " ORDER BY c.descripcion LIMIT 500", (like,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT p.id, p.descripcion, p.unidad, p.item FROM partidas_ppto p"
                " WHERE p.proyecto_id=? AND p.es_titulo=0 AND _norm(p.descripcion) LIKE ?"
                " AND EXISTS (SELECT 1 FROM acu_items a WHERE a.partida_id=p.id)"
                " ORDER BY p.item LIMIT 500", (self.proyecto_id, like)).fetchall()
        conn.close()
        self.lst.clear()
        for r in rows:
            it = QListWidgetItem(f"{r['item'] or ''}   {r['descripcion']}  [{r['unidad'] or ''}]")
            it.setData(Qt.UserRole, r['id'])
            self.lst.addItem(it)

    def _copiar(self):
        it = self.lst.currentItem()
        if it is None:
            return
        conn = get_db()
        try:
            if self.cmb.currentData() == 'bib':
                self.sub_id = SP.crear_desde_biblioteca(
                    conn, self.proyecto_id, it.data(Qt.UserRole), self.chk.isChecked())
            else:
                self.sub_id = SP.crear_desde_partida(
                    conn, self.proyecto_id, it.data(Qt.UserRole))
            conn.commit()
        except ValueError as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return
        finally:
            conn.close()
        self.accept()


class SubpartidasTab(QWidget):
    """`agregar()` mete la seleccionada en el ACU; `cambio` avisa de altas,
    ediciones o bajas (que pueden mover precios del proyecto)."""
    cambio = Signal()
    doble_clic = Signal()

    def __init__(self, part_id: int, proyecto_id: int, parent=None):
        super().__init__(parent)
        self.part_id, self.proyecto_id = part_id, proyecto_id
        conn = get_db()
        self._es_sub = SP.es_subpartida(conn, part_id)
        conn.close()
        vl = QVBoxLayout(self)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(6)
        hint = QLabel(tr("Una sub-partida no puede contener otra sub-partida.") if self._es_sub
                      else tr("Análisis propios del proyecto (un mortero, un concreto…) que entran "
                              "como una línea en otros ACU. Su precio sale de su propio análisis: "
                              "ábralo con doble clic en el panel ACU."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6c757d; font-size:11px;")
        vl.addWidget(hint)
        hl = QHBoxLayout()
        self.btn_nueva = QPushButton(tr("Nueva…"))
        self.btn_copiar = QPushButton(tr("Copiar de…"))
        self.btn_editar = QPushButton(tr("Editar…"))
        self.btn_eliminar = QPushButton(tr("Eliminar"))
        for b, f in ((self.btn_nueva, self._nueva), (self.btn_copiar, self._copiar),
                     (self.btn_editar, self._editar), (self.btn_eliminar, self._eliminar)):
            b.setFixedHeight(28)
            b.setStyleSheet("QPushButton { font-size:11px; padding:0 10px; min-height:0; }")
            b.clicked.connect(f)
            b.setEnabled(not self._es_sub)
            hl.addWidget(b)
        hl.addStretch()
        hl.addWidget(QLabel(tr("Cantidad:")))
        self.inp_cant = QLineEdit("1")
        self.inp_cant.setMaximumWidth(80)
        self.inp_cant.setEnabled(not self._es_sub)
        hl.addWidget(self.inp_cant)
        vl.addLayout(hl)
        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(
            [tr("Código"), tr("Descripción"), tr("Und."), tr("Costo unitario"), tr("Usos")])
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl.verticalHeader().hide()
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setEnabled(not self._es_sub)
        self.tbl.itemDoubleClicked.connect(lambda _i: self.doble_clic.emit())
        vl.addWidget(self.tbl, 1)
        self.cargar()

    def cargar(self, seleccionar: int | None = None):
        conn = get_db()
        self._moneda = conn.execute("SELECT moneda FROM proyectos WHERE id=?",
                                    (self.proyecto_id,)).fetchone()[0]
        filas = SP.listar(conn, self.proyecto_id)
        conn.close()
        dec = get_decimales_ppto()
        self._ids = [f['id'] for f in filas]
        self.tbl.setRowCount(len(filas))
        for r, f in enumerate(filas):
            for c, v in enumerate((f['item'], f['descripcion'], f['unidad'] or '',
                                   fmt_doc(f['precio_unitario'], dec, moneda=self._moneda), str(f['n_usos']))):
                it = QTableWidgetItem(v)
                if c >= 3:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl.setItem(r, c, it)
        if seleccionar in self._ids:
            self.tbl.selectRow(self._ids.index(seleccionar))

    def seleccionada(self) -> int | None:
        r = self.tbl.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) and self.tbl.selectedItems() else None

    def _tras(self, dlg):
        if dlg.exec() == QDialog.Accepted:
            self.cargar(dlg.sub_id)
            self.cambio.emit()

    def _nueva(self):
        self._tras(FichaSubpartidaDialog(self.proyecto_id, None, self))

    def _copiar(self):
        self._tras(CopiarSubpartidaDialog(self.proyecto_id, self))

    def _editar(self):
        sid = self.seleccionada()
        if sid:
            self._tras(FichaSubpartidaDialog(self.proyecto_id, sid, self))

    def _eliminar(self):
        sid = self.seleccionada()
        if not sid:
            return
        conn = get_db()
        try:
            usos = SP.usos(conn, sid)
            texto = tr("¿Eliminar esta sub-partida?\nEsta acción no se puede deshacer.")
            if usos:
                lista = '\n'.join(f"• {u['item']}  {u['descripcion'][:60]}" for u in usos[:10])
                if len(usos) > 10:
                    lista += '\n' + tr("… y {n} más").format(n=len(usos) - 10)
                texto = tr("La sub-partida se usa en {n} análisis:\n\n{lista}\n\nSi la elimina, "
                           "esas líneas se quitan y cambian los precios unitarios. "
                           "¿Eliminarla?").format(n=len(usos), lista=lista)
            if QMessageBox.warning(self, tr("Eliminar sub-partida"), texto,
                                   QMessageBox.Yes | QMessageBox.No,
                                   QMessageBox.No) != QMessageBox.Yes:
                return
            SP.eliminar(conn, sid, forzar=True)
            conn.commit()
        finally:
            conn.close()
        self.cargar()
        self.cambio.emit()

    def agregar(self) -> str:
        """'' si entró en el ACU; si no, el motivo."""
        from core.database import _recalcular_pu
        sid = self.seleccionada()
        if sid is None:
            return tr("Elija una sub-partida del proyecto.")
        cant = parse_num(self.inp_cant.text(), self._moneda)
        if cant <= 0:
            return tr("La cantidad debe ser mayor que cero.")
        conn = get_db()
        try:
            SP.enlazar(conn, self.part_id, sid, cant)
            _recalcular_pu(conn, self.part_id)
            conn.commit()
        except ValueError as e:
            return str(e)
        finally:
            conn.close()
        return ''
