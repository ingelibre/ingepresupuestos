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

import json
import math
from types import MappingProxyType

from core.mcp_operaciones import ErrorMCP, Operaciones
from utils.i18n import tr
from ingepresupuestos import api


class OperacionesComplemento(Operaciones):
    """Las mismas operaciones, con el nombre del complemento en el deshacer."""

    #: f(conn, resultado): se hace después del cambio, en su misma transacción.
    _despues = None

    def __init__(self, usuario, complemento: str, pila=None):
        super().__init__(usuario, pila)
        self._complemento = complemento

    def _escribir(self, herramienta, pid, nivel, cambio):
        despues = self._despues

        def todo(conn, proy):
            res = cambio(conn, proy)
            if despues is not None:
                despues(conn, res)
            return res
        return super()._escribir(f"complemento:{self._complemento}", pid, nivel, todo)


def moneda(nombre: str) -> api.Moneda:
    from core.config import moneda_cfg
    c = moneda_cfg(nombre)
    return api.Moneda(nombre, c['simbolo'], c['sep_miles'], c['sep_dec'])


MAX_AJUSTES = 60_000


def _valor_ok(v) -> bool:
    return isinstance(v, (str, bool, int)) or (
        isinstance(v, float) and math.isfinite(v))


def _ajustes_ok(ajustes) -> dict:
    nuevos = dict(ajustes)
    if not all(isinstance(k, str) and _valor_ok(v) for k, v in nuevos.items()) \
            or len(json.dumps(nuevos)) > MAX_AJUSTES:
        raise api.ErrorComplemento(
            "ajustes: solo textos, números y sí/no, hasta 60 KB")
    return nuevos


def _escribir_ajustes(conn, pid, complemento, nuevos):
    r = conn.execute("SELECT complementos_ajustes FROM proyectos WHERE id=?",
                     (pid,)).fetchone()
    todos = _todos_los_ajustes(r[0] if r else '')
    todos[complemento] = nuevos
    conn.execute("UPDATE proyectos SET complementos_ajustes=? WHERE id=?",
                 (json.dumps(todos, ensure_ascii=False), pid))


def _todos_los_ajustes(crudo) -> dict:
    """El JSON de la columna; lo ilegible (un .db ajeno) es como si no hubiera."""
    try:
        d = json.loads(crudo or '{}')
    except (TypeError, ValueError, RecursionError):
        return {}
    return d if isinstance(d, dict) else {}


def ajustes_de(proy: dict, complemento: str | None):
    d = _todos_los_ajustes(proy.get('complementos_ajustes')).get(complemento or '')
    return MappingProxyType({k: v for k, v in d.items() if _valor_ok(v)}
                            if isinstance(d, dict) else {})


def comprobar_datos(campos, *, dentro=False) -> list:
    """Los campos de `pedir_datos`, o ErrorComplemento."""
    campos, vistos = list(campos), set()
    if not 1 <= len(campos) <= 40:
        raise api.ErrorComplemento("pedir_datos: de 1 a 40 campos")
    for c in campos:
        if not isinstance(c, api.Dato) or not str(c.clave) or c.clave in vistos:
            raise api.ErrorComplemento("pedir_datos: campo repetido o que no es Dato")
        vistos.add(c.clave)
        if c.tipo not in ('numero', 'entero', 'texto', 'parrafo', 'opcion', 'si_no',
                          'tabla') or dentro and c.tipo in ('tabla', 'parrafo'):
            raise api.ErrorComplemento(f"pedir_datos: tipo {c.tipo!r}")
        if c.tipo == 'opcion' and not c.opciones:
            raise api.ErrorComplemento(f"pedir_datos: «{c.titulo}» sin opciones")
        if c.tipo in ('numero', 'entero') and not (
                math.isfinite(c.minimo) and math.isfinite(c.maximo)
                and c.minimo <= c.maximo):
            raise api.ErrorComplemento(f"pedir_datos: límites de «{c.titulo}»")
        if c.tipo == 'tabla':
            comprobar_datos(c.columnas, dentro=True)
    return campos


def presupuesto(pid: int, usuario, complemento: str | None = None) -> api.Presupuesto:
    """La foto del proyecto. Solo si ese usuario lo ve."""
    from core import partidas_ops
    from core.database import (calcular_totales, get_acu_hojas, get_acu_items,
                               get_db, get_decimales_metrado, get_decimales_ppto,
                               get_insumos_proyecto)
    from core.pie import es_impuesto, etiqueta, pie_efectivo
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
        partidas, cache = [], {}
        planillas = _planillas(conn, pid)
        for p in partidas_ops.partidas_en_orden(conn, pid):
            acu = () if p['es_titulo'] else tuple(
                map(_insumo, get_acu_items(conn, p['id'])[0]))
            abierto = None
            if any(a.es_subpartida for a in acu):
                abierto = tuple(map(_insumo, get_acu_hojas(conn, p['id'], cache)))
            partidas.append(api.Partida(
                id=p['id'], item=p['item'] or '', descripcion=p['descripcion'] or '',
                nivel=p['nivel'] or 1, es_titulo=bool(p['es_titulo']),
                unidad=p['unidad'] or '', metrado=p['metrado'] or 0.0,
                precio_unitario=p['precio_unitario'] or 0.0,
                parcial=parciales.get(p['id'], 0.0),
                rendimiento=p['rendimiento'] or 0.0,
                sub_presupuesto=subs.get(p['sub_presupuesto_id'], ''), acu=acu,
                abierto=abierto,
                especificacion=_texto_plano(p['especificaciones']),
                mediciones=tuple(planillas.get(p['id'], ()))))
        auxiliares = tuple(_auxiliar(conn, x) for x in conn.execute(
            "SELECT * FROM partidas WHERE proyecto_id=? AND es_subanalisis=1 "
            "ORDER BY item, id", (pid,)).fetchall())
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
                               x['tipo'] != 'subtotal' and es_impuesto(x),
                               etiqueta(x))
                  for x in lineas or ()),
        insumos=tuple(api.InsumoTotal(
            x['recurso_id'], x['codigo'], x['descripcion'], x['tipo'], x['unidad'],
            x['precio'], x['cantidad_total'], x['parcial_total']) for x in insumos),
        costo_directo=t['cd'], total=total,
        ajustes=ajustes_de(proy, complemento),
        decimales_metrado=get_decimales_metrado(),
        auxiliares=auxiliares, modalidad=proy.get('modalidad') or '',
        nombre_total=(proy.get('total_nombre') or '').strip())


def _texto_plano(spec) -> str:
    if not spec:
        return ''
    from core.pdf_reports import especificacion_en_parrafos
    return "\n".join(especificacion_en_parrafos(spec))[:20_000]


def _planillas(conn, pid) -> dict:
    """{partida_id: [LineaMetrado]} de todo el proyecto."""
    out = {}

    def veces(*ns):
        ns = [n for n in ns if n is not None]
        return math.prod(ns) if ns else None
    for r in conn.execute(
            "SELECT m.* FROM metrados_detalle m JOIN partidas p ON p.id=m.partida_id "
            "WHERE p.proyecto_id=? ORDER BY m.partida_id, m.orden, m.id", (pid,)):
        out.setdefault(r['partida_id'], []).append(api.LineaMetrado(
            r['descripcion'] or '', veces(r['n_estructuras'], r['n_elementos']),
            r['largo'], r['ancho'], r['alto'], r['parcial'] or 0.0, r['area']))
    for r in conn.execute(
            "SELECT m.* FROM acero_detalle m JOIN partidas p ON p.id=m.partida_id "
            "WHERE p.proyecto_id=? ORDER BY m.partida_id, m.orden, m.id", (pid,)):
        d = " ".join(x for x in (r['descripcion'], r['diametro']) if x)
        out.setdefault(r['partida_id'], []).append(api.LineaMetrado(
            d, veces(r['n_estructuras'], r['n_elementos'], r['n_veces']), r['longitud'], None, None,
            r['parcial'] or 0.0, kg_m=r['kg_ml']))
    return out


def _auxiliar(conn, p) -> api.Partida:
    from core.database import get_acu_items
    return api.Partida(
        id=p['id'], item=p['item'] or '', descripcion=p['descripcion'] or '', nivel=1,
        es_titulo=False, unidad=p['unidad'] or '', metrado=0.0,
        precio_unitario=p['precio_unitario'] or 0.0, parcial=0.0,
        rendimiento=p['rendimiento'] or 0.0, sub_presupuesto='',
        acu=tuple(map(_insumo, get_acu_items(conn, p['id'])[0])))


def _insumo(a: dict) -> api.Insumo:
    return api.Insumo(
        recurso_id=a['recurso_id'], codigo=a['codigo'] or '',
        descripcion=a['descripcion'] or '', tipo=a['tipo'] or 'MAT',
        unidad=a['unidad'] or '', cuadrilla=a['cuadrilla'] or 0.0,
        cantidad=a['cantidad'] or 0.0, precio=a['precio'] or 0.0,
        parcial=a['parcial'] or 0.0, es_subpartida=bool(a['sub_partida_id']),
        auxiliar_id=a['sub_partida_id'] or 0)


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

    def agregar_metrados(self, metrados, *, ajustes=None):
        metrados = list(metrados)
        for n, m in enumerate(metrados):
            if not isinstance(m, api.Metrado) \
                    or (m.nueva is None) == (not m.partida_id):
                raise api.ErrorComplemento(
                    f"[{n}]: un Metrado con partida_id o con nueva")
            for f in m.filas:
                if not isinstance(f, api.FilaMetrado):
                    raise api.ErrorComplemento(f"[{n}]: se esperaba FilaMetrado")
                for x in (*_dims(f), f.kg_m):
                    if isinstance(x, bool) or not isinstance(x, (int, float)) \
                            or not math.isfinite(x):
                        raise api.ErrorComplemento(f"[{n}]: un número no es válido")
        if ajustes is not None:
            ajustes = _ajustes_ok(ajustes)
        nuevas = [m for m in metrados if m.nueva is not None]
        ops = self._ops

        def despues(conn, res):
            ids = iter([x['item_id'] for x in res['added']] if nuevas else ())
            for m in metrados:
                pid = m.partida_id if m.nueva is None else next(ids)
                if m.filas:
                    self._agregar_filas(conn, pid, m.filas)
            if ajustes is not None:
                _escribir_ajustes(conn, self._pid, ops._complemento, ajustes)
        ops._despues = despues
        try:
            if nuevas:
                self.agregar([m.nueva for m in nuevas])
            else:
                self._hacer(ops._escribir, '', self._pid, 'presupuesto',
                            lambda conn, proy: None)
        finally:
            ops._despues = None

    def _agregar_filas(self, conn, partida_id, filas):
        from core.database import _rn, get_decimales_metrado
        from core.partidas_ops import CAMPOS_PLANILLA, parcial_fila
        p = self._ops._partida_de(conn, partida_id, self._pid)
        que = f"{p['item']} {p['descripcion']}"
        if p['es_titulo'] or p['es_subanalisis']:
            raise ErrorMCP(f"«{que}» no lleva planilla de metrado")
        if self._ops._filas_bim(conn, partida_id):
            raise ErrorMCP(tr("El metrado de «{que}» viene de un modelo BIM.").format(
                que=que))
        acero = any(f.diametro for f in filas)
        if acero and not all(f.diametro for f in filas):
            raise ErrorMCP("no se mezclan filas de acero y normales")
        tabla, otra = (('acero_detalle', 'metrados_detalle') if acero else
                       ('metrados_detalle', 'acero_detalle'))
        if conn.execute(f"SELECT 1 FROM {otra} WHERE partida_id=?",
                        (partida_id,)).fetchone():
            raise ErrorMCP(tr("«{que}» tiene una planilla de otra clase (acero / "
                              "metrado normal): elige otra partida.").format(que=que))
        n, suma, orden = conn.execute(
            f"SELECT COUNT(*), COALESCE(SUM(parcial),0), COALESCE(MAX(orden),0) "
            f"FROM {tabla} WHERE partida_id=?", (partida_id,)).fetchone()
        dec = get_decimales_metrado()
        if abs((p['metrado'] or 0) - suma) > 0.011 + 10 ** -dec:
            raise ErrorMCP(tr(
                "«{que}» tiene un metrado escrito a mano que no sale de su planilla: "
                "se perdería. Elige otra partida o ponla antes en 0.").format(que=que))
        for f in filas:
            orden += 1
            desc = str(f.descripcion).strip()[:200]
            if acero:
                m = _rn(math.prod(_dims(f)), 4) if _dims(f) else 0.0
                parcial = _rn(m * f.kg_m, 4)
                conn.execute(
                    "INSERT INTO acero_detalle (partida_id, orden, descripcion, "
                    "diametro, n_estructuras, n_elementos, n_veces, longitud, kg_ml, "
                    "parcial) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (partida_id, orden, desc, str(f.diametro)[:20], f.estructuras,
                     f.elementos, f.veces, f.largo, f.kg_m, parcial))
            else:
                d = dict(zip(CAMPOS_PLANILLA, (f.estructuras, f.elementos, f.area,
                                               f.largo, f.ancho, f.alto)))
                parcial = parcial_fila(d)
                conn.execute(
                    "INSERT INTO metrados_detalle (partida_id, orden, descripcion, "
                    "n_estructuras, n_elementos, area, largo, ancho, alto, parcial) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (partida_id, orden, desc, *d.values(), parcial))
            suma += parcial
        conn.execute("UPDATE partidas SET metrado=? WHERE id=?",
                     (_rn(suma, dec), partida_id))

    def fijar_precio(self, recurso_id, precio):
        self._hacer(self._ops.set_price, self._pid, recurso_id,
                    _numero(precio, "precio"))

    def _cambio_precios(self, precios):
        from core.database import calcular_totales, unificar_precio_recurso
        from core.pie import pie_efectivo
        lista = [(int(r), _numero(v, f"precio de {r}"))
                 for r, v in dict(precios).items()]
        if not lista:
            raise api.ErrorComplemento("no hay precios que cambiar")

        def cambio(conn, proy):
            for rid, precio in lista:
                r = conn.execute("SELECT unidad, codigo FROM recursos WHERE id=?",
                                 (rid,)).fetchone()
                if r is None or r['codigo'] == 'SUBPARTIDA' \
                        or (r['unidad'] or '').strip().startswith('%'):
                    raise ErrorMCP(f"el insumo {rid} no tiene precio propio")
                if not unificar_precio_recurso(conn, self._pid, rid, precio):
                    raise ErrorMCP(f"el insumo {rid} no se usa en el proyecto")
            cd = calcular_totales(self._pid, conn)[1]['cd']
            return api.Totales(cd, pie_efectivo(conn, self._pid, cd)[1])
        return cambio

    def fijar_precios(self, precios):
        self._hacer(self._ops._escribir, '', self._pid, 'presupuesto',
                    self._cambio_precios(precios))

    _espera = None

    def simular_precios(self, precios):
        if self._espera is not None:
            self._espera()          # se llama muchas veces: la ventana respira
        cambio = self._cambio_precios(precios)
        self._ops.simular = True
        try:
            return self._hacer(self._ops._escribir, '', self._pid, 'presupuesto',
                               cambio)['would_return']
        finally:
            self._ops.simular = False

    def renombrar(self, partida_id, descripcion):
        self._propia(partida_id)
        self._hacer(self._ops.edit_items, self._pid,
                    [{'item_id': partida_id, 'description': str(descripcion)[:500]}])


def _dims(f) -> list:
    v = ((f.estructuras, f.elementos, f.veces, f.largo) if f.diametro else
         (f.estructuras, f.elementos, f.area, f.largo, f.ancho, f.alto))
    return [x for x in v if x is not None]


def _numero(x, donde) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) \
            or not math.isfinite(x) or x < 0:
        raise api.ErrorComplemento(f"{donde}: debe ser un número desde 0")
    return float(x)


class Cancelado(Exception):
    """El usuario pulsó «Cancelar» mientras el complemento calculaba."""


class ContextoReal(api.Contexto):
    """`interfaz` da avisar/preguntar/pedir_archivo (la pone la ventana)."""

    def __init__(self, cargado, pid: int, usuario, interfaz, pila=None):
        self.complemento = cargado.id
        self._archivos = cargado.paquete.archivos
        self._pid, self._usuario, self._ui = pid, usuario, interfaz
        self.operaciones = OperacionesComplemento(usuario, cargado.id, pila)
        self.editar = _Editor(self.operaciones, pid)
        self.editar._espera = getattr(interfaz, 'trabajando', None)

    @property
    def presupuesto(self):
        return presupuesto(self._pid, self._usuario, self.complemento)

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

    def pedir_datos(self, titulo, campos, *, texto=''):
        campos = comprobar_datos(campos)
        r = self._ui.pedir_datos(str(titulo), campos, str(texto))
        return None if r is None else {c.clave: r[c.clave] for c in campos}

    @property
    def ajustes(self):
        from core.database import get_db
        conn = get_db()
        try:
            proy = self.operaciones._proyecto(conn, self._pid)
        except ErrorMCP as e:
            raise api.ErrorComplemento(str(e)) from None
        finally:
            conn.close()
        return ajustes_de(proy, self.complemento)

    def guardar_ajustes(self, ajustes):
        nuevos = _ajustes_ok(ajustes)

        def cambio(conn, proy):
            _escribir_ajustes(conn, self._pid, self.complemento, nuevos)
        try:
            self.operaciones._escribir('', self._pid, 'presupuesto', cambio)
        except ErrorMCP as e:
            raise api.ErrorComplemento(str(e)) from None

    def pedir_archivo(self, extensiones=()):
        return self._ui.pedir_archivo(tuple(extensiones))
