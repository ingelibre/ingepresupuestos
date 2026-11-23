# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Deshacer lo que escribió la IA: copia del proyecto antes de cada escritura.

No hay deshacer general en la app. Antes de cada escritura por MCP se
vuelcan TODAS las filas del proyecto (las tablas se descubren por sus llaves
foráneas, así una tabla nueva entra sola) y se guarda la huella de cómo quedó
después. Restaurar cambia solo las filas distintas y respeta los ids; si la
huella de ahora no es la de «después», alguien editó y se niega salvo
`forzar`.

La pila va a disco (USER_DATA_DIR/deshacer_ia, 0600): sobrevive a cerrar la
app y está acotada. Nunca incluye usuarios, configuración ni catálogos.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

MAX_ENTRADAS = 20
#: Cachés y memoria del asistente: ni se guardan ni se restauran.
EXCLUIDAS = {'dashboard_tot_cache', 'tuxia_memos', 'tuxia_memoria',
             'usuarios', 'configuracion'}
#: Se sella sola con cada edición; no es contenido.
SIN_COMPARAR = {'proyectos': {'modificado_en'}}
#: Columnas que apuntan a un padre aunque la tabla no declare la llave.
_IMPLICITAS = {'proyecto_id': 'proyectos', 'partida_id': 'partidas',
               'modelo_id': 'bim_modelos'}


class EditadoDespues(Exception):
    pass


def _q(n: str) -> str:
    return '"' + n.replace('"', '""') + '"'


def _tablas(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%'")]


def _padres(conn, tablas: set[str]) -> dict[str, list[tuple[str, str]]]:
    """{tabla: [(columna, tabla_padre)]}, declaradas e implícitas."""
    out: dict[str, list[tuple[str, str]]] = {}
    for t in tablas:
        enlaces = []
        vistas = set()
        for fk in conn.execute(f"PRAGMA foreign_key_list({_q(t)})"):
            enlaces.append((fk['from'], fk['table']))
            vistas.add(fk['from'])
        for col in conn.execute(f"PRAGMA table_info({_q(t)})"):
            padre = _IMPLICITAS.get(col['name'])
            if padre in tablas and col['name'] not in vistas and padre != t:
                enlaces.append((col['name'], padre))
        out[t] = enlaces
    return out


def tablas_del_proyecto(conn) -> list[str]:
    """Las tablas que cuelgan de `proyectos`, padres antes que hijas."""
    tablas = set(_tablas(conn)) - EXCLUIDAS
    padres = _padres(conn, tablas)
    dentro = {'proyectos'}
    crecio = True
    while crecio:
        crecio = False
        for t in tablas - dentro:
            if any(p in dentro for _c, p in padres[t]):
                dentro.add(t)
                crecio = True
    # Padres antes que hijas; un ciclo (que hoy no hay) cae en orden de nombre.
    orden = ['proyectos']
    faltan = sorted(dentro - {'proyectos'})
    while faltan:
        lista = [t for t in faltan
                 if all(p in orden or p not in dentro or p == t
                        for _c, p in padres[t])] or faltan[:1]
        orden += lista
        faltan = [t for t in faltan if t not in lista]
    return orden


def volcar(conn, pid: int) -> dict[str, dict]:
    """{tabla: {'cols': […], 'pk': […], 'filas': [[…]]}} del proyecto."""
    tablas = tablas_del_proyecto(conn)
    padres = _padres(conn, set(tablas))
    claves: dict[str, set] = {}       # tabla → ids incluidos
    filas: dict[str, dict] = {}       # tabla → {pk: fila}
    meta: dict[str, tuple] = {}
    for t in tablas:
        info = conn.execute(f"PRAGMA table_info({_q(t)})").fetchall()
        cols = [c['name'] for c in info]
        pk = [c['name'] for c in sorted(info, key=lambda c: c['pk']) if c['pk']]
        meta[t] = (cols, pk or cols)
        filas[t] = {}
        claves[t] = set()
    for t in tablas:
        cols, pk = meta[t]
        idx_pk = [cols.index(c) for c in pk]
        consultas = []
        if t == 'proyectos':
            consultas.append(("SELECT * FROM proyectos WHERE id=?", (pid,)))
        for col, padre in padres[t]:
            if padre not in claves or t == 'proyectos' or padre == t:
                continue
            ids = sorted(x for x in claves[padre] if x is not None)
            for i in range(0, len(ids), 500):
                trozo = ids[i:i + 500]
                consultas.append((
                    f"SELECT * FROM {_q(t)} WHERE {_q(col)} IN "
                    f"({','.join('?' * len(trozo))})", tuple(trozo)))
        for sql, par in consultas:
            for r in conn.execute(sql, par):
                fila = list(r)
                filas[t][tuple(fila[i] for i in idx_pk)] = fila
        if 'id' in cols:
            j = cols.index('id')
            claves[t] = {f[j] for f in filas[t].values()}
    return {t: {'cols': meta[t][0], 'pk': meta[t][1],
                'filas': [filas[t][k] for k in sorted(filas[t], key=repr)]}
            for t in tablas}


def _json_valor(v):
    if isinstance(v, (bytes, memoryview)):
        return {'b64': base64.b64encode(bytes(v)).decode()}
    raise TypeError(type(v).__name__)


def _de_json(v):
    if isinstance(v, dict) and set(v) == {'b64'}:
        return base64.b64decode(v['b64'])
    return v


def huella(volcado: dict) -> str:
    h = hashlib.sha256()
    for t in sorted(volcado):
        d = volcado[t]
        fuera = SIN_COMPARAR.get(t, ())
        idx = [i for i, c in enumerate(d['cols']) if c not in fuera]
        for f in d['filas']:
            h.update(json.dumps([t] + [f[i] for i in idx], default=_json_valor,
                                ensure_ascii=False).encode())
    return h.hexdigest()


# ── Restaurar ────────────────────────────────────────────────────────────────

def _violaciones(conn, tablas) -> set:
    out = set()
    for t in tablas:
        for r in conn.execute(f"PRAGMA foreign_key_check({_q(t)})"):
            out.add(tuple(r))
    return out


def restaurar(conn, pid: int, antes: dict) -> None:
    """Deja el proyecto como en `antes` (volcado) sin cambiar ids. El que
    llama debe haber puesto `PRAGMA foreign_keys=OFF` FUERA de la transacción
    y abierto una: aquí no se hace commit."""
    ahora = volcar(conn, pid)
    tablas = [t for t in tablas_del_proyecto(conn)]
    rotas = _violaciones(conn, tablas)

    def por_pk(v, t):
        if t not in v:
            return {}
        i_pk = [v[t]['cols'].index(c) for c in v[t]['pk']]
        return {tuple(f[i] for i in i_pk): f for f in v[t]['filas']}

    poner = []
    for t in reversed(tablas):
        a, b = por_pk(antes, t), por_pk(ahora, t)
        cols = ahora[t]['cols']
        cols_a = antes[t]['cols'] if t in antes else cols
        fuera = SIN_COMPARAR.get(t, set())
        visibles = [c for c in cols_a if c not in fuera]

        def vista(f, cs):
            d = dict(zip(cs, f))
            return [d.get(c) for c in visibles]

        for k, f in b.items():
            if k in a and vista(a[k], cols_a) == vista(f, cols):
                continue
            donde = " AND ".join(f"{_q(c)} IS ?" for c in ahora[t]['pk'])
            conn.execute(f"DELETE FROM {_q(t)} WHERE {donde}", k)
        for k, f in a.items():
            if k in b and vista(f, cols_a) == vista(b[k], cols):
                continue
            poner.append((t, [(c, x) for c, x in zip(cols_a, f) if c in cols]))
    for t, pares in poner:
        conn.execute(
            f"INSERT INTO {_q(t)} ({','.join(_q(c) for c, _ in pares)}) "
            f"VALUES ({','.join('?' * len(pares))})", [x for _c, x in pares])
    nuevas = _violaciones(conn, tablas) - rotas
    if nuevas:
        raise RuntimeError(
            "no se puede deshacer: la copia usa datos del catálogo que ya no "
            f"existen ({sorted({str(v[0]) for v in nuevas})})")


# ── Pila en disco ────────────────────────────────────────────────────────────

class Pila:
    def __init__(self, carpeta: Path | None = None, maximo: int = MAX_ENTRADAS):
        if carpeta is None:
            from core.config import USER_DATA_DIR
            carpeta = USER_DATA_DIR / "deshacer_ia"
        self.carpeta = Path(carpeta)
        self.maximo = maximo

    def _archivos(self) -> list[Path]:
        try:
            return sorted(self.carpeta.glob("*.json.gz"))
        except OSError:
            return []

    def preparar(self, *, pid: int, herramienta: str, antes: dict | None,
                 despues: str, creado: bool = False) -> Path:
        """Escribe la entrada ya con sus dos mitades, sin publicarla."""
        self.carpeta.mkdir(parents=True, exist_ok=True, mode=0o700)
        ultimos = self._archivos()
        n = int(ultimos[-1].name.split('.')[0]) + 1 if ultimos else 1
        tmp = self.carpeta / f".{n:010d}.tmp"
        datos = json.dumps(
            {'pid': pid, 'herramienta': herramienta, 'cuando': time.time(),
             'creado': creado, 'antes': antes, 'despues': despues},
            default=_json_valor, ensure_ascii=False).encode()
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(gzip.compress(datos, 5))
        return tmp

    def publicar(self, tmp: Path) -> None:
        os.replace(tmp, self.carpeta / (tmp.name[1:-4] + ".json.gz"))
        for viejo in self._archivos()[:-self.maximo]:
            try:
                viejo.unlink()
            except OSError:
                pass

    @staticmethod
    def descartar(tmp: Path) -> None:
        try:
            tmp.unlink()
        except OSError:
            pass

    def ultima(self) -> tuple[Path, dict] | None:
        for archivo in reversed(self._archivos()):
            try:
                e = json.loads(gzip.decompress(archivo.read_bytes()))
                if e['antes'] is not None:
                    for d in e['antes'].values():
                        d['filas'] = [[_de_json(x) for x in f]
                                      for f in d['filas']]
                return archivo, e
            except (OSError, ValueError, KeyError, EOFError):
                self.descartar(archivo)      # ilegible: no estorba a las demás
        return None

    def resumen(self) -> dict | None:
        u = self.ultima()
        if u is None:
            return None
        return {k: u[1][k] for k in ('pid', 'herramienta', 'cuando', 'creado')}

    def vaciar(self) -> None:
        for a in self._archivos():
            self.descartar(a)


def deshacer_ultima(pila: Pila, *, forzar: bool = False,
                    autorizar=lambda pid: None) -> dict | None:
    """Deshace la última entrada. None si no hay nada. `autorizar(pid)` debe
    lanzar si el usuario no puede tocar ese proyecto."""
    u = pila.ultima()
    if u is None:
        return None
    from core.database import get_db
    archivo, e = u
    pid = e['pid']
    conn = get_db()
    try:
        existe = conn.execute("SELECT 1 FROM proyectos WHERE id=?",
                              (pid,)).fetchone() is not None
        if not existe:
            pila.descartar(archivo)
            raise LookupError("el proyecto de la última escritura de la IA ya "
                              "no existe; se quitó esa copia de la lista")
        autorizar(pid)
        # FK fuera para restaurar filas con sus ids sin cascadas; al final se
        # comprueba que no quede ninguna colgando.
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        if not forzar and huella(volcar(conn, pid)) != e['despues']:
            raise EditadoDespues(
                "el proyecto se editó después de esa escritura; deshacerla "
                "perdería esos cambios")
        if e['creado']:
            vacio = {t: dict(d, filas=[]) for t, d in volcar(conn, pid).items()}
            restaurar(conn, pid, vacio)
            for t in EXCLUIDAS & set(_tablas(conn)):
                cols = [c['name'] for c in conn.execute(
                    f"PRAGMA table_info({_q(t)})")]
                if 'proyecto_id' in cols:
                    conn.execute(f"DELETE FROM {_q(t)} WHERE proyecto_id=?",
                                 (pid,))
        else:
            restaurar(conn, pid, e['antes'])
            conn.execute("DELETE FROM dashboard_tot_cache WHERE proyecto_id=?",
                         (pid,))
            conn.execute("UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP"
                         " WHERE id=?", (pid,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    pila.descartar(archivo)
    return {'project_id': pid, 'undone': e['herramienta'],
            'project_removed': bool(e['creado'])}
