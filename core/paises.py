# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Perfil de país (issue #9).

La mayoría de los usuarios nuevos está fuera del Perú (Colombia sobre todo) y
chocaban con supuestos peruanos: moneda Soles, autocompletado UBIGEO, «RUC»,
IGV 18 %. El país se propone en el primer arranque (detectado del sistema, el
usuario lo confirma, como Delphin Express al instalar) y se cambia en
Configuración → País. Elegirlo solo fija VALORES POR DEFECTO — moneda,
etiqueta tributaria, impuesto—; cada uno sigue editable por separado.

Claves en `configuracion`:
    pais                    código ISO 3166-1 alfa-2 ('PE', 'CO', …)
    etiqueta_id_tributaria  «RUC», «NIT», «RUT»…
    impuesto_nombre         «IGV», «IVA», «ISV», «ITBMS», «ITBIS»
    impuesto_pct            tasa general, en %
    moneda_defecto          (ya existía) nombre de `config.MONEDAS`

Sin la clave `pais` todo se comporta como Perú: a quien ya usaba el programa
no le cambia nada hasta que elija otro país.
"""
from __future__ import annotations

PAIS_DEFECTO = 'PE'

# iso: nombre, moneda (clave de config.MONEDAS), etiqueta tributaria,
#      impuesto (nombre, % tasa general), centro del mapa (lat, lon) = capital.
# Tasas generales vigentes a sep 2026. Revisar si un usuario avisa de un cambio.
# NO agregar Estados Unidos: muchos Linux vienen en `en_US` y la bienvenida le
# propondría dólares a un usuario peruano que solo pulsa «Guardar».
PAISES: dict[str, dict] = {
    'PE': dict(nombre='Perú',                 moneda='Soles',             id='RUC',  imp=('IGV', 18.0),   centro=(-12.0464, -77.0428)),
    'CO': dict(nombre='Colombia',             moneda='Pesos Colombianos', id='NIT',  imp=('IVA', 19.0),   centro=(4.7110, -74.0721)),
    'EC': dict(nombre='Ecuador',              moneda='Dólares',           id='RUC',  imp=('IVA', 15.0),   centro=(-0.1807, -78.4678)),
    'BO': dict(nombre='Bolivia',              moneda='Bolivianos',        id='NIT',  imp=('IVA', 13.0),   centro=(-16.4897, -68.1193)),
    'CL': dict(nombre='Chile',                moneda='Pesos Chilenos',    id='RUT',  imp=('IVA', 19.0),   centro=(-33.4489, -70.6693)),
    'AR': dict(nombre='Argentina',            moneda='Pesos Argentinos',  id='CUIT', imp=('IVA', 21.0),   centro=(-34.6037, -58.3816)),
    'MX': dict(nombre='México',               moneda='Pesos Mexicanos',   id='RFC',  imp=('IVA', 16.0),   centro=(19.4326, -99.1332)),
    'PY': dict(nombre='Paraguay',             moneda='Guaraníes',         id='RUC',  imp=('IVA', 10.0),   centro=(-25.2637, -57.5759)),
    'UY': dict(nombre='Uruguay',              moneda='Pesos Uruguayos',   id='RUT',  imp=('IVA', 22.0),   centro=(-34.9011, -56.1645)),
    'VE': dict(nombre='Venezuela',            moneda='Bolívares',         id='RIF',  imp=('IVA', 16.0),   centro=(10.4806, -66.9036)),
    'GT': dict(nombre='Guatemala',            moneda='Quetzales',         id='NIT',  imp=('IVA', 12.0),   centro=(14.6349, -90.5069)),
    'HN': dict(nombre='Honduras',             moneda='Lempiras',          id='RTN',  imp=('ISV', 15.0),   centro=(14.0723, -87.1921)),
    'SV': dict(nombre='El Salvador',          moneda='Dólares',           id='NIT',  imp=('IVA', 13.0),   centro=(13.6929, -89.2182)),
    'NI': dict(nombre='Nicaragua',            moneda='Córdobas',          id='RUC',  imp=('IVA', 15.0),   centro=(12.1150, -86.2362)),
    'CR': dict(nombre='Costa Rica',           moneda='Colones',           id='Céd. jurídica', imp=('IVA', 13.0), centro=(9.9281, -84.0907)),
    'PA': dict(nombre='Panamá',               moneda='Dólares',           id='RUC',  imp=('ITBMS', 7.0),  centro=(8.9824, -79.5199)),
    'DO': dict(nombre='República Dominicana', moneda='Pesos Dominicanos', id='RNC',  imp=('ITBIS', 18.0), centro=(18.4861, -69.9312)),
    'ES': dict(nombre='España',               moneda='Euros',             id='NIF',  imp=('IVA', 21.0),   centro=(40.4168, -3.7038)),
}


def _cfg(clave: str, defecto: str = '') -> str:
    try:
        from core.database import get_config
        return get_config(clave, defecto) or defecto
    except Exception:
        return defecto


def pais_configurado() -> str | None:
    """El país que eligió el usuario, o None si todavía no eligió."""
    iso = _cfg('pais')
    return iso if iso in PAISES else None


def pais_actual() -> str:
    return pais_configurado() or PAIS_DEFECTO


def perfil(iso: str | None = None) -> dict:
    return PAISES.get(iso or pais_actual(), PAISES[PAIS_DEFECTO])


def es_peru() -> bool:
    """El autocompletado UBIGEO (INEI) solo tiene sentido en el Perú."""
    return pais_actual() == 'PE'


def detectar_pais(iso_sistema: str | None = None) -> str:
    """País que PROPONE la bienvenida (el usuario lo confirma): el del sistema
    solo si es latinoamericano; si no, Perú. Muchos equipos vienen en español
    de España o en inglés sin que el usuario viva allí —el de Marco está en
    `es_ES`—, y un «Guardar» sin mirar los dejaba en euros. España sigue en
    la lista para elegirla a mano."""
    if iso_sistema is None:
        try:
            from PySide6.QtCore import QLocale
            iso_sistema = QLocale.territoryToCode(QLocale.system().territory())
        except Exception:
            iso_sistema = ''
    iso = (iso_sistema or '').upper()
    return iso if iso in PAISES and iso not in _NO_PROPONER else PAIS_DEFECTO


# En la lista para elegir, pero nunca propuestos por la detección.
_NO_PROPONER = {'ES'}


def etiqueta_tributaria() -> str:
    return _cfg('etiqueta_id_tributaria') or perfil()['id']


def impuesto() -> tuple[str, float]:
    """(nombre, tasa %) del impuesto para proyectos nuevos."""
    p = perfil()
    nombre = _cfg('impuesto_nombre') or p['imp'][0]
    try:
        pct = float(_cfg('impuesto_pct') or p['imp'][1])
    except ValueError:
        pct = p['imp'][1]
    return nombre, pct


def centro_mapa() -> tuple[float, float]:
    return perfil()['centro']


def aplicar_pais(iso: str, *, moneda: str | None = None, etiqueta: str | None = None,
                 imp_nombre: str | None = None, imp_pct: float | None = None) -> None:
    """Guarda el país y sus valores por defecto. Los argumentos permiten al
    usuario corregir cualquiera de ellos; sin ellos se toman del perfil."""
    from core.database import set_config
    p = PAISES[iso]
    set_config('pais', iso)
    set_config('moneda_defecto', moneda or p['moneda'])
    set_config('etiqueta_id_tributaria', etiqueta or p['id'])
    set_config('impuesto_nombre', imp_nombre or p['imp'][0])
    set_config('impuesto_pct', str(p['imp'][1] if imp_pct is None else float(imp_pct)))


def nombre_rubro_impuesto(pct: float | None = None) -> str:
    """«IGV (18%)», «IVA (19%)»… para la línea del pie de presupuesto."""
    nombre, tasa = impuesto()
    tasa = tasa if pct is None else pct
    return f"{nombre} ({tasa:g}%)"
