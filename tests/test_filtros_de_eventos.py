"""Filtros de eventos globales con objetos de Qt ya destruidos.

Un RuntimeError dentro de un filtro queda pendiente y cada filtro siguiente
envuelve el mensaje del anterior: con muchas vistas abiertas el proceso crecía
hasta agotar la memoria, o caía al cerrar.
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import shiboken6                                                  # noqa: E402
from PySide6.QtCore import QEvent                                 # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget               # noqa: E402

_app = QApplication.instance() or QApplication([])

import utils.tooltip as tt                                        # noqa: E402


def test_los_filtros_de_tooltip_aguantan_la_ventana_destruida():
    viejo = tt._TipWindow._inst
    tt._TipWindow._inst = None
    try:
        w = QWidget()
        f = tt._TooltipFilter('hola', 10, w)
        g = tt._GlobalTooltipFilter()
        # Ocultar lo que nunca se mostró no crea la ventana.
        for filtro in (f, g):
            assert filtro.eventFilter(w, QEvent(QEvent.Type.Hide)) is False
        assert tt._TipWindow._inst is None
        tip = tt._TipWindow.get()
        shiboken6.delete(tip)
        for filtro in (f, g):
            assert filtro.eventFilter(w, QEvent(QEvent.Type.Hide)) is False
        assert shiboken6.isValid(tt._TipWindow.get())     # se crea otra
    finally:
        tt._TipWindow._inst = viejo


def test_el_filtro_de_esc_solo_vive_con_el_widget_a_la_vista(monkeypatch):
    from views.cronograma_view import _EscGlobalMixin
    vistos = []

    class W(_EscGlobalMixin, QWidget):
        def eventFilter(self, obj, event):
            vistos.append(event.type())
            return super().eventFilter(obj, event)

    w, otro = W(), QWidget()

    def cuenta():
        vistos.clear()
        QApplication.sendEvent(otro, QEvent(QEvent.Type.User))
        return vistos.count(QEvent.Type.User)

    assert cuenta() == 0
    w.show()
    assert cuenta() == 1
    w.hide()
    assert cuenta() == 0


def test_lo_diferido_del_cronograma_no_corre_con_la_vista_cerrada():
    from views.cronograma_view import _luego
    hechos = []
    w, vivo = QWidget(), QWidget()
    _luego(w, lambda: hechos.append('muerto'))
    _luego(vivo, lambda: hechos.append('vivo'))
    shiboken6.delete(w)
    QApplication.processEvents()
    assert hechos == ['vivo']
