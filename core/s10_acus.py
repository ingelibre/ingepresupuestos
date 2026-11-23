# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Análisis de precios unitarios de S10 exportados a Excel (#51).

El reporte impreso de S10 repite, por cada partida::

    Partida      01.01   CARTEL DE OBRA …
    Rendimiento  und/DIA  MO. 1.0000  EQ. 1.0000   Costo unitario directo por : und  1,250.45
    Código  Descripción Recurso   Unidad  Cuadrilla  Cantidad  Precio S/.  Parcial S/.
            Mano de Obra
    0101010003  OPERARIO           hh      1.0000    8.0000     23.00      184.00
                                                                           184.00

Según la versión y el exportador cambian las columnas (Crystal Reports las
corre de sitio entre la cabecera y los datos), falta el código o faltan los
precios, y la palabra «Partida» puede no estar. Por eso aquí NO hay números
de columna fijos: cada fila se entiende por lo que contiene.

Lo que el archivo no dice no se inventa: los insumos sin precio quedan en 0
y se avisa, y los análisis que no cuadran con su propio costo unitario, los
que no tienen partida y las partidas que se quedan sin análisis se listan.
"""
from __future__ import annotations

import re
import unicodedata

from utils.formatting import parse_num_opt
from utils.i18n import tr

_SECCIONES = {
    'MANO DE OBRA': 'MO', 'MATERIALES': 'MAT', 'MATERIAL': 'MAT',
    'EQUIPO': 'EQ', 'EQUIPOS': 'EQ', 'EQUIPOS Y HERRAMIENTAS': 'EQ',
    'EQUIPO Y HERRAMIENTAS': 'EQ', 'HERRAMIENTAS': 'EQ',
    'SUBCONTRATO': 'SC', 'SUBCONTRATOS': 'SC', 'SUB CONTRATOS': 'SC',
    'SUB-CONTRATOS': 'SC',
    'SUBPARTIDA': 'SC', 'SUBPARTIDAS': 'SC', 'SUB PARTIDAS': 'SC',
    'SUB-PARTIDAS': 'SC',
}
_RE_ITEM = re.compile(r'\d{1,4}(?:\.\d{1,4})*\.?')
_RE_CU = re.compile(r'COSTO\s+UNITARIO(?:\s+DIRECTO)?\s+POR\s*:?\s*(\S+)(?:\s+(?:S/\.?\s*)?(\d[\d.,]*))?')
_RE_REND = re.compile(r'([^\s/:]+)\s*/\s*DIA\.?\s*(?:MO\.?)?\s*:?\s*(\d[\d.,]*)?')
_RE_EQ = re.compile(r'\bEQ\.?\s*:?\s*(\d[\d.,]*)')
_RE_MO = re.compile(r'\bMO\.?\s*:?\s*(\d[\d.,]*)')


def _norm(s) -> str:
    """MAYÚSCULAS sin tildes ni espacios repetidos."""
    s = unicodedata.normalize('NFD', str(s if s is not None else ''))
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return ' '.join(s.upper().split())


def leer_filas(filepath) -> list[list]:
    """Todas las hojas de un .xls o .xlsx, seguidas. La extensión no manda:
    S10 guarda a veces un .xlsx con nombre .xls y al revés."""
    import openpyxl
    errores = []
    try:
        import xlrd
        wb = xlrd.open_workbook(filepath)
        return [s.row_values(i) for s in wb.sheets() for i in range(s.nrows)]
    except Exception as e:                            # noqa: BLE001
        errores.append(e)
    try:
        with open(filepath, 'rb') as fh:
            wb = openpyxl.load_workbook(fh, data_only=True, read_only=True)
            return [list(r) for ws in wb.worksheets for r in ws.iter_rows(values_only=True)]
    except Exception as e:                            # noqa: BLE001
        errores.append(e)
    raise ValueError(f"No se pudo leer «{filepath}» como Excel: {errores[-1]}")


def _es_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(v):
    """Número de una celda (nativo o texto «1,250.45») o None."""
    if _es_num(v):
        return float(v)
    t = str(v).strip()
    if not re.fullmatch(r'-?(?:S/\.?\s*)?\d[\d.,]*', t):
        return None
    return parse_num_opt(t)


def _item_txt(v) -> str:
    """Código de ítem de una celda; Excel pudo haberlo vuelto número."""
    if _es_num(v):
        return str(int(v)) if float(v).is_integer() else repr(float(v))
    return str(v).strip()


def clave_item(item) -> tuple:
    """«01.01» y «1.01» son el mismo ítem."""
    partes = [p for p in str(item or '').strip().strip('.').split('.')]
    return tuple(int(p) if p.isdigit() else p for p in partes)


def leer_s10_acus(filepath) -> list[dict]:
    """Análisis del archivo, en orden::

        {'item', 'descripcion', 'unidad', 'rendimiento', 'rendimiento_eq',
         'cu' (float | None), 'con_precios' (bool),
         'items': [{codigo, descripcion, tipo, unidad, cuadrilla, cantidad,
                    precio, parcial (float | None)}]}
    """
    return _leer(leer_filas(filepath))


def _leer(filas) -> list[dict]:
    acus: list[dict] = []
    actual = None          # análisis abierto
    candidata = None       # (item, descripcion, rendimiento) que espera su «Costo unitario»
    tipo = None
    cols: dict = {}        # columna de cada cabecera de la tabla de insumos
    con_precios = True
    ult = None             # última línea, por si la descripción sigue abajo

    for fila in filas:
        celdas = [(j, v) for j, v in enumerate(fila or [])
                  if v is not None and str(v).strip() != '']
        if not celdas:
            ult = None
            continue
        textos = [(j, str(v).strip()) for j, v in celdas if _num(v) is None]
        nums = [(j, _num(v)) for j, v in celdas if _num(v) is not None]
        u0 = _norm(celdas[0][1])
        linea = _norm(' '.join(str(v) for _, v in celdas))

        # ── Cabecera de partida ──────────────────────────────────────────
        if u0 == 'PARTIDA' or re.match(r'PARTIDA\s*[: ]', u0):
            resto = str(celdas[0][1]).strip()[7:].lstrip(' :').strip()
            partes = ([resto] if resto else []) + [v for _, v in celdas[1:]]
            item, desc = '', ''
            if partes:
                item = _item_txt(partes[0])
                m = re.match(r'(\(?[\w.\-]+\)?)\s+(\S.*)$', item)
                if m and re.match(r'\(?\d', m.group(1)):
                    item, desc = m.group(1), m.group(2)
                desc = ' '.join([desc] + [
                    str(p).strip() for p in partes[1:] if not _es_num(p)
                    and not re.search(r'REND|/\s*DIA', _norm(p))]).strip()
            candidata = (item.strip(), desc, {})
            actual, tipo, ult = None, None, None
        # ── Rendimiento y costo unitario ─────────────────────────────────
        m_cu = _RE_CU.search(linea)
        if m_cu and candidata is None:
            # Otro análisis sin partida reconocible (auxiliares al final del
            # reporte): sus insumos no son de la partida anterior.
            actual, tipo, ult = None, None, None
            continue
        if m_cu and actual is None:
            actual = {'item': candidata[0], 'descripcion': candidata[1],
                      'unidad': _unidad_cu(celdas) or m_cu.group(1).lower(),
                      'rendimiento': 0.0, 'rendimiento_eq': None, 'cu': None,
                      'con_precios': con_precios, 'items': [], **candidata[2]}
            acus.append(actual)
            candidata, tipo, ult = None, None, None
            if m_cu.group(2):
                actual['cu'] = parse_num_opt(m_cu.group(2))
        if 'RENDIMIENTO' in linea or re.search(r'/\s*DIA\b', linea):
            m = _RE_REND.search(linea)
            m_mo, m_eq = _RE_MO.search(linea), _RE_EQ.search(linea)
            m_r = re.search(r'RENDIMIENTO\s*:?\s*(\d[\d.,]*)\s+\S+\s*/\s*DIA', linea)
            r = ((m_mo and m_mo.group(1)) or (m_r and m_r.group(1))
                 or (m and m.group(2)) or (m_eq and m_eq.group(1)))
            destino = actual
            if destino is None and candidata is not None:
                destino = candidata[2]    # la fila del CU viene después
            if destino is not None and r and not destino.get('rendimiento'):
                destino['rendimiento'] = parse_num_opt(r) or 0.0
                if m_eq:
                    destino['rendimiento_eq'] = parse_num_opt(m_eq.group(1))
            if m_cu or actual is not None:
                continue
        if m_cu:
            continue
        if u0 == 'PARTIDA' or re.match(r'PARTIDA\s*[: ]', u0):
            continue

        # ── Cabecera de la tabla (se repite en cada página) ──────────────
        nt = {j: _norm(t) for j, t in textos}
        if (any('DESCRIPCI' in t for t in nt.values())
                and any(t.startswith('CANTIDAD') for t in nt.values())):
            cols = {}
            for j, t in nt.items():
                for clave, pref in (('desc', 'DESCRIPCI'), ('und', 'UNID'),
                                    ('cuad', 'CUADRILLA'), ('cant', 'CANTIDAD'),
                                    ('precio', 'PRECIO'), ('parcial', 'PARCIAL'),
                                    ('cod', 'CODIGO')):
                    if t.startswith(pref) and clave not in cols:
                        cols[clave] = j
            con_precios = 'precio' in cols or 'parcial' in cols
            if actual is not None:
                actual['con_precios'] = con_precios
            ult = None
            continue

        # ── Sección ──────────────────────────────────────────────────────
        if len(textos) == 1 and len(nums) <= 1 and _norm(textos[0][1]) in _SECCIONES:
            tipo = _SECCIONES[_norm(textos[0][1])]
            ult = None
            continue

        # ── Línea de insumo ──────────────────────────────────────────────
        if actual is not None and tipo and nums:
            ln = _linea(celdas, cols, con_precios)
            if ln:
                ln['tipo'] = tipo
                actual['items'].append(ln)
                ult = ln
                continue
            if not textos:
                ult = None               # subtotal de la sección
                continue

        # ── Descripción que sigue en la fila de abajo ────────────────────
        if (ult is not None and not nums and len(textos) == 1
                and cols.get('desc') == textos[0][0]):
            ult['descripcion'] += ' ' + textos[0][1]
            continue

        # ── Posible partida sin la palabra «Partida» ─────────────────────
        if len(celdas) >= 2 and textos and not (len(textos) == len(celdas) and len(textos) > 2):
            it = _item_txt(celdas[0][1])
            if (_RE_ITEM.fullmatch(it) and len(nums) <= 1
                    and celdas[0][0] < textos[-1][0] and len(celdas) == 2):
                candidata = (it, str(celdas[1][1]).strip(), {})
                actual, tipo = None, None
        ult = None

    # Sin una sola línea leída no es este formato (p. ej. un ACU de PowerCost).
    return acus if any(a['items'] for a in acus) else []


def _unidad_cu(celdas) -> str:
    """Unidad tal como está escrita tras «Costo unitario … por :»."""
    txt = ' '.join(str(v).strip() for _, v in celdas)
    m = re.search(r'[Cc][Oo][Ss][Tt][Oo]\s+\w+(?:\s+\w+)?\s+[Pp][Oo][Rr]\s*:?\s*(\S+)', txt)
    return m.group(1) if m else ''


def _linea(celdas, cols, con_precios):
    """Fila de insumo → dict, o None si no lo es (subtotal, pie de página…).

    Primero van los textos (código, descripción, unidad) y al final los
    números. Con la cabecera completa, 4 números son cuadrilla-cantidad-
    precio-parcial y 3 son cantidad-precio-parcial; con 1 o 2 manda la
    columna más cercana de la cabecera."""
    # La descripción es el primer texto con letras que no sea un código.
    i_desc = None
    for i, (_, v) in enumerate(celdas):
        t = str(v).strip()
        if _num(v) is None and re.search(r'[^\W\d_]', t) and t != '-':
            if i == 0 and len(celdas) > 1 and re.fullmatch(r'[A-Z]{0,3}[\d\-. ]{4,}', t):
                continue                     # código alfanumérico
            i_desc = i
            break
    if i_desc is None:
        return None
    codigo = ''
    if i_desc > 0:
        v = celdas[i_desc - 1][1]
        codigo = str(int(v)) if _es_num(v) and float(v).is_integer() else str(v).strip()
    resto = celdas[i_desc + 1:]
    unidad = ''
    if resto and _num(resto[0][1]) is None and str(resto[0][1]).strip() != '-':
        unidad = str(resto[0][1]).strip()
        resto = resto[1:]
    nums = [(j, _num(v)) for j, v in resto if _num(v) is not None]
    if not nums or any(_num(v) is None and str(v).strip() not in ('-', '')
                       for _, v in resto):
        return None
    claves = ['cuad', 'cant'] + (['precio', 'parcial'] if con_precios else [])
    if len(nums) == len(claves):
        val = dict(zip(claves, (n for _, n in nums)))
    elif len(nums) == len(claves) - 1:
        val = dict(zip(claves[1:], (n for _, n in nums)))
    else:
        val, libres = {}, {k: cols[k] for k in claves if k in cols}
        for j, n in nums:
            if not libres:
                return None
            k = min(libres, key=lambda c: abs(libres[c] - j))
            val[k] = n
            libres.pop(k)
    if not unidad and 'cant' not in val:
        return None
    return {'codigo': codigo, 'descripcion': str(celdas[i_desc][1]).strip(),
            'unidad': unidad, 'cuadrilla': val.get('cuad') or 0.0,
            'cantidad': val.get('cant') or 0.0, 'precio': val.get('precio') or 0.0,
            'parcial': val.get('parcial')}


# ── Reconciliación ───────────────────────────────────────────────────────────

def _tolerancia(acu) -> float:
    """Cada parcial impreso trae medio céntimo de redondeo."""
    return max(0.02, 0.005 * len(acu['items']) + 0.005)


def suma_parciales(acu) -> float | None:
    """Suma de los parciales que trae el archivo; None si no los trae."""
    pars = [i['parcial'] for i in acu['items']]
    return None if not pars or any(p is None for p in pars) else round(sum(pars), 4)


def costo_calculado(acu) -> float:
    """PU que dará el programa con esos insumos (misma regla que el ACU)."""
    from core.database import _pu_desde_items
    return _pu_desde_items([dict(i) for i in acu['items']])


def no_cuadran(acus) -> list[dict]:
    """Análisis cuyo costo no coincide con el del propio archivo."""
    out = []
    for a in acus:
        if a['cu'] is None:
            continue
        tol = _tolerancia(a)
        s = suma_parciales(a)
        c = costo_calculado(a)
        if s is None or abs(s - a['cu']) > tol or abs(c - a['cu']) > tol:
            out.append({'item': a['item'], 'descripcion': a['descripcion'],
                        'cu': a['cu'], 'suma': s, 'calculado': c})
    return out


def emparejar(partidas, acus) -> tuple[dict, list, list]:
    """Cuelga cada análisis de su partida. Devuelve ``(acus_data,
    partidas_sin_acu, acus_sin_partida)``; `acus_data` va a
    `guardar_importacion` y las partidas emparejadas reciben `item_origen`
    único, porque con varios sub-presupuestos el ítem «01.01» se repite.

    Orden: ítem + descripción; ítem si es único en ambos lados y no
    contradice la unidad; descripción + unidad si es única."""
    hojas = [p for p in partidas if not p.get('es_titulo')]

    def _desc(x):
        return _norm(x.get('descripcion'))

    def _und(x):
        return _norm(x.get('unidad'))

    def _indice(lista, clave):
        d: dict = {}
        for x in lista:
            d.setdefault(clave(x), []).append(x)
        return d

    pend_p, pend_a = list(hojas), list(acus)
    pares = []

    def _pasada(clave, solo_unicos, acepta=lambda p, a: True):
        ip, ia = _indice(pend_p, clave), _indice(pend_a, clave)
        for k, la in ia.items():
            lp = ip.get(k) or []
            if not k or not lp or (solo_unicos and (len(la) > 1 or len(lp) > 1)):
                continue
            for p, a in zip(list(lp), list(la)):
                if acepta(p, a):
                    pares.append((p, a))
                    pend_p[:] = [x for x in pend_p if x is not p]
                    pend_a[:] = [x for x in pend_a if x is not a]

    _pasada(lambda x: (clave_item(x['item']), _desc(x)), False)
    _pasada(lambda x: clave_item(x['item']), True,
            lambda p, a: not _und(p) or not _und(a) or _und(p) == _und(a))
    _pasada(lambda x: (_desc(x), _und(x)) if _desc(x) else None, True)

    datos = {}
    for n, (p, a) in enumerate(pares):
        clave = f"s10#{n}"
        p['item_origen'] = clave
        datos[clave] = a
    return datos, pend_p, pend_a


# ── Guardado ─────────────────────────────────────────────────────────────────

def _indices_s10(acus) -> dict[str, str]:
    """{código S10: índice unificado}. Solo los códigos clásicos de 10 dígitos
    lo llevan (tipo + IU + correlativo: 01·47·010002). Los de S10 2005 usan
    otro catálogo (01·01·010003): ahí los dígitos NO son el índice y se deja
    vacío, que se completa con el diccionario de índices."""
    cods = {str(i['codigo']).zfill(10) for a in acus for i in a['items']
            if str(i['codigo']).isdigit()}
    if not any(c.startswith('0147') for c in cods):
        return {}
    return {c: c[2:4] for c in cods if c[:2] in ('01', '02', '03', '04')}


def guardar_presupuesto_s10(info, partidas, acus, recursos=None, *,
                            eligio_acus: bool = True) -> tuple[int, str]:
    """Guarda presupuesto + análisis S10 como proyecto: ``(pid, resumen)``.
    El resumen dice siempre qué pasó con los ACU."""
    from core import importer
    from core.bc3_importer import _asignar_codigos
    from core.database import get_db
    datos, sin_acu, sin_partida = emparejar(partidas, acus)
    items = [i for a in datos.values() for i in a['items']]
    iu_s10 = _indices_s10(acus)
    iu_de = {id(i): iu_s10.get(str(i['codigo']).zfill(10), '') for i in items}
    conn = get_db()
    max_rec = conn.execute("SELECT COALESCE(MAX(id),0) FROM recursos").fetchone()[0]
    conn.close()
    _asignar_codigos(list(recursos or []), items)
    pid = importer.guardar_importacion(info, partidas, datos, recursos)
    if items or recursos:
        conn = get_db()
        conn.executemany("UPDATE recursos SET indice_inei='' WHERE id>? AND codigo=?",
                         [(max_rec, i['codigo']) for i in items + list(recursos or [])])
        conn.executemany("UPDATE recursos SET indice_inei=? WHERE id>? AND codigo=?",
                         [(iu_de[id(i)], max_rec, i['codigo']) for i in items if iu_de[id(i)]])
        conn.commit()
        conn.close()
    n_part = sum(1 for p in partidas if not p.get('es_titulo'))
    partes = [f"{n_part} partidas", f"{len(datos)} ACUs"]
    if recursos:
        partes.append(f"{len(recursos)} recursos")
    return pid, "  ·  ".join(partes) + avisos_s10(
        partidas, acus, datos, sin_acu, sin_partida, eligio_acus)


def _lista(titulo, lineas, tope=200) -> str:
    if not lineas:
        return ''
    extra = ("\n   " + tr("…y {n} más.").format(n=len(lineas) - tope)
             if len(lineas) > tope else '')
    return f"\n\n⚠ {titulo} ({len(lineas)}):\n   " + "\n   ".join(lineas[:tope]) + extra


def avisos_s10(partidas, acus, datos, sin_acu, sin_partida, eligio_acus=True) -> str:
    if not eligio_acus:
        return "\n\n⚠ " + tr(
            "No se importaron los análisis (ACU): no elegiste el Excel de análisis. "
            "Las partidas quedan con su precio pero con el ACU vacío.")
    if not acus:
        return "\n\n⚠ " + tr(
            "No se importó ningún análisis (ACU): el Excel de análisis no tiene el formato "
            "de «Análisis de precios unitarios» de S10. Las partidas quedan con su precio "
            "pero con el ACU vacío.")
    out = ''
    out += _lista(tr("Análisis que no cuadran con su costo unitario"), [
        tr("{item}: archivo {cu}, suma de parciales {suma}, calculado {calc}").format(
            item=f"{m['item']} {m['descripcion'][:40]}", cu=f"{m['cu']:,.2f}",
            suma=f"{m['suma']:,.2f}" if m['suma'] is not None else '—',
            calc=f"{m['calculado']:,.2f}")
        for m in no_cuadran(acus)])
    dif = []
    for p in partidas:
        a = datos.get(p.get('item_origen'))
        if a and a['cu'] is not None and abs((p.get('precio_unitario') or 0) - a['cu']) > 0.011:
            dif.append(tr("{item}: presupuesto {pu}, análisis {cu}").format(
                item=f"{p['item']} {p['descripcion'][:40]}",
                pu=f"{p.get('precio_unitario') or 0:,.2f}", cu=f"{a['cu']:,.2f}"))
    out += _lista(tr("Precio del presupuesto distinto al del análisis"), dif)
    out += _lista(tr("Partidas sin análisis"),
                  [f"{p['item']} {p['descripcion'][:50]}" for p in sin_acu])
    out += _lista(tr("Análisis sin partida en el presupuesto (no se importaron)"),
                  [f"{a['item']} {a['descripcion'][:50]}" for a in sin_partida])
    n0 = sum(1 for a in datos.values() for i in a['items']
             if not i['precio'] and not (i['unidad'] or '').startswith('%'))
    if n0:
        out += "\n\n⚠ " + tr("{n} línea(s) de insumo sin precio en el archivo: "
                             "quedan en 0.").format(n=n0)
    out += _lista(tr("Rendimiento de equipo distinto al de mano de obra (se usa el de MO)"), [
        f"{a['item']}: MO {a['rendimiento']:g}, EQ {a['rendimiento_eq']:g}"
        for a in datos.values() if a.get('rendimiento_eq') is not None
        and abs(a['rendimiento_eq'] - a['rendimiento']) > 1e-9])
    return out
