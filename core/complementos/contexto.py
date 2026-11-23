# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Los datos que recibe un complemento y la escritura que se le permite.

Lectura: una foto (`api.Presupuesto`) armada con los mismos cálculos que la
pantalla y los reportes. Escritura: las operaciones de `core.mcp_operaciones`
—transacción, copia para deshacer, permisos y estado del proyecto—, nunca una
conexión a la base.
"""
from __future__ import annotations

from core.mcp_operaciones import ErrorMCP, Operaciones
from ingepresupuestos import api


class OperacionesComplemento(Operaciones):
    """Las mismas operaciones, con el nombre del complemento en el deshacer."""

    def __init__(self, usuario, complemento: str, pila=None):
        super().__init__(usuario, pila)
        self._complemento = complemento

    def _escribir(self, herramienta, pid, nivel, cambio):
        return super()._escribir(f"complemento:{self._complemento}", pid, nivel,
                                 cambio)


def moneda(nombre: str) -> api.Moneda:
    from core.config import moneda_cfg
    c = moneda_cfg(nombre)
    return api.Moneda(nombre, c['simbolo'], c['sep_miles'], c['sep_dec'])


def presupuesto(pid: int, usuario) -> api.Presupuesto:
    """La foto del proyecto. Solo si ese usuario lo ve."""
    from core import partidas_ops
    from core.database import (calcular_totales, get_acu_items, get_db,
                               get_decimales_ppto, get_insumos_proyecto)
    from core.pie import es_impuesto, pie_efectivo
    conn = get_db()
    try:
        try:
            proy = Operaciones(usuario)._proyecto(conn, pid)
        except ErrorMCP as e:
            raise api.ErrorComplemento(str(e)) from None
        items, t = calcular_totales(pid, conn)
        parciales = {i['partida']['id']: i['total'] for i in items}
        subs = {None: proy.get('sub_presupuesto') or ''}
        subs.update((r['id'], r['nombre']) for r in conn.execute(
            "SELECT id, nombre FROM sub_presupuestos WHERE proyecto_id=?", (pid,)))
        partidas = []
        for p in partidas_ops.partidas_en_orden(conn, pid):
            acu = () if p['es_titulo'] else tuple(
                api.Insumo(
                    recurso_id=a['recurso_id'], codigo=a['codigo'] or '',
                    descripcion=a['descripcion'] or '', tipo=a['tipo'] or 'MAT',
                    unidad=a['unidad'] or '', cuadrilla=a['cuadrilla'] or 0.0,
                    cantidad=a['cantidad'] or 0.0, precio=a['precio'] or 0.0,
                    parcial=a['parcial'] or 0.0,
                    es_subpartida=bool(a['sub_partida_id']))
                for a in get_acu_items(conn, p['id'])[0])
            partidas.append(api.Partida(
                id=p['id'], item=p['item'] or '', descripcion=p['descripcion'] or '',
                nivel=p['nivel'] or 1, es_titulo=bool(p['es_titulo']),
                unidad=p['unidad'] or '', metrado=p['metrado'] or 0.0,
                precio_unitario=p['precio_unitario'] or 0.0,
                parcial=parciales.get(p['id'], 0.0),
                rendimiento=p['rendimiento'] or 0.0,
                sub_presupuesto=subs.get(p['sub_presupuesto_id'], ''), acu=acu))
        lineas, total = pie_efectivo(conn, pid, t['cd'])
        insumos = get_insumos_proyecto(conn, pid)
    finally:
        conn.close()
    return api.Presupuesto(
        id=pid, nombre=proy.get('nombre') or '', cliente=proy.get('cliente') or '',
        ubicacion=proy.get('ubicacion') or '', fecha_costos=proy.get('costo_al') or '',
        plazo_dias=int(proy.get('plazo') or 0),
        jornada=float(proy.get('jornada_laboral') or 8),
        estado=proy.get('estado') or 'elaboracion',
        moneda=moneda(proy.get('moneda') or 'Soles'),
        decimales=get_decimales_ppto(), partidas=tuple(partidas),
        pie=tuple(api.LineaPie(x['nombre'], x['codigo'] or '', x['tipo'],
                               x['pct'] or 0.0, x['valor'],
                               x['tipo'] != 'subtotal' and es_impuesto(x))
                  for x in lineas or ()),
        insumos=tuple(api.InsumoTotal(
            x['recurso_id'], x['codigo'], x['descripcion'], x['tipo'], x['unidad'],
            x['precio'], x['cantidad_total'], x['parcial_total']) for x in insumos),
        costo_directo=t['cd'], total=total)


class _Editor(api.Editor):
    def __init__(self, ops: OperacionesComplemento, pid: int):
        self._ops, self._pid = ops, pid

    def _hacer(self, fn, *a, **k):
        try:
            return fn(*a, **k)
        except ErrorMCP as e:
            raise api.ErrorComplemento(str(e)) from None

    def _propia(self, partida_id):
        if self._hacer(self._ops._pid_de, partida_id) != self._pid:
            raise api.ErrorComplemento("esa partida es de otro proyecto")

    def agregar(self, partidas, *, sub_presupuesto_id=0):
        lista = []
        for n, p in enumerate(partidas):
            if not isinstance(p, api.PartidaNueva):
                raise api.ErrorComplemento(f"[{n}]: se esperaba una PartidaNueva")
            d = {}
            if p.item:
                d['item'] = str(p.item)
            if p.padre:
                d['parent_item'] = str(p.padre)
            if p.biblioteca_id:
                d['library_id'] = int(p.biblioteca_id)
            else:
                if not str(p.descripcion).strip():
                    raise api.ErrorComplemento(f"[{n}]: falta la descripción")
                d['description'] = str(p.descripcion).strip()[:500]
                if p.es_titulo:
                    d['title'] = True
                else:
                    d['unit'] = str(p.unidad).strip()[:20]
            if p.metrado is not None and not p.es_titulo:
                d['quantity'] = _numero(p.metrado, f"[{n}].metrado")
            lista.append(d)
        if not lista:
            return []
        # Los precios de la biblioteca son soles del Perú: en otra moneda solo
        # entra la estructura del análisis.
        info = self._hacer(self._ops.project_info, self._pid)
        precios = None if info['currency'] == 'Soles' else 'structure_only'
        r = self._hacer(self._ops.add_items, self._pid, lista,
                        sub_presupuesto_id, precios)
        return [x['item_id'] for x in r['added']]

    def fijar_metrado(self, partida_id, cantidad, *, reemplazar_planilla=False):
        self._propia(partida_id)
        self._hacer(self._ops.set_metrado, partida_id,
                    quantity=_numero(cantidad, "cantidad"),
                    replace=bool(reemplazar_planilla))

    def fijar_precio(self, recurso_id, precio):
        self._hacer(self._ops.set_price, self._pid, recurso_id,
                    _numero(precio, "precio"))

    def renombrar(self, partida_id, descripcion):
        self._propia(partida_id)
        self._hacer(self._ops.edit_items, self._pid,
                    [{'item_id': partida_id, 'description': str(descripcion)[:500]}])


def _numero(x, donde) -> float:
    import math
    if isinstance(x, bool) or not isinstance(x, (int, float)) \
            or not math.isfinite(x) or x < 0:
        raise api.ErrorComplemento(f"{donde}: debe ser un número desde 0")
    return float(x)


class ContextoReal(api.Contexto):
    """`interfaz` da avisar/preguntar/pedir_archivo (la pone la ventana)."""

    def __init__(self, cargado, pid: int, usuario, interfaz, pila=None):
        self.complemento = cargado.id
        self._archivos = cargado.paquete.archivos
        self._pid, self._usuario, self._ui = pid, usuario, interfaz
        self.operaciones = OperacionesComplemento(usuario, cargado.id, pila)
        self.editar = _Editor(self.operaciones, pid)

    @property
    def presupuesto(self):
        return presupuesto(self._pid, self._usuario)

    def recurso(self, ruta):
        try:
            return self._archivos[ruta]
        except KeyError:
            raise api.ErrorComplemento(f"el complemento no trae {ruta!r}") from None

    def indice(self, clave):
        from core.complementos import gestor
        return gestor.indice(self.complemento, clave)

    def avisar(self, texto):
        self._ui.avisar(str(texto))

    def preguntar(self, texto):
        return bool(self._ui.preguntar(str(texto)))

    def pedir_archivo(self, extensiones=()):
        return self._ui.pedir_archivo(tuple(extensiones))
