# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #55: lista de unidades y gestor que une M2 / m2 / m²."""
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QLineEdit               # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])
SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')

from core import unidades                                           # noqa: E402


@pytest.fixture(autouse=True)
def _bd(tmp_path):
    ruta = str(tmp_path / 'u.db')
    shutil.copy(SEED, ruta)
    viejo = d.DB_PATH, cfg.DB_PATH
    d.DB_PATH = cfg.DB_PATH = ruta
    d.init_db()
    yield
    d.DB_PATH, cfg.DB_PATH = viejo


def test_misma_unidad_protege_las_que_significan_algo():
    si = [('M2', 'm²'), ('m2', 'M2'), ('HH', 'hh'), ('dia', 'día'), ('GLB', 'glb'),
          ('KG', 'kg'), ('und.', 'UND')]
    no = [('hh', 'hm'), ('hh', 'h'), ('glb', 'gbl'), ('m2', 'm3'), ('m', 'ml'),
          ('%MO', '%mo'), ('día', 'días'), ('', ' '), ('bol', 'bls'),
          ('kgf', 'kgf.')]      # «kgf» es acero y «kgf.» no: no se juntan
    for a, b in si:
        assert unidades.misma_unidad(a, b), (a, b)
    for a, b in no:
        assert not unidades.misma_unidad(a, b), (a, b)


def _sin_unidad(x):
    if isinstance(x, (dict,)) or hasattr(x, 'keys'):
        return {k: _sin_unidad(x[k]) for k in x.keys() if k != 'unidad'}
    if isinstance(x, (list, tuple)):
        return [_sin_unidad(i) for i in x]
    return x


def _pus(conn):
    return {pid: _sin_unidad(d.calcular_totales(pid))
            for (pid,) in conn.execute("SELECT id FROM proyectos").fetchall()}


def test_unir_todo_no_cambia_ningun_calculo():
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET estado='elaboracion'")
    conn.commit()
    antes = _pus(conn)
    reglas = {r['id']: unidades._firma(r['unidad'])
              for r in conn.execute("SELECT id, unidad FROM recursos")}
    grupos = unidades.variantes(conn)
    assert any(set(g['grafias']) >= {'M2', 'm2', 'm²'} and g['sugerida'] == 'm²'
               for g in grupos)
    cambios = {u: g['sugerida'] for g in grupos for u in g['grafias']}
    assert not any('%' in u for u in cambios)
    previstos = sum(n for g in grupos for u, n in g['grafias'].items()
                    if u != g['sugerida'])
    assert unidades.unir(conn, cambios) == previstos       # lo que dijo la vista previa
    assert unidades.variantes(conn) == []
    assert _pus(conn) == antes
    assert reglas == {r['id']: unidades._firma(r['unidad'])
                      for r in conn.execute("SELECT id, unidad FROM recursos")}
    conn.close()


def test_una_transaccion_y_rechazo():
    conn = d.get_db()
    n = conn.execute("SELECT COUNT(*) FROM recursos WHERE unidad='M2'").fetchone()[0]
    with pytest.raises(ValueError):
        unidades.unir(conn, {'M2': 'm²', 'hh': 'hm'})
    conn.execute("CREATE TRIGGER t BEFORE UPDATE ON partidas WHEN OLD.unidad='m2'"
                 " BEGIN SELECT RAISE(ABORT,'no'); END")
    conn.execute("UPDATE proyectos SET estado='elaboracion'")
    conn.commit()
    with pytest.raises(Exception, match='no'):
        unidades.unir(conn, {'M2': 'm²', 'm2': 'm²'})
    assert conn.execute("SELECT COUNT(*) FROM recursos WHERE unidad='M2'").fetchone()[0] == n
    conn.close()


def test_presupuesto_cerrado_no_se_toca():
    conn = d.get_db()
    pid = conn.execute("INSERT INTO proyectos (nombre, estado) VALUES ('c','aprobado')").lastrowid
    conn.execute("INSERT INTO partidas (proyecto_id,item,descripcion,unidad,nivel)"
                 " VALUES (?,'01','x','M2',1)", (pid,))
    conn.commit()
    unidades.unir(conn, {'M2': 'm²'})
    assert conn.execute("SELECT unidad FROM partidas WHERE proyecto_id=?",
                        (pid,)).fetchone()[0] == 'M2'
    conn.close()


def test_lista_sin_variantes_repetidas():
    conn = d.get_db()
    l = unidades.lista(conn)
    assert l[0] == 'm²' and 'hh' in l and 'PLN' in l
    grupos = unidades.variantes(conn)
    unidades.unir(conn, {u: ('m2' if g['clave'] == 'm2' else g['sugerida'])
                         for g in grupos for u in g['grafias']
                         if unidades.misma_unidad(u, g['sugerida'])})
    conn.execute("UPDATE partidas SET unidad='m2' WHERE unidad IN ('M2','m²')")
    assert unidades.lista(conn)[0] == 'm2'              # manda la grafía de casa
    conn.close()


def test_desplegable_editable_y_gestor(monkeypatch):
    from views.unidades_dialog import GestorUnidadesDialog, poner_lista
    inp = poner_lista(QLineEdit())
    inp.setText('mi-unidad')
    assert inp.text() == 'mi-unidad'
    inp.accion_lista.trigger()
    assert inp.completer().completionCount() == len(unidades.lista())
    inp.completer().popup().hide()

    dlg = GestorUnidadesDialog()
    assert dlg.tbl.rowCount() > 5 and not dlg.btn_unir.isEnabled()   # nada marcado
    dlg.marcar_todas()
    assert dlg.btn_unir.isEnabled() and dlg.lbl.text()
    dlg.btn_unir.click()
    assert dlg.cambiadas > 0 and dlg.result() == 1
    assert GestorUnidadesDialog().tbl.rowCount() <= 2    # quedan solo las de cerrados


def test_formularios_llevan_la_lista():
    from views.partida_form_dialog import PartidaFormDialog
    import inspect
    import views.partida_form_dialog as a, views.recursos_view as b
    import views.biblioteca_view as c, views.recurso_selector_dialog as e
    import views.proyecto_view as f
    for m in (a, b, c, e, f):
        assert 'poner_lista(self.' in inspect.getsource(m), m.__name__
    assert PartidaFormDialog
