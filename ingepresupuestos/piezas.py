# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Piezas que comparten varios complementos (API 2).

    from ingepresupuestos import api, piezas

Solo cuentas y bloques de reporte: no leen ni escriben nada.
"""
from __future__ import annotations

import math

from ingepresupuestos import api


# ── Ajustes guardados: pueden venir de un .db ajeno ──────────────────────────

def numero(ajustes, clave, defecto=0.0, minimo=0.0, maximo=100.0) -> float:
    v = ajustes.get(clave)
    if isinstance(v, bool) or not isinstance(v, (int, float)) \
            or not math.isfinite(v) or not minimo <= v <= maximo:
        return defecto
    return float(v)


def texto(ajustes, clave, defecto='', maximo=1000) -> str:
    v = ajustes.get(clave)
    return v.strip()[:maximo] if isinstance(v, str) and v.strip() else defecto


def pct(p, v) -> str:
    """«7,4 %», con los separadores de la moneda del proyecto."""
    t = p.moneda.numero(v, 4)
    if p.moneda.decimal and p.moneda.decimal in t:
        t = t.rstrip('0').rstrip(p.moneda.decimal)
    return f"{t} %"


# ── Cuentas ──────────────────────────────────────────────────────────────────

def cuadrar(valores: dict, total: float, dec: int) -> dict:
    """Los valores redondeados; lo que falte para `total` va en el mayor."""
    out = {k: api.redondear(v, dec) for k, v in valores.items()}
    falta = api.redondear(total - sum(out.values()), dec)
    if falta and out:
        k = max(out, key=lambda x: abs(valores[x]))
        out[k] = api.redondear(out[k] + falta, dec)
    return out


def sumar_titulos(p, importes: dict) -> dict:
    """{id de título: suma de lo que cuelga de él}. `importes`: {id: importe}."""
    out = {}
    hojas = p.hojas()
    for x in p.partidas:
        if x.es_titulo:
            out[x.id] = api.redondear(sum(
                importes[h.id] for h in hojas
                if h.sub_presupuesto == x.sub_presupuesto
                and h.item.startswith(x.item + '.')), p.decimales)
    return out


def capitulos(p, importes: dict) -> list[tuple[str, str, float]]:
    """[(ítem, descripción, importe)] del primer nivel; las partidas sueltas
    cuentan como un capítulo propio. La suma es la de todas las partidas."""
    titulos = sumar_titulos(p, importes)
    dentro, out = set(), []
    for x in p.partidas:
        if (x.sub_presupuesto, x.item) in dentro or any(
                x.sub_presupuesto == s and x.item.startswith(i + '.')
                for s, i in dentro):
            continue
        if x.es_titulo:
            dentro.add((x.sub_presupuesto, x.item))
            out.append((x.item, x.descripcion, titulos[x.id]))
        else:
            out.append((x.item, x.descripcion, importes[x.id]))
    return out


def recorrer(p):
    """(partida, rótulo): rótulo es el sub-presupuesto al empezar cada uno, si
    hay varios; si no, ''."""
    varios = len({x.sub_presupuesto for x in p.partidas}) > 1
    antes = None
    for x in p.partidas:
        nuevo = varios and x.sub_presupuesto != antes
        antes = x.sub_presupuesto
        yield x, (x.sub_presupuesto or '—') if nuevo else ''


# ── Bloques de reporte ───────────────────────────────────────────────────────

def mediciones(p, precios: dict, importes: dict, rotulos) -> api.Tabla:
    """Capítulos con su total y, en cada partida, su texto y sus mediciones.
    `rotulos`: los diez de las columnas."""
    d, dm = p.decimales, p.decimales_metrado
    anchos = (8, 31, 6, 7, 7, 7, 8, 8, 8, 10)
    decs = (2, 2, dm, dm, dm, dm, dm, dm, d, d)
    titulos = sumar_titulos(p, importes)
    filas = []
    for x, sub in recorrer(p):
        if sub:
            filas.append(api.Fila([sub], 'titulo'))
        if x.es_titulo:
            filas.append(api.Fila([x.item, x.descripcion, *[None] * 7, titulos[x.id]],
                                  'subtotal'))
            continue
        filas.append([x.item, f"{x.unidad}  {x.descripcion}".strip()])
        if x.especificacion:
            filas.append([None, x.especificacion])
        for m in x.mediciones:
            filas.append([None, m.descripcion, m.unidades, m.largo, m.ancho, m.alto,
                          m.parcial])
        filas.append([*[None] * 7, x.metrado, precios[x.id], importes[x.id]])
    return api.Tabla([api.Columna(r, a, 'derecha' if i > 1 else 'izquierda', dc)
                      for i, (r, a, dc) in enumerate(zip(rotulos, anchos, decs))], filas)


def bloques_de(partida, nombres) -> list[tuple[str, list]]:
    """[(nombre, insumos)] en el orden de `nombres` [(tipo, nombre)]; lo de otro
    tipo va en el último. Sin los vacíos."""
    tipos = {t for t, _n in nombres}
    out = []
    for k, (tipo, nombre) in enumerate(nombres):
        ins = [i for i in partida.acu if i.tipo == tipo
               or (k == len(nombres) - 1 and i.tipo not in tipos)]
        if ins:
            out.append((nombre, ins))
    return out


def calcular_impuesto_materiales(p, partida, tasa):
    """(materiales por unidad, impuesto por unidad, materiales, impuesto)"""
    mat = api.redondear(sum(i.parcial for i in partida.acu_abierto
                            if i.tipo == "MAT"), p.decimales)
    imp = api.redondear(mat * tasa / 100, p.decimales)
    return mat, imp, p.importe(partida, mat), p.importe(partida, imp)


def impuesto_materiales(p, nombre, tasa) -> api.Documento:
    """El reporte del impuesto sobre materiales, por partida y en total."""
    partidas = p.hojas()
    if not partidas:
        raise api.ErrorComplemento(t("El presupuesto no tiene partidas."))
    d = p.decimales
    etiqueta = f"{nombre} ({pct(p, tasa)})"
    filas, mats, imps = [], 0.0, 0.0
    for x in partidas:
        mu, iu, m, i = calcular_impuesto_materiales(p, x, tasa)
        mats, imps = mats + m, imps + i
        filas.append([x.item, x.descripcion, x.unidad, x.metrado, x.precio_unitario,
                      mu, iu, api.redondear(x.precio_unitario + iu, d), i])
    mats, imps = api.redondear(mats, d), api.redondear(imps, d)
    filas.append(api.Fila([None, t("TOTAL"), None, None, None, None, None, None, imps],
                          "subtotal"))

    def m(v):
        return p.moneda.formato(v, d)
    bloques = [
        api.Parrafo(t("Reporte informativo: no altera los precios ni el total del "
                      "presupuesto.")),
        api.Tabla([api.Columna(t("Ítem"), 8), api.Columna(t("Descripción"), 28),
                   api.Columna(t("Und."), 6, "centro"),
                   api.Columna(t("Metrado"), 9, "derecha", p.decimales_metrado),
                   api.Columna(t("P. unitario"), 10, "derecha", d),
                   api.Columna(t("Materiales por und."), 10, "derecha", d),
                   api.Columna(t("Impuesto por und."), 9, "derecha", d),
                   api.Columna(t("P. unitario con impuesto"), 10, "derecha", d),
                   api.Columna(t("Impuesto total"), 10, "derecha", d)], filas),
        api.Campos([(t("Materiales"), m(mats)), (etiqueta, m(imps)),
                    (t("Costo directo"), m(p.costo_directo)),
                    (t("Costo directo con el impuesto"),
                     m(api.redondear(p.costo_directo + imps, d)))])]
    ya = [l.etiqueta or l.nombre for l in p.pie if l.es_impuesto and l.valor]
    if ya:
        bloques.append(api.Parrafo(
            t("Atención: el pie del presupuesto ya cobra {que}. Sumar además este "
              "impuesto lo cobraría dos veces sobre los materiales.").format(
                  que=", ".join(ya)), negrita=True))
    return api.Documento(t("Impuesto sobre materiales"), bloques, horizontal=True)


_TEXTOS = {'en': {'Impuesto sobre materiales': 'Tax on materials',
        'El presupuesto no tiene partidas.': 'The budget has no items.',
        'TOTAL': 'TOTAL',
        'Reporte informativo: no altera los precios ni el total del presupuesto.': 'For '
                                                                                   'information '
                                                                                   'only: '
                                                                                   'it '
                                                                                   'does '
                                                                                   'not '
                                                                                   'change '
                                                                                   'prices '
                                                                                   'or '
                                                                                   'the '
                                                                                   'budget '
                                                                                   'total.',
        'Ítem': 'Item',
        'Descripción': 'Description',
        'Und.': 'Unit',
        'Metrado': 'Quantity',
        'P. unitario': 'Unit price',
        'Materiales por und.': 'Materials per unit',
        'Impuesto por und.': 'Tax per unit',
        'P. unitario con impuesto': 'Unit price with tax',
        'Impuesto total': 'Total tax',
        'Materiales': 'Materials',
        'Costo directo': 'Direct cost',
        'Costo directo con el impuesto': 'Direct cost with the tax',
        'Atención: el pie del presupuesto ya cobra {que}. Sumar además este impuesto lo cobraría dos veces sobre los materiales.': 'Note: '
                                                                                                                                   'the '
                                                                                                                                   'budget '
                                                                                                                                   'footer '
                                                                                                                                   'already '
                                                                                                                                   'charges '
                                                                                                                                   '{que}. '
                                                                                                                                   'Adding '
                                                                                                                                   'this '
                                                                                                                                   'tax '
                                                                                                                                   'too '
                                                                                                                                   'would '
                                                                                                                                   'charge '
                                                                                                                                   'materials '
                                                                                                                                   'twice.'},
 'pt_BR': {'Impuesto sobre materiales': 'Imposto sobre materiais',
           'El presupuesto no tiene partidas.': 'O orçamento não tem itens.',
           'TOTAL': 'TOTAL',
           'Reporte informativo: no altera los precios ni el total del presupuesto.': 'Relatório '
                                                                                      'informativo: '
                                                                                      'não '
                                                                                      'altera '
                                                                                      'os '
                                                                                      'preços '
                                                                                      'nem '
                                                                                      'o '
                                                                                      'total '
                                                                                      'do '
                                                                                      'orçamento.',
           'Ítem': 'Item',
           'Descripción': 'Descrição',
           'Und.': 'Un.',
           'Metrado': 'Quantidade',
           'P. unitario': 'P. unitário',
           'Materiales por und.': 'Materiais por un.',
           'Impuesto por und.': 'Imposto por un.',
           'P. unitario con impuesto': 'P. unitário com imposto',
           'Impuesto total': 'Imposto total',
           'Materiales': 'Materiais',
           'Costo directo': 'Custo direto',
           'Costo directo con el impuesto': 'Custo direto com o imposto',
           'Atención: el pie del presupuesto ya cobra {que}. Sumar además este impuesto lo cobraría dos veces sobre los materiales.': 'Atenção: '
                                                                                                                                      'o '
                                                                                                                                      'rodapé '
                                                                                                                                      'do '
                                                                                                                                      'orçamento '
                                                                                                                                      'já '
                                                                                                                                      'cobra '
                                                                                                                                      '{que}. '
                                                                                                                                      'Somar '
                                                                                                                                      'também '
                                                                                                                                      'este '
                                                                                                                                      'imposto '
                                                                                                                                      'o '
                                                                                                                                      'cobraria '
                                                                                                                                      'duas '
                                                                                                                                      'vezes '
                                                                                                                                      'sobre '
                                                                                                                                      'os '
                                                                                                                                      'materiais.'}}


def t(s):
    return _TEXTOS.get(api.idioma(), {}).get(s, s)
