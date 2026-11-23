# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Deshacer/Rehacer de un proyecto abierto (sin Qt).

No hay una orden por cada botón: hay ~200 sitios que guardan. Tras cada
guardado se vuelca el proyecto (`mcp_deshacer.volcar`: descubre sus tablas por
las llaves foráneas) y se anota QUÉ FILAS cambiaron. Deshacer pone esas filas
como estaban, con sus ids; si entretanto alguien las cambió por fuera, se
niega en vez de pisarlo.

Fuera: catálogo, biblioteca, configuración y el estado del proyecto (deshacer
no puede ni bloquear ni desbloquear una obra aprobada).
"""
from __future__ import annotations

from core import estructura_ops, mcp_deshacer as md
from utils.i18n import N_

MAX_PASOS = 100
_FUERA = {'proyectos': {'modificado_en', 'estado'}}

#: Del más propio al más general: el primero que aparezca nombra el paso.
_NOMBRES = (
    (('valoriz', 'parte_diario', 'requerim', 'almacen', 'reprogram'),
     N_("control de obra")),
    (('bim_',), N_("modelo BIM")),
    (('pie_', 'gastos_generales'), N_("pie del presupuesto")),
    (('formula',), N_("fórmula polinómica")),
)


class Conflicto(Exception):
    """Las filas del paso ya no están como el paso las dejó."""


def _mapa(volcado: dict, t: str) -> dict:
    """{pk: {columna: valor}} de una tabla del volcado."""
    d = volcado.get(t)
    if d is None:
        return {}
    idx = [d['cols'].index(c) for c in d['pk']]
    return {tuple(f[i] for i in idx): dict(zip(d['cols'], f)) for f in d['filas']}


def _visto(t: str, fila):
    if fila is None:
        return None
    fuera = _FUERA.get(t, ())
    return {k: v for k, v in fila.items() if k not in fuera}


def diferencias(a: dict, b: dict) -> dict:
    """{tabla: {pk: (fila antes | None, fila después | None)}}."""
    out: dict = {}
    for t in {*a, *b}:
        if t in a and t in b and a[t] == b[t]:
            continue
        fa, fb = _mapa(a, t), _mapa(b, t)
        dif = {k: (fa.get(k), fb.get(k)) for k in {*fa, *fb}
               if _visto(t, fa.get(k)) != _visto(t, fb.get(k))}
        if dif:
            out[t] = dif
    return out


def nombre_de(dif: dict) -> str:
    part = dif.get('partidas', {})
    altas = [x for x in part.values() if x[0] is None]
    bajas = [x for x in part.values() if x[1] is None]
    if bajas and not altas:
        return N_("eliminar partida")
    if altas and not bajas:
        return N_("agregar partida")
    for prefijos, nombre in _NOMBRES:
        if any(t.startswith(prefijos) for t in dif):
            return nombre
    if any(t in dif for t in ('metrados_detalle', 'acero_detalle')):
        return N_("metrado")
    if 'acu_items' in dif:
        return N_("análisis de costo unitario")
    cambiadas = {c for a, b in part.values() if a and b
                 for c in a if a[c] != b.get(c)}
    if 'metrado' in cambiadas:
        return N_("metrado")
    if cambiadas & {'item', 'nivel'}:
        return N_("mover partida")
    if 'especificaciones' in cambiadas:
        return N_("especificación")
    if cambiadas:
        return N_("editar partida")
    if any(t.startswith('cronograma') for t in dif):
        return N_("cronograma")
    if 'proyectos' in dif:
        return N_("datos del proyecto")
    return N_("cambio")


def nivel_de(dif: dict) -> str | None:
    """El nivel de edición que hace falta (None = control de obra)."""
    def todas(*prefijos):
        return all(t.startswith(prefijos) for t in dif)
    if todas('cronograma'):
        return 'cronograma'
    if todas('pie_', 'gastos_generales'):
        return 'pie'
    if todas('valoriz', 'parte_diario', 'requerim', 'almacen', 'reprogram'):
        return None
    if set(dif) <= {'partidas', 'spec_imagenes'} and all(
            a and b and {c for c in a if a[c] != b.get(c)}
            <= {'especificaciones', 'spec_adjuntos'}
            for a, b in dif.get('partidas', {}).values()):
        return 'specs'
    return 'presupuesto'


class Historial:
    def __init__(self, pid: int, maximo: int = MAX_PASOS):
        self.pid, self.maximo = pid, maximo
        self.hechos: list[tuple[str, dict]] = []
        self.rehechos: list[tuple[str, dict]] = []
        self._base = self._volcar()

    def _volcar(self) -> dict:
        from core.database import get_db
        conn = get_db()
        try:
            return md.volcar(conn, self.pid)
        finally:
            conn.close()

    @property
    def vivo(self) -> bool:
        return bool(self._base.get('proyectos', {}).get('filas'))

    # ── Observar ─────────────────────────────────────────────────────────
    def revisar(self, anotar: bool = True) -> bool:
        """Compara con lo último visto. Con `anotar` el cambio es un paso; sin
        él solo se toma nota (lo que la app guarda sola al abrir una vista)."""
        ahora = self._volcar()
        dif = diferencias(self._base, ahora)
        if not dif:
            self._base = ahora
            return False
        if anotar and ({'partidas', 'sub_presupuestos'} & set(dif)) \
                and self._predecesoras(ahora):
            ahora = self._volcar()
            dif = diferencias(self._base, ahora)
        self._base = ahora
        if anotar and dif:
            self.hechos.append((nombre_de(dif), dif))
            del self.hechos[:-self.maximo]
            self.rehechos.clear()
        return True

    @staticmethod
    def _filas_gantt(volcado):
        from core.cronograma import numerar_filas
        orden = {f['id']: f.get('orden') or 0
                 for f in _mapa(volcado, 'sub_presupuestos').values()}
        ps = [f for f in _mapa(volcado, 'partidas').values()
              if not f.get('es_subanalisis')]
        ps.sort(key=lambda p: (p['sub_presupuesto_id'] is not None,
                               orden.get(p['sub_presupuesto_id'], 0),
                               p['sub_presupuesto_id'] or 0, p['item'], p['id']))
        return ({n: k for k, n in numerar_filas(ps).items()},
                {p['item']: p['id'] for p in ps})

    def _predecesoras(self, ahora) -> bool:
        """Insertar, mover o borrar partidas corre los números de fila; las
        predecesoras que NO cambiaron de texto se reescriben para que sigan
        apuntando a la misma partida (las que sí, ya las puso alguien)."""
        if not any((f.get('predecesoras') or '')
                   for f in _mapa(ahora, 'cronograma_partidas').values()):
            return False
        antes = self._filas_gantt(self._base)
        if antes == self._filas_gantt(ahora):
            return False
        viejas = {f['partida_id']: f.get('predecesoras') or ''
                  for f in _mapa(self._base, 'cronograma_partidas').values()}
        iguales = {f['partida_id']
                   for f in _mapa(ahora, 'cronograma_partidas').values()
                   if f.get('predecesoras')
                   and viejas.get(f['partida_id']) == f['predecesoras']}
        from core.database import get_db
        conn = get_db()
        try:
            estructura_ops.conservar_predecesoras(conn, self.pid, antes, iguales)
            n = conn.total_changes
            conn.commit()
        finally:
            conn.close()
        return n > 0

    # ── Deshacer / rehacer ───────────────────────────────────────────────
    def deshacer(self) -> str | None:
        return self._aplicar(self.hechos, self.rehechos, 0)

    def rehacer(self) -> str | None:
        return self._aplicar(self.rehechos, self.hechos, 1)

    def _aplicar(self, de, a, lado) -> str | None:
        from core.database import get_db
        if not de:
            return None
        nombre, dif = de[-1]
        conn = get_db()
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("BEGIN IMMEDIATE")
            ahora = md.volcar(conn, self.pid)
            meta = {}
            for t, filas in dif.items():
                d = ahora.get(t)
                if d is None:
                    raise Conflicto(t)
                actuales = _mapa(ahora, t)
                for k, par in filas.items():
                    if _visto(t, actuales.get(k)) != _visto(t, par[1 - lado]):
                        raise Conflicto(t)
                    quiere = par[lado]
                    if quiere is None:
                        actuales.pop(k, None)
                    else:
                        # Lo que no es del historial se queda como está ahora.
                        conserva = {c: actuales[k][c] for c in _FUERA.get(t, ())
                                    if k in actuales and c in actuales[k]}
                        actuales[k] = {**quiere, **conserva}
                meta[t] = dict(d, filas=[[f.get(c) for c in d['cols']]
                                         for f in actuales.values()])
            md.restaurar(conn, self.pid, {**ahora, **meta})
            conn.execute("DELETE FROM dashboard_tot_cache WHERE proyecto_id=?",
                         (self.pid,))
            conn.execute("UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP"
                         " WHERE id=?", (self.pid,))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        a.append(de.pop())
        self._base = self._volcar()
        return nombre

    def vaciar(self) -> None:
        self.hechos.clear()
        self.rehechos.clear()
        self._base = self._volcar()
