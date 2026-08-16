# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Selector de predecesoras del cronograma — estilo «Información de tarea» de
MS Project.

La columna «Predecesoras» de la tabla del Gantt se escribe a mano («3, 7CC+2»),
lo que obliga a buscar visualmente el «#» de la fila destino; peor aún, un «#»
inexistente lo descarta en silencio `core.cronograma.parse_predecesoras` y el
usuario no se entera. Aquí se elige la partida por descripción y el diálogo
arma la cadena canónica con los MISMOS helpers que usa el arrastre entre
barras (`_build_pred_token`, `_evita_ciclo`), así que ambas vías producen
exactamente el mismo texto.

Los tokens que el diálogo no sabe representar (lag en %, la extensión propia
`TN%`, o referencias por ítem en vez de por #) se conservan intactos: se
muestran como «avanzado» y se re-emiten tal cual al aceptar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

# (etiqueta española, código interno) — mismo orden que el menú de la flecha.
TIPOS_DEP = [
    ("FC  Fin → Comienzo",      'FS'),
    ("CC  Comienzo → Comienzo", 'SS'),
    ("FF  Fin → Fin",           'FF'),
    ("CF  Comienzo → Fin",      'SF'),
]

# Filas virtuales que ocupan «#» pero no tienen sentido como predecesora.
_VIRTUAL_NO_ELEGIBLE = ('proyecto', 'subppto', 'fin')


def _norm(s: str) -> str:
    """Normaliza para buscar sin acentos ni mayúsculas."""
    try:
        from utils.formatting import norm_busqueda
        return norm_busqueda(s or '')
    except Exception:
        import unicodedata
        s = unicodedata.normalize('NFKD', s or '')
        return ''.join(c for c in s if not unicodedata.combining(c)).lower()


class PredecesorasDialog(QDialog):
    """Edita la lista de predecesoras de una tarea.

    Uso::

        dlg = PredecesorasDialog(gantt_widget, pid, parent=gantt_widget)
        if dlg.exec():
            nueva_cadena = dlg.cadena()
    """

    def __init__(self, gantt, target_pid: int, parent=None):
        super().__init__(parent)
        self._g = gantt
        self._pid = target_pid
        self.setWindowTitle("Predecesoras")
        self.setWindowModality(Qt.WindowModal)
        self.resize(720, 560)

        self._candidatos = self._construir_candidatos()
        self._build_ui()
        self._cargar_actuales()
        self._filtrar('')

    # ── Datos ────────────────────────────────────────────────────────────

    def _construir_candidatos(self) -> list[dict]:
        """[{num, pid, item, desc, es_titulo}] de las filas referenciables.

        El «#» es la posición 1-based en `filas_con_hitos()` — la misma que
        usa `core.cronograma.numerar_filas`, así que no hay que recalcularla
        (y se evita el O(n) por búsqueda de `_pid_for_rownum`)."""
        out = []
        try:
            filas = self._g._cv.filas_con_hitos()
        except Exception:
            return out
        for i, p in enumerate(filas, start=1):
            virt = p.get('_virtual')
            if virt in _VIRTUAL_NO_ELEGIBLE:
                continue
            pid = p.get('id')
            if pid == self._pid:            # una tarea no es su propia pred.
                continue
            out.append({
                'num': i, 'pid': pid,
                'item': (p.get('item') or '').strip(),
                'desc': (p.get('descripcion') or '').strip(),
                'es_titulo': bool(p.get('es_titulo')),
            })
        return out

    def _etiqueta(self, c: dict) -> str:
        partes = [f"#{c['num']}"]
        if c['item']:
            partes.append(c['item'])
        partes.append(c['desc'] or '(sin descripción)')
        txt = "  ·  ".join(partes)
        return txt + ("   [título]" if c['es_titulo'] else "")

    # ── UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        num = self._g._rownum_for_pid(self._pid)
        desc = ''
        for p in getattr(self._g._cv, '_partidas', []) or []:
            if p['id'] == self._pid:
                desc = f"{(p.get('item') or '').strip()} {(p.get('descripcion') or '').strip()}"
                break
        cab = QLabel(f"<b>Predecesoras de #{num or '?'}</b> · {desc.strip()}")
        cab.setWordWrap(True)
        lay.addWidget(cab)

        # ── Predecesoras actuales ──
        lay.addWidget(QLabel("Predecesoras actuales:"))
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["#", "Tarea", "Tipo", "Desfase (días)"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl.setMinimumHeight(150)
        lay.addWidget(self.tbl, 1)

        row_btn = QHBoxLayout()
        row_btn.addStretch(1)
        self.btn_quitar = QPushButton("Quitar seleccionada")
        self.btn_quitar.setCursor(Qt.PointingHandCursor)
        self.btn_quitar.clicked.connect(self._quitar)
        row_btn.addWidget(self.btn_quitar)
        lay.addLayout(row_btn)

        # ── Agregar ──
        lay.addWidget(QLabel("Agregar predecesora — busca por número, ítem o descripción:"))
        self.inp_buscar = QLineEdit()
        self.inp_buscar.setPlaceholderText("Ej.: concreto, 02.01, 12…")
        self.inp_buscar.setClearButtonEnabled(True)
        self.inp_buscar.textChanged.connect(self._filtrar)
        self.inp_buscar.returnPressed.connect(self._agregar)
        lay.addWidget(self.inp_buscar)

        self.lst = QListWidget()
        self.lst.setMinimumHeight(150)
        self.lst.itemDoubleClicked.connect(lambda _i: self._agregar())
        lay.addWidget(self.lst, 1)

        row_add = QHBoxLayout()
        row_add.addStretch(1)
        self.btn_agregar = QPushButton("Agregar")
        self.btn_agregar.setCursor(Qt.PointingHandCursor)
        self.btn_agregar.clicked.connect(self._agregar)
        row_add.addWidget(self.btn_agregar)
        lay.addLayout(row_add)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Aceptar")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    # ── Carga de las predecesoras existentes ─────────────────────────────

    def _cargar_actuales(self):
        cmap = self._g._cv._cron_map
        actual = (cmap.get(self._pid, {}).get('predecesoras', '') or '')
        por_num = {c['num']: c for c in self._candidatos}
        for base, tipo, lag, pct, tgt_pct, raw in self._g._parse_preds(actual):
            try:
                num = int(str(base).strip())
            except (TypeError, ValueError):
                num = None
            # Lag en % y la extensión TN% no tienen control en este diálogo:
            # se preservan tal cual para no destruir datos del usuario.
            avanzado = bool(pct or tgt_pct) or num is None or num not in por_num
            c = por_num.get(num) if num is not None else None
            self._añadir_fila(num=num, cand=c, tipo=tipo, lag=lag,
                              raw=raw, avanzado=avanzado)

    def _añadir_fila(self, num, cand, tipo='FS', lag=0, raw='', avanzado=False):
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)

        it_num = QTableWidgetItem(f"#{num}" if num is not None else "—")
        it_num.setTextAlignment(Qt.AlignCenter)
        it_num.setData(Qt.UserRole, raw if avanzado else '')
        it_num.setData(Qt.UserRole + 1, cand['pid'] if cand else None)
        self.tbl.setItem(r, 0, it_num)

        if cand:
            txt = "  ·  ".join(x for x in (cand['item'], cand['desc']) if x)
        else:
            txt = f"(no encontrada — se conserva «{raw}»)"
        self.tbl.setItem(r, 1, QTableWidgetItem(txt))

        if avanzado:
            it_t = QTableWidgetItem(raw)
            it_t.setToolTip("Token avanzado (lag en % o referencia por ítem): "
                            "se conserva tal cual.")
            self.tbl.setItem(r, 2, it_t)
            self.tbl.setItem(r, 3, QTableWidgetItem("—"))
        else:
            cb = QComboBox()
            for label, code in TIPOS_DEP:
                cb.addItem(label, code)
            idx = max(0, [c for _l, c in TIPOS_DEP].index(tipo)
                      if tipo in [c for _l, c in TIPOS_DEP] else 0)
            cb.setCurrentIndex(idx)
            self.tbl.setCellWidget(r, 2, cb)

            sp = QSpinBox()
            sp.setRange(-999, 999)
            sp.setValue(int(lag or 0))
            sp.setToolTip("Días de adelanto (negativo) o retraso (positivo).")
            self.tbl.setCellWidget(r, 3, sp)

    # ── Acciones ─────────────────────────────────────────────────────────

    def _filtrar(self, texto: str):
        q = _norm(texto)
        ya = self._pids_en_tabla()
        self.lst.clear()
        for c in self._candidatos:
            if c['pid'] in ya:
                continue
            if q and q not in _norm(f"{c['num']} {c['item']} {c['desc']}"):
                continue
            it = QListWidgetItem(self._etiqueta(c))
            it.setData(Qt.UserRole, c['num'])
            self.lst.addItem(it)
        if self.lst.count():
            self.lst.setCurrentRow(0)

    def _pids_en_tabla(self) -> set:
        out = set()
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            pid = it.data(Qt.UserRole + 1) if it else None
            if pid is not None:
                out.add(pid)
        return out

    def _agregar(self):
        it = self.lst.currentItem()
        if it is None:
            return
        num = it.data(Qt.UserRole)
        cand = next((c for c in self._candidatos if c['num'] == num), None)
        if cand is None:
            return
        # Mismo criterio que el arrastre entre barras: se valida al agregar,
        # no al aceptar, para que el aviso llegue en el momento.
        if self._g._evita_ciclo(cand['pid'], self._pid):
            QMessageBox.warning(
                self, "Dependencia circular",
                f"«{cand['desc']}» no puede ser predecesora: crearía un ciclo "
                f"con esta tarea.")
            return
        self._añadir_fila(num=cand['num'], cand=cand)
        self._filtrar(self.inp_buscar.text())

    def _quitar(self):
        r = self.tbl.currentRow()
        if r < 0:
            return
        self.tbl.removeRow(r)
        self._filtrar(self.inp_buscar.text())

    # ── Resultado ────────────────────────────────────────────────────────

    def cadena(self) -> str:
        """Cadena canónica de predecesoras lista para `cron_map`."""
        tokens = []
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            if it is None:
                continue
            raw = it.data(Qt.UserRole) or ''
            if raw:                       # token avanzado → intacto
                tokens.append(raw)
                continue
            pid = it.data(Qt.UserRole + 1)
            cb = self.tbl.cellWidget(r, 2)
            sp = self.tbl.cellWidget(r, 3)
            tipo = cb.currentData() if cb else 'FS'
            lag = sp.value() if sp else 0
            tok = self._g._build_pred_token(pid, tipo=tipo, lag=lag)
            if tok:
                tokens.append(tok)
        return ', '.join(tokens)
