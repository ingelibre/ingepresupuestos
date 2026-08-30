# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""core.formula_polinomica — cálculo y persistencia de la fórmula polinómica.

La fórmula polinómica expresa el reajuste de precios de obra según los
índices INEI:

    K = J·(Jr/Jo) + M·(Mr/Mo) + E·(Er/Eo)

donde J, M, E son los coeficientes (suma 1.000) y r/o son los índices del
período de reajuste / oferta. Cada monomio se guarda en
``formula_monomios`` con: orden · símbolo · descripción · indice_inei ·
coeficiente.

Funciones:
    - ``cargar_monomios(pid)``  → lista de dicts persistidos
    - ``calcular_desde_acu(pid)`` → coeficientes auto-derivados desde el ACU
    - ``guardar_monomios(pid, monomios)`` → reemplaza el set persistido

Espejo de las rutas Flask ``/api/proyecto/<pid>/formula/calcular`` y
``/api/proyecto/<pid>/formula/guardar``.
"""
from __future__ import annotations

import unicodedata

from core.config import INEI_DEFAULT
from core.database import get_db, get_insumos_para_partidas


# Reglas del D.S. 011-79-VC que acotan la fórmula.
MIN_INCIDENCIA = 0.05     # art. 3: cada monomio pesa al menos 5%
MAX_MONOMIOS = 8          # art. 3: y no puede haber más de ocho
DECIMALES_K = 3           # art. 2: coeficientes «con aproximación al milésimo»

# Art. 2: «el índice de precio considerado en cada monomio podrá corresponder
# al índice del elemento más representativo o al promedio ponderado de los
# índices HASTA DE TRES (3) ELEMENTOS COMO MÁXIMO». Un monomio puede agrupar la
# incidencia de más insumos —si no, se perdería costo directo— pero el índice
# que lo representa sale de sus tres componentes de mayor peso.
MAX_IU_POR_INDICE = 3

# Índice del monomio de gastos generales y utilidad. El D.S. lo trata siempre
# como UN solo monomio y no fija su índice; la práctica usa el índice general
# de precios al consumidor.
IU_GASTOS_GENERALES = '39'
SIMBOLO_GU = 'GU'

# Letra con la que se nombra el monomio según el tipo que lo domina. J de
# jornal, M de materiales, E de equipo: la convención de las fórmulas peruanas.
SIMBOLO_POR_TIPO = {'MO': 'J', 'MAT': 'M', 'EQ': 'E', 'SC': 'S'}


def cargar_monomios(proyecto_id: int) -> list[dict]:
    """Lista los monomios persistidos para el proyecto, ordenados."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, orden, simbolo, descripcion, indice_inei, coeficiente "
        "FROM formula_monomios WHERE proyecto_id=? "
        "ORDER BY orden, id",
        (proyecto_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def calcular_desde_acu(proyecto_id: int) -> dict:
    """Auto-deriva los 3 monomios MO/MAT/EQ desde los totales del ACU.

    SUPERADA por `calcular_por_iu`, que agrupa por índice unificado y es la que
    usa la vista desde la 3.0.4. Se conserva porque su criterio —repartir el CD
    entre tres monomios por tipo— sigue siendo el que aplica `calcular_por_iu`
    cuando ningún índice llega al 5%, y porque describe qué hacía la app en las
    fórmulas guardadas antes de esta versión.

    Retorna dict con::

        {
          'ok':       bool,
          'msg':      str,                   # solo si ok=False
          'monomios': [...],                 # 3 monomios base si ok=True
          'totales':  {'MO','MAT','EQ','cd'} # totales calculados
        }
    """
    conn = get_db()

    # 1) Insumos normales (excluir overhead con unidad %)
    rows = conn.execute(
        """SELECT r.tipo, SUM(ai.cantidad * p.metrado * COALESCE(ai.precio, r.precio, 0))
                 AS parcial_total
           FROM acu_items ai
           JOIN recursos r ON r.id = ai.recurso_id
           JOIN partidas p ON p.id = ai.partida_id
           WHERE p.proyecto_id=? AND p.es_titulo=0
             AND SUBSTR(r.unidad,1,1) != '%'
           GROUP BY r.tipo""",
        (proyecto_id,)
    ).fetchall()

    totales = {'MO': 0.0, 'MAT': 0.0, 'EQ': 0.0}
    for r in rows:
        tipo = r['tipo'] if r['tipo'] in totales else 'MAT'
        totales[tipo] += r['parcial_total'] or 0

    # 2) Herramientas (% MO) — se contabilizan dentro de EQ
    pct_rows = conn.execute(
        """SELECT p.metrado,
                  SUM(CASE WHEN SUBSTR(r.unidad,1,1)!='%' AND r.tipo='MO'
                           THEN ai.cantidad * COALESCE(ai.precio, r.precio, 0)
                           ELSE 0 END) AS mo_cu,
                  SUM(CASE WHEN LOWER(r.unidad)='%mo'
                           THEN ai.cantidad ELSE 0 END) AS pct_mo
           FROM acu_items ai
           JOIN recursos r ON r.id = ai.recurso_id
           JOIN partidas p ON p.id = ai.partida_id
           WHERE p.proyecto_id=? AND p.es_titulo=0
           GROUP BY p.id""",
        (proyecto_id,)
    ).fetchall()
    for row in pct_rows:
        metrado = row['metrado'] or 0
        mo_cu   = row['mo_cu']  or 0
        totales['EQ'] += (row['pct_mo'] or 0) / 100 * mo_cu * metrado

    cd = totales['MO'] + totales['MAT'] + totales['EQ']
    conn.close()

    if cd == 0:
        return {
            'ok': False,
            'msg': "El proyecto no tiene costos en el ACU.",
            'totales': {**totales, 'cd': 0},
        }

    mo_k  = round(totales['MO']  / cd, 4)
    mat_k = round(totales['MAT'] / cd, 4)
    eq_k  = round(totales['EQ']  / cd, 4)
    # Ajustar al cuarto decimal para que sumen 1.000 exactos
    diferencia = round(1.0 - mo_k - mat_k - eq_k, 4)
    mat_k = round(mat_k + diferencia, 4)

    monomios_base = [
        {'orden': 1, 'simbolo': 'J', 'descripcion': 'Mano de Obra',
         'indice_inei': '47', 'coeficiente': mo_k},
        {'orden': 2, 'simbolo': 'M', 'descripcion': 'Materiales de Construcción',
         'indice_inei': '39', 'coeficiente': mat_k},
        {'orden': 3, 'simbolo': 'E', 'descripcion': 'Maquinaria y Equipo',
         'indice_inei': '48', 'coeficiente': eq_k},
    ]
    return {
        'ok':       True,
        'monomios': monomios_base,
        'totales':  {**totales, 'cd': cd},
    }


def incidencias_por_iu(proyecto_id: int,
                       serie: str | None = None) -> dict:
    """Reparte el costo directo del proyecto entre los índices unificados.

    Es lo que faltaba para armar una fórmula polinómica de verdad. Hasta ahora
    `calcular_desde_acu` producía SIEMPRE tres monomios fijos (J/M/E con los
    índices 47, 39 y 48) a partir de los totales de MO/MAT/EQ: la columna
    `recursos.indice_inei` existía, estaba poblada al 89% y hasta tenía índice
    en la BD, pero la fórmula no la miraba nunca. Por eso no había componentes
    que mostrar — no se calculaban.

    Los montos salen de `get_insumos_para_partidas`, que es el mismo camino que
    arma el reporte de insumos: reparte el parcial de cada partida entre sus
    recursos en proporción y cuadra el redondeo al final, de modo que la suma
    de las incidencias ES el costo directo del presupuesto, sin deriva. El
    overhead con unidad «porcentaje» ya viene resuelto sobre su base.

    Un insumo sin índice asignado cae en el de su tipo (`INEI_DEFAULT`), que es
    la convención que la app ya usa al dar de alta un recurso; se contabiliza
    aparte para poder avisar cuánto costo está apoyado en ese supuesto.

    Retorna::

        {'ok': bool, 'msg': str, 'cd': float,
         'ius': [{'codigo','nombre','tipo','monto','incidencia','n_insumos',
                  'asignado'}],
         'monto_sin_indice': float}
    """
    # Los códigos de índice de los insumos pertenecen a una SERIE: el 22 es
    # «Cemento Portland Tipo II» en la base 1992 y no existe en la de 2025. La
    # que manda es la del presupuesto base, así que los nombres se buscan ahí.
    from core.indices_inei import asegurar_seed, serie_de
    if serie is None:
        per = cargar_periodos(proyecto_id)
        serie = serie_de(per['oferta_anio'], per['oferta_mes'])

    conn = get_db()
    try:
        partida_ids = [r['id'] for r in conn.execute(
            "SELECT id FROM partidas WHERE proyecto_id=? AND es_titulo=0",
            (proyecto_id,)
        ).fetchall()]
        insumos = get_insumos_para_partidas(conn, partida_ids)
        indices = {r['id']: (r['indice_inei'] or '').strip()
                   for r in conn.execute("SELECT id, indice_inei FROM recursos")}
        # La fórmula puede ser el primer camino que toque los índices, y sin
        # esto el catálogo de la serie estaría vacío y todo saldría como
        # «Índice 80» en vez de su nombre.
        asegurar_seed(conn)
        nombres = dict(conn.execute(
            "SELECT codigo, nombre FROM indices_inei WHERE serie=?",
            (serie,)).fetchall())
    finally:
        conn.close()

    acum: dict[str, dict] = {}
    sin_indice = 0.0
    for ins in insumos:
        monto = ins.get('parcial_total') or 0
        if not monto:
            continue
        tipo = ins.get('tipo') or 'MAT'
        cod = indices.get(ins['recurso_id'], '')
        asignado = bool(cod) and cod != '00'
        if not asignado:
            cod = INEI_DEFAULT.get(tipo, '39')
            sin_indice += monto
        a = acum.setdefault(cod, {
            'codigo': cod, 'monto': 0.0, 'n_insumos': 0,
            'por_tipo': {}, 'monto_asignado': 0.0,
        })
        a['monto'] += monto
        a['n_insumos'] += 1
        a['por_tipo'][tipo] = a['por_tipo'].get(tipo, 0.0) + monto
        if asignado:
            a['monto_asignado'] += monto

    cd = sum(a['monto'] for a in acum.values())
    if cd <= 0:
        return {'ok': False, 'msg': "El proyecto no tiene costos en el ACU.",
                'cd': 0.0, 'base': 0.0, 'ius': [], 'monto_sin_indice': 0.0}

    # La base de las incidencias es el SUBTOTAL del presupuesto —costo directo
    # + gastos generales + utilidad—, no el costo directo. Es lo que dice el
    # art. 2 con su `e·(GU/GUo)`: si se reparte solo el CD, ese 15-20% del
    # contrato se queda sin reajustar.
    from core.database import calcular_totales
    try:
        _, tot = calcular_totales(proyecto_id)
        gg_util = float(tot.get('gf') or 0) + float(tot.get('utilidad') or 0)
        base = float(tot.get('subtotal') or 0) or (cd + gg_util)
    except Exception:
        gg_util, base = 0.0, cd
    if gg_util > 0:
        acum[IU_GASTOS_GENERALES + '@GU'] = {
            'codigo': IU_GASTOS_GENERALES, 'monto': gg_util, 'n_insumos': 0,
            'por_tipo': {'GU': gg_util}, 'monto_asignado': gg_util,
        }

    ius = []
    for a in acum.values():
        # El tipo del índice es el que aporta más plata dentro de él: decide
        # con qué monomio se agrupa cuando su incidencia no llega al mínimo.
        tipo = max(a['por_tipo'].items(), key=lambda kv: kv[1])[0]
        nombre = ("Gastos generales y utilidad" if tipo == 'GU'
                  else nombres.get(a['codigo'], f"Índice {a['codigo']}"))
        ius.append({
            'codigo': a['codigo'],
            'nombre': nombre,
            'tipo': tipo,
            'monto': a['monto'],
            'incidencia': a['monto'] / base,
            'n_insumos': a['n_insumos'],
            'asignado': a['monto_asignado'] >= a['monto'] - 1e-9,
        })
    ius.sort(key=lambda x: -x['monto'])
    return {'ok': True, 'msg': '', 'cd': cd, 'base': base, 'ius': ius,
            'serie': serie, 'gg_utilidad': gg_util,
            'monto_sin_indice': sin_indice}


def _simbolos_unicos(monomios: list[dict]) -> None:
    """Asigna la letra de cada monomio, sin repetir. Modifica in situ.

    Las fórmulas peruanas nombran el monomio por lo que representa: J el
    jornal, E el equipo, y para los materiales la inicial del índice que lo
    encabeza — C de cemento, A de acero, M de madera, T de tubería. Numerar
    M2, M3, M4 sería correcto y ilegible.
    """
    usados: set[str] = {SIMBOLO_GU}
    for m in monomios:
        tipo = m.get('tipo') or 'MAT'
        if tipo in ('MO', 'EQ'):
            base = SIMBOLO_POR_TIPO[tipo]
        else:
            comp = (m.get('componentes') or [{}])[0]
            # Sin tilde: el símbolo va en la fórmula impresa y en los reportes,
            # y «Índice general» daba una «Í» que no es letra de fórmula.
            plano = unicodedata.normalize('NFKD', comp.get('nombre') or '')
            inicial = ''.join(ch for ch in plano if 'A' <= ch.upper() <= 'Z')[:1].upper()
            base = inicial if inicial else SIMBOLO_POR_TIPO.get(tipo, 'M')
        s = base
        n = 2
        while s in usados:
            s = f"{base}{n}"
            n += 1
        usados.add(s)
        m['simbolo'] = s


def calcular_por_iu(proyecto_id: int, max_monomios: int = MAX_MONOMIOS,
                    min_incidencia: float = MIN_INCIDENCIA,
                    serie: str | None = None) -> dict:
    """Arma los monomios agrupando los índices unificados por su incidencia.

    Criterio, que es el estándar del D.S. 011-79-VC:

    * cada índice cuya incidencia llega al mínimo (5%) es un monomio propio;
    * los que no llegan se acumulan en el monomio afín —el de mayor peso de su
      mismo tipo— hasta que el conjunto sí cumple, porque un monomio por debajo
      del 5% no es válido y descartarlos perdería costo directo;
    * si sobran monomios sobre el máximo (8), los más chicos se van al afín;
    * si NINGÚN índice llega al mínimo (presupuesto muy fragmentado), degrada a
      los tres monomios por tipo, que es lo que la app hacía siempre.

    El monomio conserva como `indice_inei` el índice que más pesa dentro de él;
    la composición completa queda en `componentes` para poder verla, editarla y
    —al calcular K— promediar los índices por su peso.
    """
    inc = incidencias_por_iu(proyecto_id, serie)
    if not inc['ok']:
        return {'ok': False, 'msg': inc['msg'], 'monomios': [],
                'cd': 0.0, 'base': 0.0, 'ius': []}

    base = inc['base']
    ius = list(inc['ius'])

    # Gastos generales y utilidad van SIEMPRE en un monomio propio (art. 2), y
    # ni ese ni el de mano de obra están sujetos al tope de tres índices.
    gu = next((i for i in ius if i['tipo'] == 'GU'), None)
    if gu:
        ius.remove(gu)

    grandes = [i for i in ius if i['incidencia'] >= min_incidencia]
    chicos = [i for i in ius if i['incidencia'] < min_incidencia]

    if not grandes:
        # Nada llega al 5%: agrupar por tipo, la conducta histórica.
        por_tipo: dict[str, list] = {}
        for i in ius:
            por_tipo.setdefault(i['tipo'], []).append(i)
        grandes = []
        for tipo, lista in por_tipo.items():
            lista.sort(key=lambda x: -x['monto'])
            grandes.append({**lista[0], 'tipo': tipo})
            chicos = [c for c in chicos if c is not lista[0]]
        grandes.sort(key=lambda x: -x['monto'])

    # El tope de monomios deja sitio al de gastos generales y utilidad.
    tope = max_monomios - (1 if gu else 0)
    if len(grandes) > tope:
        chicos = chicos + grandes[tope:]
        grandes = grandes[:tope]

    monomios = [{
        'tipo': g['tipo'],
        'descripcion': g['nombre'],
        'indice_inei': g['codigo'],
        'componentes': [dict(g)],
        'monto': g['monto'],
    } for g in grandes]

    # El índice general de precios al consumidor es el cajón de sastre de las
    # fórmulas peruanas: lo que no tiene índice propio termina ahí.
    IU_GENERAL = INEI_DEFAULT.get('MAT', '39')

    def _destino(iu):
        """El monomio afín al que se suma un índice que no llega al mínimo.

        Por orden: el de más peso de su MISMO tipo que todavía tenga hueco
        (menos de tres índices); si no hay, el que lleva el índice general; y
        recién entonces el mayor. Sin el paso del medio, un equipo del 2% se
        fundía en el monomio de mano de obra solo por ser el más grande — que
        no es afín ni de lejos.
        """
        def con_hueco(cands):
            libres = [m for m in cands
                      if len(m['componentes']) < MAX_IU_POR_INDICE]
            return libres or cands

        mismos = [m for m in monomios if m['tipo'] == iu['tipo']]
        if mismos:
            return max(con_hueco(mismos), key=lambda m: m['monto'])
        generales = [m for m in monomios
                     if any(c['codigo'] == IU_GENERAL for c in m['componentes'])]
        if generales:
            return max(con_hueco(generales), key=lambda m: m['monto'])
        return max(con_hueco(monomios), key=lambda m: m['monto'])

    for c in sorted(chicos, key=lambda x: -x['monto']):
        # Si todavía cabe un monomio más y el índice llega solo al mínimo,
        # dejarlo aparte antes que engordar otro: menos índices por monomio.
        if (len(monomios) < tope and c['incidencia'] >= min_incidencia):
            monomios.append({'tipo': c['tipo'], 'descripcion': c['nombre'],
                             'indice_inei': c['codigo'],
                             'componentes': [dict(c)], 'monto': c['monto']})
            continue
        d = _destino(c)
        d['componentes'].append(dict(c))
        d['monto'] += c['monto']

    # El índice que representa al monomio y su descripción salen del componente
    # de mayor peso; si hay más de uno, se dice que es agrupado.
    for m in monomios:
        m['componentes'].sort(key=lambda x: -x['monto'])
        principal = m['componentes'][0]
        m['indice_inei'] = principal['codigo']
        m['descripcion'] = (
            principal['nombre'] if len(m['componentes']) == 1
            else f"{principal['nombre']} y {len(m['componentes']) - 1} más"
        )

    monomios.sort(key=lambda m: -m['monto'])
    _simbolos_unicos(monomios)

    # Gastos generales y utilidad, al final y con su símbolo propio.
    if gu:
        monomios.append({
            'tipo': 'GU', 'simbolo': SIMBOLO_GU,
            'descripcion': 'Gastos generales y utilidad',
            'indice_inei': IU_GASTOS_GENERALES,
            'componentes': [dict(gu)], 'monto': gu['monto'],
        })

    recalcular_coeficientes(monomios, base)

    return {'ok': True, 'msg': '', 'monomios': monomios, 'cd': inc['cd'],
            'base': base, 'ius': inc['ius'], 'serie': inc.get('serie'),
            'gg_utilidad': inc.get('gg_utilidad', 0.0),
            'monto_sin_indice': inc['monto_sin_indice']}


def recalcular_coeficientes(monomios: list[dict], cd: float) -> None:
    """Recalcula el coeficiente de cada monomio desde sus componentes.

    Modifica la lista in situ: renumera el `orden`, recalcula el monto y el
    coeficiente de cada monomio como la parte del costo directo que aportan sus
    índices, y cuadra la suma a 1.000.

    Vive en el núcleo y no en la vista porque la usan las dos: el auto-cálculo
    al armar la fórmula y el editor cuando el usuario mueve un índice de un
    monomio a otro. Escribirla dos veces es cómo empezaron la cuadrilla y la
    base del overhead.
    """
    if cd <= 0:
        return
    for i, m in enumerate(monomios):
        m['orden'] = i
        comps = m.get('componentes') or []
        if comps:
            m['monto'] = sum(float(c.get('monto') or 0) for c in comps)
        m['coeficiente'] = round(float(m.get('monto') or 0) / cd,
                                 DECIMALES_K)
    _ajustar_a_uno(monomios)


def _ajustar_a_uno(monomios: list[dict]) -> None:
    """Corrige el último decimal para que los coeficientes sumen 1.000 exactos.

    El sobrante va al monomio más grande: es donde menos se nota y es lo que ya
    hacía `calcular_desde_acu` (que se lo daba a materiales).
    """
    if not monomios:
        return
    total = round(sum(m['coeficiente'] for m in monomios), DECIMALES_K)
    dif = round(1.0 - total, DECIMALES_K)
    if dif:
        mayor = max(monomios, key=lambda m: m['coeficiente'])
        mayor['coeficiente'] = round(mayor['coeficiente'] + dif, DECIMALES_K)


def cargar_componentes(proyecto_id: int,
                       serie: str | None = None) -> dict[int, list[dict]]:
    """Composición guardada de cada monomio: {orden: [{codigo, nombre, monto}]}.

    Los monomios de proyectos anteriores a esta versión no tienen composición
    guardada; para ellos devuelve un dict vacío y la vista muestra el monomio
    como lo que era: un solo índice escrito a mano.

    El nombre del índice se busca en la SERIE que corresponde al presupuesto
    base. Sin ese filtro el join devolvía una fila por serie —el mismo código
    existe en las dos— y cada componente salía duplicado, repartiendo su peso
    a la mitad en el promedio ponderado de K.
    """
    from core.indices_inei import serie_de
    if serie is None:
        per = cargar_periodos(proyecto_id)
        serie = serie_de(per['oferta_anio'], per['oferta_mes'])
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT c.orden, c.indice_inei, c.monto,
                      COALESCE(i.nombre, '') AS nombre
                 FROM formula_monomio_iu c
                 LEFT JOIN indices_inei i
                        ON i.codigo = c.indice_inei AND i.serie = ?
                WHERE c.proyecto_id=?
                ORDER BY c.orden, c.monto DESC""",
            (serie, proyecto_id)
        ).fetchall()
    finally:
        conn.close()
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(r['orden'], []).append({
            'codigo': r['indice_inei'],
            'nombre': r['nombre'] or f"Índice {r['indice_inei']}",
            'monto': r['monto'] or 0.0,
        })
    return out


def guardar_monomios(proyecto_id: int, monomios: list[dict]) -> None:
    """Reemplaza los monomios del proyecto. ``monomios`` es lista de dicts
    con claves: simbolo, descripcion, indice_inei, coeficiente."""
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM formula_monomios WHERE proyecto_id=?", (proyecto_id,)
        )
        conn.execute(
            "DELETE FROM formula_monomio_iu WHERE proyecto_id=?", (proyecto_id,)
        )
        for i, m in enumerate(monomios):
            conn.execute(
                "INSERT INTO formula_monomios "
                "(proyecto_id, orden, simbolo, descripcion, indice_inei, coeficiente) "
                "VALUES (?,?,?,?,?,?)",
                (proyecto_id, i,
                 (m.get('simbolo') or '').strip(),
                 (m.get('descripcion') or '').strip(),
                 (m.get('indice_inei') or '').strip(),
                 float(m.get('coeficiente') or 0))
            )
            # La composición se guarda enlazada por `orden`, no por id: esta
            # función borra y reinserta los monomios enteros, así que los ids
            # cambian en cada guardado y el orden es lo único estable.
            for c in (m.get('componentes') or []):
                cod = str(c.get('codigo') or '').strip()
                if not cod:
                    continue
                conn.execute(
                    "INSERT INTO formula_monomio_iu "
                    "(proyecto_id, orden, indice_inei, monto) VALUES (?,?,?,?)",
                    (proyecto_id, i, cod, float(c.get('monto') or 0))
                )
        conn.commit()
    finally:
        conn.close()


# ─── REAJUSTE K (con valores INEI) ───────────────────────────────────────────

def cargar_periodos(proyecto_id: int) -> dict:
    """Lee los períodos (oferta/reajuste) y área INEI guardados para el
    proyecto. Si no hay registro, retorna defaults inteligentes:
        - oferta: derivado de proyectos.costo_al si se puede parsear, si no
          año actual / enero
        - reajuste: año/mes actual
        - área: '01' (Lima Metropolitana)
    """
    from datetime import date
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT oferta_anio, oferta_mes, reajuste_anio, reajuste_mes, area_inei "
            "FROM formula_periodos WHERE proyecto_id=?",
            (proyecto_id,)
        ).fetchone()
        proy = conn.execute(
            "SELECT costo_al FROM proyectos WHERE id=?", (proyecto_id,)
        ).fetchone()
    finally:
        conn.close()

    hoy = date.today()
    if row:
        return {
            'oferta_anio':   row['oferta_anio']   or hoy.year,
            'oferta_mes':    row['oferta_mes']    or 1,
            'reajuste_anio': row['reajuste_anio'] or hoy.year,
            'reajuste_mes':  row['reajuste_mes']  or hoy.month,
            'area_inei':     row['area_inei']     or '01',
        }

    # Defaults: parsear costo_al para oferta, hoy para reajuste
    oferta_anio = hoy.year
    oferta_mes = 1
    if proy and proy['costo_al']:
        try:
            from views.calendario_view import _parsear_costo_al
            d = _parsear_costo_al(proy['costo_al'])
            if d:
                oferta_anio, oferta_mes = d.year, d.month
        except Exception:
            pass
    return {
        'oferta_anio':   oferta_anio,
        'oferta_mes':    oferta_mes,
        'reajuste_anio': hoy.year,
        'reajuste_mes':  hoy.month,
        'area_inei':     '01',
    }


def guardar_periodos(proyecto_id: int, oferta_anio: int, oferta_mes: int,
                     reajuste_anio: int, reajuste_mes: int,
                     area_inei: str = '01') -> None:
    """Persiste (upsert) los períodos de reajuste del proyecto."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO formula_periodos "
            "(proyecto_id, oferta_anio, oferta_mes, reajuste_anio, reajuste_mes, area_inei) "
            "VALUES (?,?,?,?,?,?)",
            (proyecto_id, int(oferta_anio), int(oferta_mes),
             int(reajuste_anio), int(reajuste_mes), str(area_inei))
        )
        conn.commit()
    finally:
        conn.close()


def _indice_ponderado(comps, obtener_valor, oa, om, ra, rm, area):
    """Índice de un monomio agrupado: promedio de sus índices por su peso.

    El peso de cada componente es el monto con que entró al monomio. Los
    componentes sin valor cargado para el período se excluyen y los pesos se
    renormalizan sobre los que sí lo tienen —descartar el monomio entero por un
    componente del 1% sería peor—, pero se devuelve cuántos faltaron para que
    la vista lo diga.

    Devuelve (valor_oferta, valor_reajuste, n_sin_dato, detalle_componentes).
    """
    # Art. 2: el índice del monomio es el del elemento más representativo o el
    # promedio ponderado de HASTA TRES. El monomio puede agrupar la incidencia
    # de más índices —si no, se perdería costo directo— pero solo los tres de
    # mayor peso forman su índice.
    comps = sorted(comps, key=lambda c: -float(c.get('monto') or 0))
    representativos = comps[:MAX_IU_POR_INDICE]
    acompanantes = len(comps) - len(representativos)

    utiles = []
    sin_dato = 0
    for c in representativos:
        cod = str(c.get('codigo') or '').strip().zfill(2)[:2]
        vo = obtener_valor(cod, oa, om, area) if cod else None
        vr = obtener_valor(cod, ra, rm, area) if cod else None
        if vo and vr and vo > 0:
            utiles.append((c, cod, float(vo), float(vr)))
        else:
            sin_dato += 1
    total = sum(float(c.get('monto') or 0) for c, _, _, _ in utiles)
    if not utiles or total <= 0:
        return None, None, sin_dato, []
    vo_p = vr_p = 0.0
    det = []
    for c, cod, vo, vr in utiles:
        peso = float(c.get('monto') or 0) / total
        vo_p += peso * vo
        vr_p += peso * vr
        det.append({'codigo': cod, 'nombre': c.get('nombre') or '',
                    'peso': peso, 'valor_o': vo, 'valor_r': vr})
    det.sort(key=lambda x: -x['peso'])
    for d in det:
        d['acompanantes'] = acompanantes
    return vo_p, vr_p, sin_dato, det


def calcular_reajuste_k(proyecto_id: int,
                        oferta_anio: int | None = None,
                        oferta_mes: int | None = None,
                        reajuste_anio: int | None = None,
                        reajuste_mes: int | None = None,
                        area_inei: str | None = None) -> dict:
    """Calcula el coeficiente K de reajuste con los valores INEI cargados.

    Fórmula:  K = Σ k_i · (I_r / I_o)  donde I_r es el valor del índice en el
    período de reajuste y I_o en el período de oferta.

    Si algún parámetro es None, usa el guardado en ``formula_periodos`` o el
    default de ``cargar_periodos``.

    Retorna::

        {
            'ok': bool,
            'k_total': float,
            'oferta':    {'anio': int, 'mes': int},
            'reajuste':  {'anio': int, 'mes': int},
            'area':      str,
            'detalle':   [{
                'simbolo': str, 'indice_inei': str, 'descripcion': str,
                'coeficiente': float,
                'valor_o': float|None, 'valor_r': float|None,
                'ratio':   float|None,
                'aporte':  float|None,    # k × ratio
                'falta_dato': bool,
            }, ...],
            'monomios_sin_datos': int,
        }
    """
    from core.indices_inei import obtener_valor

    per = cargar_periodos(proyecto_id)
    oa = oferta_anio   or per['oferta_anio']
    om = oferta_mes    or per['oferta_mes']
    ra = reajuste_anio or per['reajuste_anio']
    rm = reajuste_mes  or per['reajuste_mes']
    area = area_inei   or per['area_inei']

    # Las dos bases del INEI no se pueden mezclar. La RJ 016-2026-INEI fijó
    # «Diciembre 2025 = 100» y con ella 30 códigos cambiaron de significado, así
    # que dividir un índice de la serie nueva entre uno de la vieja da un número
    # sin sentido. Cuando el reajuste cruza el cambio de base hace falta el
    # factor de empalme oficial: mejor decirlo que devolver una cifra falsa.
    from core.indices_inei import serie_de, serie_nombre
    s_oferta, s_reajuste = serie_de(oa, om), serie_de(ra, rm)
    if s_oferta != s_reajuste:
        return {
            'ok': False,
            'msg': (f"El presupuesto base ({om:02d}/{oa}) está en la "
                    f"{serie_nombre(s_oferta)} y el reajuste ({rm:02d}/{ra}) en "
                    f"la {serie_nombre(s_reajuste)}. El INEI cambió la base en "
                    f"diciembre de 2025 y los índices de una serie no se "
                    f"dividen entre los de la otra: hace falta el factor de "
                    f"empalme oficial."),
            'k_total': 0.0,
            'oferta': {'anio': oa, 'mes': om},
            'reajuste': {'anio': ra, 'mes': rm},
            'area': area, 'detalle': [], 'monomios_sin_datos': 0,
            'series': (s_oferta, s_reajuste),
        }

    monomios = cargar_monomios(proyecto_id)
    componentes = cargar_componentes(proyecto_id)
    detalle = []
    k_total = 0.0
    sin_datos = 0
    for m in monomios:
        cod = (m.get('indice_inei') or '').strip().zfill(2)[:2]
        k = float(m.get('coeficiente') or 0)
        comps = componentes.get(m.get('orden'), [])

        if len(comps) > 1:
            # Monomio agrupado: su índice es el promedio de los que lo forman,
            # ponderado por el monto con que cada uno entró. Usar solo el
            # principal ignoraría el resto del monomio, que es justo lo que el
            # usuario no podía ni ver.
            vo, vr, sin_dato_comp, det_comp = _indice_ponderado(
                comps, obtener_valor, oa, om, ra, rm, area
            )
        else:
            vo = obtener_valor(cod, oa, om, area) if cod else None
            vr = obtener_valor(cod, ra, rm, area) if cod else None
            sin_dato_comp = 0
            det_comp = []

        ratio = (vr / vo) if (vo and vr and vo > 0) else None
        aporte = (k * ratio) if ratio is not None else None
        falta = (ratio is None)
        if not falta:
            k_total += aporte
        else:
            sin_datos += 1
        detalle.append({
            'simbolo':     m.get('simbolo'),
            'indice_inei': cod,
            'descripcion': m.get('descripcion') or '',
            'coeficiente': k,
            'valor_o':     vo,
            'valor_r':     vr,
            'ratio':       ratio,
            'aporte':      aporte,
            'falta_dato':  falta,
            'componentes': det_comp,
            'componentes_sin_dato': sin_dato_comp,
        })

    return {
        'ok':       True,
        'k_total':  round(k_total, 4),
        'oferta':   {'anio': oa, 'mes': om},
        'reajuste': {'anio': ra, 'mes': rm},
        'area':     area,
        'detalle':  detalle,
        'monomios_sin_datos': sin_datos,
        'series':   (s_oferta, s_reajuste),
    }
