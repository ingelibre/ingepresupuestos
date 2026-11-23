# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #17 — la primera impresión en Linux: la AppImage se integra al menú
de aplicaciones, la ventana del Flatpak se asocia a su lanzador (icono del
dock) y la ficha del Flatpak trae capturas. Lo mismo que IngeCAD (77ca931) e
IngeTrazo (cb9e86f) tras la revisión externa del 10-09-2026.

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_appimage.py
"""
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

import core.database as d
from core import appimage

_app = QApplication.instance() or QApplication([])
RAIZ = Path(__file__).resolve().parents[1]
SEED = RAIZ / 'presupuestos_seed.db'
_fd, _tmpdb = tempfile.mkstemp(suffix='_appimage_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)


def _bd():
    if d.DB_PATH != _tmpdb:
        d.DB_PATH = _tmpdb
        d.init_db()


def test_sin_las_variables_del_runtime_no_es_appimage(monkeypatch):
    monkeypatch.delenv('APPIMAGE', raising=False)
    assert appimage.appimage_path() is None


def test_integrar_escribe_lanzador_icono_y_mime_apuntando_al_archivo(tmp_path, monkeypatch):
    img = tmp_path / 'IngePresupuestos-3.0.18-x86_64.AppImage'
    img.write_bytes(b'AI')
    data = tmp_path / 'data'
    monkeypatch.setenv('APPIMAGE', str(img))
    monkeypatch.setenv('XDG_DATA_HOME', str(data))
    monkeypatch.setattr(appimage, '_refrescar_caches', lambda: None)
    assert appimage.appimage_path() == img
    assert not appimage.esta_integrada(img)

    f = appimage.integrar(img, base=RAIZ)
    assert f == data / 'applications' / 'ingepresupuestos.desktop'
    texto = f.read_text(encoding='utf-8')
    assert f'Exec="{img}" %F' in texto and f'TryExec={img}' in texto
    assert 'Icon=ingepresupuestos' in texto
    assert 'StartupWMClass=ingepresupuestos' in texto
    assert 'MimeType=application/x-ingepresupuestos-db;' in texto
    icono = data / 'icons/hicolor/256x256/apps/ingepresupuestos.png'
    assert icono.read_bytes() == (RAIZ / 'resources/icons/elementary/24/ingepresupuestos.png').read_bytes()
    assert (data / 'mime/packages/ingepresupuestos.xml').is_file()
    docs = list((data / 'icons/hicolor').glob('*/mimetypes/application-x-ingepresupuestos-db.*'))
    assert len(docs) >= 7      # un icono de documento por tamaño, más el SVG
    assert appimage.esta_integrada(img)
    # Una AppImage movida cuenta como no integrada (el lanzador quedaría roto).
    assert not appimage.esta_integrada(tmp_path / 'otra-carpeta.AppImage')

    appimage.quitar(base=RAIZ)
    assert not f.exists() and not icono.exists()
    assert not (data / 'mime/packages/ingepresupuestos.xml').exists()
    assert not list((data / 'icons/hicolor').glob('*/mimetypes/*'))


def test_acerca_de_ofrece_el_menu_solo_como_appimage(tmp_path, monkeypatch):
    from views.acerca_view import AcercaView
    _bd()
    monkeypatch.delenv('APPIMAGE', raising=False)
    assert AcercaView().btn_menu_apps is None

    img = tmp_path / 'IngePresupuestos.AppImage'
    img.write_bytes(b'AI')
    monkeypatch.setenv('APPIMAGE', str(img))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setattr(appimage, '_refrescar_caches', lambda: None)
    v = AcercaView()
    assert v.btn_menu_apps.text() == 'Agregar al menú de aplicaciones'
    v.btn_menu_apps.click()
    assert appimage.esta_integrada(img)
    assert v.btn_menu_apps.text() == 'Quitar del menú de aplicaciones'
    v.btn_menu_apps.click()
    assert not appimage.esta_integrada(img)
    assert v.btn_menu_apps.text() == 'Agregar al menú de aplicaciones'


def test_la_ficha_del_flatpak_trae_capturas_por_https():
    """GNOME Software decía «Sin capturas»: el metainfo no traía ninguna."""
    for canal in ('flatpak', 'flathub'):
        texto = (RAIZ / f'installer/{canal}/com.ingepresupuestos.IngePresupuestos.metainfo.xml').read_text(encoding='utf-8')
        imagenes = re.findall(r'<image>([^<]+)</image>', texto)
        assert len(imagenes) >= 5, canal
        assert all(u.startswith('https://ingepresupuestos.com/images/screenshots/') for u in imagenes)
        assert texto.count('<screenshot type="default">') == 1
        # cada captura con su leyenda en los dos idiomas
        assert texto.count('<caption>') == len(imagenes)
        assert texto.count('<caption xml:lang="en">') == len(imagenes)


def test_el_flatpak_instala_el_icono_png_y_no_el_svg():
    """El SVG no es cuadrado y flatpak-builder lo rechaza: tumbó el Flatpak
    de la 3.0.18. El icono es el PNG de 256 px."""
    for canal in ('flatpak', 'flathub'):
        texto = (RAIZ / f'installer/{canal}/com.ingepresupuestos.IngePresupuestos.yml').read_text(encoding='utf-8')
        assert 'hicolor/256x256/apps/${FLATPAK_ID}.png' in texto, canal
        assert 'hicolor/scalable/apps/${FLATPAK_ID}.svg' not in texto, canal


def test_la_ventana_se_asocia_al_lanzador_del_flatpak():
    """Dentro del Flatpak la entrada .desktop se llama como el id de la app;
    sin decirlo, el dock mostraba un icono genérico y el botón «Abrir» de
    GNOME Software no veía abrirse la app."""
    texto = (RAIZ / 'main.py').read_text(encoding='utf-8')
    assert 'app.setDesktopFileName(os.environ.get("FLATPAK_ID") or "ingepresupuestos")' in texto


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-q']))
