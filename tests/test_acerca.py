# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""«Apoya al proyecto» en Acerca de (Marco, 9 sep 2026): espejo de
ingepresupuestos.com/apoyar — probarlo y reportar, recomendarlo, o un aporte
por Yape/Plin (QR + número) o Liberapay/PayPal.

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_acerca.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

import core.database as d

_app = QApplication.instance() or QApplication([])
SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_acerca_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)


def _bd():
    if d.DB_PATH != _tmpdb:
        d.DB_PATH = _tmpdb
        d.init_db()


def test_acerca_de_apoya_al_proyecto_con_yape_y_copia_el_numero():
    from core.config import BASE_DIR
    from views.acerca_view import AcercaView
    _bd()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog
    v = AcercaView()
    assert (BASE_DIR / 'resources' / 'qr_yape.png').exists()
    # La fila de Información técnica abre la ventana (modal: se cierra sola).
    assert 'Apoya al proyecto' in [k for k, _v in __import__('views.acerca_view', fromlist=['_app_info'])._app_info()]
    QTimer.singleShot(50, lambda: v._dlg_apoyo.accept())
    v.lbl_apoyo.linkActivated.emit('apoyar')
    assert isinstance(v._dlg_apoyo, QDialog) and v._dlg_apoyo.windowTitle() == 'Apoya al proyecto'
    v._copiar_yape()
    assert _app.clipboard().text() == '998839090'
    assert v.btn_copiar_yape.text().startswith('Copiado')
    # Mismo número y misma ruta que la web
    web = os.path.join(os.path.dirname(__file__), '..', '..', 'web', 'apoyar.html')
    if os.path.exists(web):
        html = open(web, encoding='utf-8').read()
        assert '998 839 090' in html and AcercaView.LIBERAPAY_URL in html


def test_el_qr_de_yape_viaja_en_el_paquete():
    spec = open(os.path.join(os.path.dirname(__file__), '..', 'ingepresupuestos.spec'),
                encoding='utf-8').read()
    assert "('resources/qr_yape.png',                'resources')" in spec


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-q']))
