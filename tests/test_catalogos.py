# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Tests de la base común de los catálogos (Insumos y Biblioteca de CU).

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_catalogos.py

Las dos vistas nacieron por copia y llegaron a tener cinco métodos idénticos
carácter por carácter (`_mk_btn`, `_mk_kpi`, `_rid_at`, `_eliminar_seleccion`
y `_menu_contextual`). Ahora viven una sola vez en `views/_catalogo_base.py`.
Estos tests fijan esa conducta para que un arreglo futuro no vuelva a llegar
a una vista y no a la otra:

* que las dos vistas sigan heredando la base (no una copia propia);
* que el menú contextual dispare sobre la fila del clic y en plural sobre
  la multiselección;
* que `fecha_dmy` y `superindice_unidad` —lo que antes estaba duplicado en
  los reportes y en los dos formularios— den exactamente lo de siempre.

No toca la BD: la tabla se puebla a mano.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QLineEdit, QMenu, QTableWidget, QTableWidgetItem, QWidget,
)

import views._catalogo_base as base
from views._catalogo_base import CatalogoTablaMixin, UnidadSuperindiceMixin
from utils.formatting import fecha_dmy, superindice_unidad

_app = QApplication.instance() or QApplication([])


# ── Andamio ──────────────────────────────────────────────────────────────────

class _Catalogo(CatalogoTablaMixin, QWidget):
    """Vista-catálogo mínima: cumple el contrato y anota lo que le piden."""

    def __init__(self, filas=3):
        super().__init__()
        self.llamadas = []
        self.tbl = QTableWidget(filas, 1)
        for r in range(filas):
            it = QTableWidgetItem(f"fila {r}")
            it.setData(Qt.UserRole, 100 + r)
            self.tbl.setItem(r, 0, it)

    def _editar_id(self, i): self.llamadas.append(('editar', i))
    def _duplicar_id(self, i): self.llamadas.append(('duplicar', i))
    def _eliminar_id(self, i): self.llamadas.append(('eliminar', i))
    def _eliminar_ids(self, ids): self.llamadas.append(('eliminar_ids', list(ids)))


class _MenuFalso(QMenu):
    """QMenu que no abre nada: registra sus acciones y las dispara.

    Se inyecta en el namespace de `views/_catalogo_base.py`; un QMenu real
    abriría un popup modal y colgaría la prueba.
    """
    acciones = []
    disparar = False

    def exec(self, *a, **k):
        _MenuFalso.acciones = ['---' if x.isSeparator() else x.text()
                               for x in self.actions()]
        if _MenuFalso.disparar:
            for x in self.actions():
                if not x.isSeparator():
                    x.trigger()


def _abrir_menu(vista, filas_sel, *, disparar=False):
    """Abre el menú contextual sobre la primera fila de `filas_sel`."""
    for r in filas_sel:
        vista.tbl.item(r, 0).setSelected(True)
    pos = vista.tbl.visualItemRect(vista.tbl.item(filas_sel[0], 0)).center()
    real, base.QMenu = base.QMenu, _MenuFalso
    _MenuFalso.acciones, _MenuFalso.disparar = [], disparar
    try:
        vista._menu_contextual(pos)
    finally:
        base.QMenu, _MenuFalso.disparar = real, False
    return _MenuFalso.acciones


# ── Las dos vistas comparten la base, no una copia ───────────────────────────

def test_las_dos_vistas_heredan_la_base():
    from views.biblioteca_view import BibliotecaView, CUFormDialog
    from views.recursos_view import RecursosView, RecursoFormDialog

    for V in (RecursosView, BibliotecaView):
        assert issubclass(V, CatalogoTablaMixin), f"{V.__name__} dejó de heredar la base"
        # …y no volvió a definir por su cuenta lo que la base ya resuelve.
        for m in ('_mk_btn', '_mk_kpi', '_rid_at', '_eliminar_seleccion',
                  '_menu_contextual'):
            assert m not in V.__dict__, \
                f"{V.__name__}.{m} volvió a ser una copia local de la base"

    for D in (RecursoFormDialog, CUFormDialog):
        assert issubclass(D, UnidadSuperindiceMixin), \
            f"{D.__name__} dejó de heredar el auto-superíndice"
        assert '_auto_superindice_unidad' not in D.__dict__


# ── Lectura de la tabla ──────────────────────────────────────────────────────

def test_rid_at_devuelve_none_fuera_de_rango():
    v = _Catalogo(filas=3)
    assert [v._rid_at(r) for r in (-1, 0, 1, 2, 3, 99)] == \
           [None, 100, 101, 102, None, None]


def test_rid_at_tolera_celda_vacia():
    """Una fila sin item (tabla a medio poblar) no debe reventar."""
    v = _Catalogo(filas=2)
    v.tbl.setItem(1, 0, None)
    assert v._rid_at(1) is None


def test_ids_seleccionados_sin_repetir_y_en_orden():
    v = _Catalogo(filas=3)
    for r in (2, 0, 2):
        v.tbl.item(r, 0).setSelected(True)
    assert v._ids_seleccionados() == [100, 102]


# ── Menú contextual ──────────────────────────────────────────────────────────

def test_menu_una_fila():
    v = _Catalogo()
    assert _abrir_menu(v, [1]) == ['Editar', 'Duplicar', '---', 'Eliminar']


def test_menu_multiseleccion_va_en_plural():
    v = _Catalogo()
    assert _abrir_menu(v, [0, 1, 2]) == \
           ['Editar', 'Duplicar', '---', 'Eliminar 3 seleccionados']


def test_menu_actua_sobre_la_fila_del_clic():
    """Editar y Duplicar van siempre a la fila clicada, no a la selección."""
    v = _Catalogo()
    _abrir_menu(v, [1], disparar=True)
    assert v.llamadas == [('editar', 101), ('duplicar', 101), ('eliminar', 101)]


def test_menu_borra_toda_la_seleccion():
    v = _Catalogo()
    _abrir_menu(v, [0, 1, 2], disparar=True)
    assert ('eliminar_ids', [100, 101, 102]) in v.llamadas


def test_menu_no_abre_fuera_de_la_tabla():
    from PySide6.QtCore import QPoint
    v = _Catalogo()
    real, base.QMenu = base.QMenu, _MenuFalso
    _MenuFalso.acciones = []
    try:
        v._menu_contextual(QPoint(5000, 5000))
    finally:
        base.QMenu = real
    assert _MenuFalso.acciones == []


# ── Borrado por selección ────────────────────────────────────────────────────

def test_eliminar_seleccion():
    v = _Catalogo()
    for r in (0, 2):
        v.tbl.item(r, 0).setSelected(True)
    v._eliminar_seleccion()
    assert v.llamadas == [('eliminar_ids', [100, 102])]


def test_eliminar_seleccion_vacia_no_hace_nada():
    v = _Catalogo()
    v._eliminar_seleccion()
    assert v.llamadas == []


# ── Card KPI — una sola definición para las tres vistas ──────────────────────

def test_kpi_card_expone_sus_labels():
    from utils.theme import crear_kpi_card
    c = crear_kpi_card("Insumos", "42", "#F37329")
    assert c.objectName() == "kpiCard"
    assert c.lbl_etiqueta.text() == "Insumos"
    assert c.lbl_valor.text() == "42"
    # El selector va acotado por objectName: un `QFrame {…}` pelado teñiría
    # a cualquier QFrame descendiente (ver «Stylesheet» en CLAUDE.md).
    assert c.styleSheet().startswith("QFrame#kpiCard")
    assert c.graphicsEffect() is not None, "perdió la sombra 'sm'"


def test_kpi_card_densidad_de_indices_inei():
    """Índices INEI la usa más apretada; el resto, la densidad normal."""
    from utils.theme import crear_kpi_card
    # Hay que retener las cards: si se recolectan, Qt destruye su layout.
    c_normal = crear_kpi_card("a", "1", "#000")
    c_inei = crear_kpi_card("a", "1", "#000",
                            margenes=(14, 8, 14, 8), espaciado=0)
    m_normal = c_normal.layout().contentsMargins()
    assert (m_normal.top(), m_normal.bottom()) == (10, 10)
    assert c_normal.layout().spacing() == 2
    assert (c_inei.layout().contentsMargins().top(), c_inei.layout().spacing()) == (8, 0)


# ── Helpers que antes estaban duplicados ─────────────────────────────────────

def test_superindice_unidad():
    assert superindice_unidad("m2") == "m²"
    assert superindice_unidad("m3") == "m³"
    assert superindice_unidad("cm3") == "cm³"
    assert superindice_unidad("m/2") == "m/²"
    assert superindice_unidad("M2") == "M²"
    # Lo que NO debe tocar: no es una unidad entera terminada en 2 o 3.
    for txt in ("kg", "m4", "m22", "m 2", "m2 ", "2", "", None):
        assert superindice_unidad(txt) is None, txt


def test_auto_superindice_en_el_formulario():
    class _Form(UnidadSuperindiceMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.inp_unidad = QLineEdit()

    f = _Form()
    f.inp_unidad.setText("m2"); f._auto_superindice_unidad("m2")
    assert f.inp_unidad.text() == "m²"
    # Un texto que no aplica se deja intacto (no se borra el campo).
    f.inp_unidad.setText("kg"); f._auto_superindice_unidad("kg")
    assert f.inp_unidad.text() == "kg"


def test_fecha_dmy():
    assert fecha_dmy("2026-08-29") == "29/08/2026"
    assert fecha_dmy("2026-8-9") == "9/8/2026"
    # Lo que no es ISO vuelve tal cual — es lo que hacían las dos copias.
    assert fecha_dmy("29/08/2026") == "29/08/2026"
    assert fecha_dmy("2026-08") == "2026-08"
    assert fecha_dmy(None) == ""
    assert fecha_dmy("") == ""


def test_usuarios_tienen_un_solo_dueno():
    """`hay_usuarios` vive en utils.auth y en ningún otro lado.

    En core.database había otra que contestaba distinto (excluía al
    invitado del conteo): importar la equivocada mostraba la pantalla de
    setup cuando no correspondía.
    """
    import core.database
    import utils.auth
    assert hasattr(utils.auth, 'hay_usuarios')
    assert not hasattr(core.database, 'hay_usuarios')



# ── Pestañas de topbar: una sola definición para las cuatro barras ───────────

def test_tab_topbar_reproduce_las_cuatro_densidades():
    """La pestaña activa va en naranja marca; las demás, transparentes.

    Estaba copiada en Cronograma, Control de Obra, Metrados y el pie de
    presupuesto, y tres de las cuatro hardcodeaban el hex de la marca. Las
    cuatro daban exactamente el mismo CSS salvo el padding.
    """
    from utils.theme import C, tab_topbar

    activa = tab_topbar(True)
    assert f"background:{C.brand}" in activa
    assert "hover" not in activa, "la pestaña activa no lleva hover"

    inactiva = tab_topbar(False)
    assert "background:transparent" in inactiva
    assert "QPushButton:hover" in inactiva

    # Las densidades reales de cada barra, tal como estaban antes de unificar.
    assert "padding:4px 14px" in tab_topbar(True)                        # cronograma · control de obra
    assert "padding:3px 14px" in tab_topbar(True, padding='3px 14px')    # metrados
    assert "padding:3px 12px" in tab_topbar(True, padding='3px 12px')    # pie de presupuesto


def test_ninguna_vista_reescribe_el_estilo_de_pestana():
    """Las cuatro delegan; ninguna volvió a armar el CSS a mano."""
    import io
    import os
    raiz = os.path.join(os.path.dirname(__file__), '..')
    for arch in ('views/cronograma_view.py', 'views/control_obra_view.py',
                 'views/metrados_view.py', 'views/proyecto_view.py'):
        src = io.open(os.path.join(raiz, arch), encoding='utf-8').read()
        i = src.find('def _tab_style')
        assert i >= 0, f"{arch} ya no tiene _tab_style"
        cuerpo = src[i:i + 400]
        assert 'tab_topbar' in cuerpo, f"{arch} dejó de delegar en tab_topbar"
        assert 'font-weight:700' not in cuerpo, \
            f"{arch} volvió a escribir el CSS de la pestaña a mano"


def test_la_regla_del_editor_no_pinta_los_widgets_permanentes():
    """El borde naranja es para marcar que una celda está EN EDICIÓN.

    La regla alcanza a cualquier descendiente de la vista, así que al incluir
    QComboBox pintaba de naranja los desplegables permanentes de una columna
    —los de «Monomio» en la composición de la fórmula— y quedaban como cuadros
    de colores rompiendo la tabla.
    """
    import re
    from pathlib import Path
    from core.config import BASE_DIR
    qss = (Path(BASE_DIR) / "resources" / "styles" / "main.qss").read_text(
        encoding='utf-8')
    m = re.search(r'((?:QAbstractItemView [A-Za-z]+,?\s*)+)\{[^}]*?'
                  r'border:\s*1\.5px solid #F37329', qss)
    assert m, "no encuentro la regla del editor de celda"
    selectores = [s.strip() for s in m.group(1).split(',') if s.strip()]
    assert selectores == ['QAbstractItemView QLineEdit'], selectores


if __name__ == "__main__":
    fallos = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  OK  {name}")
            except AssertionError as e:
                fallos += 1
                print(f"  FAIL {name}: {e}")
    sys.exit(1 if fallos else 0)
