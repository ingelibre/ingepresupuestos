#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Genera `resources/indices_inei_valores.json.gz` desde las fuentes del INEI.

Se corre A MANO antes de cortar un release:

    venv/bin/python3 scripts/generar_indices_valores.py

Por qué existe. Los índices cambian todos los meses y un release sale cada
tanto, así que empaquetar la app sin ellos condena a **toda instalación nueva**
a arrancar con huecos: el Excel de la base 2025 lleva meses congelado en marzo
y gob.pe solo deja el PDF del mes vigente, de modo que quien instale en
noviembre no tiene forma automática de recuperar julio. Este archivo es el
histórico acumulado hasta el día del tag; la sincronización se encarga de lo
que venga después.

Las tres fuentes, todas oficiales:

* **base Julio 1992** — `06_..._dic25.xlsx`, acumulativo, 2013-01 a 2025-12.
  Le falta oct-2014 y abr-2015: no están en el archivo del INEI.
* **corrección de 2018** — la hoja «Indices Modif Ene-Mar 2018» del mismo libro
  publica valores rectificados para 6 índices de enero a marzo de 2018 que las
  hojas mensuales NO incorporaron. Se comprobó que corresponden al **área 02**
  (18 de 18 coincidencias con la columna «ANTERIOR») y se aplican.
* **base Diciembre 2025** — el `07_..._1.xlsx` más las resoluciones mensuales
  que gob.pe publique en ese momento.
* **El Peruano** — el relleno de los meses que a las otras dos se les escapan.
  El Excel se congeló en marzo de 2026 y gob.pe solo deja el mes vigente, así
  que abril, mayo y junio de 2026 no salían por ningún lado automático. Sus
  resoluciones sí están publicadas y la página de cada dispositivo viene
  servida en HTML. Los identificadores se buscaron A MANO —el buscador de El
  Peruano es una aplicación de cliente y no se puede consultar sin navegador—
  y por eso quedan escritos aquí abajo: es un rellenado histórico, no un
  mecanismo. De aquí en adelante cada mes se captura de gob.pe cuando sale.
"""
import gzip
import json
import os
import sys
import urllib.request
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.indices_inei import (            # noqa: E402
    SERIE_1992, SERIE_2025, serie_de, ELPERUANO_DISPOSITIVO,
    buscar_ultimo_excel_inei, descargar_desde_url,
    buscar_resoluciones_gobpe, descargar_resolucion_gobpe,
    importar_html_elperuano,
)

DESTINO = os.path.join(os.path.dirname(__file__), '..', 'resources',
                       'indices_inei_valores.json.gz')

# Hoja «Indices Modif Ene-Mar 2018»: (código, mes) -> valor rectificado.
# El área es la 02, verificado contra la columna «ANTERIOR» del propio INEI.
CORRECCION_2018_AREA = '02'
CORRECCION_2018 = {
    ('04', 1): 935.68, ('04', 2): 949.12, ('04', 3): 943.93,
    ('05', 1): 215.22, ('05', 2): 216.04, ('05', 3): 216.76,
    ('17', 1): 665.25, ('17', 2): 677.40, ('17', 3): 679.31,
    ('38', 1): 936.00, ('38', 2): 948.27, ('38', 3): 961.33,
    ('40', 1): 436.72, ('40', 2): 436.72, ('40', 3): 436.72,
    ('43', 1): 662.98, ('43', 2): 664.78, ('43', 3): 666.28,
}


def _aplicar_correccion_2018(filas: list[dict]) -> int:
    n = 0
    for f in filas:
        if (f['anio'] == 2018 and f['area'] == CORRECCION_2018_AREA
                and (f['codigo'], f['mes']) in CORRECCION_2018):
            nuevo = CORRECCION_2018[(f['codigo'], f['mes'])]
            if abs(f['valor'] - nuevo) > 0.005:
                f['valor'] = nuevo
                n += 1
    return n


# Meses que ni el Excel del INEI ni gob.pe entregan, con el identificador de su
# resolución en El Peruano. (2026, 4) -> R.J. 125-2026-INEI, y así.
RESOLUCIONES_ELPERUANO = {
    (2026, 4): 2516442,      # R.J. 125-2026-INEI
    (2026, 5): 2526641,      # R.J. 149-2026-INEI
    (2026, 6): 2535771,      # R.J. 171-2026-INEI
}


def _traer_elperuano(ya_tengo: set[tuple[int, int]]) -> list[dict]:
    filas: list[dict] = []
    for (anio, mes), ident in sorted(RESOLUCIONES_ELPERUANO.items()):
        if (anio, mes) in ya_tengo:
            continue
        r = importar_html_elperuano(ELPERUANO_DISPOSITIVO.format(id=ident))
        if r.get('ok'):
            filas += r['rows']
            print(f"  El Peruano {anio}-{mes:02d}: {len(r['rows'])} valores")
        else:
            print(f"  ! El Peruano {anio}-{mes:02d}: {r.get('msg')}")
    return filas


def _traer_1992() -> list[dict]:
    b = buscar_ultimo_excel_inei(SERIE_1992)
    if not b['ok']:
        print(f"  ! base 1992: {b['msg']}")
        return []
    r = descargar_desde_url(b['url'], anio_override=b['anio_detectado'],
                            serie=SERIE_1992)
    filas = r.get('rows') or []
    print(f"  base 1992: {len(filas)} valores  ({b['url'].rsplit('/', 1)[-1]})")
    n = _aplicar_correccion_2018(filas)
    print(f"    corrección ene-mar 2018 (área 02): {n} valores rectificados")
    return filas


def _traer_2025() -> list[dict]:
    filas: list[dict] = []
    b = buscar_ultimo_excel_inei(SERIE_2025)
    if b['ok']:
        r = descargar_desde_url(b['url'], anio_override=b['anio_detectado'],
                                serie=SERIE_2025)
        filas += r.get('rows') or []
        print(f"  base 2025 (Excel): {len(filas)} valores")
    else:
        print(f"  ! base 2025: {b['msg']}")
    try:
        resoluciones = buscar_resoluciones_gobpe()
    except Exception as e:
        resoluciones = []
        print(f"  ! gob.pe: {e}")
    for res in resoluciones:
        if serie_de(res['anio'], res['mes']) != SERIE_2025:
            continue
        d = descargar_resolucion_gobpe(res['url'], serie=SERIE_2025)
        if d.get('ok'):
            filas += d['rows']
            print(f"  R.J. {res['resolucion']}: {len(d['rows'])} valores "
                  f"({res['anio']}-{res['mes']:02d})")
        else:
            print(f"  ! R.J. {res['resolucion']}: {d.get('msg')}")
    return filas


def _empaquetar(filas: list[dict]) -> dict:
    """Formato compacto: un arreglo de valores por (período, código).

    Guardar un dict por valor multiplicaría por diez el tamaño. Así el
    histórico completo entra en menos de un megabyte comprimido.
    """
    series: dict[str, dict] = {}
    for f in filas:
        s = f.get('serie') or serie_de(f['anio'], f['mes'])
        d = series.setdefault(s, {'areas': set(), 'datos': {}})
        d['areas'].add(f['area'])
        clave = f"{f['anio']}-{f['mes']:02d}"
        d['datos'].setdefault(clave, {})[f['codigo']] = (f['area'], f['valor'])

    out: dict = {
        '_fuente': ("Instituto Nacional de Estadística e Informática (INEI). "
                    "Índices Unificados de Precios de la Construcción. "
                    "Archivos acumulativos y resoluciones jefaturales "
                    "mensuales publicadas en inei.gob.pe y gob.pe."),
        'generado': date.today().isoformat(),
        'series': {},
    }
    # Segunda pasada: ahora que se conocen las áreas, un arreglo por código.
    for s, d in series.items():
        areas = sorted(d['areas'])
        pos = {a: i for i, a in enumerate(areas)}
        datos: dict[str, dict] = {}
        for f in filas:
            if (f.get('serie') or serie_de(f['anio'], f['mes'])) != s:
                continue
            clave = f"{f['anio']}-{f['mes']:02d}"
            fila = datos.setdefault(clave, {}).setdefault(
                f['codigo'], [None] * len(areas))
            fila[pos[f['area']]] = round(float(f['valor']), 2)
        out['series'][s] = {'areas': areas,
                            'datos': dict(sorted(datos.items()))}
    return out


def main() -> int:
    print("Generando el histórico de índices unificados…")
    filas = _traer_1992() + _traer_2025()
    filas += _traer_elperuano({(f['anio'], f['mes']) for f in filas})
    if not filas:
        print("No se obtuvo ningún valor. No se toca el archivo.")
        return 1
    doc = _empaquetar(filas)
    tmp = DESTINO + '.tmp'          # mismo sistema de archivos que el destino
    # mtime=0: gzip guarda la hora de compresión en su cabecera, así que sin
    # esto el archivo sale distinto en cada corrida aunque el contenido sea el
    # mismo — y la Action commitearía un cambio falso dos veces al mes.
    with open(tmp, 'wb') as bruto:
        with gzip.GzipFile(fileobj=bruto, mode='wb', compresslevel=9,
                           mtime=0) as gz:
            gz.write(json.dumps(doc, ensure_ascii=False,
                                separators=(',', ':')).encode('utf-8'))
    os.replace(tmp, DESTINO)

    print(f"\n{os.path.relpath(DESTINO)} — {os.path.getsize(DESTINO) / 1024:.0f} KB")
    for s, d in sorted(doc['series'].items()):
        per = sorted(d['datos'])
        n = sum(len(v) for v in d['datos'].values())
        print(f"  serie {s}: {len(d['areas'])} áreas · {len(per)} meses "
              f"({per[0]} a {per[-1]}) · {n} filas código-mes")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
