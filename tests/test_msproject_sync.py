# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Sincronización del Gantt con un XML de Microsoft Project.

Corre con:  venv/bin/python3 tests/test_msproject_sync.py

Lo que fija:

* el lector entiende lo que Project escribe de verdad (medido el 8 sep
  2026 con Project 16.0.20326): horas ISO, tipos 0-3, lag en décimas de
  minuto, Text29 conservado, tarea UID 0 agregada, resúmenes recalculados;
* el plan empareja por IngeID y NUNCA por «#» del archivo — un
  `PredecessorUID` que en Project apunta a la fila 14 se traduce al «#»
  que esa partida tiene AQUÍ, aunque no coincidan;
* los resúmenes no aportan duración, lo que no es de aquí se informa, y
  aplicar el plan solo toca lo que el plan dice.

No usa la BD: el plan trabaja sobre la lista de partidas y el cron_map,
que es lo que la vista tiene en memoria.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import msproject_importer as ms
from core.cronograma import numerar_filas, INICIO_PID, FIN_PID

XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <MinutesPerDay>480</MinutesPerDay>
  <ExtendedAttributes>
    <ExtendedAttribute><FieldID>188744015</FieldID><FieldName>Texto29</FieldName><Alias>IngeID</Alias></ExtendedAttribute>
  </ExtendedAttributes>
  <Tasks>
    <Task><UID>0</UID><ID>0</ID><Name>Proyecto</Name><Summary>1</Summary><Duration>PT96H0M0S</Duration></Task>
    <Task><UID>1</UID><ID>1</ID><Name>Obra</Name><Summary>1</Summary><OutlineLevel>1</OutlineLevel><Duration>PT96H0M0S</Duration></Task>
    <Task><UID>2</UID><ID>2</ID><Name>Inicio de Obra</Name><Milestone>1</Milestone><OutlineLevel>2</OutlineLevel><Duration>PT0H0M0S</Duration></Task>
    <Task><UID>3</UID><ID>3</ID><Name>Principal</Name><Summary>1</Summary><OutlineLevel>2</OutlineLevel><Duration>PT96H0M0S</Duration></Task>
    <Task><UID>4</UID><ID>4</ID><Name>01 TITULO</Name><Summary>1</Summary><OutlineLevel>3</OutlineLevel><Duration>PT96H0M0S</Duration>
      <ExtendedAttribute><FieldID>188744015</FieldID><Value>100</Value></ExtendedAttribute></Task>
    <Task><UID>5</UID><ID>5</ID><Name>01.01 A</Name><OutlineLevel>4</OutlineLevel><Duration>PT16H0M0S</Duration>
      <ExtendedAttribute><FieldID>188744015</FieldID><Value>101</Value></ExtendedAttribute>
      <PredecessorLink><PredecessorUID>2</PredecessorUID><Type>1</Type><LinkLag>0</LinkLag></PredecessorLink></Task>
    <Task><UID>6</UID><ID>6</ID><Name>01.02 B</Name><OutlineLevel>4</OutlineLevel><Duration>PT24H0M0S</Duration>
      <ExtendedAttribute><FieldID>188744015</FieldID><Value>102</Value></ExtendedAttribute>
      <PredecessorLink><PredecessorUID>5</PredecessorUID><Type>3</Type><LinkLag>9600</LinkLag></PredecessorLink></Task>
    <Task><UID>7</UID><ID>7</ID><Name>01.03 C</Name><OutlineLevel>4</OutlineLevel><Duration>PT8H0M0S</Duration>
      <ExtendedAttribute><FieldID>188744015</FieldID><Value>103</Value></ExtendedAttribute>
      <PredecessorLink><PredecessorUID>6</PredecessorUID><Type>1</Type><LinkLag>0</LinkLag></PredecessorLink>
      <PredecessorLink><PredecessorUID>99</PredecessorUID><Type>1</Type><LinkLag>0</LinkLag></PredecessorLink></Task>
    <Task><UID>8</UID><ID>8</ID><Name>Tarea creada en Project</Name><OutlineLevel>4</OutlineLevel><Duration>PT8H0M0S</Duration></Task>
    <Task><UID>9</UID><ID>9</ID><Name>Termino de Obra</Name><Milestone>1</Milestone><OutlineLevel>2</OutlineLevel><Duration>PT0H0M0S</Duration>
      <PredecessorLink><PredecessorUID>7</PredecessorUID><Type>1</Type><LinkLag>0</LinkLag></PredecessorLink></Task>
  </Tasks>
</Project>
"""

# El Gantt de AQUÍ: el «#» de cada partida es #1 proyecto, #2 inicio,
# #3 cabecera del sub, #4 título, #5 A, #6 B, #7 C, #8 fin. Coincide con
# Project en este caso simple; el test de abajo lo desalinea a propósito.
PARTIDAS = [
    {'id': 100, 'item': '01', 'descripcion': 'TITULO', 'es_titulo': 1, 'sub_presupuesto_id': None},
    {'id': 101, 'item': '01.01', 'descripcion': 'A', 'es_titulo': 0, 'sub_presupuesto_id': None},
    {'id': 102, 'item': '01.02', 'descripcion': 'B', 'es_titulo': 0, 'sub_presupuesto_id': None},
    {'id': 103, 'item': '01.03', 'descripcion': 'C', 'es_titulo': 0, 'sub_presupuesto_id': None},
]


def _xml_tmp(texto=XML) -> str:
    fd, path = tempfile.mkstemp(suffix='_project.xml')
    os.close(fd)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(texto)
    return path


def test_el_lector_entiende_lo_que_project_escribe():
    d = ms.leer_project_xml(_xml_tmp())
    assert d['horas_dia'] == 8.0
    t = d['tareas']
    assert t['5']['inge_id'] == '101' and t['5']['horas'] == 16.0
    assert t['4']['resumen'] and t['4']['inge_id'] == '100'
    assert t['2']['hito'] and t['2']['inge_id'] is None
    # 9600 décimas de minuto = 960 min = 16 h = 2 días; tipo 3 = SS
    assert t['6']['preds'] == [('5', 'SS', 2)], t['6']['preds']
    assert ms._horas('PT7H30M0S') == 7.5 and ms._horas('') == 0.0


def test_el_plan_empareja_por_ingeid_y_traduce_al_numero_de_aqui():
    d = ms.leer_project_xml(_xml_tmp())
    cron = {101: {'duracion': 1, 'predecesoras': '2'},
            102: {'duracion': 3, 'predecesoras': ''},
            103: {'duracion': 1, 'predecesoras': '6'}}
    plan = ms.planificar(d, PARTIDAS, cron)
    assert plan['emparejadas'] == 3
    dur = {c['pid']: (c['antes'], c['despues']) for c in plan['duraciones']}
    assert dur == {101: (1, 2)}, dur          # B sigue en 3 días, C en 1: sin cambio
    pre = {c['pid']: c['despues'] for c in plan['predecesoras']}
    assert pre == {102: '5CC+2'}, pre         # A ya colgaba de 2; C ya tenía 6
    assert plan['sin_correspondencia'] == ['Tarea creada en Project']
    assert plan['ignoradas'] and '01.03' in plan['ignoradas'][0]   # el vínculo al UID 99
    assert plan['no_en_archivo'] == 0


def test_el_numero_del_archivo_no_se_copia_nunca():
    """Si aquí hay un sub-presupuesto más (una fila virtual extra), el «#»
    de cada partida corre una posición: el vínculo 5→6 de Project debe
    salir como «6CC+2», no como «5CC+2»."""
    partidas = [dict(p, sub_presupuesto_id=7) for p in PARTIDAS]
    partidas.insert(0, {'id': 90, 'item': '00', 'descripcion': 'OTRO SUB', 'es_titulo': 1,
                        'sub_presupuesto_id': None})
    rn = numerar_filas(partidas)
    # #1 proy, #2 inicio, #3 cab principal, #4 «00», #5 cab sub 7, #6 título, #7 A
    assert rn[101] == 7, rn
    d = ms.leer_project_xml(_xml_tmp())
    plan = ms.planificar(d, partidas, {102: {'duracion': 3, 'predecesoras': ''}})
    pre = {c['pid']: c['despues'] for c in plan['predecesoras']}
    assert pre[102] == '7CC+2', pre
    assert pre[101] == '2', pre                # el hito de inicio sigue siendo #2


def test_aplicar_solo_toca_lo_que_el_plan_dice():
    d = ms.leer_project_xml(_xml_tmp())
    cron = {101: {'duracion': 1, 'predecesoras': '2', 'color': '#123456'},
            102: {'duracion': 3, 'predecesoras': ''}}
    plan = ms.planificar(d, PARTIDAS, cron)
    n = ms.aplicar(cron, plan, duraciones=True, predecesoras=False)
    assert n == 1 and cron[101]['duracion'] == 2 and cron[102]['predecesoras'] == ''
    assert cron[101]['color'] == '#123456'     # lo demás no se toca
    n = ms.aplicar(cron, plan, duraciones=False, predecesoras=True)
    assert n >= 1 and cron[102]['predecesoras'] == '5CC+2'
    assert 103 in cron                          # C no tenía fila: se crea con sus preds
    assert 'duraci' in ms.resumen(plan)


def test_hitos_marcados_con_ingeid_tienen_prioridad():
    """Los archivos nuevos marcan los hitos con IngeID -2/-3; si el usuario
    los renombró o reordenó en Project, igual se reconocen."""
    xml = XML.replace('<Name>Inicio de Obra</Name><Milestone>1</Milestone><OutlineLevel>2</OutlineLevel><Duration>PT0H0M0S</Duration>',
                      '<Name>Arranque</Name><Milestone>1</Milestone><OutlineLevel>2</OutlineLevel><Duration>PT0H0M0S</Duration>'
                      f'<ExtendedAttribute><FieldID>188744015</FieldID><Value>{INICIO_PID}</Value></ExtendedAttribute>')
    d = ms.leer_project_xml(_xml_tmp(xml))
    h = ms._resolver_hitos(d['tareas'])
    assert h['inicio'] == '2' and h['fin'] == '9', h


def test_archivo_real_de_project_si_esta_en_descargas():
    """La vuelta real del 8 sep 2026 (proyecto 431): 123 IngeID, dos
    duraciones a 16 h y una predecesora nueva hacia el UID 126."""
    path = os.path.expanduser('~/Descargas/cronograma-prueba-desde project.xml')
    if not os.path.exists(path):
        print('  (sin archivo real; se omite)')
        return
    ida = os.path.expanduser('~/Descargas/cronograma-prueba-project.xml')
    d = ms.leer_project_xml(path)
    con_id = [t for t in d['tareas'].values() if t['inge_id']]
    assert len(con_id) == 123, len(con_id)
    if os.path.exists(ida):
        antes = {t['inge_id']: t['horas'] for t in ms.leer_project_xml(ida)['tareas'].values() if t['inge_id']}
        cambiadas = sorted(t['nombre'][:5] for t in con_id
                           if not t['resumen'] and antes.get(t['inge_id']) != t['horas'])
        assert cambiadas == ['01.01', '01.02'], cambiadas
    t127 = next(t for t in d['tareas'].values() if t['id'] == '127')
    assert ('126', 'FS', 0) in t127['preds'], t127['preds']


def test_export_conserva_predecesoras_que_van_despues_de_la_tarea(tmp_path, monkeypatch):
    """#43: si la predecesora está MÁS ABAJO en la lista, el enlace se perdía
    (el UID se asignaba en el mismo bucle que escribía los enlaces). Incluye
    el caso de una predecesora de OTRO sub-presupuesto, cuya cabecera también
    consume un UID."""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget
    app = QApplication.instance() or QApplication([])
    import core.database as bd
    monkeypatch.setattr(bd, 'DB_PATH', str(tmp_path / 't43.db'))
    bd.init_db()
    get_db = bd.get_db
    conn = get_db()
    pid = conn.execute("INSERT INTO proyectos (nombre, plazo) VALUES ('T43', 30)").lastrowid
    sub = conn.execute("INSERT INTO sub_presupuestos (proyecto_id, nombre, orden) "
                       "VALUES (?, 'Sanitarias', 1)", (pid,)).lastrowid
    ids = {}
    for item, sid, tit in [('01', None, 1), ('01.01', None, 0), ('01.02', None, 0),
                           ('01', sub, 1), ('01.01', sub, 0)]:
        ids[(item, sid)] = conn.execute(
            "INSERT INTO partidas (proyecto_id, sub_presupuesto_id, item, descripcion, "
            "unidad, metrado, nivel, es_titulo) VALUES (?,?,?,?,'m2',1,?,?)",
            (pid, sid, item, f'P {item}', item.count('.') + 1, tit)).lastrowid
    a, b, c = ids[('01.01', None)], ids[('01.02', None)], ids[('01.01', sub)]
    # Filas: #1 proyecto #2 inicio #3 sub #4 título #5 a #6 b #7 sub2 #8 título #9 c
    for part, pred in [(a, '6FC+2,9CC'), (b, ''), (c, '6')]:
        conn.execute("INSERT INTO cronograma_partidas (partida_id, duracion, inicio_dia, "
                     "predecesoras) VALUES (?,3,1,?)", (part, pred))
    conn.commit()
    proy = dict(conn.execute("SELECT * FROM proyectos WHERE id=?", (pid,)).fetchone())
    conn.close()
    destino = str(tmp_path / 'crono.xml')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (destino, ''))
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    from views.cronograma_view import CronogramaView
    cv = CronogramaView(pid, proy, lambda: None)
    cv.show()
    cv.cargar()
    try:
        GW = [w for w in cv.findChildren(QWidget) if type(w).__name__ == 'GanttWidget'][0]
        GW._exportar_mpp()
        d = ms.leer_project_xml(destino)
        por_inge = {t['inge_id']: t for t in d['tareas'].values() if t['inge_id']}
        uid = {k: t['uid'] for k, t in por_inge.items()}
        assert sorted(por_inge[str(a)]['preds']) == sorted(
            [(uid[str(b)], 'FS', 2), (uid[str(c)], 'SS', 0)]), por_inge[str(a)]['preds']
        assert por_inge[str(c)]['preds'] == [(uid[str(b)], 'FS', 0)]
        # Y de vuelta a la app no aparece ninguna diferencia
        plan = ms.planificar(d, cv._partidas, cv._cron_map)
        assert plan['predecesoras'] == [], plan['predecesoras']
        assert len(set(t['uid'] for t in d['tareas'].values())) == len(d['tareas'])
    finally:
        cv.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    fallos = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and not name.startswith("test_export_"):
            try:
                fn()
                print(f"  OK  {name}")
            except AssertionError as e:
                fallos += 1
                print(f"  FAIL {name}: {e}")
    sys.exit(1 if fallos else 0)
