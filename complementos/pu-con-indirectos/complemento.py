# SPDX-License-Identifier: GPL-3.0-or-later
"""Presupuesto con el pie repartido en los precios unitarios, sin enseñar los %.

El total es el del presupuesto: lo que deja el redondeo va en una línea aparte.
"""
import re

from ingepresupuestos import api, piezas

from .textos import t


def registrar(app):
    app.accion("opciones", t("Precios con indirectos: opciones…"), configurar)
    app.reporte("presupuesto", t("Presupuesto con indirectos en los precios"), reporte,
                ayuda=t("No cambia el total del presupuesto"))


def configurar(ctx):
    r = ctx.pedir_datos(
        t("Precios con indirectos"),
        [api.Dato("impuesto", t("Incluir también el impuesto en los precios"), "si_no",
                  ctx.ajustes.get("impuesto") is True)],
        texto=t("Cada precio unitario lleva su parte de todas las líneas del pie. El "
                "impuesto puede quedar aparte, al final."))
    if r is not None:
        ctx.guardar_ajustes(r)


def calcular(p, con_impuesto):
    """{id: (precio, importe)}, residuo, lo repartido y las líneas del impuesto."""
    if not p.costo_directo:
        raise api.ErrorComplemento(t("El presupuesto no tiene costo directo."))
    d = p.decimales
    aparte = [] if con_impuesto else [l for l in p.pie if l.es_impuesto and l.valor]
    meta = api.redondear(p.total - sum(l.valor for l in aparte), d)
    factor = meta / p.costo_directo
    out = {}
    for x in p.hojas():
        pu = api.redondear(x.precio_unitario * factor, d)
        out[x.id] = (pu, p.importe(x, pu))
    residuo = api.redondear(meta - sum(v[1] for v in out.values()), d)
    return out, residuo, meta, aparte


def reporte(p):
    con = p.ajustes.get("impuesto") is True
    lin, residuo, meta, aparte = calcular(p, con)
    d = p.decimales
    importes = {k: v[1] for k, v in lin.items()}
    tit = piezas.sumar_titulos(p, importes)
    filas = []
    for x, sub in piezas.recorrer(p):
        if sub:
            filas.append(api.Fila([sub], "titulo"))
        if x.es_titulo:
            filas.append(api.Fila([x.item, x.descripcion, None, None, None, tit[x.id]],
                                  "subtotal"))
        else:
            filas.append([x.item, x.descripcion, x.unidad, x.metrado, *lin[x.id]])
    if residuo:
        filas.append([None, t("Ajuste por redondeo de los precios"), None, None, None,
                      residuo])
    pie = []
    if aparte:
        pie.append(api.Fila([t("Subtotal"), meta], "subtotal"))
        pie += [[l.nombre, l.valor] for l in aparte]
    pie.append(api.Fila([f"{p.nombre_total or t('PRESUPUESTO TOTAL')} "
                         f"({p.moneda.simbolo})", p.total], "subtotal"))
    dentro = [re.sub(r"\s*\([^)]*%[^)]*\)|\s*\d[\d.,]*\s*%", "", l.nombre) for l in p.pie
              if l.tipo != "subtotal" and l.valor and l not in aparte]
    notas = [t("Los precios unitarios incluyen: {que}.").format(
        que=", ".join(dentro) or t("solo el costo directo"))]
    if aparte:
        notas.append(t("Aparte: {que}.").format(que=", ".join(l.nombre for l in aparte)))
    notas.append(t("Este reporte no cambia el presupuesto: el total es el mismo."))
    return api.Documento(t("Presupuesto"), [
        api.Tabla([api.Columna(t("Ítem"), 10), api.Columna(t("Descripción"), 43),
                   api.Columna(t("Und."), 7, "centro"),
                   api.Columna(t("Metrado"), 12, "derecha", p.decimales_metrado),
                   api.Columna(t("P. unitario"), 13, "derecha", d),
                   api.Columna(t("Parcial"), 15, "derecha", d)], filas),
        api.Tabla([api.Columna("", 80, "derecha"), api.Columna("", 20, "derecha", d)],
                  pie, cabecera=False),
        *[api.Parrafo(x) for x in notas]])
