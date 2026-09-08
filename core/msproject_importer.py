# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Sincronización del cronograma con Microsoft Project por archivo XML.

El viaje es de ida y vuelta: el botón «MPP» del Gantt exporta un XML
(MSPDI) que escribe en cada tarea el id de la partida en el campo Text29
(alias «IngeID»); el usuario lo abre en Project, cambia duraciones y
dependencias, lo guarda con «Guardar como → XML» (Ctrl+S insiste en .mpp,
comprobado el 8 sep 2026) y este módulo lo lee, empareja cada tarea con su
partida por ese id y arma un PLAN de cambios que la vista muestra antes de
aplicar. Pedido de David Ramos (5 sep 2026): «copiar valores a las columnas
de predecesoras y duración desde Project».

Por qué por id y no pegando columnas: en Project el «12» es la tarea 12 de
SU archivo; en el Gantt de la app el «#» numera TODAS las filas, incluidas
las virtuales (resumen del proyecto, «Inicio de Obra», cabeceras de
sub-presupuesto, «Termino de Obra»). Pegar el texto tal cual crea
dependencias equivocadas que parecen correctas. Acá cada `PredecessorUID`
se resuelve UID → IngeID → partida → «#» actual.

Lo que Project hace por su cuenta y hay que ignorar (medido el 8 sep 2026
con Project 16.0.20326 sobre el proyecto 431): agrega una tarea UID 0 con el
resumen del proyecto; recalcula la duración de los resúmenes sumando sus
hijos (por eso las duraciones se leen SOLO de partidas); renombra el campo a
«Texto29» pero conserva el FieldID; escribe `LinkLag` como `0` donde
nosotros no escribíamos nada; y devuelve algún nombre con un espacio de más
(por eso los nombres no se usan para emparejar).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from core.cronograma import (
    FIN_PID, INICIO_PID, _TIPO_ES, numerar_filas, parse_predecesoras,
)

NS = {'p': 'http://schemas.microsoft.com/project'}
# FieldID del campo personalizado Text29 (enumeración PjCustomField).
MSPDI_TEXT29 = '188744015'
# Valores del IngeID que el export escribe en los hitos virtuales (desde el
# 8 sep 2026). Los archivos anteriores no los llevan: ver `_resolver_hitos`.
INGEID_INICIO = str(INICIO_PID)
INGEID_FIN = str(FIN_PID)
# Códigos de tipo de vínculo de Project.
TIPO_PROJECT = {'0': 'FF', '1': 'FS', '2': 'SF', '3': 'SS'}

_DUR = re.compile(r'^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$')


def _horas(iso: str | None) -> float:
    """`PT16H0M0S` → 16.0. Vacío o ilegible → 0."""
    m = _DUR.match((iso or '').strip())
    if not m:
        return 0.0
    h, mi, s = (float(x or 0) for x in m.groups())
    return h + mi / 60.0 + s / 3600.0


def leer_project_xml(path: str) -> dict:
    """Lee un XML de Project y devuelve::

        {'horas_dia': 8.0,
         'tareas': {uid: {'uid', 'id', 'nombre', 'horas', 'resumen', 'hito',
                          'nivel', 'inge_id', 'preds': [(pred_uid, tipo, lag_dias)]}}}

    `inge_id` es el Text29 (None si la tarea no lo trae). `tipo` ya viene
    como 'FS'/'SS'/'FF'/'SF'. `lag_dias` es entero (Project guarda el lag en
    décimas de minuto).
    """
    root = ET.parse(path).getroot()
    minutos_dia = float(root.findtext('p:MinutesPerDay', default='480', namespaces=NS) or 480)
    horas_dia = minutos_dia / 60.0 or 8.0
    tareas: dict[str, dict] = {}
    for t in root.findall('p:Tasks/p:Task', NS):
        uid = t.findtext('p:UID', namespaces=NS)
        if uid is None:
            continue
        inge = None
        for ea in t.findall('p:ExtendedAttribute', NS):
            if ea.findtext('p:FieldID', namespaces=NS) == MSPDI_TEXT29:
                inge = (ea.findtext('p:Value', namespaces=NS) or '').strip() or None
        preds = []
        for pl in t.findall('p:PredecessorLink', NS):
            puid = pl.findtext('p:PredecessorUID', namespaces=NS)
            tipo = TIPO_PROJECT.get((pl.findtext('p:Type', namespaces=NS) or '1').strip(), 'FS')
            try:
                lag_dm = float(pl.findtext('p:LinkLag', namespaces=NS) or 0)
            except ValueError:
                lag_dm = 0.0
            lag_dias = int(round(lag_dm / 10.0 / 60.0 / horas_dia)) if lag_dm else 0
            if puid:
                preds.append((puid.strip(), tipo, lag_dias))
        tareas[uid.strip()] = {
            'uid': uid.strip(),
            'id': (t.findtext('p:ID', namespaces=NS) or '').strip(),
            'nombre': (t.findtext('p:Name', default='', namespaces=NS) or '').strip(),
            'horas': _horas(t.findtext('p:Duration', namespaces=NS)),
            'resumen': (t.findtext('p:Summary', namespaces=NS) or '0').strip() == '1',
            'hito': (t.findtext('p:Milestone', namespaces=NS) or '0').strip() == '1',
            'nivel': int(t.findtext('p:OutlineLevel', namespaces=NS) or 0),
            'inge_id': inge,
            'preds': preds,
        }
    return {'horas_dia': horas_dia, 'tareas': tareas}


def _resolver_hitos(tareas: dict) -> dict:
    """UID de los hitos virtuales «Inicio de Obra» y «Termino de Obra».

    Los archivos exportados desde el 8 sep 2026 los marcan con IngeID -2/-3.
    En los anteriores no hay marca: se toman el primer y el último hito sin
    IngeID (el export los emite en ese orden, y Project conserva los UID).
    """
    ini = fin = None
    for t in tareas.values():
        if t['inge_id'] == INGEID_INICIO:
            ini = t['uid']
        elif t['inge_id'] == INGEID_FIN:
            fin = t['uid']
    if ini is None or fin is None:
        hitos = [t for t in tareas.values()
                 if t['hito'] and not t['inge_id'] and t['uid'] != '0']
        hitos.sort(key=lambda t: int(t['uid']) if t['uid'].isdigit() else 0)
        if hitos:
            ini = ini or hitos[0]['uid']
            fin = fin or hitos[-1]['uid']
    return {'inicio': ini, 'fin': fin}


def _token(rn: int, tipo: str, lag: int) -> str:
    """Un token de predecesora en la notación del Gantt: «14», «14CC+2», «9FF-1»."""
    tok = str(rn)
    if tipo != 'FS':
        tok += _TIPO_ES.get(tipo, tipo)
    if lag:
        tok += ('+' if lag > 0 else '-') + str(abs(int(lag)))
    return tok


def _canon(preds_txt: str, rownum_inv: dict, item_map: dict) -> set:
    return {(p['pid'], p['tipo'], int(p['lag'] or 0), int(p['pct'] or 0),
             int(p['tgt_pct'] or 0))
            for p in parse_predecesoras(preds_txt or '', rownum_inv, item_map)}


def planificar(datos: dict, partidas: list, cron_map: dict) -> dict:
    """Arma el plan de cambios sin tocar nada.

    `partidas` es la lista del Gantt (agrupada por sub-presupuesto, como la
    carga la vista) y `cron_map` el `{partida_id: {...}}` de
    `get_cronograma_map`. Devuelve::

        {'duraciones':    [{'pid', 'item', 'descripcion', 'antes', 'despues'}],
         'predecesoras':  [{'pid', 'item', 'descripcion', 'antes', 'despues'}],
         'sin_correspondencia': [nombre, ...],   # tareas del archivo que no son de aquí
         'no_en_archivo': n,                     # partidas de aquí que el archivo no trae
         'emparejadas': n}
    """
    tareas = datos['tareas']
    horas_dia = float(datos.get('horas_dia') or 8.0)
    rownum = numerar_filas(partidas)
    rownum_inv = {v: k for k, v in rownum.items()}
    item_map = {p.get('item'): p['id'] for p in partidas if p.get('item')}
    por_id = {p['id']: p for p in partidas}
    hitos = _resolver_hitos(tareas)

    # UID del archivo → partida (o hito virtual) de aquí
    uid_a_pid: dict[str, int] = {}
    for t in tareas.values():
        if t['inge_id'] == INGEID_INICIO or t['uid'] == hitos['inicio']:
            uid_a_pid[t['uid']] = INICIO_PID
        elif t['inge_id'] == INGEID_FIN or t['uid'] == hitos['fin']:
            uid_a_pid[t['uid']] = FIN_PID
        elif t['inge_id'] and t['inge_id'].lstrip('-').isdigit():
            pid = int(t['inge_id'])
            if pid in por_id:
                uid_a_pid[t['uid']] = pid

    plan = {'duraciones': [], 'predecesoras': [], 'sin_correspondencia': [],
            'no_en_archivo': 0, 'emparejadas': 0, 'ignoradas': []}
    vistas: set[int] = set()
    for t in tareas.values():
        pid = uid_a_pid.get(t['uid'])
        if pid is None:
            # El resumen del proyecto (UID 0), las cabeceras de sub-presupuesto
            # y lo que el usuario haya creado en Project: se informa, no se toca.
            if t['uid'] != '0' and not t['resumen']:
                plan['sin_correspondencia'].append(t['nombre'] or f"UID {t['uid']}")
            continue
        if pid in (INICIO_PID, FIN_PID):
            continue
        p = por_id[pid]
        vistas.add(pid)
        if p.get('es_titulo'):
            continue          # Project recalcula los resúmenes: no son dato
        plan['emparejadas'] += 1
        cd = cron_map.get(pid, {})

        # Duración: horas → días de jornada del archivo, entero, mínimo 1.
        dias = max(1, int(round(t['horas'] / horas_dia))) if t['horas'] > 0 else 0
        antes = int(cd.get('duracion', 1) or 1)
        if dias > 0 and dias != antes:
            plan['duraciones'].append({'pid': pid, 'item': p.get('item') or '',
                                       'descripcion': p.get('descripcion') or '',
                                       'antes': antes, 'despues': dias})

        # Predecesoras: cada vínculo del archivo → token con el «#» actual.
        tokens, perdidas = [], []
        for puid, tipo, lag in t['preds']:
            ppid = uid_a_pid.get(puid)
            if ppid is None:
                perdidas.append(puid)
                continue
            rn = rownum.get(ppid)
            if rn is None:
                perdidas.append(puid)
                continue
            tokens.append(_token(rn, tipo, lag))
        if perdidas:
            plan['ignoradas'].append(
                f"{p.get('item') or ''} {p.get('descripcion') or ''}: "
                f"{len(perdidas)} vínculo(s) a tareas que no son de aquí")
        nuevo = ', '.join(tokens)
        actual = (cd.get('predecesoras') or '').strip()
        if _canon(nuevo, rownum_inv, item_map) != _canon(actual, rownum_inv, item_map):
            plan['predecesoras'].append({'pid': pid, 'item': p.get('item') or '',
                                         'descripcion': p.get('descripcion') or '',
                                         'antes': actual, 'despues': nuevo})

    plan['no_en_archivo'] = sum(1 for p in partidas
                                if not p.get('es_titulo') and p['id'] not in vistas)
    return plan


def aplicar(cron_map: dict, plan: dict, *, duraciones: bool = True,
            predecesoras: bool = True) -> int:
    """Vuelca el plan sobre `cron_map` (el dict vivo de la vista). Devuelve
    cuántas partidas cambiaron. El llamador guarda a BD y recalcula el CPM."""
    n = 0
    tocadas: set[int] = set()

    def _fila(pid):
        if pid not in cron_map:
            cron_map[pid] = {'partida_id': pid, 'duracion': 1, 'inicio_dia': 1,
                             'predecesoras': '', 'es_hito': 0, 'segmentos': '',
                             'color': ''}
        return cron_map[pid]

    if duraciones:
        for c in plan.get('duraciones', []):
            _fila(c['pid'])['duracion'] = int(c['despues'])
            tocadas.add(c['pid'])
    if predecesoras:
        for c in plan.get('predecesoras', []):
            _fila(c['pid'])['predecesoras'] = c['despues']
            tocadas.add(c['pid'])
    n = len(tocadas)
    return n


def resumen(plan: dict) -> str:
    """Una línea para el diálogo: «2 duraciones · 1 predecesora · 0 sin correspondencia»."""
    d, pr, sc = (len(plan.get('duraciones', [])), len(plan.get('predecesoras', [])),
                 len(plan.get('sin_correspondencia', [])))
    partes = [f"{d} {'duraciones' if d != 1 else 'duración'}",
              f"{pr} predecesora{'s' if pr != 1 else ''}"]
    if sc:
        partes.append(f"{sc} tarea{'s' if sc != 1 else ''} sin correspondencia")
    if plan.get('no_en_archivo'):
        partes.append(f"{plan['no_en_archivo']} partida(s) de aquí que el archivo no trae")
    return ' · '.join(partes)
