# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #53: partidas con precio de relleno 1.00, sin precio o sin ACU."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QMessageBox             # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])
SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_revisar_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

from views import aviso_partidas_dialog as av                       # noqa: E402

_VIVAS = []


def _proyecto():
    conn = d.get_db()
    pid = conn.execute("INSERT INTO proyectos (nombre) VALUES ('Revisar')").lastrowid
    rec = conn.execute("SELECT id FROM recursos WHERE tipo='MAT' AND unidad NOT LIKE '\\%%'"
                       " ESCAPE '\\' LIMIT 1").fetchone()['id']
    ids = {}
    for item, pu, acu in (('01', 1.0, True), ('02', 0, False), ('03', 50, False),
                          ('04', 50, True), ('05', 1.004, True)):
        ids[item] = conn.execute(
            "INSERT INTO partidas (proyecto_id,item,descripcion,unidad,metrado,"
            "precio_unitario,nivel,es_titulo) VALUES (?,?,?,'m2',1,?,1,0)",
            (pid, item, f'P{item}', pu)).lastrowid
        if acu:
            conn.execute("INSERT INTO acu_items (partida_id,recurso_id,cantidad,precio)"
                         " VALUES (?,?,1,?)", (ids[item], rec, pu))
    conn.execute("INSERT INTO partidas (proyecto_id,item,descripcion,nivel,es_titulo)"
                 " VALUES (?,'06','TITULO',1,1)", (pid,))
    conn.commit()
    conn.close()
    return pid, ids


def test_detecta_y_resume():
    pid, _ = _proyecto()
    conn = d.get_db()
    ps = d.partidas_por_revisar(conn, pid)
    conn.close()
    assert {p['item']: p['motivo'] for p in ps} == {
        '01': 'precio_1', '02': 'sin_precio', '03': 'sin_acu', '05': 'precio_1'}
    # Un presupuesto importado con sus precios y sin ACU no se avisa.
    assert av.resumen([p for p in ps if p['motivo'] == 'sin_acu']) == []
    assert av.resumen(ps) == ['2 partidas con precio 1.00', '1 partidas sin precio']


def test_arbol_en_rojo_con_tooltip_y_se_quita_al_corregir():
    from views.proyecto_view import ProyectoView
    from models.usuario import Usuario
    from utils.theme import RED_500
    pid, ids = _proyecto()
    v = ProyectoView(pid, Usuario(id=1, nombre='t', rol='admin'))
    _VIVAS.append(v)
    v.recargar_partidas()

    def rojo(item):
        tw = v._id_to_item[ids[item]]
        return tw.foreground(4).color().name().upper() == RED_500, bool(tw.toolTip(4))
    assert [rojo(i) for i in ('01', '02', '03', '04')] == [
        (True, True), (True, True), (True, True), (False, False)]
    conn = d.get_db()
    conn.execute("UPDATE partidas SET precio_unitario=20 WHERE id=?", (ids['01'],))
    conn.commit()
    conn.close()
    v._actualizar_arbol_partida(ids['01'])
    assert rojo('01') == (False, False)


def test_aviso_se_puede_cancelar_y_apagar(monkeypatch):
    pid, _ = _proyecto()
    av._confirmados.clear()
    d.set_config(av.CLAVE, '1')
    veces = []

    def responder(texto, apagar=False):
        def _exec(box):
            veces.append(box.text())
            box.checkBox().setChecked(apagar)
            b = next(b for b in box.buttons() if b.text() == texto)
            monkeypatch.setattr(QMessageBox, 'clickedButton', lambda self: b)
        monkeypatch.setattr(QMessageBox, 'exec', _exec)

    responder('Volver a revisar')
    assert av.confirmar_salida(None, pid, 'presupuesto') is False
    assert '2 partidas con precio 1.00' in veces[0]
    assert av.confirmar_salida(None, pid, 'metrados') is True and len(veces) == 1
    responder('Continuar')
    assert av.confirmar_salida(None, pid, 'presupuesto') is True
    assert av.confirmar_salida(None, pid, 'acus') is True and len(veces) == 2
    av._confirmados.clear()
    responder('Continuar', apagar=True)
    assert av.confirmar_salida(None, pid, 'acus') is True
    av._confirmados.clear()
    assert av.confirmar_salida(None, pid, 'acus') is True and len(veces) == 3
    d.set_config(av.CLAVE, '1')
