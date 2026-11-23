# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Lo que el núcleo consulta: los datos de los complementos ACTIVOS.

Sin complementos activos todo devuelve vacío y el programa usa lo de fábrica.
Cada función es barata (la lista de activos está en memoria) y nunca lanza.
"""
from __future__ import annotations

from core.complementos import gestor

_cache: dict = {}


def invalidar() -> None:
    _cache.clear()


def _de(clave: str) -> list:
    if clave not in _cache:
        _cache[clave] = [x for i in gestor.activos()
                         for x in i.paquete.manifiesto[clave]]
    return _cache[clave]


def perfil_de(x: dict) -> dict:
    """País del manifiesto → la forma de `core.paises.PAISES`."""
    p = {k: x[k] for k in ('nombre', 'moneda', 'id', 'imp')}
    for k in ('centro', 'indirectos', 'pie'):
        if k in x:
            p[k] = x[k]
    return p


def paises() -> dict[str, dict]:
    return {x['iso']: perfil_de(x) for x in _de('paises')}


def titulos() -> list[str]:
    return list(dict.fromkeys(_de('titulos')))


def unidades() -> list[str]:
    return list(dict.fromkeys(_de('unidades')))


def importadores_excel() -> list[dict]:
    """El último activado manda: va primero."""
    from core.paises import pais_actual
    lista = [x for x in reversed(_de('importadores_excel'))]
    if not any(x['pais'] for x in lista):
        return lista
    iso = pais_actual()
    return [x for x in lista if x['pais'] in (None, iso)]


def vocabulario(idioma: str) -> dict[str, str]:
    """{texto original en español: reemplazo} para ese idioma y el país."""
    grupos = [v for v in _de('vocabulario') if v['idioma'] == idioma]
    if not grupos:
        return {}
    from core.paises import pais_actual
    iso, out = pais_actual(), {}
    for v in grupos:
        if v['pais'] in (None, iso):
            out.update(v['textos'])
    return out
