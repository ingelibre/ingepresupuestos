# SPDX-License-Identifier: GPL-3.0-or-later
"""Materiales y mano de obra por partida (equipos dentro de la mano de obra)."""
from ingepresupuestos import api, piezas

from .textos import t


def registrar(app):
    app.accion("reparto", t("Reparto de subcontratos…"), configurar)
    app.reporte("mat-mo", t("Materiales y mano de obra"), reporte,
                ayuda=t("No altera precios ni totales"))


def configurar(ctx):
    r = ctx.pedir_datos(
        t("Reparto de subcontratos"),
        [api.Dato("repartir", t("Repartir los subcontratos"), "si_no",
                  ctx.ajustes.get("repartir") is True),
         api.Dato("mat", t("Parte de materiales"), sufijo="%", maximo=100,
                  valor=piezas.numero(ctx.ajustes, "mat"))],
        texto=t("El resto del subcontrato va a mano de obra. Sin repartir, quedan en "
                "su propia columna."))
    if r is not None:
        ctx.guardar_ajustes(r)


def calcular(p, partida, pct_mat):
    """{mat, mo, otros} por unidad; suman el precio unitario. `pct_mat` None =
    sin repartir."""
    v = {"mat": 0.0, "mo": 0.0, "otros": 0.0}
    for i in partida.acu_abierto:
        if i.tipo == "MAT":
            v["mat"] += i.parcial
        elif i.tipo in ("MO", "EQ"):
            v["mo"] += i.parcial
        elif pct_mat is None:
            v["otros"] += i.parcial
        else:
            v["mat"] += i.parcial * pct_mat / 100
            v["mo"] += i.parcial * (100 - pct_mat) / 100
    if not partida.acu:
        v["otros"] = partida.precio_unitario
    return piezas.cuadrar(v, partida.precio_unitario, p.decimales)


def reporte(p):
    hojas = p.hojas()
    if not hojas:
        raise api.ErrorComplemento(t("El presupuesto no tiene partidas."))
    repartir = p.ajustes.get("repartir") is True
    pm = piezas.numero(p.ajustes, "mat") if repartir else None
    d = p.decimales
    v = {x.id: calcular(p, x, pm) for x in hojas}
    otros = any(c["otros"] for c in v.values())
    tit = piezas.sumar_titulos(p, {x.id: x.parcial for x in hojas})
    n = 7 + otros
    filas = []
    for x, sub in piezas.recorrer(p):
        if sub:
            filas.append(api.Fila([sub], "titulo"))
        if x.es_titulo:
            filas.append(api.Fila([x.item, x.descripcion, *[None] * (n - 2),
                                   tit[x.id]], "subtotal"))
            continue
        c = v[x.id]
        filas.append([x.item, x.descripcion, x.unidad, x.metrado, c["mat"], c["mo"],
                      *([c["otros"]] if otros else []), x.precio_unitario, x.parcial])
    filas.append(api.Fila([None, t("COSTO DIRECTO"), *[None] * (n - 2),
                           p.costo_directo], "subtotal"))
    cols = [api.Columna(t("Ítem"), 8), api.Columna(t("Descripción"), 32),
            api.Columna(t("Und."), 6, "centro"),
            api.Columna(t("Cantidad"), 10, "derecha", p.decimales_metrado)]
    cols += [api.Columna(x, 11, "derecha", d) for x in (
        t("Materiales"), t("Mano de obra"),
        *([t("Subcontratos y otros")] if otros else []), t("Parcial"), t("Total"))]
    notas = [t("Parcial = materiales + mano de obra. La mano de obra incluye los "
               "equipos.")]
    if repartir:
        notas.append(t("Subcontratos repartidos: {a} materiales y {b} mano de "
                       "obra.").format(a=piezas.pct(p, pm), b=piezas.pct(p, 100 - pm)))
    elif otros:
        notas.append(t("Los subcontratos y las partidas sin análisis no se reparten."))
    notas.append(t("Reporte informativo: no altera los precios ni el total del "
                   "presupuesto."))
    return api.Documento(t("Materiales y mano de obra"), [
        api.Tabla(cols, filas), *[api.Parrafo(x) for x in notas]], horizontal=True)
