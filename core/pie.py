# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Pie de presupuesto — el ÚNICO cálculo de sus líneas.

Hasta el 24 sep 2026 este cálculo estaba escrito cinco veces
(`database.calcular_totales`, `ProyectoView._filas_resumen`,
`exporter._calcular_rubros_pie`, `pdf_reports._build_pie_rows` y
`asistente_local`) y ninguna redondeaba: el pie sumaba montos con todos sus
decimales y el total no cuadraba con la suma a mano de lo impreso
(issue #3). Ahora cada línea se redondea a los decimales de montos ANTES de
sumarse — lo que se ve es lo que se suma — y todos leen de aquí.

Tipos de línea (`pie_rubros.tipo`):
    rubro     monto manual, o detalle de `gastos_generales`, o % del CD
    pct_cd    % del costo directo
    pct_sub   % del último subtotal (el IGV peruano)
    pct_util  % de la utilidad (líneas con código 'UTIL'): el IVA colombiano
              del AIU, que grava solo la utilidad (issue #10)
    subtotal  separador: fija la base de los `pct_sub` siguientes
"""
from __future__ import annotations

TIPOS_PCT = ('pct_cd', 'pct_sub', 'pct_util')
CODIGO_IMPUESTO = 'IGV'      # el código no cambia con el país; el nombre sí


def _valor_rubro(conn, proyecto_id, codigo, pct, cd):
    """Monto de una línea tipo `rubro`: manual > detalle > % del CD.
    Devuelve (valor, tiene_detalle)."""
    manual = conn.execute(
        "SELECT precio FROM gastos_generales"
        " WHERE proyecto_id=? AND rubro=? AND tipo='manual'",
        (proyecto_id, codigo)).fetchone()
    if manual is not None:
        return (manual['precio'] or 0), True
    items = conn.execute(
        "SELECT cantidad, pct_participacion, precio FROM gastos_generales"
        " WHERE proyecto_id=? AND rubro=? AND tipo='item'",
        (proyecto_id, codigo)).fetchall()
    if items:
        return sum((i['cantidad'] or 0) * ((i['pct_participacion'] or 100) / 100)
                   * (i['precio'] or 0) for i in items), True
    return cd * pct / 100, False


def calcular_pie(conn, proyecto_id: int, cd: float):
    """Líneas del pie para un costo directo `cd`.

    Devuelve `(lineas, total)`:
      - `lineas` = None si el proyecto nunca configuró su pie (el llamador
        usa el cálculo simple con `gf_pct`/`utilidad_pct`/`igv_pct`); [] si
        lo configuró pero no tiene líneas activas; si no, una lista de dicts
        `{tipo, nombre, codigo, pct, valor, mostrar_pct, has_items, pct_real}`.
      - `total` = CD + todas las líneas, ya redondeadas.
    """
    from core.database import _rn, get_decimales_ppto
    dec = get_decimales_ppto()
    cd = _rn(cd or 0, dec)

    if conn.execute("SELECT 1 FROM pie_rubros WHERE proyecto_id=? LIMIT 1",
                    (proyecto_id,)).fetchone() is None:
        return None, cd
    rubros = conn.execute(
        "SELECT * FROM pie_rubros WHERE proyecto_id=? AND activo=1 ORDER BY orden",
        (proyecto_id,)).fetchall()
    if not rubros:
        return [], cd

    lineas = []
    acum = cd
    last_sub = cd
    utilidad = 0.0
    for r in rubros:
        tipo, codigo = r['tipo'], r['codigo']
        pct = r['pct'] or 0
        mp = r['mostrar_pct'] if r['mostrar_pct'] is not None else 1
        has_items = False
        if tipo == 'subtotal':
            last_sub = acum
            val = acum
        else:
            if tipo == 'pct_sub':
                val = last_sub * pct / 100
            elif tipo == 'pct_cd':
                val = cd * pct / 100
            elif tipo == 'pct_util':
                val = utilidad * pct / 100
            else:                                   # 'rubro' (y lo desconocido)
                val, has_items = _valor_rubro(conn, proyecto_id, codigo, pct, cd)
            val = _rn(val, dec)
            acum = _rn(acum + val, dec)
            if codigo == 'UTIL':
                utilidad += val
        lineas.append({
            'tipo': tipo, 'nombre': r['nombre'], 'codigo': codigo, 'pct': pct,
            'valor': val, 'mostrar_pct': mp, 'has_items': has_items,
            'destacado': bool(tipo == 'subtotal' and r['destacado']),
            'pct_real': round(val / cd * 100, 2) if (cd and tipo != 'subtotal') else 0,
        })
    return lineas, acum


def nombre_total(proy, defecto: str = 'PRESUPUESTO TOTAL') -> str:
    """Nombre del total final: el que escribió el usuario («Costo de
    inversión», issue #34) o el de siempre. Un nombre propio sigue las
    mayúsculas del defecto. `proy` es la fila/dict del proyecto o su id."""
    if isinstance(proy, int):
        from core.database import get_db
        conn = get_db()
        proy = conn.execute("SELECT total_nombre FROM proyectos WHERE id=?",
                            (proy,)).fetchone()
        conn.close()
    try:
        propio = (proy['total_nombre'] or '').strip()
    except (IndexError, KeyError, TypeError):
        propio = ''
    if not propio:
        return defecto
    return propio.upper() if defecto.isupper() else propio


def lineas_simples(proyecto, cd: float):
    """Pie de un proyecto que nunca abrió su pestaña «Pie»: gastos generales y
    utilidad sobre el CD, e impuesto sobre el subtotal, con los porcentajes
    del proyecto. Mismo retorno que `calcular_pie` (nunca None)."""
    from core.database import _rn, get_decimales_ppto
    from core.paises import impuesto
    dec = get_decimales_ppto()
    cd = _rn(cd or 0, dec)

    def _pct(campo):
        return (proyecto[campo] if campo in proyecto.keys() else 0) or 0

    def _linea(tipo, codigo, nombre, pct, valor):
        return {'tipo': tipo, 'nombre': nombre, 'codigo': codigo, 'pct': pct,
                'valor': valor, 'mostrar_pct': 1, 'has_items': False,
                'destacado': False,
                'pct_real': round(valor / cd * 100, 2)
                if (cd and tipo != 'subtotal') else 0}

    gf = _rn(cd * _pct('gf_pct') / 100, dec)
    util = _rn(cd * _pct('utilidad_pct') / 100, dec)
    sub = _rn(cd + gf + util, dec)
    igv = _rn(sub * _pct('igv_pct') / 100, dec)
    lineas = [
        _linea('pct_cd', 'GG', 'Gastos Generales', _pct('gf_pct'), gf),
        _linea('pct_cd', 'UTIL', 'Utilidad', _pct('utilidad_pct'), util),
        _linea('subtotal', 'SUB', 'Sub Total', 0, sub),
        _linea('pct_sub', CODIGO_IMPUESTO, impuesto()[0], _pct('igv_pct'), igv),
    ]
    return [l for l in lineas if l['valor'] or l['tipo'] == 'subtotal'], _rn(sub + igv, dec)


def pie_efectivo(conn, proyecto_id: int, cd: float):
    """El pie que se IMPRIME: el configurado o, si el proyecto nunca lo
    configuró, el simple. Con `calcular_pie` a secas ese proyecto imprimía el
    costo directo como PRESUPUESTO TOTAL mientras el KPI y el monto en letras
    (`calcular_totales`) llevaban gastos, utilidad e impuesto."""
    lineas, total = calcular_pie(conn, proyecto_id, cd)
    if lineas is None:
        proy = conn.execute("SELECT * FROM proyectos WHERE id=?",
                            (proyecto_id,)).fetchone()
        if proy is not None:
            return lineas_simples(proy, cd)
    return lineas, total


def etiqueta(linea: dict, *, mayus: bool = False) -> str:
    """Nombre de la línea con su porcentaje, como lo imprimen los reportes:
    «IVA (19%)». En un `rubro` el % mostrado es el REAL sobre el CD (el monto
    sale del detalle y el `pct` guardado puede no corresponder)."""
    nombre = linea['nombre'].upper() if mayus else linea['nombre']
    if not linea.get('mostrar_pct') or linea['tipo'] == 'subtotal':
        return nombre
    pct = linea['pct'] if linea['tipo'] in TIPOS_PCT else linea.get('pct_real')
    from utils.formatting import con_separadores
    return f"{nombre} ({con_separadores(f'{pct:g}')}%)" if pct else nombre


def es_impuesto(linea: dict) -> bool:
    """IGV/IVA/ISV/ITBMS/ITBIS. Por código (el pie por defecto usa 'IGV' en
    todos los países) o, en pies importados, por el nombre."""
    import re
    if linea.get('codigo') == CODIGO_IMPUESTO:
        return True
    return bool(re.search(r'\b(IGV|IVA|ISV|ITBMS|ITBIS)\b', (linea.get('nombre') or '').upper()))


# ── Pie por defecto de un proyecto nuevo, según el país ──────────────────────

def lineas_por_defecto(proy) -> list[tuple]:
    """(codigo, nombre, pct, activo, orden, tipo, mostrar_pct) del pie que
    se siembra la primera vez. Las líneas son las del país (`core.paises`):
    Colombia usa AIU con IVA sobre la utilidad, Brasil un solo BDI, el resto
    gastos generales + utilidad + impuesto; un complemento puede traer otras."""
    from core import paises
    igv = proy['igv_pct'] if proy['igv_pct'] is not None else 18.0
    datos = {'gastos_generales': proy['gf_pct'] or 10.0,
             'utilidad': proy['utilidad_pct'] or 5.0, 'impuesto': igv}
    nombre, rubro = paises.impuesto()[0], paises.nombre_rubro_impuesto(igv)
    return [(l['codigo'],
             l['nombre'].replace('{impuesto_pct}', rubro)
                        .replace('{impuesto}', nombre),
             datos[l['pct']] if isinstance(l['pct'], str) else l['pct'],
             int(l['activo']), orden, l['tipo'], int(l['mostrar_pct']))
            for orden, l in enumerate(paises.pie_de(paises.perfil()))]
