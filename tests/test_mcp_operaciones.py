# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Operaciones MCP: permisos, transacción, deshacer, BIM (con un doble del
módulo), refresco de la vista y «ocupado». Sobre una copia del seed."""
import json
import os
import shutil
import sys
import types
from dataclasses import dataclass, field

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PySide6.QtWidgets import QApplication                 # noqa: E402

_app = QApplication.instance() or QApplication([])

import core.database as d                                  # noqa: E402
from core import mcp_deshacer, mcp_esquemas                # noqa: E402
from core.mcp_operaciones import ErrorMCP, Operaciones     # noqa: E402
from models.usuario import Usuario                         # noqa: E402

PID = 397
SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')


@pytest.fixture
def ops(tmp_path, monkeypatch):
    db = tmp_path / 'p.db'
    shutil.copy(SEED, db)
    monkeypatch.setattr(d, 'DB_PATH', str(db))
    d.init_db()
    sql("INSERT OR IGNORE INTO usuarios (id,nombre,username,email,password_hash,"
        "rol) VALUES (1,'t','t','t@x','h','admin')")
    sql("UPDATE proyectos SET estado='elaboracion' WHERE id=?", PID)
    return Operaciones(Usuario(id=1, rol='admin'),
                       mcp_deshacer.Pila(tmp_path / 'pila'))


def sql(q, *p):
    conn = d.get_db()
    r = conn.execute(q, p).fetchall()
    conn.commit()
    conn.close()
    return [tuple(x) for x in r]


def volcado():
    conn = d.get_db()
    try:
        v = mcp_deshacer.volcar(conn, PID)
    finally:
        conn.close()
    return v


def huella():
    return mcp_deshacer.huella(volcado())


def partida(con_acu=True):
    q = ("SELECT p.id FROM partidas p WHERE proyecto_id=? AND es_titulo=0 AND "
         + ("" if con_acu else "NOT ")
         + "EXISTS (SELECT 1 FROM acu_items a WHERE a.partida_id=p.id) LIMIT 1")
    return sql(q, PID)[0][0]


# ── Deshacer ────────────────────────────────────────────────────────────────

def test_el_volcado_cubre_todas_las_tablas_que_cuelgan_del_proyecto(ops):
    conn = d.get_db()
    tablas = set(mcp_deshacer.tablas_del_proyecto(conn))
    conn.close()
    assert {'proyectos', 'partidas', 'acu_items', 'metrados_detalle',
            'acero_detalle', 'cronograma_partidas', 'sub_presupuestos',
            'pie_rubros', 'gastos_generales', 'formulas', 'formula_monomios',
            'valorizacion_detalle', 'parte_diario_recurso'} <= tablas
    assert not tablas & {'usuarios', 'configuracion', 'recursos',
                         'biblioteca_cu', 'biblioteca_acu_items', 'portafolios'}


def test_deshacer_restaura_todo_sin_cambiar_ids(ops):
    p = partida()
    sql("INSERT INTO valorizaciones (id, proyecto_id, numero) VALUES (77,?,1)", PID)
    sql("INSERT INTO valorizacion_detalle (valorizacion_id, partida_id, "
        "metrado_periodo) VALUES (77,?,3)", p)
    antes = volcado()
    rid = sql("SELECT recurso_id FROM acu_items WHERE partida_id=?", p)[0][0]
    cu = ops.search_library("concreto")["results"][0]["library_id"]
    ops.add_items(PID, [{"title": True, "description": "X"},
                        {"library_id": cu, "parent_item": "01"}])
    ops.set_metrado(p, rows=[{"length": 2, "width": 3}], replace=True)
    ops.set_acu(p, library_id=cu, mode="replace")
    ops.set_schedule(PID, durations_from_quantities=True)
    try:
        ops.set_price(PID, rid, 12.34)
        n = 5
    except ErrorMCP:
        n = 4           # ese insumo solo estaba en la partida reemplazada
    for _ in range(n):
        ops.undo_last()
    despues = volcado()
    for t in antes:
        a = [[x for x, c in zip(f, antes[t]['cols']) if c != 'modificado_en']
             for f in antes[t]['filas']]
        b = [[x for x, c in zip(f, despues[t]['cols']) if c != 'modificado_en']
             for f in despues[t]['filas']]
        assert a == b, t
    assert sql("PRAGMA foreign_key_check") == []


def test_si_el_usuario_edito_despues_se_niega_y_con_force_si(ops):
    p = partida()
    h0 = huella()
    ops.set_metrado(p, quantity=5, replace=True)
    sql("UPDATE partidas SET descripcion='EDITADA' WHERE id=?", p)
    with pytest.raises(ErrorMCP, match="editó después"):
        ops.undo_last()
    assert sql("SELECT descripcion FROM partidas WHERE id=?", p) == [('EDITADA',)]
    ops.undo_last(force=True)
    assert huella() == h0


def test_tocar_solo_la_fecha_de_modificado_no_es_editar(ops):
    ops.set_metrado(partida(), quantity=5, replace=True)
    sql("UPDATE proyectos SET modificado_en='2001-01-01' WHERE id=?", PID)
    ops.undo_last()


def test_la_pila_esta_acotada_y_es_privada(ops):
    p = partida()
    ops.pila.maximo = 3
    for n in range(6):
        ops.set_metrado(p, quantity=n + 100, replace=True)
    archivos = list(ops.pila.carpeta.glob('*'))
    assert len(archivos) == 3
    assert all(a.stat().st_mode & 0o077 == 0 for a in archivos)
    for _ in range(3):
        ops.undo_last()
    assert sql("SELECT metrado FROM partidas WHERE id=?", p) == [(102.0,)]


def test_deshacer_un_proyecto_ya_borrado_no_lo_resucita(ops):
    pid = ops.create_project("P")["project_id"]
    ops.add_items(pid, [{"title": True, "description": "A"}])
    sql("DELETE FROM proyectos WHERE id=?", pid)
    with pytest.raises(ErrorMCP, match="ya no existe"):
        ops.undo_last(force=True)
    assert sql("SELECT 1 FROM proyectos WHERE id=?", pid) == []


def test_deshacer_respeta_el_estado_del_proyecto(ops):
    ops.set_metrado(partida(), quantity=5, replace=True)
    sql("UPDATE proyectos SET estado='aprobado' WHERE id=?", PID)
    with pytest.raises(ErrorMCP, match="Aprobado"):
        ops.undo_last(force=True)


def test_deshacer_con_un_insumo_del_catalogo_borrado_no_deja_nada_roto(ops):
    p = partida()
    rid = sql("INSERT INTO recursos (descripcion, tipo, unidad, precio) "
              "VALUES ('EFIMERO','MAT','und',1) RETURNING id")[0][0]
    ops.set_acu(p, resources=[{"resource_id": rid, "quantity": 1}], mode="append")
    ops.set_acu(p, library_id=ops.search_library("muro")["results"][0]["library_id"],
                mode="replace")
    sql("DELETE FROM recursos WHERE id=?", rid)
    h = huella()
    with pytest.raises(RuntimeError, match="catálogo"):
        ops.undo_last()
    assert huella() == h and sql("PRAGMA foreign_key_check") == []


# ── Una sola transacción ────────────────────────────────────────────────────

def test_si_falla_a_medias_no_queda_nada(ops):
    h = huella()
    with pytest.raises(ErrorMCP, match=r"items\[2\]"):
        ops.add_items(PID, [{"title": True, "description": "A"},
                            {"description": "B", "unit": "m2"},
                            {"library_id": 10 ** 9}])
    assert huella() == h and ops.pila.resumen() is None


def test_si_el_disco_falla_al_guardar_la_copia_no_se_escribe(ops, monkeypatch):
    h = huella()

    def lleno(*a, **k):
        raise OSError("disco lleno")
    monkeypatch.setattr(ops.pila, 'preparar', lleno)
    with pytest.raises(OSError):
        ops.set_metrado(partida(), quantity=9, replace=True)
    assert huella() == h


# ── Permisos ────────────────────────────────────────────────────────────────

def test_invitado_solo_lee(ops):
    inv = Operaciones(Usuario(id=0, rol='invitado'), ops.pila)
    sql("UPDATE proyectos SET usuario_id=NULL WHERE id=?", PID)
    assert inv.totals(PID)["total"] > 0
    h = huella()
    for f, a in (('create_project', ("X",)), ('add_items', (
            PID, [{"title": True, "description": "A"}])),
            ('set_metrado', (partida(), None, 3.0, True)), ('undo_last', ())):
        with pytest.raises(ErrorMCP, match="invitado"):
            getattr(inv, f)(*a)
    assert huella() == h


def test_un_usuario_no_ve_ni_toca_los_proyectos_de_otro(ops):
    sql("INSERT OR IGNORE INTO usuarios (id,nombre,username,email,password_hash)"
        " VALUES (501,'a','a','a@x','h'),(502,'b','b','b@x','h')")
    sql("UPDATE proyectos SET usuario_id=501 WHERE id=?", PID)
    otro = Operaciones(Usuario(id=502, rol='usuario'), ops.pila)
    assert PID not in [p["project_id"] for p in otro.list_projects()["projects"]]
    p = partida()
    for f, a in (('totals', (PID,)), ('list_items', (PID,)), ('get_acu', (p,)),
                 ('get_metrados', (p,)), ('validate', (PID,)),
                 ('project_info', (PID,)), ('set_metrado', (p, None, 3.0, True)),
                 ('export_report', (PID, 'resumen', '/tmp/no.pdf'))):
        with pytest.raises(ErrorMCP, match="no existe"):
            getattr(otro, f)(*a)
    Operaciones(Usuario(id=501, rol='usuario'), ops.pila).set_metrado(
        p, quantity=1, replace=True)
    with pytest.raises(ErrorMCP, match="no existe"):
        otro.undo_last(force=True)


def test_un_proyecto_aprobado_no_se_edita(ops):
    sql("UPDATE proyectos SET estado='aprobado' WHERE id=?", PID)
    with pytest.raises(ErrorMCP, match="Aprobado"):
        ops.set_metrado(partida(), quantity=1, replace=True)


def test_ninguna_lectura_enseña_claves_ni_usuarios(ops):
    sql("INSERT OR REPLACE INTO configuracion VALUES ('api_key','SECRETO-XYZ')")
    sql("INSERT OR IGNORE INTO usuarios (id,nombre,username,email,password_hash)"
        " VALUES (503,'c','nombre-usr','correo@secreto','HASH-ABC')")
    sql("UPDATE proyectos SET usuario_id=503 WHERE id=?", PID)
    p = partida()
    todo = json.dumps([ops.list_projects(), ops.project_info(PID),
                       ops.list_items(PID), ops.get_acu(p), ops.get_metrados(p),
                       ops.totals(PID), ops.validate(PID),
                       ops.search_library("muro"), ops.search_resources("cemento")])
    ops.set_metrado(p, quantity=1, replace=True)
    import gzip
    todo += ''.join(gzip.decompress(a.read_bytes()).decode()
                    for a in ops.pila.carpeta.glob('*.gz'))
    for s in ('SECRETO-XYZ', 'HASH-ABC', 'correo@secreto', 'nombre-usr'):
        assert s not in todo


# ── Reglas ──────────────────────────────────────────────────────────────────

def test_la_biblioteca_en_otra_moneda_pide_decidir(ops):
    pid = ops.create_project("CO", currency="Pesos Colombianos")["project_id"]
    cu = ops.search_library("concreto columnas")["results"][0]["library_id"]
    with pytest.raises(ErrorMCP, match="library_prices"):
        ops.add_items(pid, [{"library_id": cu}])
    r = ops.add_items(pid, [{"library_id": cu}], library_prices="structure_only")
    acu = ops.get_acu(r["added"][0]["item_id"])
    assert acu["resources"] and acu["unit_price"] == 0


def test_set_acu_deriva_la_cantidad_de_la_cuadrilla(ops):
    pid = ops.create_project("A", workday_hours=8)["project_id"]
    part = ops.add_items(pid, [{"description": "P", "unit": "m2"}])["added"][0]["item_id"]
    mo = sql("SELECT id FROM recursos WHERE tipo='MO' AND unidad='hh' LIMIT 1")[0][0]
    mat = sql("SELECT id FROM recursos WHERE tipo='MAT' AND precio>2 AND "
              "unidad='kg' LIMIT 1")[0][0]
    ops.set_acu(part, performance=20, resources=[
        {"resource_id": mo, "crew": 1}, {"resource_id": mat, "quantity": 2.5}])
    acu = {r["resource_id"]: r for r in ops.get_acu(part)["resources"]}
    assert acu[mo]["quantity"] == pytest.approx(0.4)       # 1/20*8
    assert acu[mat]["crew"] == 0
    ops.set_acu(part, performance=40)
    assert {r["resource_id"]: r["quantity"] for r in
            ops.get_acu(part)["resources"]}[mo] == pytest.approx(0.2)
    with pytest.raises(ErrorMCP, match="cuadrilla"):
        ops.set_acu(part, mode="append", resources=[
            {"resource_id": sql("SELECT id FROM recursos WHERE tipo='MAT' AND id<>?"
                                " AND unidad='kg' LIMIT 1", mat)[0][0], "crew": 1}])
    pr = ops.set_price(pid, mat, 7.5)
    assert pr["items_updated"] == [part]
    assert sql("SELECT precio FROM recursos WHERE id=?", mat)[0][0] != 7.5


def test_la_planilla_del_mcp_da_lo_mismo_que_la_de_la_vista(ops):
    """Misma regla que `ProyectoView._metrado_guardar_silencioso`."""
    from views.proyecto_view import ProyectoView
    p = partida()
    filas = [("a", 2, None, None, 1.333, 2.5, None),
             ("solo texto", None, None, None, None, None, None),
             ("c", None, 3, 0.777, None, None, 1.11)]
    ops.set_metrado(p, replace=True, rows=[
        {k: v for k, v in zip(("description", "structures", "elements", "area",
                               "length", "width", "height"), f) if v is not None}
        for f in filas])
    mcp = sql("SELECT parcial FROM metrados_detalle WHERE partida_id=? ORDER BY "
              "orden", p), sql("SELECT metrado FROM partidas WHERE id=?", p)
    v = ProyectoView(PID, Usuario(id=1, rol='admin'))
    v._completar_panel_tabs()
    v._cargar_datos_inicial()
    v.cargar_metrados(p)
    v._metrado_guardar_silencioso()
    assert mcp == (sql("SELECT parcial FROM metrados_detalle WHERE partida_id=? "
                       "ORDER BY orden", p),
                   sql("SELECT metrado FROM partidas WHERE id=?", p))
    v.deleteLater()


def test_aplicar_rendimiento_da_lo_mismo_que_la_vista(ops):
    from views.proyecto_view import ProyectoView
    p = sql("SELECT a.partida_id FROM acu_items a JOIN partidas p ON "
            "p.id=a.partida_id WHERE p.proyecto_id=? AND a.cuadrilla>0 "
            "AND p.unidad NOT IN ('glb','est') LIMIT 1", PID)[0][0]
    ops.set_acu(p, performance=33)
    q = "SELECT id, cantidad FROM acu_items WHERE partida_id=? ORDER BY id"
    mcp = sql(q, p), sql("SELECT precio_unitario FROM partidas WHERE id=?", p)
    ops.undo_last()
    v = ProyectoView(PID, Usuario(id=1, rol='admin'))
    v._completar_panel_tabs()
    v._cargar_datos_inicial()
    v.cargar_acu(p)
    v.inp_rend.setText("33")
    v._guardar_rendimiento()
    assert mcp == (sql(q, p),
                   sql("SELECT precio_unitario FROM partidas WHERE id=?", p))
    v.deleteLater()


def test_add_items_valida_codigos(ops):
    pid = ops.create_project("Z")["project_id"]
    ops.add_items(pid, [{"title": True, "item": "01", "description": "A"},
                        {"item": "01.01", "description": "p", "unit": "m"}])
    for malo, msg in (({"item": "01", "title": True, "description": "x"}, "ya existe"),
                      ({"item": "05.01", "description": "x", "unit": "m"}, "05"),
                      ({"parent_item": "01.01", "description": "x", "unit": "m"},
                       "partida"),
                      ({"description": "x"}, "unit")):
        with pytest.raises(ErrorMCP, match=msg):
            ops.add_items(pid, [malo])


def test_export_no_sigue_enlaces_ni_deja_restos(ops, tmp_path, monkeypatch):
    real = tmp_path / 'real.pdf'
    real.write_bytes(b'mio')
    enlace = tmp_path / 'l.pdf'
    enlace.symlink_to(real)
    with pytest.raises(ErrorMCP, match="normal"):
        ops.export_report(PID, 'resumen', str(enlace), overwrite=True)
    from core import pdf_reports

    def peta(*a, **k):
        raise ValueError("x")
    monkeypatch.setattr(pdf_reports, 'generar_pdf_archivo', peta)
    with pytest.raises(ValueError):
        ops.export_report(PID, 'resumen', str(real), overwrite=True)
    assert real.read_bytes() == b'mio'
    assert not list(tmp_path.glob('.ingeppto*'))


# ── BIM con un doble del contrato ───────────────────────────────────────────

@dataclass
class _Elem:
    global_id: str


@dataclass
class _Modelo:
    nombre: str = 'M'
    elementos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)


@pytest.fixture
def bim(monkeypatch):
    """Doble de core.bim_modelo que escribe de verdad sus tablas."""
    import core
    m = types.ModuleType('core.bim_modelo')

    def crear():
        conn = d.get_db()
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS bim_modelos (id INTEGER PRIMARY KEY,
            proyecto_id INTEGER, nombre TEXT);
          CREATE TABLE IF NOT EXISTS bim_elementos (modelo_id INTEGER,
            global_id TEXT, datos TEXT);
          CREATE TABLE IF NOT EXISTS bim_vinculos (id INTEGER PRIMARY KEY,
            partida_id INTEGER, modelo_id INTEGER, global_id TEXT, medida TEXT,
            factor REAL, metrado_detalle_id INTEGER);""")
        conn.close()

    def registrar(pid, modelo, ruta):
        mid = sql("INSERT INTO bim_modelos (proyecto_id,nombre) VALUES (?,?) "
                  "RETURNING id", pid, modelo.nombre)[0][0]
        for e in modelo.elementos:
            sql("INSERT INTO bim_elementos VALUES (?,?,'{}')", mid, e.global_id)
        return mid

    def vincular(part, mid, gids, medida=None, factor=1.0):
        for g in gids:
            md = sql("INSERT INTO metrados_detalle (partida_id,descripcion,parcial)"
                     " VALUES (?,?,2) RETURNING id", part, g)[0][0]
            sql("INSERT INTO bim_vinculos (partida_id,modelo_id,global_id,"
                "metrado_detalle_id) VALUES (?,?,?,?)", part, mid, g, md)
            if g == 'ROMPE':
                raise ValueError("a medias")
    m.leer_takeoff = lambda t: _Modelo(elementos=[_Elem(e['global_id'])
                                                  for e in t['elements']])
    m.leer_ifc = lambda p: _Modelo()
    m.registrar_modelo = registrar
    m.modelos = lambda pid: [dict(id=i, nombre=n) for i, n in sql(
        "SELECT id,nombre FROM bim_modelos WHERE proyecto_id=?", pid)]
    m.elementos = lambda mid: [_Elem(g) for g, in sql(
        "SELECT global_id FROM bim_elementos WHERE modelo_id=?", mid)]
    m.vincular = vincular
    m.vinculos_partida = lambda p: [dict(global_id=g) for g, in sql(
        "SELECT global_id FROM bim_vinculos WHERE partida_id=?", p)]
    m.diferencias = lambda mid, mod: dict(nuevos=['N'], borrados=[], cambiados=[],
                                          iguales=[1, 2], partidas=[])
    m.proponer_partidas = lambda mod: [dict(descripcion='MURO', global_ids=['A'])]

    def aplicar(mid, mod, partidas=None):
        sql("UPDATE bim_modelos SET nombre='aplicado' WHERE id=?", mid)
    m.aplicar = aplicar
    monkeypatch.setitem(sys.modules, 'core.bim_modelo', m)
    monkeypatch.setattr(core, 'bim_modelo', m, raising=False)
    m.crear = crear
    return m


TAKE = {"schema": "inge-takeoff", "version": 1,
        "elements": [{"global_id": "A"}, {"global_id": "B"},
                     {"global_id": "ROMPE"}]}


def test_bim_registra_vincula_aplica_y_se_deshace(ops, bim):
    bim.crear()
    h0 = huella()
    assert ops.bim_diff(PID, 'ingetrazo', _takeoff=TAKE)["proposals"]
    mid = ops.bim_apply(PID, 'ingetrazo', _takeoff=TAKE)["model_id"]
    p = partida()
    sql("DELETE FROM metrados_detalle WHERE partida_id=?", p)
    h1 = huella()
    assert ops.link_elements(p, mid, ["A", "B", "A"])["links"] == 2
    assert {r["bim_global_id"] for r in ops.get_metrados(p)["rows"]} == {"A", "B"}
    with pytest.raises(ErrorMCP, match="BIM"):
        ops.set_metrado(p, quantity=1, replace=True)
    with pytest.raises(ErrorMCP, match="no tiene"):
        ops.link_elements(p, mid, ["ZZ"])
    assert ops.elementos_a_mostrar(item_id=p) == ["A", "B"]
    r = ops.bim_apply(PID, 'ingetrazo', model_id=mid, _takeoff=TAKE)
    assert r["applied"]["counts"]["iguales"] == 2
    ops.undo_last()
    ops.undo_last()
    assert huella() == h1
    ops.undo_last(force=True)                # el DELETE de arriba fue «a mano»
    assert huella() == h0


def test_bim_que_falla_a_medias_se_restaura(ops, bim):
    bim.crear()
    mid = ops.bim_apply(PID, 'ingetrazo', _takeoff=TAKE)["model_id"]
    h = huella()
    with pytest.raises(ValueError):
        ops.link_elements(partida(), mid, ["A", "ROMPE"])
    assert huella() == h
    assert ops.pila.resumen()['herramienta'] == 'bim_apply'


def test_bim_ifc_solo_rutas_ifc(ops, bim, tmp_path):
    bim.crear()
    for ruta in ('rel.ifc', '/etc/passwd', str(tmp_path / 'no.ifc'), None):
        with pytest.raises(ErrorMCP):
            ops.bim_diff(PID, 'ifc', path=ruta)


# ── En la ventana ───────────────────────────────────────────────────────────

@pytest.fixture
def puente(ops, monkeypatch):
    import utils.auth as auth
    from views.main_window import MainWindow
    from views.mcp_puente import puente_de
    u = Usuario(id=1, nombre='t', rol='admin')
    monkeypatch.setattr(auth, '_usuario_actual', u)
    w = MainWindow(usuario=None)
    w.usuario = u
    w.show()
    w._abrir_proyecto(PID)
    _girar(lambda: hasattr(_vista(w), 'tbl_acu')
           and getattr(_vista(w), '_id_to_item', None))
    p = puente_de(w)
    p.pila = ops.pila
    yield p
    p.apagar()
    w.close()
    w.deleteLater()


def _girar(cond, n=400):
    import time
    for _ in range(n):
        _app.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("no llegó")


def _vista(w):
    for i in range(w.stack.count()):
        if w.stack.widget(i).property('vista_nombre') == f'proyecto_{PID}':
            return w.stack.widget(i)


def test_apagado_por_defecto(ops, puente):
    assert not puente.encendido
    assert sql("SELECT valor FROM configuracion WHERE clave='mcp_activo'") == []


def test_escribir_refresca_arbol_acu_y_planilla(puente):
    v = _vista(puente._ventana)
    p = partida()
    v.cargar_acu(p)
    v.cargar_metrados(p)
    puente.ejecutar('set_metrado', {"item_id": p, "replace": True,
                                    "rows": [{"length": 7, "width": 3}]})
    assert v._id_to_item[p].text(3) == "21.00"
    assert v.tbl_met.item(0, 4).text() == "7.0"
    # La planilla recargada no reescribe la vieja al guardarse sola.
    v._metrado_guardar_silencioso()
    assert sql("SELECT metrado FROM partidas WHERE id=?", p) == [(21.0,)]
    # Deshacer un agregado con esa partida a la vista deja el panel en blanco.
    r = puente.ejecutar('add_items', {"project_id": PID, "items": [
        {"description": "NUEVA", "unit": "m2", "parent_item": "01"}]})
    nueva = r["added"][0]["item_id"]
    assert nueva in v._id_to_item
    v.cargar_acu(nueva)
    v.cargar_metrados(nueva)
    puente.ejecutar('undo_last', {})
    assert nueva not in v._id_to_item
    assert v._partida_actual_id is None and v._met_panel_pid is None


def test_con_una_celda_en_edicion_responde_ocupado(puente):
    v = _vista(puente._ventana)
    p = partida()
    h = huella()
    item = v._id_to_item[p]
    from PySide6.QtCore import Qt
    item.setFlags(item.flags() | Qt.ItemIsEditable)
    v.tree.setCurrentItem(item)
    v.tree.editItem(item, 3)
    ed = [w for w in v.tree.viewport().children() if hasattr(w, 'setText')]
    assert ed
    ed[0].setText("55")
    with pytest.raises(ErrorMCP, match="ocupado"):
        puente.ejecutar('set_metrado', {"item_id": p, "quantity": 1,
                                        "replace": True})
    assert huella() == h and ed[0].text() == "55"        # no perdió lo escrito
    assert puente.ejecutar('totals', {"project_id": PID})   # leer sí se puede


def test_especificacion_sin_guardar_responde_ocupado(puente):
    v = _vista(puente._ventana)
    v._spec_modificada = True
    with pytest.raises(ErrorMCP, match="especificaciones"):
        puente.ejecutar('set_metrado', {"item_id": partida(), "quantity": 1,
                                        "replace": True})


def test_sin_sesion_no_atiende(puente, monkeypatch):
    import utils.auth as auth
    monkeypatch.setattr(auth, '_usuario_actual', None)
    with pytest.raises(ErrorMCP, match="sesión"):
        puente.ejecutar('list_projects', {})


def test_la_captura_nunca_enseña_configuracion(puente):
    w = puente._ventana
    assert puente.ejecutar('screenshot', {})["view"] == f'proyecto_{PID}'
    w._ir_a_configuracion()
    with pytest.raises(ErrorMCP, match="claves"):
        puente.ejecutar('screenshot', {})


def test_el_boton_pregunta_si_el_usuario_edito_despues(puente, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from views.mcp_dialog import deshacer_con_aviso
    p = partida()
    h = huella()
    puente.ejecutar('set_metrado', {"item_id": p, "quantity": 1, "replace": True})
    sql("UPDATE partidas SET descripcion='MÍA' WHERE id=?", p)
    monkeypatch.setattr(QMessageBox, 'question',
                        staticmethod(lambda *a, **k: QMessageBox.No))
    assert not deshacer_con_aviso(None, puente)
    assert sql("SELECT descripcion FROM partidas WHERE id=?", p) == [('MÍA',)]
    monkeypatch.setattr(QMessageBox, 'question',
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    assert deshacer_con_aviso(None, puente)
    assert huella() == h


def test_el_panel_enciende_apaga_y_copia(puente, tmp_path, monkeypatch):
    monkeypatch.setenv('INGEPRESUPUESTOS_MCP_REGISTRO', str(tmp_path / 'reg'))
    from views.mcp_dialog import DialogoMCP
    dlg = DialogoMCP(puente._ventana)
    dlg.panel.chk.click()
    assert puente.encendido
    assert len(list((tmp_path / 'reg').glob('*.json'))) == 1
    assert sql("SELECT valor FROM configuracion WHERE clave='mcp_activo'") == [('1',)]
    dlg.panel._copiar()
    assert QApplication.clipboard().text().startswith('claude mcp add ingepresupuestos')
    dlg.panel.chk.click()
    assert not puente.encendido and not list((tmp_path / 'reg').glob('*.json'))
    dlg.deleteLater()


def test_configuracion_trae_la_seccion(puente):
    from views.configuracion_view import ConfiguracionView
    v = ConfiguracionView(ventana=puente._ventana)
    v.set_tab('mcp')
    assert v._panel_mcp.chk.isEnabled()
    v.deleteLater()


# ── Líneas para cada cliente ────────────────────────────────────────────────

@pytest.mark.parametrize("env,plat,cong,exe,espera", [
    ({"FLATPAK_ID": "com.x"}, "linux", False, "/usr/bin/python3",
     ["flatpak", "run", "com.x", "--mcp"]),
    ({"SNAP_NAME": "ingepresupuestos"}, "linux", True, "/snap/x",
     ["snap", "run", "ingepresupuestos", "--mcp"]),
    ({"APPIMAGE": "/a b/I.AppImage"}, "linux", True, "/tmp/.mount/x",
     ["/a b/I.AppImage", "--mcp"]),
    ({}, "darwin", True, "/A/ingepresupuestos", ["/A/ingepresupuestos", "--mcp"]),
])
def test_comando_por_instalacion(env, plat, cong, exe, espera):
    from views.mcp_dialog import comando_servidor, instrucciones
    cmd = comando_servidor(env, plat, cong, exe)
    assert cmd == espera
    ins = {n: t for n, _d, t in instrucciones(cmd, plat)}
    assert json.loads(ins["Claude Desktop"])["mcpServers"]["ingepresupuestos"][
        "command"] == espera[0]
    import tomllib
    assert tomllib.loads(ins["Codex"])["mcp_servers"]["ingepresupuestos"][
        "args"] == espera[1:]


def test_comando_windows_es_el_exe_de_consola():
    from views.mcp_dialog import comando_servidor
    cmd, = comando_servidor({}, "win32", True, "/P/ingepresupuestos.exe")
    assert cmd.endswith("ingepresupuestos-mcp.exe")


def test_registro_en_snap_y_flatpak(monkeypatch, tmp_path):
    from core import mcp_registro as r
    monkeypatch.delenv(r.VARIABLE, raising=False)
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('XDG_STATE_HOME', '/sandbox/state')     # Flatpak: se ignora
    normal = tmp_path / '.local/state/ingepresupuestos/mcp'
    assert r.carpeta() == normal
    comun = tmp_path / 'snap/ingepresupuestos/common'
    assert comun / 'mcp' in r.carpetas_lectura()               # host lee del snap
    monkeypatch.setenv('SNAP_NAME', 'ingepresupuestos')
    monkeypatch.setenv('SNAP_USER_COMMON', str(comun))
    monkeypatch.setenv('SNAP_REAL_HOME', str(tmp_path))
    monkeypatch.setenv('HOME', str(tmp_path / 'snap/ingepresupuestos/3'))
    assert r.carpeta() == comun / 'mcp'
    a = r.publicar('i1', 1, r.nuevo_token())
    monkeypatch.delenv('SNAP_NAME')
    monkeypatch.setenv('HOME', str(tmp_path))
    assert [x['instancia'] for x in r.leer()] == ['i1'] and a.is_file()
    # Nadie escucha en el puerto 1: se poda.
    monkeypatch.setenv(r.VARIABLE, str(comun / 'mcp'))
    assert r.podar() == 1 and not a.exists()


def test_validador_rechaza_nan_y_bool():
    for args in ({"project_id": 1, "resource_id": 1, "price": float('nan')},
                 {"project_id": 1, "resource_id": 1, "price": True},
                 {"project_id": 1, "resource_id": 1, "price": -1}):
        with pytest.raises(mcp_esquemas.ErrorDeArgumentos):
            mcp_esquemas.validar("set_price", args)
