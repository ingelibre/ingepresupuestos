# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Ejecutar el código de los complementos activos.

El código se lee UNA vez, se comprueba su huella y se importa desde esa misma
copia en memoria: no se vuelve a leer el disco (nadie lo cambia entre el
control y la ejecución) y nunca se usa un `.pyc`. Vale igual bajo PyInstaller,
Flatpak, Snap y MSIX, porque no depende de rutas de importación.

Un complemento que falla al cargar se apaga y se explica; el programa sigue.
"""
from __future__ import annotations

import importlib.abc
import importlib.util
import sys
import traceback
from dataclasses import dataclass, field

from core.complementos import gestor
from ingepresupuestos import api

PREFIJO = 'ingepresupuestos_complementos'


def _paquete_py(id_: str) -> str:
    return f"{PREFIJO}.{id_.replace('-', '_')}"


class _Cargador(importlib.abc.InspectLoader):
    def __init__(self, fuente: bytes, archivo: str, es_paquete: bool):
        self._fuente, self._archivo, self._es = fuente, archivo, es_paquete

    def get_source(self, nombre):
        return importlib.util.decode_source(self._fuente)

    def is_package(self, nombre):
        return self._es

    def get_code(self, nombre):
        return compile(self._fuente, self._archivo, 'exec', dont_inherit=True)

    def exec_module(self, modulo):
        modulo.__file__ = self._archivo
        exec(self.get_code(modulo.__name__), modulo.__dict__)


class _Buscador(importlib.abc.MetaPathFinder):
    """Encuentra los módulos de los complementos cargados, en memoria."""

    def __init__(self):
        self.modulos: dict[str, tuple[bytes, str, bool]] = {}

    def poner(self, id_: str, paquete) -> None:
        base = _paquete_py(id_)
        carpeta = gestor.carpeta_de(id_)
        self.modulos.setdefault(PREFIJO, (b'', PREFIJO, True))
        self.modulos[base] = (paquete.archivos.get('__init__.py', b''),
                              str(carpeta / '__init__.py'), True)
        for rel, b in paquete.archivos.items():
            if not rel.endswith('.py') or rel == '__init__.py':
                continue
            partes = rel[:-3].split('/')
            for n in range(1, len(partes)):
                self.modulos.setdefault(
                    '.'.join([base, *partes[:n]]),
                    (b'', str(carpeta.joinpath(*partes[:n])), True))
            es = partes[-1] == '__init__'
            if es:
                partes = partes[:-1]
            self.modulos['.'.join([base, *partes])] = (
                b, str(carpeta.joinpath(*rel.split('/'))), es)

    def quitar(self, id_: str) -> None:
        base = _paquete_py(id_)
        for n in [n for n in self.modulos if n == base or n.startswith(base + '.')]:
            del self.modulos[n]
        for n in [n for n in sys.modules if n == base or n.startswith(base + '.')]:
            del sys.modules[n]

    def find_spec(self, nombre, path=None, target=None):
        m = self.modulos.get(nombre)
        if m is None:
            return None
        return importlib.util.spec_from_loader(
            nombre, _Cargador(*m), origin=m[1], is_package=m[2])


_buscador = _Buscador()


@dataclass
class Cargado:
    id: str
    nombre: str
    huella: str
    paquete: object
    registros: list = field(default_factory=list)

    def de(self, clase: str) -> list:
        return [r for r in self.registros if r.clase == clase]


_cargados: dict[str, Cargado] = {}
#: [(id, texto)] de lo que falló al cargar en esta sesión.
fallos: list[tuple[str, str]] = []


def cargados() -> list[Cargado]:
    return list(_cargados.values())


def descargar(id_: str) -> None:
    _cargados.pop(id_, None)
    _buscador.quitar(id_)


def texto_error(e: BaseException, id_: str) -> str:
    """Error legible: el mensaje y la última línea DEL COMPLEMENTO."""
    if isinstance(e, api.ErrorComplemento):
        return str(e)
    carpeta = str(gestor.carpeta_de(id_))
    donde = ''
    for f in traceback.extract_tb(e.__traceback__):
        if f.filename.startswith(carpeta):
            donde = f" ({f.filename[len(carpeta):].lstrip('/' + chr(92))}, línea {f.lineno})"
    if isinstance(e, SyntaxError) and e.filename:
        donde = f" ({str(e.filename)[len(carpeta):].lstrip('/' + chr(92))}, línea {e.lineno})"
    return f"{type(e).__name__}: {e}{donde}"


def cargar(info: gestor.Info) -> Cargado:
    """Importa y llama a `registrar`. Lanza lo que lance el complemento."""
    p, id_ = info.paquete, info.id
    descargar(id_)
    c = Cargado(id_, info.nombre, p.huella, p)
    if _buscador not in sys.meta_path:
        sys.meta_path.insert(0, _buscador)
    _buscador.poner(id_, p)
    try:
        mod = importlib.import_module(
            f"{_paquete_py(id_)}.{p.manifiesto['codigo'][:-3]}")
        registrar = getattr(mod, 'registrar', None)
        if not callable(registrar):
            raise api.ErrorComplemento(
                f"{p.manifiesto['codigo']} no define registrar(app)")
        app = api.Aplicacion(id_)
        registrar(app)
        app._abierta = False
        c.registros = list(app._registros)
    except BaseException:
        _buscador.quitar(id_)
        raise
    _cargados[id_] = c
    return c


def cargar_activos() -> list[tuple[str, str]]:
    """Al arrancar (y al activar uno). Nunca lanza: lo que falla se apaga y
    queda en `fallos` con su motivo."""
    if gestor.modo_seguro():
        return []
    nuevos: list[tuple[str, str]] = []
    try:
        caido = gestor.recuperar_de_un_cierre()
        if caido:
            nuevos.append((caido, "el programa se cerró mientras lo cargaba"))
        for info in gestor.activos():
            if not info.paquete.con_codigo:
                continue
            ya = _cargados.get(info.id)
            if ya is not None and ya.huella == info.paquete.huella:
                continue
            try:
                gestor.empezar_carga(info.id)
                cargar(info)
            except (Exception, SystemExit, RecursionError) as e:  # noqa: BLE001
                t = texto_error(e, info.id)
                nuevos.append((info.id, t))
                gestor.desactivar(info.id, t)
            finally:
                # Un KeyboardInterrupt o un cierre de verdad deja el centinela
                # solo si el proceso muere: aquí siempre se quita.
                gestor.terminar_carga()
    except Exception as e:  # noqa: BLE001 — disco lleno, carpeta sin permiso…
        nuevos.append(('', f"{type(e).__name__}: {e}"))
    fallos.extend(nuevos)
    return nuevos
