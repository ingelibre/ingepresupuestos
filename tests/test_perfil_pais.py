# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #9 (perfil de país) y #5 (ubicación fuera del Perú).

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_perfil_pais.py

Sin país guardado todo se comporta como Perú (nadie ve cambios hasta elegir).
Con Colombia: COP, NIT, IVA 19 % en proyectos nuevos, sin autocompletado
UBIGEO y el mapa en Bogotá.
Usa una COPIA temporal del seed.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication                          # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_pais_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

from core import paises                                             # noqa: E402

_VIVAS = []


def _borrar_pais():
    conn = d.get_db()
    conn.execute("DELETE FROM configuracion WHERE clave IN ('pais',"
                 " 'etiqueta_id_tributaria', 'impuesto_nombre', 'impuesto_pct')")
    conn.execute("UPDATE configuracion SET valor='Soles' WHERE clave='moneda_defecto'")
    conn.commit()
    conn.close()


def test_sin_pais_todo_es_como_antes():
    _borrar_pais()
    assert paises.pais_configurado() is None
    assert paises.es_peru()
    assert paises.etiqueta_tributaria() == 'RUC'
    assert paises.impuesto() == ('IGV', 18.0)
    assert paises.nombre_rubro_impuesto() == 'IGV (18%)'


def test_la_deteccion_solo_propone_paises_latinoamericanos():
    assert paises.detectar_pais('CO') == 'CO'
    assert paises.detectar_pais('BO') == 'BO'
    assert paises.detectar_pais('ES') == 'PE'     # sistema en es_ES
    assert paises.detectar_pais('US') == 'PE'     # sistema en en_US
    assert paises.detectar_pais('') == 'PE'


def test_cada_pais_usa_una_moneda_que_existe():
    for iso, p in paises.PAISES.items():
        assert p['moneda'] in cfg.MONEDAS, (iso, p['moneda'])


def test_colombia_fija_sus_valores_por_defecto():
    _borrar_pais()
    paises.aplicar_pais('CO')
    try:
        assert not paises.es_peru()
        assert d.get_config('moneda_defecto') == 'Pesos Colombianos'
        assert paises.etiqueta_tributaria() == 'NIT'
        assert paises.impuesto() == ('IVA', 19.0)
        assert paises.nombre_rubro_impuesto() == 'IVA (19%)'
        assert paises.centro_mapa() == paises.PAISES['CO']['centro']
    finally:
        _borrar_pais()


def test_el_usuario_puede_corregir_cualquier_valor():
    _borrar_pais()
    paises.aplicar_pais('CO', moneda='Dólares', etiqueta='NIT/CC', imp_pct=0)
    try:
        assert d.get_config('moneda_defecto') == 'Dólares'
        assert paises.etiqueta_tributaria() == 'NIT/CC'
        assert paises.impuesto() == ('IVA', 0.0)
    finally:
        _borrar_pais()


def test_formulario_de_nuevo_proyecto_sin_ubigeo_fuera_del_peru():
    from views.nuevo_proyecto_view import NuevoProyectoView
    from models.usuario import Usuario
    _borrar_pais()
    v = NuevoProyectoView(Usuario(id=1, nombre="t", rol="admin"))
    _VIVAS.append(v)
    assert v.inp_ubic.completer() is not None          # Perú: UBIGEO
    paises.aplicar_pais('CO')
    try:
        v2 = NuevoProyectoView(Usuario(id=1, nombre="t", rol="admin"))
        _VIVAS.append(v2)
        assert v2.inp_ubic.completer() is None         # Colombia: texto libre
        assert 'UBIGEO' not in v2.inp_ubic.placeholderText()
    finally:
        _borrar_pais()


def test_ubigeo_pone_primero_lo_que_empieza_por_lo_escrito():
    from views.nuevo_proyecto_view import NuevoProyectoView
    from models.usuario import Usuario
    _borrar_pais()
    v = NuevoProyectoView(Usuario(id=1, nombre="t", rol="admin"))
    _VIVAS.append(v)
    proxy = v._ubigeo_proxy
    proxy.set_query('bog')
    primeros = [proxy.data(proxy.index(i, 0)) for i in range(min(3, proxy.rowCount()))]
    assert primeros, 'sin sugerencias'
    from utils.formatting import norm_busqueda
    assert norm_busqueda(primeros[0]).startswith('bog') or \
        not any(norm_busqueda(proxy.data(proxy.index(i, 0))).startswith('bog')
                for i in range(proxy.rowCount())), primeros


def test_proyecto_nuevo_en_colombia_lleva_iva_19():
    from views.nuevo_proyecto_view import NuevoProyectoView
    from models.usuario import Usuario
    _borrar_pais()
    paises.aplicar_pais('CO')
    try:
        # id=None: el seed no trae usuarios y la FK de usuario_id lo exige.
        v = NuevoProyectoView(Usuario(id=None, nombre="t", rol="admin"))
        _VIVAS.append(v)
        creados = []
        v.proyecto_creado.connect(creados.append)
        v.inp_nombre.setText("Prueba Colombia")
        v._crear()
        assert creados, v.lbl_error.text()
        conn = d.get_db()
        p = conn.execute("SELECT moneda, igv_pct FROM proyectos WHERE id=?",
                         (creados[0],)).fetchone()
        conn.close()
        assert p['moneda'] == 'Pesos Colombianos', dict(p)
        assert p['igv_pct'] == 19.0, dict(p)
    finally:
        _borrar_pais()


def test_la_bienvenida_sale_solo_si_falta_el_pais():
    from views.pais_dialog import PaisBienvenidaDialog
    _borrar_pais()
    dlg = PaisBienvenidaDialog()
    dlg.form._poner_pais('BO')
    dlg.reject()                       # cerrar sin elegir deja el propuesto
    try:
        assert paises.pais_configurado() == 'BO'
        assert paises.etiqueta_tributaria() == 'NIT'
        assert d.get_config('moneda_defecto') == 'Bolivianos'
    finally:
        _borrar_pais()


def test_excel_del_cronograma_reconoce_las_monedas_nuevas():
    import re
    from views.cronograma_view import _re_simbolos_moneda
    rx = r'^\s*-?\s*(?:' + _re_simbolos_moneda() + r')?\s*[\d.,]+$'
    for s in ('COP$ 1.234,50', 'Q 1,234.50', 'RD$ 10.00', '₡ 1.000,00', 'S/. 5.00', 'Bs 3'):
        assert re.match(rx, s), s


if __name__ == "__main__":
    fallos = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  OK  {name}")
            except Exception as e:                       # noqa: BLE001
                fallos += 1
                import traceback
                print(f"  FAIL {name}: {e}")
                traceback.print_exc()
    print("\nTODO OK" if not fallos else f"\n{fallos} FALLOS")
    for w in _VIVAS:
        w.close()
        w.deleteLater()
    _app.processEvents()
    try:
        os.remove(_tmpdb)
    except OSError:
        pass
    sys.exit(1 if fallos else 0)
