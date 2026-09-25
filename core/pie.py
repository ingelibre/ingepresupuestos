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
            'pct_real': round(val / cd * 100, 2) if (cd and tipo != 'subtotal') else 0,
        })
    return lineas, acum


def etiqueta(linea: dict, *, mayus: bool = False) -> str:
    """Nombre de la línea con su porcentaje, como lo imprimen los reportes:
    «IVA (19%)». En un `rubro` el % mostrado es el REAL sobre el CD (el monto
    sale del detalle y el `pct` guardado puede no corresponder)."""
    nombre = linea['nombre'].upper() if mayus else linea['nombre']
    if not linea.get('mostrar_pct') or linea['tipo'] == 'subtotal':
        return nombre
    pct = linea['pct'] if linea['tipo'] in TIPOS_PCT else linea.get('pct_real')
    return f"{nombre} ({pct:g}%)" if pct else nombre


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
    se siembra la primera vez. Colombia usa AIU con IVA sobre la utilidad
    (issue #10); el resto, gastos generales + utilidad + impuesto."""
    from core.paises import nombre_rubro_impuesto, pais_actual
    igv = proy['igv_pct'] if proy['igv_pct'] is not None else 18.0
    if pais_actual() == 'CO':
        # AIU ≈ 27 %: Administración 20 · Imprevistos 2 · Utilidad 5 (valores
        # de partida, cada obra los ajusta). El IVA grava SOLO la utilidad.
        return [
            ('GG',   'Administración (A)', 20.0, 1, 0, 'pct_cd',   1),
            ('IMP',  'Imprevistos (I)',     2.0, 1, 1, 'pct_cd',   1),
            ('UTIL', 'Utilidad (U)',        5.0, 1, 2, 'pct_cd',   1),
            ('SUB',  'Sub Total',           0,   1, 3, 'subtotal', 1),
            ('IGV',  f"{nombre_rubro_impuesto(igv)} sobre la utilidad",
                                            igv, 1, 4, 'pct_util', 0),
        ]
    gf = proy['gf_pct'] or 10.0
    util = proy['utilidad_pct'] or 5.0
    return [
        ('GG',   'Gastos Generales',   gf,   1, 0, 'rubro',    1),
        ('UTIL', 'Utilidad',            util, 1, 1, 'pct_cd',   1),
        ('SUB',  'Sub Total',           0,    1, 2, 'subtotal', 1),
        ('SUP',  'Supervisión',         5.0,  0, 3, 'rubro',    0),
        ('ET',   'Expediente Técnico',  3.0,  0, 4, 'rubro',    0),
        ('LQ',   'Liquidación de Obra', 2.0,  0, 5, 'rubro',    0),
        ('IGV',  nombre_rubro_impuesto(igv), igv, 1, 6, 'pct_sub', 1),
    ]
