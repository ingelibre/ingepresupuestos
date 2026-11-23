# SPDX-License-Identifier: GPL-3.0-or-later
"""Llegar a un total escalando precios de insumos del proyecto (issue #40)."""
from ingepresupuestos import api

from .textos import t

TIPOS = (("MO", "Mano de obra"), ("MAT", "Materiales"), ("EQ", "Equipos"),
         ("SC", "Subcontratos"))
#: Un precio no baja de la mitad ni pasa del doble.
MENOR, MAYOR = 0.5, 2.0
RETOQUES = 40


def registrar(app):
    app.accion("ajustar", t("Ajustar a un total…"), ajustar,
               ayuda=t("Escala los precios de este proyecto, con vista previa"))


def grupos(p):
    """[(rótulo, ids de partida)] de los títulos, para elegir uno."""
    varios = len({x.sub_presupuesto for x in p.partidas}) > 1
    out, hojas = [], p.hojas()
    for x in p.partidas:
        ids = {h.id for h in hojas if h.sub_presupuesto == x.sub_presupuesto
               and h.item.startswith(x.item + ".")} if x.es_titulo else None
        if ids:
            rot = f"{x.item} {x.descripcion}"[:70]
            out.append((f"{x.sub_presupuesto} · {rot}" if varios else rot, ids))
    return out


def compartidos(p, base, ids):
    """Insumos de `base` que también usa alguna partida de fuera de `ids`."""
    fuera = {i.recurso_id for h in p.hojas() if h.id not in ids
             for i in h.acu_abierto if not i.es_subpartida}
    return [base[r][0] for r in base if r in fuera]


def precios_de(p, tipos, ids=None):
    """({recurso_id: (descripcion, precio, cantidad en la obra)}, hay_distintos).
    Sin filas en % ni sub-partidas: su precio sale de los demás."""
    cantidad = {i.recurso_id: i.cantidad for i in p.insumos}
    out, distintos = {}, False
    for x in p.hojas():
        if ids is not None and x.id not in ids:
            continue
        for i in x.acu_abierto:
            if (i.tipo not in tipos or i.es_subpartida or i.precio <= 0
                    or i.unidad.strip().startswith("%")):
                continue
            if i.recurso_id in out:
                distintos |= out[i.recurso_id][1] != i.precio
            else:
                out[i.recurso_id] = (i.descripcion, i.precio,
                                     cantidad.get(i.recurso_id, 0.0))
    return out, distintos


def buscar(base, objetivo, dec, simular, fmt=str):
    """(precios, total alcanzado). `base`: {id: (descripcion, precio, cantidad)};
    `simular({id: precio})` da el total, con los redondeos de verdad."""
    minimo = 10 ** -dec

    def con(f):
        return {r: max(minimo, min(api.redondear(MAYOR * v, dec) or minimo,
                                   max(api.redondear(MENOR * v, dec),
                                       api.redondear(v * f, dec))))
                for r, (_d, v, _c) in base.items()}

    def probar(precios):
        return precios, api.redondear(simular(precios), dec)

    bajo, alto = probar(con(MENOR)), probar(con(MAYOR))
    if not bajo[1] <= objetivo <= alto[1]:
        raise api.ErrorComplemento(t(
            "Con esos insumos solo se puede llegar a un total entre {a} y {b} sin bajar "
            "ningún precio de la mitad ni pasar del doble.").format(a=fmt(bajo[1]), b=fmt(alto[1])))
    fa, fb = MENOR, MAYOR
    mejor = min((bajo, alto), key=lambda x: abs(x[1] - objetivo))
    for _ in range(40):
        if mejor[1] == objetivo or fb - fa < 1e-7:
            break
        f = (fa + fb) / 2
        m = probar(con(f))
        if abs(m[1] - objetivo) < abs(mejor[1] - objetivo):
            mejor = m
        if m[1] < objetivo:
            fa = f
        else:
            fb = f
    # Lo que deja el redondeo se reparte moviendo un insumo cada vez.
    orden = sorted((r for r in base if base[r][2] > 0),
                   key=lambda r: -base[r][2])
    for r in (orden * 4)[:RETOQUES]:
        falta = objetivo - mejor[1]
        if not falta:
            break
        _d, v, c = base[r]
        actual = mejor[0][r]
        paso = api.redondear(falta / c, dec) if falta > 0 else \
            -api.redondear(-falta / c, dec)
        paso = paso or (minimo if falta > 0 else -minimo)
        nuevo = api.redondear(actual + paso, dec)
        if not max(minimo, MENOR * v) <= nuevo <= MAYOR * v:
            continue
        m = probar({**mejor[0], r: nuevo})
        if abs(m[1] - objetivo) < abs(mejor[1] - objetivo):
            mejor = m
    return mejor


def ajustar(ctx):
    p = ctx.presupuesto
    todas = t("Todas las partidas")
    gs = grupos(p)
    r = ctx.pedir_datos(
        t("Ajustar a un total"),
        [api.Dato("objetivo", t("Total objetivo"), valor=p.total, minimo=0.01,
                  decimales=p.decimales, sufijo=p.moneda.simbolo)]
        + [api.Dato("grupo", t("Partidas"), "opcion", todas,
                    opciones=[todas, *dict(gs)])]
        + [api.Dato(c, t(n), "si_no", c == "MAT") for c, n in TIPOS],
        texto=t("Total actual: {v}. Marca los insumos cuyos precios se pueden "
                "escalar.").format(v=p.moneda.formato(p.total, p.decimales)))
    if r is None:
        return
    tipos = {c for c, _n in TIPOS if r[c]}
    if not tipos:
        raise api.ErrorComplemento(t("Marca al menos un tipo de insumo."))
    objetivo, d = api.redondear(r["objetivo"], p.decimales), p.decimales
    if objetivo == api.redondear(p.total, d):
        ctx.avisar(t("El presupuesto ya tiene ese total."))
        return
    ids = dict(gs).get(r["grupo"])
    base, distintos = precios_de(p, tipos, ids)
    if not base:
        raise api.ErrorComplemento(t("No hay insumos con precio de esos tipos."))
    def m(v):
        return p.moneda.formato(v, d)

    precios, total = buscar(base, objetivo, d,
                            lambda x: ctx.editar.simular_precios(x).total, m)
    cambios = [(base[k], v) for k, v in precios.items() if v != base[k][1]]
    if not cambios:
        ctx.avisar(t("Ningún cambio de precio acerca más el total al objetivo."))
        return
    falta = api.redondear(objetivo - total, d)
    lineas = [t("Total actual: {v}").format(v=m(p.total)),
              t("Objetivo: {v}").format(v=m(objetivo)),
              t("Alcanzado: {v}").format(v=m(total)),
              t("Diferencia con el objetivo: {v}").format(v=m(falta))]
    if falta:
        lineas.append(t("El redondeo no permite llegar exacto.") if abs(falta) < 1
                      else t("No se encontró una combinación exacta."))
    lineas += ["", t("Cambian {n} precios de este proyecto; la biblioteca no se "
                     "toca.").format(n=len(cambios))]
    comunes = compartidos(p, base, ids) if ids is not None else []
    if comunes:
        lineas.append(t(
            "ATENCIÓN: {n} de esos insumos se usan también en partidas de fuera del "
            "grupo, y allí cambiarán igual: {que}.").format(
                n=len(comunes), que=", ".join(x[:40] for x in comunes[:6])
                + ("…" if len(comunes) > 6 else "")))
    if distintos:
        lineas.append(t("Algún insumo tenía precios distintos según la partida: "
                        "quedará con uno solo."))
    cambios.sort(key=lambda x: -abs(x[1] - x[0][1]) * x[0][2])
    lineas += [f"• {b[0][:50]}: {m(b[1])} → {m(v)}" for b, v in cambios[:8]]
    if len(cambios) > 8:
        lineas.append(t("… y {n} más.").format(n=len(cambios) - 8))
    if ctx.preguntar("\n".join([*lineas, "", t("¿Aplicar?")])):
        # Si algo cambió mientras tanto, los números ya no son los enseñados.
        if ctx.presupuesto != p:
            raise api.ErrorComplemento(t("El presupuesto cambió; vuelve a intentarlo."))
        ctx.editar.fijar_precios({k: v for k, v in precios.items() if v != base[k][1]})
