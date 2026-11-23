# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #32: recuperar la contraseña con un código, sin internet."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QMessageBox             # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

from PySide6.QtCore import QSettings                                # noqa: E402
QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, tempfile.mkdtemp())
_app = QApplication.instance() or QApplication([])
SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_recuperar_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()
d.init_db()

from utils import auth                                              # noqa: E402
auth.DB_PATH = _tmpdb

import views.recuperar_dialog as rec                                # noqa: E402


def _cuenta(nombre, con_codigo=True):
    conn = d.get_db()
    conn.execute("DELETE FROM usuarios WHERE username=?", (nombre,))
    conn.commit()
    conn.close()
    ok, msg = auth.crear_admin(nombre, nombre, 'secreto1', email=f'{nombre}@x.y')
    assert ok, msg
    uid = next(u.id for u in auth.listar_usuarios() if u.username == nombre)
    return uid, auth.crear_codigo_recuperacion(uid) if con_codigo else ''


def test_codigo_valido_cambia_la_clave_y_se_gasta():
    uid, cod = _cuenta('ana')
    conn = d.get_db()
    h = conn.execute("SELECT recuperacion_hash FROM usuarios WHERE id=?", (uid,)).fetchone()[0]
    conn.close()
    assert cod not in h and cod.replace('-', '') not in h       # solo el hash
    ok, _m, nuevo = auth.restablecer_con_codigo('ana', cod.lower().replace('-', ' '), 'otra123')
    assert ok and nuevo != cod
    assert auth.login('ana', 'otra123')[0] and not auth.login('ana', 'secreto1')[0]
    assert not auth.restablecer_con_codigo('ana', cod, 'mala123')[0]
    assert auth.restablecer_con_codigo('ana@x.y', nuevo, 'tercera1')[0]


def test_codigo_invalido_y_cuenta_vieja_no_cambian_nada():
    uid, cod = _cuenta('beto')
    _cuenta('vieja', con_codigo=False)
    assert not auth.tiene_codigo_recuperacion(
        next(u.id for u in auth.listar_usuarios() if u.username == 'vieja'))
    for user, c in (('beto', 'AAAA-AAAA-AAAA-AAAA'), ('beto', ''), ('vieja', ''),
                    ('vieja', cod), ('nadie', cod), ('', cod)):
        ok, msg, _n = auth.restablecer_con_codigo(user, c, 'nueva123')
        assert not ok and msg == auth.MSG_CODIGO_INVALIDO
    assert not auth.restablecer_con_codigo('beto', cod, '123')[0]
    assert auth.login('beto', 'secreto1')[0] and auth.login('vieja', 'secreto1')[0]
    auth.toggle_activo(uid)
    assert not auth.restablecer_con_codigo('beto', cod, 'nueva123')[0]


def test_crear_cuenta_muestra_el_codigo_y_el_rodeo_sigue(monkeypatch):
    from views.login_dialog import LoginDialog
    vistos = []
    monkeypatch.setattr(rec.CodigoRecuperacionDialog, 'exec',
                        lambda self: vistos.append(self.inp_codigo.text()))
    _cuenta('previa')                       # con usuarios previos, como el rodeo
    dlg = LoginDialog()
    for w, t in ((dlg.inp_nombre, 'Caro'), (dlg.inp_reg_user, 'caro'),
                 (dlg.inp_email, 'caro@x.y'), (dlg.inp_reg_pass, 'secreto1'),
                 (dlg.inp_reg_pass2, 'secreto1')):
        w.setText(t)
    dlg._do_registro()
    assert len(vistos) == 1
    u = auth.usuario_actual()
    assert u.username == 'caro' and u.rol == 'admin'
    assert auth.restablecer_con_codigo('caro', vistos[0], 'nueva123')[0]


def test_dialogo_de_recuperacion(monkeypatch):
    _uid, cod = _cuenta('dora')
    monkeypatch.setattr(rec.CodigoRecuperacionDialog, 'exec', lambda self: 1)
    dlg = rec.RecuperarPasswordDialog(None, 'dora')
    dlg.inp_codigo.setText('nada')
    dlg.inp_p1.setText('nueva123')
    dlg.inp_p2.setText('nueva12')
    dlg._cambiar()
    assert dlg.lbl_err.text() and not dlg.result()
    dlg.inp_p2.setText('nueva123')
    dlg._cambiar()
    assert not dlg.result()
    dlg._mostrar_camino()
    assert 'Crear cuenta' in dlg.lbl_sin_codigo.text()
    dlg.inp_codigo.setText(cod)
    dlg._cambiar()
    assert dlg.result() and auth.login('dora', 'nueva123')[0]


def test_cuenta_vieja_se_le_ofrece_una_sola_vez(monkeypatch):
    from PySide6.QtCore import QSettings
    from views.login_dialog import LoginDialog
    uid, _ = _cuenta('emma', con_codigo=False)
    QSettings("ingePresupuestos", "avisos").remove("avisos/codigo_recuperacion_emma")
    preguntas = []
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(
        lambda *a, **k: preguntas.append(1) or QMessageBox.No))
    for _ in range(2):
        dlg = LoginDialog()
        dlg.inp_user.setText('emma')
        dlg.inp_pass.setText('secreto1')
        dlg._do_login()
        assert dlg.result()
    assert len(preguntas) == 1 and not auth.tiene_codigo_recuperacion(uid)
    QSettings("ingePresupuestos", "avisos").remove("avisos/codigo_recuperacion_emma")
