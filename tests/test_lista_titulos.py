"""Issue #20: la lista de «Agregar título» se puede editar, ordenar y
restaurar, sin tocar los proyectos."""
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox  # noqa: E402

from PySide6.QtTest import QTest                                    # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402
from core import titulos                                            # noqa: E402

_app = QApplication.instance() or QApplication([])
SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')


@pytest.fixture(autouse=True)
def conn(tmp_path, monkeypatch):
    ruta = str(tmp_path / 't.db')
    shutil.copy(SEED, ruta)
    monkeypatch.setattr(d, 'DB_PATH', ruta)
    monkeypatch.setattr(cfg, 'DB_PATH', ruta, raising=False)
    d.init_db()
    c = d.get_db()
    antes = [tuple(r) for r in c.execute("SELECT * FROM partidas ORDER BY id")]
    yield c
    # Nada de lo que se haga con la lista escribe en los proyectos.
    assert [tuple(r) for r in c.execute("SELECT * FROM partidas ORDER BY id")
            if r['descripcion'] != 'ZZ NUEVO DE PROYECTO'] == antes
    c.close()


def _fabrica(c):
    return [r[0] for r in c.execute("SELECT DISTINCT descripcion FROM partidas"
                                    " WHERE es_titulo=1 ORDER BY descripcion")]


def _titulo_en_proyecto(c, desc):
    pid = c.execute("SELECT id FROM proyectos LIMIT 1").fetchone()[0]
    c.execute("INSERT INTO partidas (proyecto_id, item, descripcion, nivel, es_titulo)"
              " VALUES (?,'99',?,1,1)", (pid, desc))
    c.commit()


def test_sin_cambios_es_la_lista_de_siempre(conn):
    assert titulos.lista(conn) == _fabrica(conn)
    titulos.guardar(conn, titulos.filas(conn))
    assert conn.execute("SELECT COUNT(*) FROM titulos_lista").fetchone()[0] == 0


def test_agregar_editar_borrar_ordenar_y_restaurar(conn):
    fab = _fabrica(conn)
    f = titulos.filas(conn)
    borrado = f.pop(2)['descripcion']
    viejo, f[5]['descripcion'] = f[5]['descripcion'], 'CORREGIDO'
    f.append({'descripcion': 'PROPIO', 'claves': [], 'propia': True})
    f.insert(0, f.pop(10))
    esperado = [x['descripcion'] for x in f]
    titulos.guardar(conn, f)
    assert titulos.lista(conn) == esperado
    assert borrado not in esperado and viejo not in esperado
    # Guardar otra vez sin cambios no altera nada.
    titulos.guardar(conn, titulos.filas(conn))
    assert titulos.lista(conn) == esperado
    d.init_db()
    assert titulos.lista(conn) == esperado
    titulos.restaurar(conn)
    assert titulos.lista(conn) == sorted(fab + ['PROPIO'])


def test_mover_uno_arriba_solo_numera_ese_tramo(conn):
    f = titulos.filas(conn)
    f.insert(0, f.pop())
    titulos.guardar(conn, f)
    assert conn.execute("SELECT COUNT(*) FROM titulos_lista").fetchone()[0] == 1
    # Un título nuevo de un proyecto sigue entrando solo, en su sitio.
    _titulo_en_proyecto(conn, 'ZZ NUEVO DE PROYECTO')
    lst = titulos.lista(conn)
    assert lst[0] == f[0]['descripcion'] and 'ZZ NUEVO DE PROYECTO' in lst
    assert lst[1:] == sorted(lst[1:])


def test_titulo_renombrado_y_usado_es_una_sola_fila(conn):
    f = titulos.filas(conn)
    viejo, f[0]['descripcion'] = f[0]['descripcion'], 'ZZ NUEVO DE PROYECTO'
    titulos.guardar(conn, f)
    _titulo_en_proyecto(conn, 'ZZ NUEVO DE PROYECTO')
    f = titulos.filas(conn)
    fila = [x for x in f if x['descripcion'] == 'ZZ NUEVO DE PROYECTO']
    assert len(fila) == 1 and len(fila[0]['claves']) == 2
    f.remove(fila[0])
    titulos.guardar(conn, f)
    lst = titulos.lista(conn)
    assert 'ZZ NUEVO DE PROYECTO' not in lst and viejo not in lst
    # Guardar de nuevo no resucita lo borrado.
    titulos.guardar(conn, titulos.filas(conn))
    assert titulos.lista(conn) == lst
    titulos.restaurar(conn)
    assert titulos.lista(conn) == _fabrica(conn)


def test_intercambiar_dos_textos_y_volver_a_agregar(conn):
    f = titulos.filas(conn)
    a, b = f[0]['descripcion'], f[1]['descripcion']
    f[0]['descripcion'], f[1]['descripcion'] = b, a
    titulos.guardar(conn, f)
    assert titulos.lista(conn)[:2] == [b, a]
    titulos.restaurar(conn)
    f = [x for x in titulos.filas(conn) if x['descripcion'] != a]   # borrar…
    f[0]['descripcion'] = 'OTRO'                                    # …renombrar b
    titulos.guardar(conn, f)
    f = titulos.filas(conn)
    for t in (a, b):                                                # …y volver
        f.append({'descripcion': t, 'claves': [], 'propia': True})
    titulos.guardar(conn, f)
    lst = titulos.lista(conn)
    assert {a, b, 'OTRO'} <= set(lst) and len(lst) == len(set(lst))


def test_gestor(conn, monkeypatch):
    import views.titulos_dialog as vt
    avisos = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *a: avisos.append(a))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    fab = _fabrica(conn)
    g = vt.GestorTitulosDialog()
    assert g._textos() == fab
    assert g.agregar('  AAA PRIMERO ') and not g.agregar(fab[0])
    assert g._textos() == sorted(fab + ['AAA PRIMERO'])
    it = g.lst.findItems(fab[3], vt.Qt.MatchExactly)[0]
    it.setText(fab[4])                              # repetido: vuelve
    assert it.text() == fab[3] and len(avisos) == 1
    it.setText('ZZZ FINAL')                         # lista alfabética: a su sitio
    assert g._textos() == sorted(g._textos()) and 'ZZZ FINAL' in g._textos()
    # Lo mismo escribiendo en la celda, con el editor abierto.
    g.show()
    it = g.lst.findItems('ZZZ FINAL', vt.Qt.MatchExactly)[0]
    g.lst.clearSelection()
    g.lst.setCurrentItem(it)
    g._editar()
    ed = g.lst.viewport().findChild(QLineEdit)
    ed.setText('AAA ANTES')
    QTest.keyClick(ed, vt.Qt.Key_Return)
    QTest.qWait(50)
    assert g._textos()[0] == 'AAA ANTES' and g.isVisible()
    g.lst.item(0).setText('ZZZ FINAL')
    QTest.qWait(50)
    g.lst.clearSelection()
    g.lst.setCurrentRow(0)
    assert not g.btn_subir.isEnabled()
    g._mover(1)
    g.inp_buscar.setText(fab[6])
    assert not g.btn_bajar.isEnabled()
    g.lst.clearSelection()
    g.lst.findItems(fab[6], vt.Qt.MatchExactly)[0].setSelected(True)
    g._borrar()
    esperado = g._textos()
    assert fab[6] not in esperado
    assert titulos.lista(conn) == fab               # aún nada guardado
    g._guardar()
    assert titulos.lista(conn) == esperado
    from views.agregar_titulo_dialog import AgregarTituloDialog
    pid = conn.execute("SELECT id FROM proyectos LIMIT 1").fetchone()[0]
    dlg = AgregarTituloDialog(pid, None)
    assert [dlg.lst_titulos.item(i).text()
            for i in range(dlg.lst_titulos.count())] == esperado[:200]
    dlg.inp_buscar.setText('zzz fínal')
    dlg._buscar_titulos()
    assert dlg.lst_titulos.count() == 1
    g2 = vt.GestorTitulosDialog()
    g2._restaurar()
    assert titulos.lista(conn) == sorted(fab + ['AAA PRIMERO'])


def test_el_menu_catalogos_lo_abre():
    import inspect
    import views.main_window as mw
    assert '_abrir_lista_titulos' in inspect.getsource(mw.MainWindow._mostrar_menu_catalogos)
