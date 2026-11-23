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
import tempfile
from pathlib import Path

from core import mcp_deshacer, partidas_ops as ops
from core.config import ESTADOS_PROYECTO_NOMBRE, puede_editar
from core.mcp_esquemas import REPORTES_XLSX


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
        if not puede_editar(estado, nivel):
            raise ErrorMCP(
                f"el proyecto está «{ESTADOS_PROYECTO_NOMBRE.get(estado, estado)}» "
                f"y no admite cambios de {nivel}; el usuario puede volverlo a "
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
            antes = mcp_deshacer.volcar(conn, pid)
            res = cambio(conn, proy)
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

    def _externa(self, herramienta: str, pid: int, accion):
        """Como `_escribir` para código que abre su propia conexión y hace su
        propio commit (core.bim_modelo). Si falla a medias, se restaura."""
        from core.database import get_db
        conn = get_db()
        try:
            proy = self._proyecto(conn, pid)
            self._editable(proy)
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
                "SELECT SUM(es_titulo=1), SUM(es_titulo=0) FROM partidas"
                " WHERE proyecto_id=?", (project_id,)).fetchone()
        finally:
            conn.close()
        est = p.get('estado') or 'elaboracion'
        puede = not self.usuario.es_invitado
        return {
            "project_id": project_id, "name": p['nombre'],
            "client": p.get('cliente') or '',
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
                     "unit": i['unidad'], "crew": i['cuadrilla'] or 0,
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
        from core.pie import calcular_pie
        conn = get_db()
        try:
            p = self._proyecto(conn, project_id)
        finally:
            conn.close()
        items, t = calcular_totales(project_id)
        conn = get_db()
        try:
            lineas, _total = calcular_pie(conn, project_id, t['cd'])
        finally:
            conn.close()
        if lineas is None:
            pie = [{"name": n, "value": t[k]} for n, k in
                   (("Gastos generales", 'gf'), ("Utilidad", 'utilidad'),
                    ("Subtotal", 'subtotal'), ("Impuesto", 'igv'))]
        else:
            pie = [{"name": x['nombre'], "kind": x['tipo'], "pct": x['pct'],
                    "value": x['valor']} for x in lineas]
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
                "SELECT item, es_titulo FROM partidas WHERE proyecto_id=? AND "
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
                rec = conn.execute("SELECT tipo, unidad FROM recursos WHERE id=?",
                                   (r['resource_id'],)).fetchone()
                if rec is None:
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

    def set_price(self, project_id: int, resource_id: int, price: float):
        def cambio(conn, proy):
            from core.database import unificar_precio_recurso
            r = conn.execute("SELECT unidad FROM recursos WHERE id=?",
                             (resource_id,)).fetchone()
            if r is None:
                raise ErrorMCP(f"no existe el insumo {resource_id}")
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

    def undo_last(self, force: bool = False):
        self._puede_escribir()

        def autorizar(pid):
            from core.database import get_db
            conn = get_db()
            try:
                proy = self._proyecto(conn, pid)
            finally:
                conn.close()
            for nivel in ('presupuesto', 'cronograma'):
                self._editable(proy, nivel)
        try:
            r = mcp_deshacer.deshacer_ultima(self.pila, forzar=force,
                                             autorizar=autorizar)
        except mcp_deshacer.EditadoDespues as e:
            err = ErrorMCP(f"{e}. Pregunta al usuario y usa force: true solo si "
                           "acepta perderlos")
            err.editado = True
            raise err from None
        except LookupError as e:
            raise ErrorMCP(str(e)) from None
        if r is None:
            raise ErrorMCP("no hay nada de la IA que deshacer")
        (self.borrados if r['project_removed'] else self.tocados).append(
            r['project_id'])
        return r

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
        if ext not in ('.pdf', '.xlsx'):
            raise ErrorMCP("la ruta debe terminar en .pdf o .xlsx")
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
            else:
                from core import exporter
                fn = {'presupuesto': exporter.exportar_presupuesto,
                      'insumos': exporter.exportar_insumos,
                      'insumos_sub': lambda i: exporter.exportar_insumos(
                          i, por_sub=True),
                      'acus': exporter.exportar_acus,
                      'metrados': exporter.exportar_metrados,
                      'gastos_generales': exporter.exportar_gastos_generales,
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
                      unlink: bool = False):
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
        if unlink:
            self._externa('link_elements', pid, lambda:
                          bim.desvincular(item_id, model_id, ids))
        else:
            hay = {_plano(e).get('global_id') for e in bim.elementos(model_id)}
            faltan = [g for g in ids if g not in hay]
            if faltan:
                raise ErrorMCP("el modelo no tiene: " + ", ".join(faltan[:20]))
            self._externa('link_elements', pid, lambda: bim.vincular(
                item_id, model_id, ids, medida=measure, factor=factor))
        conn = get_db()
        try:
            q = conn.execute("SELECT metrado FROM partidas WHERE id=?",
                             (item_id,)).fetchone()[0]
        finally:
            conn.close()
        return {"item_id": item_id, "quantity": q,
                "links": len(bim.vinculos_partida(item_id))}

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
