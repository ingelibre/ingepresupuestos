# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Las herramientas MCP sobre la base de datos (sin Qt).

Cada escritura: permisos → BEGIN IMMEDIATE → copia → cambios → huella →
commit. Si algo falla no queda nada, ni en la base ni en la pila de deshacer.
Los números los calcula `core.database` / `core.pie` / `core.partidas_ops`.

Nunca se lee la tabla `usuarios` ni las claves de `configuracion`: las
consultas nombran sus columnas.
"""
from __future__ import annotations

import dataclasses
import os
import re
import tempfile
from pathlib import Path

from core import estructura_ops, mcp_deshacer, partidas_ops as ops
from core.config import ESTADOS_PROYECTO_NOMBRE, puede_editar
from core.mcp_esquemas import REPORTES_DOCX, REPORTES_XLSX


#: Qué permiso pide cada escritura que no es de «presupuesto»/«cronograma».
#: Deshacerla pide el mismo: en «En revisión» se pueden escribir
#: especificaciones, y por tanto también deshacerlas.
NIVEL = {'set_specs': 'specs', 'set_memoria': 'specs', 'set_overhead': 'pie',
         'set_formula': 'pie', 'create_valuation': 'obra',
         'set_valuation_progress': 'obra'}

_NOMBRE_NIVEL = {'specs': 'especificaciones ni memoria',
                 'pie': 'pie de presupuesto, gastos ni fórmula'}


class ErrorMCP(Exception):
    """Error con un texto para el agente."""


def _num(v):
    return float(v) if v is not None else None


class Operaciones:
    def __init__(self, usuario, pila: mcp_deshacer.Pila | None = None):
        self.usuario = usuario
        self.pila = pila or mcp_deshacer.Pila()
        #: Proyectos tocados por la última llamada, para refrescar la vista.
        self.tocados: list[int] = []
        self.borrados: list[int] = []
        self.creados: list[int] = []
        #: Simulación: la siguiente escritura se calcula y se revierte.
        self.simular = False

    # ── Permisos ─────────────────────────────────────────────────────────
    def _visible_sql(self) -> tuple[str, tuple]:
        """Los mismos proyectos que le muestra el Inicio."""
        if self.usuario.es_admin:
            return "1=1", ()
        return "(usuario_id=? OR usuario_id IS NULL)", (self.usuario.id,)

    def _proyecto(self, conn, pid: int) -> dict:
        cond, par = self._visible_sql()
        r = conn.execute(
            f"SELECT * FROM proyectos WHERE id=? AND {cond}",
            (pid, *par)).fetchone()
        if r is None:
            raise ErrorMCP(f"no existe el proyecto {pid} (usa list_projects)")
        return dict(r)

    def _partida(self, conn, part_id: int) -> tuple[dict, dict]:
        p = conn.execute("SELECT * FROM partidas WHERE id=?",
                         (part_id,)).fetchone()
        if p is None:
            raise ErrorMCP(f"no existe la partida {part_id} (usa list_items)")
        try:
            proy = self._proyecto(conn, p['proyecto_id'])
        except ErrorMCP:
            raise ErrorMCP(f"no existe la partida {part_id} (usa list_items)") from None
        return dict(p), proy

    def _puede_escribir(self):
        if self.usuario.es_invitado:
            raise ErrorMCP("la sesión es de invitado: solo lectura")

    def _editable(self, proy: dict, nivel: str = 'presupuesto'):
        self._puede_escribir()
        estado = proy.get('estado') or 'elaboracion'
        if nivel == 'obra':            # como Control de Obra en la app
            if estado != 'ejecutado':
                raise ErrorMCP("las valorizaciones solo se registran con el "
                               "proyecto «En ejecución»")
            return
        if not puede_editar(estado, nivel):
            raise ErrorMCP(
                f"el proyecto está «{ESTADOS_PROYECTO_NOMBRE.get(estado, estado)}» "
                f"y no admite cambios de {_NOMBRE_NIVEL.get(nivel, nivel)}; el usuario puede volverlo a "
                "«En elaboración» en la app")

    # ── Transacción con copia ────────────────────────────────────────────
    def _escribir(self, herramienta: str, pid: int, nivel: str, cambio):
        """`cambio(conn, proy)` dentro de una transacción con su copia."""
        from core.database import get_db
        self._puede_escribir()
        conn = get_db()
        tmp = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            proy = self._proyecto(conn, pid)
            self._editable(proy, nivel)
            if self.simular:
                return self._simulada(conn, pid, proy, cambio)
            antes = mcp_deshacer.volcar(conn, pid)
            filas = estructura_ops.foto_filas(conn, pid)
            res = cambio(conn, proy)
            estructura_ops.conservar_predecesoras(conn, pid, filas)
            conn.execute("DELETE FROM dashboard_tot_cache WHERE proyecto_id=?",
                         (pid,))
            despues = mcp_deshacer.huella(mcp_deshacer.volcar(conn, pid))
            if despues != mcp_deshacer.huella(antes):
                tmp = self.pila.preparar(pid=pid, herramienta=herramienta,
                                         antes=antes, despues=despues)
            conn.commit()
        except BaseException:
            conn.rollback()
            if tmp is not None:
                self.pila.descartar(tmp)
            raise
        finally:
            conn.close()
        if tmp is not None:
            self.pila.publicar(tmp)
        self.tocados.append(pid)
        return res

    @staticmethod
    def _simulada(conn, pid, proy, cambio):
        """El cambio dentro de la transacción, medido y REVERTIDO."""
        from core.database import calcular_totales
        try:
            t0 = calcular_totales(pid, conn)[1]
            filas = estructura_ops.foto_filas(conn, pid)
            res = cambio(conn, proy)
            quitadas = estructura_ops.conservar_predecesoras(conn, pid, filas)
            t1 = calcular_totales(pid, conn)[1]
        finally:
            conn.rollback()
        return {"dry_run": True, "saved": False,
                "currency": proy.get('moneda') or 'Soles',
                "direct_cost": {"before": t0['cd'], "after": t1['cd']},
                "total": {"before": t0['total'], "after": t1['total']},
                "predecessors_removed": quitadas,
                "note": "no se guardó nada; los ids nuevos no existen",
                "would_return": res}

    def _externa(self, herramienta: str, pid: int, accion,
                 nivel: str = 'presupuesto'):
        """Como `_escribir` para código que abre su propia conexión y hace su
        propio commit (core.bim_modelo). Si falla a medias, se restaura."""
        from core.database import get_db
        conn = get_db()
        try:
            proy = self._proyecto(conn, pid)
            self._editable(proy, nivel)
            antes = mcp_deshacer.volcar(conn, pid)
        finally:
            conn.close()
        h0 = mcp_deshacer.huella(antes)
        try:
            res = accion()
        except BaseException:
            self._volver(pid, antes, h0)
            raise
        conn = get_db()
        try:
            despues = mcp_deshacer.huella(mcp_deshacer.volcar(conn, pid))
            conn.execute("DELETE FROM dashboard_tot_cache WHERE proyecto_id=?",
                         (pid,))
            conn.commit()
        finally:
            conn.close()
        if despues != h0:
            self.pila.publicar(self.pila.preparar(
                pid=pid, herramienta=herramienta, antes=antes, despues=despues))
        self.tocados.append(pid)
        return res

    def _volver(self, pid, antes, h0):
        from core.database import get_db
        conn = get_db()
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("BEGIN IMMEDIATE")
            if mcp_deshacer.huella(mcp_deshacer.volcar(conn, pid)) != h0:
                mcp_deshacer.restaurar(conn, pid, antes)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Lectura ──────────────────────────────────────────────────────────
    def list_projects(self, query: str = "", limit: int = 100):
        from core.database import get_db
        from utils.formatting import norm_busqueda
        cond, par = self._visible_sql()
        conn = get_db()
        try:
            conn.create_function("_norm", 1, norm_busqueda)
            sql = (f"SELECT id, nombre, cliente, ubicacion, estado, moneda, "
                   f"modificado_en FROM proyectos WHERE {cond}")
            par = list(par)
            if query.strip():
                sql += " AND _norm(nombre || ' ' || COALESCE(cliente,'')) LIKE ?"
                par.append(f"%{norm_busqueda(query)}%")
            total = conn.execute(f"SELECT COUNT(*) FROM ({sql})", par).fetchone()[0]
            filas = conn.execute(
                sql + " ORDER BY COALESCE(modificado_en, creado_en) DESC LIMIT ?",
                (*par, limit)).fetchall()
        finally:
            conn.close()
        return {"total": total, "projects": [
            {"project_id": r['id'], "name": r['nombre'],
             "client": r['cliente'] or '', "location": r['ubicacion'] or '',
             "state": r['estado'] or 'elaboracion',
             "currency": r['moneda'] or 'Soles',
             "modified": r['modificado_en']} for r in filas]}

    def project_info(self, project_id: int):
        from core.database import get_db
        conn = get_db()
        try:
            p = self._proyecto(conn, project_id)
            subs = conn.execute(
                "SELECT id, nombre FROM sub_presupuestos WHERE proyecto_id=?"
                " ORDER BY orden, id", (project_id,)).fetchall()
            n = conn.execute(
                "SELECT SUM(es_titulo=1), SUM(es_titulo=0) FROM partidas_ppto"
                " WHERE proyecto_id=?", (project_id,)).fetchone()
        finally:
            conn.close()
        est = p.get('estado') or 'elaboracion'
        puede = not self.usuario.es_invitado
        return {
            "project_id": project_id, "name": p['nombre'],
            "client": p.get('cliente') or '',
            "modality": p.get('modalidad') or '',
            "location": p.get('ubicacion') or '', "state": est,
            "cost_date": p.get('costo_al') or '', "term_days": p.get('plazo'),
            "start_date": p.get('fecha_inicio') or '',
            "currency": p.get('moneda') or 'Soles',
            "workday_hours": p.get('jornada_laboral') or 8,
            "editable": {k: puede and puede_editar(est, k) for k in
                         ('presupuesto', 'pie', 'specs', 'cronograma')},
            "sub_budgets": [{"sub_budget_id": 0, "name":
                             p.get('sub_presupuesto') or 'Principal'}]
            + [{"sub_budget_id": s['id'], "name": s['nombre']} for s in subs],
            "titles": n[0] or 0, "items": n[1] or 0}

    def list_items(self, project_id: int, query: str = "", offset: int = 0,
                   limit: int = 200, sub_budget_id: int | None = None):
        from core.cronograma import numerar_filas
        from core.database import calcular_totales, get_db
        from utils.formatting import norm_busqueda
        conn = get_db()
        try:
            self._proyecto(conn, project_id)
            partidas = ops.partidas_en_orden(conn, project_id)
            con_plan = {r[0] for r in conn.execute(
                "SELECT DISTINCT d.partida_id FROM metrados_detalle d "
                "JOIN partidas p ON p.id=d.partida_id WHERE p.proyecto_id=?",
                (project_id,))}
            con_acu = {r[0] for r in conn.execute(
                "SELECT DISTINCT a.partida_id FROM acu_items a "
                "JOIN partidas p ON p.id=a.partida_id WHERE p.proyecto_id=?",
                (project_id,))}
        finally:
            conn.close()
        fila_gantt = numerar_filas(partidas)
        tot = {i['partida']['id']: i['total']
               for i in calcular_totales(project_id)[0]}
        q = norm_busqueda(query) if query.strip() else ''
        sel = []
        for p in partidas:
            if sub_budget_id is not None and \
                    (p['sub_presupuesto_id'] or 0) != sub_budget_id:
                continue
            if q and q not in norm_busqueda(p['descripcion']) \
                    and not p['item'].startswith(query.strip()):
                continue
            d = {"item_id": p['id'], "item": p['item'],
                 "description": p['descripcion'], "level": p['nivel'],
                 "title": bool(p['es_titulo']),
                 "sub_budget_id": p['sub_presupuesto_id'] or 0,
                 "total": tot.get(p['id'], 0),
                 "gantt_row": fila_gantt.get(p['id'])}
            if not p['es_titulo']:
                d.update(unit=p['unidad'] or '', quantity=p['metrado'] or 0,
                         unit_price=p['precio_unitario'] or 0,
                         has_acu=p['id'] in con_acu,
                         has_metrados=p['id'] in con_plan)
            sel.append(d)
        return {"total": len(sel), "offset": offset,
                "items": sel[offset:offset + limit]}

    def get_acu(self, item_id: int):
        from core.database import get_acu_items, get_db
        conn = get_db()
        try:
            p, proy = self._partida(conn, item_id)
            if p['es_titulo']:
                raise ErrorMCP("un título no tiene ACU")
            items, tipos = get_acu_items(conn, item_id)
        finally:
            conn.close()
        return {"item_id": item_id, "item": p['item'],
                "description": p['descripcion'], "unit": p['unidad'] or '',
                "performance": p['rendimiento'] or 0,
                "workday_hours": proy.get('jornada_laboral') or 8,
                "currency": proy.get('moneda') or 'Soles',
                "unit_price": p['precio_unitario'] or 0,
                "by_type": tipos,
                "resources": [
                    {"resource_id": i['recurso_id'], "code": i['codigo'],
                     "description": i['descripcion'], "type": i['tipo'],
                     "unit": i['unidad'], "subitem_id": i['sub_partida_id'],
                     "crew": i['cuadrilla'] or 0,
                     "quantity": i['cantidad'] or 0, "price": i['precio'] or 0,
                     "partial": i['parcial']} for i in items]}

    @staticmethod
    def _buscar(conn, tabla: str, cols: str, campo: str, query: str,
                extra: str, par: tuple, limit: int):
        """Todas las palabras; si no sale nada, las que más acierten."""
        from utils.formatting import norm_busqueda
        conn.create_function("_norm", 1, norm_busqueda)
        palabras = [w for w in norm_busqueda(query).split() if w][:10]
        if not palabras:
            raise ErrorMCP("escribe qué buscar")
        likes = [f"%{w}%" for w in palabras]
        c = f"_norm({campo}) LIKE ?"
        filas = conn.execute(
            f"SELECT {cols} FROM {tabla} WHERE "
            + " AND ".join([c] * len(likes)) + extra
            + f" ORDER BY LENGTH({campo}) LIMIT ?",
            (*likes, *par, limit)).fetchall()
        if filas or len(palabras) == 1:
            return filas, True
        puntaje = " + ".join([f"({c})"] * len(likes))
        filas = conn.execute(
            f"SELECT {cols}, {puntaje} AS _n FROM {tabla} WHERE ("
            + " OR ".join([c] * len(likes)) + ")" + extra
            + f" ORDER BY _n DESC, LENGTH({campo}) LIMIT ?",
            (*likes, *likes, *par, limit)).fetchall()
        return filas, False

    def search_library(self, query: str, group: str = "", limit: int = 25):
        from core.database import get_db
        conn = get_db()
        try:
            extra, par = (" AND grupo=?", (group,)) if group else ("", ())
            filas, exacto = self._buscar(
                conn, "biblioteca_cu",
                "id, descripcion, unidad, rendimiento, costo_unitario, grupo",
                "descripcion", query, extra, par, limit)
        finally:
            conn.close()
        return {"all_words_match": exacto,
                "note": "precios referenciales del Perú, en soles",
                "results": [
                    {"library_id": r['id'], "description": r['descripcion'],
                     "unit": r['unidad'] or '', "group": r['grupo'] or '',
                     "performance": r['rendimiento'],
                     "unit_price": r['costo_unitario']} for r in filas]}

    def search_resources(self, query: str, type: str = "", limit: int = 25):  # noqa: A002
        from core.database import get_db
        conn = get_db()
        try:
            extra, par = (" AND tipo=?", (type,)) if type else ("", ())
            extra += " AND COALESCE(codigo,'') != 'SUBPARTIDA'"
            filas, exacto = self._buscar(
                conn, "recursos",
                "id, codigo, descripcion, tipo, unidad, precio, indice_inei",
                "descripcion", query, extra, par, limit)
        finally:
            conn.close()
        return {"all_words_match": exacto, "results": [
            {"resource_id": r['id'], "code": r['codigo'] or '',
             "description": r['descripcion'], "type": r['tipo'],
             "unit": r['unidad'] or '', "price": r['precio'] or 0,
             "index": r['indice_inei'] or ''} for r in filas]}

    def totals(self, project_id: int):
        from core.database import calcular_totales, get_db
        from core.pie import pie_efectivo
        conn = get_db()
        try:
            p = self._proyecto(conn, project_id)
        finally:
            conn.close()
        items, t = calcular_totales(project_id)
        conn = get_db()
        try:
            lineas, _total = pie_efectivo(conn, project_id, t['cd'])
        finally:
            conn.close()
        if lineas is None:
            pie = [{"name": n, "value": t[k]} for n, k in
                   (("Gastos generales", 'gf'), ("Utilidad", 'utilidad'),
                    ("Subtotal", 'subtotal'), ("Impuesto", 'igv'))]
        else:
            pie = [{"name": x['nombre'], "kind": x['tipo'], "value": x['valor'],
                    **({"effective_pct": round(100 * x['valor'] / t['cd'], 2)}
                       if x['tipo'] == 'rubro' and t['cd'] else
                       {"pct": x['pct']})} for x in lineas]
        return {"project_id": project_id, "currency": p.get('moneda') or 'Soles',
                "direct_cost": t['cd'], "footer": pie, "total": t['total'],
                "titles": [{"item_id": i['partida']['id'],
                            "item": i['partida']['item'],
                            "description": i['partida']['descripcion'],
                            "total": i['total']}
                           for i in items if i['partida']['es_titulo']][:500]}

    @staticmethod
    def _filas_bim(conn, part_id: int) -> dict:
        """{metrado_detalle_id: global_id} de las filas que vienen del modelo."""
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'"
                            " AND name='bim_vinculos'").fetchone():
            return {}
        return {r[0]: r[1] for r in conn.execute(
            "SELECT metrado_detalle_id, global_id FROM bim_vinculos"
            " WHERE partida_id=?", (part_id,))}

    def get_metrados(self, item_id: int):
        from core.database import get_db
        conn = get_db()
        try:
            p, _ = self._partida(conn, item_id)
            filas = conn.execute("SELECT * FROM metrados_detalle WHERE"
                                 " partida_id=? ORDER BY orden, id",
                                 (item_id,)).fetchall()
            acero = conn.execute("SELECT * FROM acero_detalle WHERE"
                                 " partida_id=? ORDER BY orden, id",
                                 (item_id,)).fetchall()
            bim = self._filas_bim(conn, item_id)
        finally:
            conn.close()
        return {"item_id": item_id, "item": p['item'],
                "description": p['descripcion'], "unit": p['unidad'] or '',
                "quantity": p['metrado'] or 0,
                "rows": [{"description": r['descripcion'] or '',
                          "structures": r['n_estructuras'],
                          "elements": r['n_elementos'], "area": r['area'],
                          "length": r['largo'], "width": r['ancho'],
                          "height": r['alto'], "partial": r['parcial'],
                          "bim_global_id": bim.get(r['id'])} for r in filas],
                "steel_rows": [{"description": r['descripcion'] or '',
                                "diameter": r['diametro'],
                                "structures": r['n_estructuras'],
                                "times": r['n_veces'],
                                "elements": r['n_elementos'],
                                "length": r['longitud'], "kg_m": r['kg_ml'],
                                "partial": r['parcial']} for r in acero]}

    def validate(self, project_id: int):
        from core.database import (get_db, partidas_pu_inconsistente,
                                   precios_desactualizados,
                                   precios_inconsistentes)
        conn = get_db()
        try:
            self._proyecto(conn, project_id)
            partidas = ops.partidas_en_orden(conn, project_id)
            pu = partidas_pu_inconsistente(conn, project_id)
            precios = precios_inconsistentes(conn, project_id)
            viejos = precios_desactualizados(conn, project_id)
            con_acu = {r[0] for r in conn.execute(
                "SELECT DISTINCT a.partida_id FROM acu_items a "
                "JOIN partidas p ON p.id=a.partida_id WHERE p.proyecto_id=?",
                (project_id,))}
            cero = conn.execute(
                """SELECT DISTINCT r.id, r.descripcion FROM acu_items a
                   JOIN partidas p ON p.id=a.partida_id
                   JOIN recursos r ON r.id=a.recurso_id
                   WHERE p.proyecto_id=? AND COALESCE(a.precio, r.precio, 0)=0
                     AND SUBSTR(COALESCE(r.unidad,''),1,1)<>'%'""",
                (project_id,)).fetchall()
        finally:
            conn.close()
        hojas = [p for p in partidas if not p['es_titulo']]

        def ref(p):
            return {"item_id": p['id'], "item": p['item'],
                    "description": p['descripcion']}
        vistos, repetidos = set(), []
        for p in partidas:
            k = (p['sub_presupuesto_id'], p['item'])
            if k in vistos:
                repetidos.append(ref(p))
            vistos.add(k)
        grupos = {
            "no_quantity": [ref(p) for p in hojas if not (p['metrado'] or 0)],
            "no_acu": [ref(p) for p in hojas if p['id'] not in con_acu],
            "no_price": [ref(p) for p in hojas if not (p['precio_unitario'] or 0)],
            "no_unit": [ref(p) for p in hojas if not (p['unidad'] or '').strip()],
            "duplicate_item_code": repetidos,
            "unit_price_differs_from_acu": [
                {"item_id": x['partida_id'], "item": x['item'],
                 "description": x['descripcion'], "stored": x['pu_guardado'],
                 "from_acu": x['pu_acu']} for x in pu],
            "resource_with_several_prices": [
                {"resource_id": k, "description": v['descripcion'],
                 "prices": [x[0] for x in v['variantes']]}
                for k, v in precios.items()],
            "resource_price_zero": [
                {"resource_id": r['id'], "description": r['descripcion']}
                for r in cero],
            "price_differs_from_catalog": [
                {"resource_id": x['recurso_id'], "description": x['descripcion'],
                 "project": x['precio_proyecto'], "catalog": x['precio_catalogo']}
                for x in viejos],
        }
        return {"project_id": project_id,
                "counts": {k: len(v) for k, v in grupos.items()},
                "ok": not any(len(v) for k, v in grupos.items()
                              if k != "price_differs_from_catalog"),
                **{k: v[:100] for k, v in grupos.items()}}

    # ── Escritura ────────────────────────────────────────────────────────
    def create_project(self, name: str, client: str = "", location: str = "",
                       sub_budget: str = "", cost_date: str = "",
                       term_days: int = 60, currency: str | None = None,
                       workday_hours: int | None = None):
        from datetime import date
        from core.config import monedas
        from core.database import get_config, get_db
        from core.paises import impuesto
        self._puede_escribir()
        moneda = currency or get_config('moneda_defecto', 'Soles')
        if currency and currency not in monedas():
            raise ErrorMCP(f"moneda desconocida: {currency!r}; las hay: "
                           + ", ".join(sorted(monedas())))
        jornada = workday_hours or int(get_config('jornada_defecto', '8') or 8)
        conn = get_db()
        tmp = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            pid = conn.execute(
                """INSERT INTO proyectos
                   (nombre, cliente, ubicacion, sub_presupuesto, costo_al,
                    plazo, gf_pct, utilidad_pct, igv_pct, jornada_laboral,
                    moneda, estado, usuario_id)
                   VALUES (?,?,?,?,?,?,10.0,5.0,?,?,?,'elaboracion',?)""",
                (name.strip(), client.strip(), location.strip(),
                 sub_budget.strip(),
                 cost_date.strip() or date.today().strftime('%d/%m/%Y'),
                 term_days, impuesto()[1], jornada, moneda,
                 self.usuario.id or None)).lastrowid
            despues = mcp_deshacer.huella(mcp_deshacer.volcar(conn, pid))
            tmp = self.pila.preparar(pid=pid, herramienta='create_project',
                                     antes=None, despues=despues, creado=True)
            conn.commit()
        except BaseException:
            conn.rollback()
            if tmp is not None:
                self.pila.descartar(tmp)
            raise
        finally:
            conn.close()
        self.pila.publicar(tmp)
        self.creados.append(pid)
        return {"project_id": pid, "name": name.strip(), "currency": moneda}

    @staticmethod
    def _solo_estructura(proy: dict, eleccion: str | None, hace_falta: bool) -> bool:
        if (proy.get('moneda') or 'Soles') == 'Soles':
            return eleccion == 'structure_only'
        if hace_falta and eleccion is None:
            raise ErrorMCP(
                f"el proyecto está en {proy['moneda']} y la biblioteca trae "
                "precios del Perú en soles: pregunta al usuario y pasa "
                "library_prices = «structure_only» (rendimientos y cantidades, "
                "insumos nuevos a 0) o «library» (con esos precios)")
        return eleccion != 'library'

    def add_items(self, project_id: int, items: list, sub_budget_id: int = 0,
                  library_prices: str | None = None):
        def cambio(conn, proy):
            sub = sub_budget_id or None
            if sub and not conn.execute(
                    "SELECT 1 FROM sub_presupuestos WHERE id=? AND proyecto_id=?",
                    (sub, project_id)).fetchone():
                raise ErrorMCP(f"no existe el sub-presupuesto {sub}")
            solo = self._solo_estructura(
                proy, library_prices, any('library_id' in i for i in items))
            codigos = {r[0]: bool(r[1]) for r in conn.execute(
                "SELECT item, es_titulo FROM partidas_ppto WHERE proyecto_id=? AND "
                "sub_presupuesto_id IS ?", (project_id, sub))}
            hechos = []
            for n, it in enumerate(items):
                donde = f"items[{n}]"
                if 'library_id' in it and (it.get('title') or 'unit' in it
                                           or 'description' in it):
                    raise ErrorMCP(f"{donde}: con library_id no van title, "
                                   "description ni unit")
                if 'library_id' not in it and 'description' not in it:
                    raise ErrorMCP(f"{donde}: falta description o library_id")
                if it.get('title') and ('unit' in it or 'quantity' in it):
                    raise ErrorMCP(f"{donde}: un título no lleva unidad ni metrado")
                if not it.get('title') and 'library_id' not in it \
                        and not (it.get('unit') or '').strip():
                    raise ErrorMCP(f"{donde}: falta unit")
                padre = it.get('parent_item')
                codigo = it.get('item')
                if codigo:
                    if codigo in codigos:
                        raise ErrorMCP(f"{donde}: el ítem {codigo} ya existe")
                    arriba = codigo.rpartition('.')[0]
                    if padre and padre != arriba:
                        raise ErrorMCP(f"{donde}: {codigo} no cuelga de {padre}")
                    if arriba and arriba not in codigos:
                        raise ErrorMCP(f"{donde}: primero crea el título {arriba}")
                    padre = arriba or None
                if padre:
                    if padre not in codigos:
                        raise ErrorMCP(f"{donde}: no existe el ítem {padre}")
                    if not codigos[padre]:
                        raise ErrorMCP(f"{donde}: {padre} es una partida, no un título")
                if not codigo:
                    codigo = ops.siguiente_item(conn, project_id, padre, bool(padre))
                    if codigo in codigos:
                        raise ErrorMCP(f"{donde}: no queda código libre bajo "
                                       f"{padre or 'la raíz'}")
                if 'library_id' in it:
                    part = ops.insertar_desde_biblioteca(
                        conn, project_id, it['library_id'], codigo, sub, solo)
                    if part is None:
                        raise ErrorMCP(f"{donde}: no existe library_id "
                                       f"{it['library_id']} (usa search_library)")
                elif it.get('title'):
                    part = ops.insertar_titulo(conn, project_id, codigo,
                                               it['description'].strip(), sub)
                else:
                    part = ops.insertar_partida(
                        conn, project_id, codigo, it['description'].strip(),
                        it['unit'].strip(), sub)
                codigos[codigo] = bool(it.get('title'))
                if 'quantity' in it:
                    ops.fijar_metrado(conn, part, it['quantity'])
                r = conn.execute(
                    "SELECT id, item, descripcion, unidad, metrado, "
                    "precio_unitario, es_titulo FROM partidas WHERE id=?",
                    (part,)).fetchone()
                d = {"item_id": r['id'], "item": r['item'],
                     "description": r['descripcion'],
                     "title": bool(r['es_titulo'])}
                if not r['es_titulo']:
                    d.update(unit=r['unidad'], quantity=r['metrado'],
                             unit_price=r['precio_unitario'])
                hechos.append(d)
            from core.database import igualar_codigos_hermanos
            if igualar_codigos_hermanos(conn, project_id):
                for d in hechos:
                    d['item'] = conn.execute(
                        "SELECT item FROM partidas WHERE id=?",
                        (d['item_id'],)).fetchone()[0]
            return {"added": hechos}
        return self._escribir('add_items', project_id, 'presupuesto', cambio)

    def _pid_de(self, part_id: int) -> int:
        from core.database import get_db
        conn = get_db()
        try:
            p, _ = self._partida(conn, part_id)
            return p['proyecto_id']
        finally:
            conn.close()

    def set_metrado(self, item_id: int, rows: list | None = None,
                    quantity: float | None = None, replace: bool = False):
        if (rows is None) == (quantity is None):
            raise ErrorMCP("da rows o quantity (una de las dos)")

        def cambio(conn, proy):
            p, _ = self._partida(conn, item_id)
            if p['es_titulo']:
                raise ErrorMCP("un título no lleva metrado")
            if p['es_subanalisis']:
                raise ErrorMCP("una sub-partida no lleva metrado: su cantidad "
                               "va en el ACU que la usa")
            if self._filas_bim(conn, item_id):
                raise ErrorMCP("el metrado de esta partida viene de un modelo "
                               "BIM; usa bim_apply, o desvincula con "
                               "link_elements (unlink: true)")
            hay = conn.execute(
                "SELECT (SELECT COUNT(*) FROM metrados_detalle WHERE partida_id=?)"
                " + (SELECT COUNT(*) FROM acero_detalle WHERE partida_id=?)",
                (item_id, item_id)).fetchone()[0]
            if hay and not replace:
                raise ErrorMCP(f"la partida ya tiene una planilla de {hay} filas; "
                               "mírala con get_metrados y pasa replace: true "
                               "para reemplazarla")
            if quantity is not None:
                ops.fijar_metrado(conn, item_id, quantity)
            else:
                ops.guardar_planilla(conn, item_id, [
                    {'descripcion': f.get('description', ''),
                     'n_estructuras': _num(f.get('structures')),
                     'n_elementos': _num(f.get('elements')),
                     'area': _num(f.get('area')), 'largo': _num(f.get('length')),
                     'ancho': _num(f.get('width')), 'alto': _num(f.get('height'))}
                    for f in rows])
            r = conn.execute("SELECT metrado, precio_unitario, unidad FROM partidas"
                             " WHERE id=?", (item_id,)).fetchone()
            from core.database import parcial_wysiwyg
            return {"item_id": item_id, "quantity": r['metrado'],
                    "unit": r['unidad'],
                    "partial": parcial_wysiwyg(r['metrado'], r['precio_unitario'])}
        return self._escribir('set_metrado', self._pid_de(item_id),
                              'presupuesto', cambio)

    def set_acu(self, item_id: int, performance: float | None = None,
                library_id: int | None = None, library_prices: str | None = None,
                mode: str | None = None, resources: list | None = None):
        if performance is None and library_id is None and not resources:
            raise ErrorMCP("indica performance, resources o library_id")
        if library_id is not None and resources:
            raise ErrorMCP("resources y library_id no van juntos")
        pid = self._pid_de(item_id)

        def cambio(conn, proy):
            from core.database import _recalcular_pu
            p, _ = self._partida(conn, item_id)
            if p['es_titulo']:
                raise ErrorMCP("un título no tiene ACU")
            hay = conn.execute("SELECT COUNT(*) FROM acu_items WHERE partida_id=?",
                               (item_id,)).fetchone()[0]
            if library_id is not None or resources:
                if hay and mode is None:
                    raise ErrorMCP(f"la partida ya tiene {hay} insumos; pasa "
                                   "mode: append o replace")
                if hay and mode == 'replace':
                    conn.execute("DELETE FROM acu_items WHERE partida_id=?",
                                 (item_id,))
            rend = performance
            if library_id is not None:
                cu = conn.execute("SELECT rendimiento FROM biblioteca_cu WHERE id=?",
                                  (library_id,)).fetchone()
                if cu is None:
                    raise ErrorMCP(f"no existe library_id {library_id}")
                ops.copiar_acu_biblioteca(
                    conn, pid, item_id, library_id,
                    self._solo_estructura(proy, library_prices, True))
                if not (hay and mode == 'append'):
                    # La cantidad copiada ya corresponde a ese rendimiento.
                    conn.execute("UPDATE partidas SET rendimiento=? WHERE id=?",
                                 (cu['rendimiento'] or 1, item_id))
            if rend is not None:
                ops.aplicar_rendimiento(conn, item_id, rend)
            for n, r in enumerate(resources or []):
                rec = conn.execute("SELECT tipo, unidad, codigo FROM recursos WHERE id=?",
                                   (r['resource_id'],)).fetchone()
                if rec is None or rec['codigo'] == 'SUBPARTIDA':
                    raise ErrorMCP(f"resources[{n}]: no existe el insumo "
                                   f"{r['resource_id']} (usa search_resources)")
                if not r.get('crew') and 'quantity' not in r:
                    raise ErrorMCP(f"resources[{n}]: da crew o quantity")
                from core.database import (partida_global, recurso_por_dia,
                                           recurso_por_hora)
                deriva = (not partida_global(p['unidad'])
                          and (recurso_por_dia(rec['tipo'], rec['unidad'])
                               or recurso_por_hora(rec['tipo'], rec['unidad'])))
                if r.get('crew') and not deriva:
                    raise ErrorMCP(f"resources[{n}]: este insumo no lleva "
                                   "cuadrilla aquí; da quantity")
                if r.get('crew') and 'quantity' in r:
                    raise ErrorMCP(f"resources[{n}]: con crew la cantidad se "
                                   "deriva; no des quantity")
                if conn.execute("SELECT 1 FROM acu_items WHERE partida_id=? AND "
                                "recurso_id=?", (item_id, r['resource_id'])).fetchone():
                    raise ErrorMCP(f"resources[{n}]: ese insumo ya está en el ACU")
                ops.insertar_insumo(conn, item_id, r['resource_id'],
                                    cuadrilla=float(r.get('crew') or 0),
                                    cantidad=float(r.get('quantity') or 0))
            pu = _recalcular_pu(conn, item_id)
            return {"item_id": item_id, "unit_price": pu}
        return self._escribir('set_acu', pid, 'presupuesto', cambio)

    # ── Editar lo existente ──────────────────────────────────────────────
    def edit_items(self, project_id: int, changes: list):
        def cambio(conn, proy):
            vistas, hechos = set(), []
            for n, c in enumerate(changes):
                donde = f"changes[{n}]"
                if c['item_id'] in vistas:
                    raise ErrorMCP(f"{donde}: la partida {c['item_id']} se repite")
                vistas.add(c['item_id'])
                p = self._partida_de(conn, c['item_id'], project_id, donde)
                if 'description' not in c and 'unit' not in c:
                    raise ErrorMCP(f"{donde}: da description o unit")
                if 'unit' in c and p['es_titulo']:
                    raise ErrorMCP(f"{donde}: un título no lleva unidad")
                desc = c.get('description', p['descripcion']).strip()
                und = c.get('unit', p['unidad'] or '').strip()
                if not p['es_titulo'] and not und and 'unit' in c:
                    raise ErrorMCP(f"{donde}: la unidad no puede quedar vacía")
                conn.execute("UPDATE partidas SET descripcion=?, unidad=? WHERE id=?",
                             (desc, und, p['id']))
                hechos.append({"item_id": p['id'], "item": p['item'],
                               "description": desc, "unit": und})
            return {"updated": hechos}
        return self._escribir('edit_items', project_id, 'presupuesto', cambio)

    def _partida_de(self, conn, part_id, pid, donde=''):
        """La fila, del presupuesto de ESE proyecto (no una sub-partida)."""
        p, _ = self._partida(conn, part_id)
        pre = f"{donde}: " if donde else ""
        if p['proyecto_id'] != pid:
            raise ErrorMCP(f"{pre}la partida {part_id} no es de este proyecto")
        if p['es_subanalisis']:
            raise ErrorMCP(f"{pre}{part_id} es una sub-partida; el usuario la "
                           "edita en la app")
        return p

    @staticmethod
    def _destino(arbol, parent_item_id, after_item_id, quitar=()):
        """(padre, posición) del sitio pedido en `arbol`."""
        if (parent_item_id is None) == (after_item_id is None):
            raise ErrorMCP("da parent_item_id (0 = raíz) o after_item_id "
                           "(una de las dos)")
        if parent_item_id is not None:
            padre = parent_item_id or None
            if padre is not None and not arbol.titulo.get(padre):
                raise ErrorMCP("parent_item_id debe ser un título del mismo "
                               "sub-presupuesto")
            pos = len(arbol.hijos.get(padre, []))
        else:
            if after_item_id not in arbol.padre:
                raise ErrorMCP("after_item_id no es del mismo sub-presupuesto")
            padre = arbol.padre[after_item_id]
            pos = arbol.hijos[padre].index(after_item_id) + 1
        if padre in quitar or after_item_id in quitar:
            raise ErrorMCP("no se puede mover algo dentro de sí mismo")
        return padre, pos

    def move_item(self, project_id: int, item_id: int,
                  parent_item_id: int | None = None,
                  after_item_id: int | None = None):
        def cambio(conn, proy):
            p = self._partida_de(conn, item_id, project_id)
            a = estructura_ops.Arbol(conn, project_id, p['sub_presupuesto_id'])
            suyos = {item_id, *a.descendientes(item_id)}
            self._destino(a, parent_item_id, after_item_id, suyos)
            a.quitar(item_id)
            padre, pos = self._destino(a, parent_item_id, after_item_id)
            a.poner(item_id, padre, pos)
            a.renumerar(conn)
            return self._resumen_items(conn, [item_id])
        return self._escribir('move_item', project_id, 'presupuesto', cambio)

    def copy_item(self, project_id: int, item_id: int,
                  parent_item_id: int | None = None,
                  after_item_id: int | None = None):
        from utils import partidas_clipboard as pc

        def cambio(conn, proy):
            p = self._partida_de(conn, item_id, project_id)
            sub = p['sub_presupuesto_id']
            a = estructura_ops.Arbol(conn, project_id, sub)
            self._destino(a, parent_item_id, after_item_id)
            # Se pega en la raíz (código libre seguro) y luego se coloca.
            arbol = [pc._serializar_partida(conn, i)
                     for i in pc._subarbol_ids(conn, item_id)]
            (nueva,) = pc.pegar_datos(conn, [arbol], project_id, sub)
            a = estructura_ops.Arbol(conn, project_id, sub)
            a.quitar(nueva)
            padre, pos = self._destino(a, parent_item_id, after_item_id)
            a.poner(nueva, padre, pos)
            a.renumerar(conn)
            return self._resumen_items(conn, [nueva, *a.descendientes(nueva)])
        return self._escribir('copy_item', project_id, 'presupuesto', cambio)

    @staticmethod
    def _resumen_items(conn, ids):
        return {"items": [
            {"item_id": r['id'], "item": r['item'], "description": r['descripcion'],
             "title": bool(r['es_titulo'])} for i in ids
            for r in [conn.execute("SELECT id, item, descripcion, es_titulo FROM "
                                   "partidas WHERE id=?", (i,)).fetchone()]]}

    def delete_items(self, project_id: int, item_ids: list,
                     with_children: bool = False):
        def cambio(conn, proy):
            arboles: dict = {}
            todos: dict = {}
            for i in dict.fromkeys(item_ids):
                p = self._partida_de(conn, i, project_id)
                sub = p['sub_presupuesto_id']
                a = arboles.get(sub)
                if a is None:
                    a = arboles[sub] = estructura_ops.Arbol(conn, project_id, sub)
                todos[i] = a
                for h in a.descendientes(i):
                    if not with_children and h not in item_ids:
                        raise ErrorMCP(f"{p['item']} tiene partidas dentro; pasa "
                                       "with_children: true para borrarlas también")
                    todos[h] = a
            obra = estructura_ops.con_obra_registrada(conn, todos)
            if obra:
                raise ErrorMCP("hay avance de obra registrado (valorizaciones o "
                               "partes diarios) en: " + ", ".join(map(str, obra[:20]))
                               + "; bórralas en la app si de verdad corresponde")
            borradas = self._resumen_items(conn, list(todos))["items"]
            for i, a in todos.items():
                a.quitar(i)
            # Los archivos adjuntos se quedan en disco: hacen falta al deshacer.
            for i in todos:
                conn.execute("DELETE FROM partidas WHERE id=?", (i,))
            for a in arboles.values():
                a.renumerar(conn)
            return {"deleted": borradas}
        return self._escribir('delete_items', project_id, 'presupuesto', cambio)

    def edit_acu(self, item_id: int, changes: list | None = None,
                 remove: list | None = None):
        if not changes and not remove:
            raise ErrorMCP("da changes o remove")
        pid = self._pid_de(item_id)

        def cambio(conn, proy):
            from core.database import (_recalcular_pu, partida_global,
                                       recurso_por_dia, recurso_por_hora)
            p, _ = self._partida(conn, item_id)
            if p['es_titulo']:
                raise ErrorMCP("un título no tiene ACU")
            vistas = set()

            def linea(ref, donde):
                if ('resource_id' in ref) == ('subitem_id' in ref):
                    raise ErrorMCP(f"{donde}: da resource_id o subitem_id")
                if 'subitem_id' in ref:
                    filas = conn.execute(
                        "SELECT a.*, r.tipo, r.unidad FROM acu_items a JOIN recursos r"
                        " ON r.id=a.recurso_id WHERE a.partida_id=? AND "
                        "a.sub_partida_id=?", (item_id, ref['subitem_id'])).fetchall()
                else:
                    filas = conn.execute(
                        "SELECT a.*, r.tipo, r.unidad FROM acu_items a JOIN recursos r"
                        " ON r.id=a.recurso_id WHERE a.partida_id=? AND a.recurso_id=?"
                        " AND a.sub_partida_id IS NULL",
                        (item_id, ref['resource_id'])).fetchall()
                if not filas:
                    raise ErrorMCP(f"{donde}: no está en este ACU (usa get_acu)")
                if len(filas) > 1:
                    raise ErrorMCP(f"{donde}: está {len(filas)} veces en el ACU; "
                                   "el usuario debe corregirlo en la app")
                if filas[0]['id'] in vistas:
                    raise ErrorMCP(f"{donde}: se repite")
                vistas.add(filas[0]['id'])
                return filas[0]
            for n, c in enumerate(changes or []):
                donde = f"changes[{n}]"
                ln = linea(c, donde)
                if ('crew' in c) == ('quantity' in c):
                    raise ErrorMCP(f"{donde}: da crew o quantity (una de las dos)")
                cuad, cant = 0.0, c.get('quantity')
                if 'crew' in c:
                    if partida_global(p['unidad']) or not (
                            recurso_por_dia(ln['tipo'], ln['unidad'])
                            or recurso_por_hora(ln['tipo'], ln['unidad'])) \
                            or c['crew'] <= 0 or 'subitem_id' in c:
                        raise ErrorMCP(f"{donde}: este insumo no lleva cuadrilla "
                                       "aquí; da quantity")
                    cuad, cant = ops.cuadrilla_y_cantidad(
                        ln['tipo'], ln['unidad'], cuad=float(c['crew']), cant=0,
                        rend=p['rendimiento'], jornada=ops.jornada_de(conn, pid),
                        es_global=False)
                conn.execute("UPDATE acu_items SET cuadrilla=?, cantidad=? WHERE id=?",
                             (cuad, cant, ln['id']))
            for n, c in enumerate(remove or []):
                conn.execute("DELETE FROM acu_items WHERE id=?",
                             (linea(c, f"remove[{n}]")['id'],))
            return {"item_id": item_id, "unit_price": _recalcular_pu(conn, item_id)}
        return self._escribir('edit_acu', pid, 'presupuesto', cambio)

    # ── Proyecto y pie ───────────────────────────────────────────────────
    _CAMPOS_PROYECTO = {'name': 'nombre', 'client': 'cliente',
                        'location': 'ubicacion', 'sub_budget': 'sub_presupuesto',
                        'cost_date': 'costo_al', 'term_days': 'plazo',
                        'total_name': 'total_nombre'}

    def update_project(self, project_id: int, **campos):
        if not campos:
            raise ErrorMCP("no indicaste qué cambiar")
        if 'cost_date' in campos:
            from datetime import datetime
            try:
                datetime.strptime(campos['cost_date'], '%d/%m/%Y')
            except ValueError:
                raise ErrorMCP("cost_date va como dd/mm/aaaa") from None

        def cambio(conn, proy):
            for k, v in campos.items():
                conn.execute(
                    f"UPDATE proyectos SET {self._CAMPOS_PROYECTO[k]}=? WHERE id=?",
                    (v.strip() if isinstance(v, str) else v, project_id))
            return {"project_id": project_id, "updated": sorted(campos)}
        return self._escribir('update_project', project_id, 'presupuesto', cambio)

    @staticmethod
    def _lineas_pie(conn, proy):
        """(líneas, ¿guardadas?) del pie; si nunca se configuró, las que
        sembraría la pestaña «Pie» para su país."""
        pid = proy['id']
        filas = [dict(r) for r in conn.execute(
            "SELECT codigo, nombre, pct, activo, orden, tipo, mostrar_pct, destacado"
            " FROM pie_rubros WHERE proyecto_id=? ORDER BY orden, id", (pid,))]
        if filas:
            return filas, True
        from core.pie import lineas_por_defecto
        return [dict(zip(('codigo', 'nombre', 'pct', 'activo', 'orden', 'tipo',
                          'mostrar_pct'), x), destacado=0)
                for x in lineas_por_defecto(proy)], False

    @staticmethod
    def _montos_pie(conn, pid):
        """({código: monto fijo}, {códigos con detalle})."""
        fijos, detalle = {}, set()
        for r in conn.execute("SELECT rubro, tipo, precio FROM gastos_generales "
                              "WHERE proyecto_id=?", (pid,)):
            if r['tipo'] == 'manual':
                fijos[r['rubro']] = r['precio'] or 0
            else:
                detalle.add(r['rubro'])
        return fijos, detalle

    def get_footer(self, project_id: int):
        from core.database import get_db
        conn = get_db()
        try:
            proy = self._proyecto(conn, project_id)
            lineas, guardadas = self._lineas_pie(conn, proy)
            fijos, detalle = self._montos_pie(conn, project_id)
        finally:
            conn.close()
        return {"project_id": project_id, "configured": guardadas, "lines": [
            {"code": x['codigo'], "name": x['nombre'], "kind": x['tipo'],
             **({} if x['codigo'] in fijos or x['codigo'] in detalle
               else {"pct": x['pct'] or 0}), "active": bool(x['activo']),
             "show_pct": bool(x['mostrar_pct']),
             **({"amount": fijos[x['codigo']]} if x['codigo'] in fijos else {}),
             "has_detail": x['codigo'] in detalle} for x in lineas]}

    def set_footer(self, project_id: int, lines: list):
        def cambio(conn, proy):
            viejas, _ = self._lineas_pie(conn, proy)
            previas = {x['codigo']: x for x in viejas}
            fijos, detalle = self._montos_pie(conn, project_id)
            usados, nuevas = set(), []
            for n, ln in enumerate(lines):
                donde = f"lines[{n}]"
                cod = ln.get('code')
                if cod is None:
                    k = 1
                    while f"L{k}" in previas or f"L{k}" in usados \
                            or f"L{k}" in fijos or f"L{k}" in detalle:
                        k += 1
                    cod = f"L{k}"
                elif cod not in previas and cod not in ('GG', 'UTIL', 'SUB', 'IGV'):
                    raise ErrorMCP(f"{donde}: no existe el código {cod} (usa "
                                   "get_footer; una línea nueva va sin code)")
                if cod in usados:
                    raise ErrorMCP(f"{donde}: el código {cod} se repite")
                usados.add(cod)
                prev = previas.get(cod, {})
                tipo = ln['kind']
                if 'amount' in ln and tipo != 'rubro':
                    raise ErrorMCP(f"{donde}: amount solo con kind «rubro»")
                if 'amount' in ln and cod in detalle:
                    raise ErrorMCP(f"{donde}: {cod} tiene un detalle de gastos "
                                   "hecho por el usuario; no lo cambio por un monto")
                if cod in detalle and tipo != 'rubro':
                    raise ErrorMCP(f"{donde}: {cod} tiene detalle; su kind es rubro")
                if 'pct' in ln and cod in detalle | set(fijos) and 'amount' not in ln \
                        and tipo == 'rubro' and ln['pct'] != (prev.get('pct') or 0):
                    raise ErrorMCP(f"{donde}: {cod} sale de un monto o detalle; "
                                   "cambiar su pct no tendría efecto")
                nuevas.append((cod, ln['name'].strip(),
                               ln.get('pct', prev.get('pct') or 0),
                               int(ln.get('active', prev.get('activo', 1))), n, tipo,
                               int(ln.get('show_pct', prev.get('mostrar_pct', 1) or 0)),
                               prev.get('destacado') or 0))
                if 'amount' in ln:
                    conn.execute("DELETE FROM gastos_generales WHERE proyecto_id=? "
                                 "AND rubro=? AND tipo='manual'", (project_id, cod))
                    conn.execute(
                        "INSERT INTO gastos_generales (proyecto_id, rubro, tipo, "
                        "descripcion, precio, orden) VALUES (?,?,'manual',"
                        "'__manual__',?,0)", (project_id, cod, ln['amount']))
            perdidas = (detalle | set(fijos)) & set(previas) - usados
            if perdidas:
                raise ErrorMCP("faltan líneas con monto o detalle propio: "
                               + ", ".join(sorted(perdidas))
                               + "; inclúyelas (active: false las oculta)")
            conn.execute("DELETE FROM pie_rubros WHERE proyecto_id=?", (project_id,))
            conn.executemany(
                "INSERT INTO pie_rubros (proyecto_id, codigo, nombre, pct, activo, "
                "orden, tipo, mostrar_pct, destacado) VALUES (?,?,?,?,?,?,?,?,?)",
                [(project_id, *x) for x in nuevas])
            from core.database import calcular_totales
            t = calcular_totales(project_id, conn)[1]
            return {"direct_cost": t['cd'], "total": t['total'],
                    "codes": [x[0] for x in nuevas]}
        return self._escribir('set_footer', project_id, 'pie', cambio)

    def set_price(self, project_id: int, resource_id: int, price: float):
        def cambio(conn, proy):
            from core.database import unificar_precio_recurso
            r = conn.execute("SELECT unidad, codigo FROM recursos WHERE id=?",
                             (resource_id,)).fetchone()
            if r is None:
                raise ErrorMCP(f"no existe el insumo {resource_id}")
            if r['codigo'] == 'SUBPARTIDA':
                raise ErrorMCP("el precio de una sub-partida sale de su propio ACU")
            if (r['unidad'] or '').strip().startswith('%'):
                raise ErrorMCP("el precio de un insumo en % lo deriva el ACU")
            hechas = unificar_precio_recurso(conn, project_id, resource_id,
                                             float(price))
            if not hechas:
                raise ErrorMCP("ese insumo no se usa en el proyecto")
            return {"resource_id": resource_id, "price": price,
                    "items_updated": hechas}
        return self._escribir('set_price', project_id, 'presupuesto', cambio)

    def set_schedule(self, project_id: int, tasks: list | None = None,
                     durations_from_quantities: bool = False):
        if not tasks and not durations_from_quantities:
            raise ErrorMCP("da tasks o durations_from_quantities: true")

        def cambio(conn, proy):
            from core import cronograma as c
            partidas = ops.partidas_en_orden(conn, project_id)
            por_id = {p['id']: p for p in partidas}
            mapa = c.get_cronograma_map(conn, project_id)
            rownum = c.numerar_filas(partidas)
            tocar: dict[int, dict] = {}

            def fila(i):
                if i not in tocar:
                    b = mapa.get(i, {})
                    tocar[i] = {'duracion': b.get('duracion') if b else 1,
                                'inicio_dia': (b.get('inicio_dia') or 1) if b else 1,
                                'predecesoras': b.get('predecesoras') or '',
                                'es_hito': b.get('es_hito') or 0}
                return tocar[i]
            if durations_from_quantities:
                for i, d in c.calcular_duraciones_desde_metrado(
                        partidas, proy.get('jornada_laboral') or 8).items():
                    fila(i)['duracion'] = d
            for n, t in enumerate(tasks or []):
                p = por_id.get(t['item_id'])
                if p is None:
                    raise ErrorMCP(f"tasks[{n}]: la partida {t['item_id']} no es "
                                   "de este proyecto")
                if p['es_titulo']:
                    raise ErrorMCP(f"tasks[{n}]: un título no se programa")
                f = fila(p['id'])
                if 'duration' in t:
                    f['duracion'] = t['duration']
                if 'start_day' in t:
                    f['inicio_dia'] = t['start_day']
                if 'milestone' in t:
                    f['es_hito'] = int(t['milestone'])
                if 'predecessors' in t:
                    refs = []
                    for q in t['predecessors']:
                        if q['item_id'] not in por_id:
                            raise ErrorMCP(f"tasks[{n}]: la predecesora "
                                           f"{q['item_id']} no es de este proyecto")
                        s = str(rownum[q['item_id']])
                        lag = q.get('lag', 0)
                        if q.get('type', 'FC') != 'FC' or lag:
                            s += q.get('type', 'FC')
                        if lag:
                            s += f"{lag:+d}"
                        refs.append(s)
                    f['predecesoras'] = ",".join(refs)
                if (f['duracion'] or 0) == 0 and not f['es_hito']:
                    raise ErrorMCP(f"tasks[{n}]: duración 0 solo en un hito")
            for i, f in tocar.items():
                conn.execute(
                    """INSERT INTO cronograma_partidas
                       (partida_id, duracion, inicio_dia, predecesoras, es_hito)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(partida_id) DO UPDATE SET
                         duracion=excluded.duracion,
                         inicio_dia=excluded.inicio_dia,
                         predecesoras=excluded.predecesoras,
                         es_hito=excluded.es_hito""",
                    (i, f['duracion'], f['inicio_dia'], f['predecesoras'],
                     f['es_hito']))
            mapa = c.get_cronograma_map(conn, project_id)
            inv = {v: k for k, v in rownum.items()}
            items = {p['item']: p['id'] for p in partidas}
            grafo = {i: [x['pid'] for x in c.parse_predecesoras(
                d.get('predecesoras') or '', inv, items)] for i, d in mapa.items()}
            # Solo los ciclos que pasan por lo enlazado en ESTA llamada: un
            # proyecto importado puede traer alguno y no debe bloquear el resto.
            for t in tasks or []:
                if 'predecessors' in t:
                    ciclo = _ciclo(grafo, t['item_id'])
                    if ciclo:
                        raise ErrorMCP("las predecesoras forman un ciclo: "
                                       + " → ".join(por_id[i]['item'] if i in por_id
                                                    else str(i) for i in ciclo))
            plazo = proy.get('plazo') or 0
            tareas = c.cpm(mapa, partidas, plazo,
                           c.dias_no_laborables(proy, plazo + 365))
            return {"updated": len(tocar),
                    "programmed_days": max((t['EF'] for t in tareas.values()),
                                           default=0),
                    "term_days": plazo,
                    "tasks": [{"item_id": i, "start": tareas[i]['ES'],
                               "finish": tareas[i]['EF'],
                               "critical": bool(tareas[i]['critical'])}
                              for i in list(tocar)[:500] if i in tareas]}
        return self._escribir('set_schedule', project_id, 'cronograma', cambio)

    def _niveles_de_forzar(self, conn, proy) -> set:
        """Los permisos que pide lo que de verdad cambiaría al deshacer por
        encima de ediciones posteriores. Vacío = la regla general, estricta."""
        from core import historial
        e = self.pila.ultima()[1]
        if e['creado']:
            return set()
        ahora, antes = mcp_deshacer.volcar(conn, proy['id']), e['antes']
        (viejo,) = historial._mapa(antes, 'proyectos').values()
        if viejo.get('estado') != proy.get('estado'):
            return set()
        niveles = set()
        for t, filas in historial.diferencias(ahora, antes).items():
            if t == 'proyectos' and all(
                    a and b and {c for c in a if a[c] != b.get(c)}
                    <= {'memoria_descriptiva', 'modificado_en'}
                    for a, b in filas.values()):
                niveles.add('specs')
            else:
                niveles.add(historial.nivel_de({t: filas}) or 'obra')
        return niveles

    def undo_last(self, force: bool = False):
        self._puede_escribir()

        def autorizar(pid):
            from core.database import get_db
            conn = get_db()
            try:
                proy = self._proyecto(conn, pid)
                if force and (propios := self._niveles_de_forzar(conn, proy)):
                    for nivel in sorted(propios):
                        self._editable(proy, nivel)
                    return
            finally:
                conn.close()
            ult = self.pila.resumen() or {}
            propio = None if force else NIVEL.get(ult.get('herramienta'))
            for nivel in ((propio,) if propio else ('presupuesto', 'cronograma')):
                self._editable(proy, nivel)
        try:
            r = mcp_deshacer.deshacer_ultima(self.pila, forzar=force,
                                             autorizar=autorizar)
        except mcp_deshacer.EditadoDespues as e:
            err = ErrorMCP(f"{e}. Solo el usuario puede deshacerlo igualmente: "
                           "en la app, menú IA, deshacer lo último de la IA")
            err.editado = True
            raise err from None
        except LookupError as e:
            raise ErrorMCP(str(e)) from None
        if r is None:
            raise ErrorMCP("no hay nada de la IA que deshacer")
        (self.borrados if r['project_removed'] else self.tocados).append(
            r['project_id'])
        return r

    # ── Especificaciones y memoria ───────────────────────────────────────
    def get_specs(self, project_id: int, item_ids: list | None = None,
                  only_missing: bool = False, offset: int = 0, limit: int = 100):
        from core.database import get_db
        from core.textos_spec import a_texto
        conn = get_db()
        try:
            self._proyecto(conn, project_id)
            filas = [p for p in ops.partidas_en_orden(conn, project_id)
                     if not p['es_titulo']]
        finally:
            conn.close()
        if item_ids:
            por_id = {p['id']: p for p in filas}
            malas = [i for i in item_ids if i not in por_id]
            if malas:
                raise ErrorMCP(f"no son partidas de este proyecto: {malas}")
            filas = [por_id[i] for i in dict.fromkeys(item_ids)]
        textos = [a_texto(p['especificaciones']) for p in filas]
        sin = sum(1 for t, n in textos if not t)
        pares = [x for x in zip(filas, textos)
                 if not (only_missing and x[1][0])]
        total = len(pares)
        out = []
        for p, (t, n) in pares[
                0 if item_ids else offset:None if item_ids else offset + limit]:
            d = {"item_id": p['id'], "item": p['item'],
                 "description": p['descripcion'], "unit": p['unidad'] or '',
                 "chars": len(t), "images": n}
            if item_ids:
                d["text"] = t
            out.append(d)
        return {"total": total, "without_spec": sin, "items": out}

    @staticmethod
    def _cuidar_texto(donde, anterior, replace, discard_images):
        """Lo escrito por el usuario no se pisa sin que lo pida."""
        from core.textos_spec import a_texto
        texto, imagenes = a_texto(anterior)
        resto = re.sub(r'<style.*?</style>|<[^>]*>|\s|&nbsp;', '', anterior or '',
                       flags=re.S)
        if (texto or resto) and not replace:
            raise ErrorMCP(f"{donde} ya tiene texto; léelo y pasa replace: true "
                           "para reemplazarlo")
        if imagenes and not discard_images:
            raise ErrorMCP(f"{donde} tiene {imagenes} imagen(es) que se "
                           "perderían; pasa discard_images: true solo si el "
                           "usuario lo aprueba")

    def set_specs(self, project_id: int, specs: list, replace: bool = False,
                  discard_images: bool = False):
        from core.textos_spec import a_html

        def cambio(conn, proy):
            por_id = {p['id']: p for p in ops.partidas_en_orden(conn, project_id)}
            vistos = set()
            for n, x in enumerate(specs):
                p = por_id.get(x['item_id'])
                if p is None:
                    raise ErrorMCP(f"specs[{n}]: la partida {x['item_id']} no es "
                                   "de este proyecto")
                if p['es_titulo']:
                    raise ErrorMCP(f"specs[{n}]: un título no lleva especificación")
                if p['id'] in vistos:
                    raise ErrorMCP(f"specs[{n}]: la partida se repite")
                vistos.add(p['id'])
                self._cuidar_texto(f"specs[{n}] ({p['item']})",
                                   p['especificaciones'], replace, discard_images)
                conn.execute("UPDATE partidas SET especificaciones=? WHERE id=?",
                             (a_html(x['text'].strip()), p['id']))
            return {"updated": sorted(vistos)}
        return self._escribir('set_specs', project_id, 'specs', cambio)

    def get_memoria(self, project_id: int):
        from core.database import get_db
        from core.textos_spec import a_texto
        conn = get_db()
        try:
            p = self._proyecto(conn, project_id)
        finally:
            conn.close()
        texto, n = a_texto(p.get('memoria_descriptiva'))
        return {"project_id": project_id, "text": texto, "images": n}

    def set_memoria(self, project_id: int, text: str, replace: bool = False,
                    discard_images: bool = False):
        from core.textos_spec import a_html

        def cambio(conn, proy):
            self._cuidar_texto("la memoria", proy.get('memoria_descriptiva'),
                               replace, discard_images)
            conn.execute("UPDATE proyectos SET memoria_descriptiva=? WHERE id=?",
                         (a_html(text.strip()), project_id))
            return {"project_id": project_id, "chars": len(text.strip())}
        return self._escribir('set_memoria', project_id, 'specs', cambio)

    # ── Detalle de gastos (generales u otro rubro del pie) ───────────────
    def _rubro(self, conn, proy, code):
        lineas, guardadas = self._lineas_pie(conn, proy)
        ln = next((x for x in lineas if x['codigo'] == code), None)
        if ln is None:
            raise ErrorMCP(f"no existe el código {code} (usa get_footer)")
        return ln, guardadas

    @staticmethod
    def _filas_gasto(conn, pid, code):
        return [dict(r) for r in conn.execute(
            "SELECT tipo, descripcion, unidad, cantidad, pct_participacion, "
            "precio FROM gastos_generales WHERE proyecto_id=? AND rubro=? "
            "ORDER BY orden, id", (pid, code))]

    def get_overhead(self, project_id: int, code: str = "GG"):
        from core import pie
        from core.database import get_db, calcular_totales
        conn = get_db()
        try:
            proy = self._proyecto(conn, project_id)
            ln, guardadas = self._rubro(conn, proy, code)
            filas = self._filas_gasto(conn, project_id, code)
            cd = calcular_totales(project_id, conn)[1]['cd']
            lineas, _t = pie.pie_efectivo(conn, project_id, cd)
        finally:
            conn.close()
        rows, fijo = [], None
        for f in filas:
            if f['tipo'] == 'manual':
                fijo = f['precio'] or 0
            elif f['tipo'] == 'item':
                rows.append({"description": f['descripcion'] or '',
                             "unit": f['unidad'] or '',
                             "quantity": f['cantidad'] or 0,
                             "participation_pct": f['pct_participacion'] or 100,
                             "price": f['precio'] or 0})
            else:
                rows.append({"group": True, "description": f['descripcion'] or ''})
        return {"code": code, "name": ln['nombre'], "kind": ln['tipo'],
                "configured": guardadas, "fixed_amount": fijo, "rows": rows,
                "amount": next((x['valor'] for x in lineas or []
                                if x['codigo'] == code), 0),
                "direct_cost": cd}

    def set_overhead(self, project_id: int, rows: list, code: str = "GG",
                     replace: bool = False):
        def cambio(conn, proy):
            from core import pie
            from core.database import calcular_totales
            ln, guardadas = self._rubro(conn, proy, code)
            if not guardadas:
                raise ErrorMCP("el pie del proyecto aún no está configurado; "
                               "guárdalo antes con set_footer (get_footer da sus "
                               "líneas)")
            if ln['tipo'] != 'rubro':
                raise ErrorMCP(f"{code} es un porcentaje ({ln['tipo']}); un "
                               "detalle solo cuenta en kind «rubro»: cámbialo con "
                               "set_footer")
            if not any(not r.get('group') for r in rows):
                raise ErrorMCP("el detalle no tiene ningún gasto")
            hay = self._filas_gasto(conn, project_id, code)
            if hay and not replace:
                que = ("un monto fijo" if any(f['tipo'] == 'manual' for f in hay)
                       else "un detalle")
                raise ErrorMCP(f"{code} ya tiene {que}; pasa replace: true para "
                               "reemplazarlo")
            conn.execute("DELETE FROM gastos_generales WHERE proyecto_id=? AND "
                         "rubro=?", (project_id, code))
            base = conn.execute("SELECT COALESCE(MAX(orden),0) FROM "
                                "gastos_generales WHERE proyecto_id=?",
                                (project_id,)).fetchone()[0] or 0
            for n, r in enumerate(rows, 1):
                grupo = bool(r.get('group'))
                sobra = {'unit', 'quantity', 'price', 'participation_pct'} & set(r)
                if grupo and sobra:
                    raise ErrorMCP(f"rows[{n - 1}]: un grupo solo lleva "
                                   "description")
                if r.get('participation_pct') == 0:   # el pie lee 0 como «sin dato»
                    raise ErrorMCP(f"rows[{n - 1}]: con participation_pct 0 no "
                                   "cuesta nada; quita la fila")
                if not grupo and not {'quantity', 'price'} <= set(r):
                    raise ErrorMCP(f"rows[{n - 1}]: faltan quantity y price")
                conn.execute(
                    "INSERT INTO gastos_generales (proyecto_id, rubro, tipo, "
                    "descripcion, unidad, cantidad, pct_participacion, precio, "
                    "orden) VALUES (?,?,?,?,?,?,?,?,?)",
                    (project_id, code, 'grupo' if grupo else 'item',
                     r['description'].strip(), r.get('unit', ''),
                     None if grupo else r['quantity'],
                     None if grupo else r.get('participation_pct', 100),
                     None if grupo else r['price'], base + n))
            t = calcular_totales(project_id, conn)[1]
            lineas, _x = pie.pie_efectivo(conn, project_id, t['cd'])
            return {"code": code, "active": bool(ln['activo']),
                    "amount": next((x['valor'] for x in lineas or []
                                    if x['codigo'] == code), 0),
                    "direct_cost": t['cd'], "total": t['total']}
        return self._escribir('set_overhead', project_id, 'pie', cambio)

    # ── Fórmula polinómica (los coeficientes los calcula core) ───────────
    def _formula_lista(self, conn, pid, formula_id):
        """(fila de la fórmula o None, todas). Sin crear nada al leer."""
        todas = [dict(r) for r in conn.execute(
            "SELECT id, numero, nombre FROM formulas WHERE proyecto_id=? "
            "ORDER BY numero", (pid,))]
        if formula_id is None:
            return (todas[0] if todas else None), todas
        f = next((x for x in todas if x['id'] == formula_id), None)
        if f is None:
            raise ErrorMCP(f"no existe la fórmula {formula_id} (usa get_formula)")
        return f, todas

    #: Monomios sin una fórmula de su proyecto: de versiones de una sola
    #: fórmula, o de un proyecto duplicado.
    _HUERFANOS = ("proyecto_id=? AND (formula_id IS NULL OR formula_id NOT IN "
                  "(SELECT id FROM formulas f WHERE f.proyecto_id=?))")

    @staticmethod
    def _areas(per):
        from core.indices_inei import listar_areas, serie_de
        return [{"code": a['codigo'], "name": a['nombre']} for a in listar_areas(
            serie=serie_de(per['oferta_anio'], per['oferta_mes']))]

    @staticmethod
    def _monomio(m):
        return {"symbol": m.get('simbolo') or '',
                "description": m.get('descripcion') or '',
                "index_code": m.get('indice_inei') or '',
                "coefficient": m.get('coeficiente') or 0,
                "indices": [{"code": c['codigo'], "name": c.get('nombre') or ''}
                            for c in m.get('componentes') or []]}

    @staticmethod
    def _avisos_formula(monomios, sin_indice, base):
        from core import formula_polinomica as fp
        av = []
        if len(monomios) > fp.MAX_MONOMIOS:
            av.append(f"hay más de {fp.MAX_MONOMIOS} monomios")
        for m in monomios:
            if (m.get('coeficiente') or 0) < fp.MIN_INCIDENCIA:
                av.append(f"{m.get('simbolo')}: coeficiente menor que "
                          f"{fp.MIN_INCIDENCIA:g}")
            if m.get('tipo') not in ('MO', 'GU') \
                    and len(m.get('componentes') or []) > fp.MAX_IU_POR_INDICE:
                av.append(f"{m.get('simbolo')}: más de {fp.MAX_IU_POR_INDICE} "
                          "índices; su índice promedia los de mayor peso")
        if sin_indice > 0 and base > 0:
            av.append(f"{sin_indice / base:.1%} del presupuesto son insumos sin "
                      "índice asignado (se les supone el de su tipo); lo asigna "
                      "el usuario en la app")
        return av

    def get_formula(self, project_id: int, formula_id: int | None = None):
        from core import formula_polinomica as fp
        from core.database import get_db
        conn = get_db()
        try:
            self._proyecto(conn, project_id)
            f, todas = self._formula_lista(conn, project_id, formula_id)
        finally:
            conn.close()
        aplica, motivo = fp.aplica_formula(project_id)
        per = fp.cargar_periodos(project_id)
        out = {"applies": aplica, "reason": motivo,
               "formulas": [{"formula_id": x['id'], "number": x['numero'],
                             "name": x['nombre']} for x in todas],
               "periods": {"base_year": per['oferta_anio'],
                           "base_month": per['oferta_mes'],
                           "adjust_year": per['reajuste_anio'],
                           "adjust_month": per['reajuste_mes'],
                           "area": per['area_inei']},
               "areas": self._areas(per), "monomials": [],
               "k": None}
        if f is not None:
            comps = fp.cargar_componentes(project_id, formula_id=f['id'])
            mons = [dict(m, componentes=comps.get(m['orden'], []))
                    for m in fp.cargar_monomios(project_id, f['id'])]
            out["formula_id"] = f['id']
            out["monomials"] = [self._monomio(m) for m in mons]
            if mons and aplica:
                k = fp.calcular_reajuste_k(project_id, formula_id=f['id'])
                completo = k['ok'] and not k['monomios_sin_datos']
                out["k"] = k['k_total'] if completo else None
                if not completo:
                    out["k_missing"] = k.get('msg') or (
                        f"{k['monomios_sin_datos']} monomio(s) sin valor del "
                        "INEI en esos períodos")
        inc = fp.incidencias_por_iu(project_id,
                                    formula_id=f['id'] if f else None)
        out["incidences_ok"] = inc['ok']
        if not inc['ok']:
            out["message"] = inc['msg']
        out["incidences"] = [
            {"code": "GU" if i['tipo'] == 'GU' else i['codigo'],
             "name": i['nombre'], "type": i['tipo'],
             "incidence": round(i['incidencia'], 6),
             "all_assigned": i['tipo'] == 'GU' or i['asignado']}
            for i in inc['ius']]
        out["resources_without_index"] = [
            {"resource_id": x['recurso_id'], "description": x['descripcion'],
             "assumed_index": x['supuesto'], "amount": round(x['monto'], 2)}
            for x in sorted(inc.get('sin_asignar') or [],
                            key=lambda x: -x['monto'])[:20]]
        if f is None:
            conn = get_db()
            try:
                viejos = [dict(r) for r in conn.execute(
                    f"SELECT * FROM formula_monomios WHERE {self._HUERFANOS} "
                    "ORDER BY orden", (project_id, project_id))]
            finally:
                conn.close()
            out["monomials"] = [self._monomio(m) for m in viejos]
        return out

    def _armar_formula(self, project_id, formula_id, monomials):
        """Los monomios, sin guardar. Sin `monomials`, el cálculo automático."""
        from core import formula_polinomica as fp
        if monomials is None:
            r = fp.calcular_por_iu(project_id, formula_id=formula_id)
            if not r['ok']:
                raise ErrorMCP(r['msg'])
            return r['monomios'], r['monto_sin_indice'], r['base']
        inc = fp.incidencias_por_iu(project_id, formula_id=formula_id)
        if not inc['ok']:
            raise ErrorMCP(inc['msg'])
        gu = next((i for i in inc['ius'] if i['tipo'] == 'GU'), None)
        libres = {i['codigo']: i for i in inc['ius'] if i['tipo'] != 'GU'}
        mons = []
        for n, m in enumerate(monomials):
            comps = []
            for cod in m['index_codes']:
                if cod not in libres:
                    raise ErrorMCP(f"monomials[{n}]: el índice {cod} no está en "
                                   "la obra o ya se usó (get_formula da las "
                                   "incidencias; GU va solo)")
                comps.append(dict(libres.pop(cod)))
            comps.sort(key=lambda c: -c['monto'])
            c0 = comps[0]
            mons.append({'tipo': c0['tipo'], 'indice_inei': c0['codigo'],
                         'componentes': comps,
                         'monto': sum(c['monto'] for c in comps),
                         'descripcion': (m.get('description') or '').strip() or (
                             c0['nombre'] if len(comps) == 1
                             else f"{c0['nombre']} y {len(comps) - 1} más")})
        if libres:
            raise ErrorMCP("faltan índices por repartir: "
                           + ", ".join(sorted(libres)))
        fp._simbolos_unicos(mons)
        propios = [(m.get('symbol') or '').strip() for m in monomials]
        for m, s in zip(mons, propios):
            if s:
                m['simbolo'] = s
        if gu:
            mons.append({'tipo': 'GU', 'simbolo': fp.SIMBOLO_GU,
                         'descripcion': 'Gastos generales y utilidad',
                         'indice_inei': fp.IU_GASTOS_GENERALES,
                         'componentes': [dict(gu)], 'monto': gu['monto']})
        simbolos = [m['simbolo'] for m in mons]
        if len(set(simbolos)) != len(simbolos):
            raise ErrorMCP("los símbolos se repiten: " + ", ".join(simbolos))
        if len(mons) > fp.MAX_MONOMIOS:
            raise ErrorMCP(f"son {len(mons)} monomios; el máximo es "
                           f"{fp.MAX_MONOMIOS} (con gastos generales y utilidad)")
        fp.recalcular_coeficientes(mons, inc['base'])
        return mons, inc['monto_sin_indice'], inc['base']

    def set_formula(self, project_id: int, formula_id: int | None = None,
                    monomials: list | None = None, replace: bool = False,
                    periods: dict | None = None, preview: bool = False):
        from core import formula_polinomica as fp
        from core.database import get_db
        conn = get_db()
        try:
            proy = self._proyecto(conn, project_id)
            self._editable(proy, 'pie')
            f, _todas = self._formula_lista(conn, project_id, formula_id)
            huerfanos = conn.execute(
                f"SELECT COUNT(*) FROM formula_monomios WHERE {self._HUERFANOS}",
                (project_id, project_id)).fetchone()[0]
        finally:
            conn.close()
        aplica, motivo = fp.aplica_formula(project_id)
        if not aplica:
            raise ErrorMCP(motivo)
        fid = f['id'] if f else None
        if periods and preview:
            raise ErrorMCP("preview no admite periods: los coeficientes se "
                           "enseñan con los períodos guardados")
        per = dict(fp.cargar_periodos(project_id))
        for k, col in (('base_year', 'oferta_anio'), ('base_month', 'oferta_mes'),
                       ('adjust_year', 'reajuste_anio'),
                       ('adjust_month', 'reajuste_mes'), ('area', 'area_inei')):
            if k in (periods or {}):
                per[col] = periods[k]
        if periods:
            if (per['reajuste_anio'], per['reajuste_mes']) < (
                    per['oferta_anio'], per['oferta_mes']):
                raise ErrorMCP("el período de reajuste es anterior al base")
            areas = self._areas(per)
            if per['area_inei'] not in [a['code'] for a in areas]:
                raise ErrorMCP("área INEI no válida; hay: " + "; ".join(
                    f"{a['code']} {a['name']}" for a in areas))
        tiene = bool(f and fp.cargar_monomios(project_id, fid)) or (
            f is None and huerfanos > 0)
        # Cambiar el mes de reajuste no rehace los monomios.
        if periods and f and tiene and monomials is None and not replace:
            def solo_periodos():
                fp.guardar_periodos(project_id, **per)
                return {"formula_id": fid, "saved": True, "periods_only": True}
            return self._externa('set_formula', project_id, solo_periodos, 'pie')
        if not preview and tiene and not replace:
            raise ErrorMCP("la fórmula ya tiene monomios; pasa replace: true "
                           "para reemplazarla")

        def responder(mons, sin, base):
            return {"formula_id": fid,
                    "monomials": [self._monomio(m) for m in mons],
                    "sum": round(sum(m['coeficiente'] for m in mons), 3),
                    "warnings": self._avisos_formula(mons, sin, base)}
        if preview:
            return dict(responder(*self._armar_formula(project_id, fid, monomials)),
                        preview=True, saved=False)

        def accion():
            nonlocal fid
            if periods:
                fp.guardar_periodos(project_id, **per)
            if fid is None:
                fid = fp.formula_por_defecto(project_id)
            mons, sin, base = self._armar_formula(project_id, fid, monomials)
            conn = get_db()
            try:
                for t in ('formula_monomios', 'formula_monomio_iu'):
                    conn.execute(f"DELETE FROM {t} WHERE {self._HUERFANOS}",
                                 (project_id, project_id))
                conn.commit()
            finally:
                conn.close()
            fp.guardar_monomios(project_id, mons, fid)
            return dict(responder(mons, sin, base), saved=True)
        return self._externa('set_formula', project_id, accion, 'pie')

    # ── Cronograma (lectura) y curva S ───────────────────────────────────
    def get_schedule(self, project_id: int, offset: int = 0, limit: int = 200):
        from core import cronograma as c
        from core.database import get_db
        conn = get_db()
        try:
            proy = self._proyecto(conn, project_id)
            partidas = ops.partidas_en_orden(conn, project_id)
            mapa = c.get_cronograma_map(conn, project_id)
        finally:
            conn.close()
        plazo = proy.get('plazo') or 0
        tareas = c.cpm(mapa, partidas, plazo, c.dias_no_laborables(proy, plazo + 365))
        fila = c.numerar_filas(partidas)
        todas = [p for p in partidas if not p['es_titulo']]
        out = []
        for p in todas[offset:offset + limit]:
            m, t = mapa.get(p['id'], {}), tareas.get(p['id'])
            out.append({"item_id": p['id'], "item": p['item'],
                        "description": p['descripcion'],
                        "gantt_row": fila[p['id']], "scheduled": bool(m),
                        "duration": m.get('duracion') if m else None,
                        "predecessors": m.get('predecesoras') or '',
                        "milestone": bool(m.get('es_hito')),
                        "start": t['ES'] if t else None,
                        "finish": t['EF'] if t else None,
                        "critical": bool(t and t['critical'])})
        return {"total": len(todas), "term_days": plazo,
                "start_date": proy.get('fecha_inicio') or '',
                "programmed_days": max((t['EF'] for t in tareas.values()),
                                       default=0),
                "tasks": out}

    def s_curve(self, project_id: int, period: str = "month"):
        from core.curva_s import curva_s_comparada
        from core.database import get_db
        conn = get_db()
        try:
            self._proyecto(conn, project_id)
        finally:
            conn.close()
        r = curva_s_comparada(project_id, {'month': 'mes', 'week': 'semana',
                                           'calendar_month': 'mes_cal'}[period])
        return {"period": period, "unit": r['unidad'],
                "total": r['total_general'], "start_date": r['fecha_inicio'],
                "rows": [{k: round(v, 4) if isinstance(v, float) else v
                          for k, v in {"label": x['label'], "planned_pct": x['p_eje'],
                          "planned_accum_pct": x['p_acu'],
                          "planned_amount": x['p_mon'],
                          "replanned_accum_pct": x['r_acu'],
                          "real_pct": x['x_eje'], "real_accum_pct": x['x_acu'],
                          "real_amount": x['x_mon'],
                          "deviation_pct": x['desviacion']}.items()}
                         for x in r['filas']]}

    # ── Valorizaciones ───────────────────────────────────────────────────
    def _valorizacion(self, conn, val_id):
        v = conn.execute("SELECT * FROM valorizaciones WHERE id=?",
                         (val_id,)).fetchone()
        if v is not None:
            try:
                self._proyecto(conn, v['proyecto_id'])
                return dict(v)
            except ErrorMCP:
                pass
        raise ErrorMCP(f"no existe la valorización {val_id} (usa list_valuations)")

    @staticmethod
    def _resumen_val(r):
        return {k: round(r[c], 4) for k, c in (
            ("base", 'base_val'), ("previous", 'ant_val'), ("current", 'act_val'),
            ("accumulated", 'acu_val'), ("balance", 'sal_val'),
            ("progress_pct", 'pct_fisico'))}

    def list_valuations(self, project_id: int):
        from core import valorizacion as V
        from core.database import get_db
        conn = get_db()
        try:
            proy = self._proyecto(conn, project_id)
        finally:
            conn.close()
        return {"project_id": project_id,
                "can_write": not self.usuario.es_invitado
                and (proy.get('estado') or '') == 'ejecutado',
                "valuations": [
                    {"valuation_id": v['id'], "number": v['numero'],
                     "from": v['periodo_desde'], "to": v['periodo_hasta'],
                     "state": v['estado'],
                     **self._resumen_val(V.get_valorizacion_detalle(v['id'])[1])}
                    for v in V.listar_valorizaciones(project_id)]}

    def get_valuation(self, valuation_id: int, only_executed: bool = False,
                      offset: int = 0, limit: int = 200):
        from core import valorizacion as V
        from core.database import get_db
        conn = get_db()
        try:
            v = self._valorizacion(conn, valuation_id)
        finally:
            conn.close()
        filas, res = V.get_valorizacion_detalle(valuation_id)
        filas = [f for f in filas if not f['es_titulo']
                 and (not only_executed or f['acu_metr'])]
        return {"valuation_id": valuation_id, "project_id": v['proyecto_id'],
                "number": v['numero'], "from": v['periodo_desde'],
                "to": v['periodo_hasta'], "state": v['estado'],
                **self._resumen_val(res), "adjustment": _plano(res['reajuste']),
                "total": len(filas),
                "items": [{"item_id": f['id'], "item": f['item'],
                           "description": f['descripcion'], "unit": f['unidad'],
                           "unit_price": f['precio_unitario'],
                           "contract_qty": f['base_metr'],
                           "previous_qty": f['ant_metr'],
                           "current_qty": f['act_metr'],
                           "current_amount": f['act_val'],
                           "accumulated_qty": f['acu_metr'],
                           "progress_pct": round(f['pct'], 4),
                           "from_daily_report": f['origen'] == 'diario'}
                          for f in filas[offset:offset + limit]]}

    def create_valuation(self, project_id: int, from_date: str, to_date: str):
        import datetime as dt
        from core import valorizacion as V
        from core.database import get_db
        try:
            a, b = dt.date.fromisoformat(from_date), dt.date.fromisoformat(to_date)
        except ValueError:
            raise ErrorMCP("las fechas van como aaaa-mm-dd") from None
        if a > b:
            raise ErrorMCP("from_date es posterior a to_date")
        conn = get_db()
        try:
            self._proyecto(conn, project_id)
        finally:
            conn.close()
        for v in V.listar_valorizaciones(project_id):
            if (v['periodo_hasta'] or '') >= from_date:
                raise ErrorMCP(f"el período se cruza o es anterior a la "
                               f"valorización {v['numero']} ({v['periodo_desde']} a "
                               f"{v['periodo_hasta']})")

        def accion():
            vid = V.crear_valorizacion(project_id, from_date, to_date)
            return {"valuation_id": vid,
                    "number": V.get_valorizacion(vid)['numero']}
        return self._externa('create_valuation', project_id, accion, 'obra')

    def set_valuation_progress(self, valuation_id: int, items: list):
        from core import valorizacion as V
        from core.database import get_db
        conn = get_db()
        try:
            v = self._valorizacion(conn, valuation_id)
        finally:
            conn.close()
        pid = v['proyecto_id']

        def cambio(conn, proy):
            v = self._valorizacion(conn, valuation_id)
            if v['estado'] == 'cerrada':
                raise ErrorMCP("la valorización está cerrada; la reabre el "
                               "usuario en la app")
            por_id = {p['id']: p for p in ops.partidas_en_orden(conn, pid)}
            diario = {r[0] for r in conn.execute(
                "SELECT partida_id FROM valorizacion_detalle WHERE "
                "valorizacion_id=? AND origen='diario'", (valuation_id,))}
            vistos, exceso = set(), []
            for n, x in enumerate(items):
                p = por_id.get(x['item_id'])
                if p is None:
                    raise ErrorMCP(f"items[{n}]: {x['item_id']} no es una partida "
                                   "de este proyecto")
                if p['es_titulo']:
                    raise ErrorMCP(f"items[{n}]: {p['item']} es un título")
                if p['id'] in vistos:
                    raise ErrorMCP(f"items[{n}]: la partida se repite")
                if p['id'] in diario:
                    raise ErrorMCP(f"items[{n}]: {p['item']} sale del cuaderno de "
                                   "obra y se cambia allí")
                vistos.add(p['id'])
                conn.execute(
                    "INSERT INTO valorizacion_detalle (valorizacion_id, "
                    "partida_id, metrado_periodo, origen) VALUES (?,?,?,'manual') "
                    "ON CONFLICT(valorizacion_id, partida_id) DO UPDATE SET "
                    "metrado_periodo=excluded.metrado_periodo, origen='manual'",
                    (valuation_id, p['id'], x['quantity']))
                acu = conn.execute(
                    "SELECT SUM(d.metrado_periodo) FROM valorizacion_detalle d "
                    "JOIN valorizaciones w ON w.id=d.valorizacion_id WHERE "
                    "w.proyecto_id=? AND d.partida_id=?",
                    (pid, p['id'])).fetchone()[0] or 0
                if acu > (p['metrado'] or 0) + 1e-9:
                    exceso.append({"item_id": p['id'], "item": p['item'],
                                   "accumulated_qty": acu,
                                   "contract_qty": p['metrado'] or 0})
            return {"valuation_id": valuation_id, "updated": len(vistos),
                    "over_contract": exceso}
        res = self._escribir('set_valuation_progress', pid, 'obra', cambio)
        if not self.simular:
            res = dict(res, **self._resumen_val(
                V.get_valorizacion_detalle(valuation_id)[1]))
        return res

    # ── Reportes ─────────────────────────────────────────────────────────
    def export_report(self, project_id: int, report: str, path: str,
                      overwrite: bool = False, cover: bool = True):
        from core.database import get_db
        conn = get_db()
        try:
            self._proyecto(conn, project_id)
        finally:
            conn.close()
        if '\0' in path:
            raise ErrorMCP("ruta no válida")
        ruta = Path(path).expanduser()
        if not ruta.is_absolute():
            raise ErrorMCP("la ruta debe ser absoluta")
        ext = ruta.suffix.lower()
        if ext not in ('.pdf', '.xlsx', '.docx'):
            raise ErrorMCP("la ruta debe terminar en .pdf, .xlsx o .docx")
        if ext == '.docx' and report not in REPORTES_DOCX:
            raise ErrorMCP("en Word hay: " + ", ".join(REPORTES_DOCX))
        if ext == '.xlsx' and report not in REPORTES_XLSX:
            raise ErrorMCP("en Excel hay: " + ", ".join(REPORTES_XLSX))
        if not ruta.parent.is_dir():
            raise ErrorMCP(f"no existe la carpeta {ruta.parent}")
        if ruta.is_dir():
            raise ErrorMCP("la ruta es una carpeta")
        if os.path.lexists(ruta):
            if not overwrite:
                raise ErrorMCP(f"ya existe {ruta}; pasa overwrite: true para "
                               "reemplazarlo")
            if ruta.is_symlink() or not ruta.is_file():
                raise ErrorMCP("la ruta existe y no es un archivo normal")
        # Se genera aparte y se coloca entero: un fallo no deja medio archivo
        # ni pisa el que había.
        try:
            fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=".ingeppto-",
                                       suffix=ext)
        except OSError as e:
            raise ErrorMCP(f"no se puede escribir en {ruta.parent}: {e.strerror}. "
                           "En Flatpak o snap la app solo ve algunas carpetas "
                           "(Documentos, Descargas)") from None
        os.close(fd)
        try:
            if ext == '.pdf':
                from core import pdf_reports
                pdf_reports.generar_pdf_archivo(report, project_id, tmp,
                                                with_cover=cover)
            elif ext == '.docx':
                from core import word_reports
                word_reports.generar_word(report, project_id, tmp)
            else:
                from core import exporter
                fn = {'presupuesto': exporter.exportar_presupuesto,
                      'insumos': exporter.exportar_insumos,
                      'insumos_sub': lambda i: exporter.exportar_insumos(
                          i, por_sub=True),
                      'acus': exporter.exportar_acus,
                      'metrados': exporter.exportar_metrados,
                      'gastos_generales': exporter.exportar_gastos_generales,
                      'formula_polinomica':
                          exporter.exportar_formula_polinomica,
                      'completo': exporter.exportar_reporte_completo}[report]
                Path(tmp).write_bytes(fn(project_id).getvalue())
            tam = os.path.getsize(tmp)
            if not tam:
                raise ErrorMCP("el reporte salió vacío")
            try:                          # mkstemp crea 0600
                um = os.umask(0)
                os.umask(um)
                os.chmod(tmp, 0o666 & ~um)
            except OSError:
                pass
            if not overwrite and os.path.lexists(ruta):
                raise ErrorMCP(f"ya existe {ruta}")
            os.replace(tmp, ruta)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return {"path": str(ruta), "bytes": tam, "report": report}

    # ── BIM (core.bim_modelo; import perezoso) ───────────────────────────
    @staticmethod
    def _bim():
        try:
            from core import bim_modelo
        except ImportError:
            raise ErrorMCP("esta versión no trae el módulo BIM") from None
        return bim_modelo

    def bim_models(self, project_id: int):
        from core.database import get_db
        conn = get_db()
        try:
            self._proyecto(conn, project_id)
        finally:
            conn.close()
        return {"models": [_plano(m) for m in self._bim().modelos(project_id)]}

    def _modelo_del_proyecto(self, model_id: int, pid: int) -> dict:
        for m in self._bim().modelos(pid):
            d = _plano(m)
            if d.get('id', d.get('modelo_id')) == model_id:
                return d
        raise ErrorMCP(f"el proyecto no tiene el modelo {model_id} (usa bim_models)")

    def _leer_modelo(self, source: str, path: str | None, takeoff):
        bim = self._bim()
        if source == 'ingetrazo':
            if path:
                raise ErrorMCP("path solo va con source=ifc")
            if takeoff is None:
                raise ErrorMCP("no llegó el modelo de IngeTrazo")
            return bim.leer_takeoff(takeoff), ''
        if not path:
            raise ErrorMCP("falta path (el .ifc)")
        ruta = Path(path).expanduser()
        if not ruta.is_absolute() or ruta.suffix.lower() != '.ifc':
            raise ErrorMCP("path debe ser la ruta absoluta de un .ifc")
        if not ruta.is_file():
            raise ErrorMCP(f"no existe {ruta}")
        return bim.leer_ifc(str(ruta)), str(ruta)

    def bim_diff(self, project_id: int, source: str, path: str | None = None,
                 model_id: int | None = None, document_id: str | None = None,
                 _takeoff=None):
        from core.database import get_db
        conn = get_db()
        try:
            self._proyecto(conn, project_id)
        finally:
            conn.close()
        bim = self._bim()
        if model_id is not None:
            self._modelo_del_proyecto(model_id, project_id)
        modelo, _ruta = self._leer_modelo(source, path, _takeoff)
        res = {"elements": len(modelo.elementos),
               "warnings": [str(a) for a in modelo.avisos][:50]}
        if model_id is None:
            return {**res, "proposals": _plano(bim.proponer_partidas(modelo))}
        return {**res, **_resumen_diff(bim.diferencias(model_id, modelo))}

    def bim_apply(self, project_id: int, source: str, path: str | None = None,
                  model_id: int | None = None, document_id: str | None = None,
                  item_ids: list | None = None, _takeoff=None):
        from core.database import get_db
        self._puede_escribir()
        bim = self._bim()
        conn = get_db()
        try:
            self._editable(self._proyecto(conn, project_id))
            for i in item_ids or []:
                if self._partida(conn, i)[0]['proyecto_id'] != project_id:
                    raise ErrorMCP(f"la partida {i} no es de este proyecto")
        finally:
            conn.close()
        if model_id is None and item_ids:
            raise ErrorMCP("item_ids solo va con model_id")
        if model_id is not None:
            self._modelo_del_proyecto(model_id, project_id)
        modelo, ruta = self._leer_modelo(source, path, _takeoff)
        avisos = [str(a) for a in modelo.avisos][:50]
        if model_id is None:
            mid = self._externa('bim_apply', project_id, lambda:
                                bim.registrar_modelo(project_id, modelo, ruta))
            return {"model_id": mid, "registered": True, "warnings": avisos,
                    "elements": len(modelo.elementos)}
        dif = _resumen_diff(bim.diferencias(model_id, modelo))
        self._externa('bim_apply', project_id, lambda:
                      bim.aplicar(model_id, modelo, partidas=item_ids))
        return {"model_id": model_id, "applied": dif, "warnings": avisos}

    def link_elements(self, item_id: int, model_id: int, global_ids: list,
                      measure: str | None = None, factor: float = 1.0,
                      unlink: bool = False, replace_manual: bool = False):
        from core.database import get_db
        conn = get_db()
        try:
            p, _ = self._partida(conn, item_id)
        finally:
            conn.close()
        if p['es_titulo']:
            raise ErrorMCP("un título no se vincula")
        pid = p['proyecto_id']
        bim = self._bim()
        self._modelo_del_proyecto(model_id, pid)
        ids = list(dict.fromkeys(global_ids))
        omitidos = []
        if unlink:
            self._externa('link_elements', pid, lambda:
                          bim.desvincular(item_id, model_id, ids))
        else:
            hay = {_plano(e).get('global_id') for e in bim.elementos(model_id)}
            faltan = [g for g in ids if g not in hay]
            if faltan:
                raise ErrorMCP("el modelo no tiene: " + ", ".join(faltan[:20]))
            def accion():
                try:
                    return bim.vincular(item_id, model_id, ids, medida=measure,
                                        factor=factor,
                                        **({'reemplazar_manual': True}
                                           if replace_manual else {}))
                except ValueError as e:
                    raise ErrorMCP(str(e)) from e
            res = self._externa('link_elements', pid, accion)
            if isinstance(res, dict):
                omitidos = _plano(res.get('omitidos') or [])
        conn = get_db()
        try:
            q = conn.execute("SELECT metrado FROM partidas WHERE id=?",
                             (item_id,)).fetchone()[0]
        finally:
            conn.close()
        return {"item_id": item_id, "quantity": q,
                "links": len(bim.vinculos_partida(item_id)),
                "skipped": omitidos}

    def elementos_a_mostrar(self, item_id: int | None = None,
                            global_ids: list | None = None) -> list[str]:
        """Los GlobalId de show_in_model."""
        if (item_id is None) == (global_ids is None):
            raise ErrorMCP("da item_id o global_ids (una de las dos)")
        if global_ids:
            return global_ids
        from core.database import get_db
        conn = get_db()
        try:
            self._partida(conn, item_id)
        finally:
            conn.close()
        ids = list(dict.fromkeys(
            _plano(v)['global_id'] for v in self._bim().vinculos_partida(item_id)))
        if not ids:
            raise ErrorMCP("la partida no tiene elementos vinculados")
        return ids


def _ciclo(grafo: dict, desde) -> list | None:
    """Camino que sale de `desde` y vuelve a `desde`, o None."""
    padre: dict = {}
    cola = [desde]
    while cola:
        n = cola.pop()
        for s in grafo.get(n, ()):
            if s == desde:
                camino = [desde]
                while n != desde:
                    camino.append(n)
                    n = padre[n]
                return [desde] + camino[::-1]
            if s not in padre:
                padre[s] = n
                cola.append(s)
    return None


def _plano(x):
    """dataclass / sqlite3.Row / tuplas → tipos de JSON."""
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return _plano(dataclasses.asdict(x))
    if hasattr(x, 'keys'):
        return {str(k): _plano(x[k]) for k in x.keys()}
    if isinstance(x, (list, tuple, set)):
        return [_plano(i) for i in x]
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    return str(x)


def _resumen_diff(d) -> dict:
    """Cuántos y los primeros: un modelo grande no cabe en una respuesta."""
    out, cuenta = {}, {}
    for k in ('nuevos', 'borrados', 'cambiados', 'iguales', 'partidas'):
        v = d.get(k)
        if isinstance(v, int) or v is None:
            cuenta[k] = v or 0
            continue
        v = list(v.items()) if hasattr(v, 'items') else list(v)
        cuenta[k] = len(v)
        if k != 'iguales':
            out[k] = _plano(v[:200])
    return {"counts": cuenta, **out}
