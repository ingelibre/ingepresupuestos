# SPDX-License-Identifier: GPL-3.0-or-later
"""Impuesto sobre los materiales, por partida y en total (issue #57). Solo reporte."""
from ingepresupuestos import api

from .textos import t

#: La del ejemplo del issue #57 (ITBIS de República Dominicana); se edita.
NOMBRE, TASA = "ITBIS", 18.0


def registrar(app):
    app.accion("tasa", t("Tasa del impuesto sobre materiales…"), configurar)
    app.reporte("impuesto", t("Impuesto sobre materiales"), reporte,
                ayuda=t("No altera precios ni totales"))


def ajustes_de(a):
    v, n = a.get("tasa"), a.get("nombre")
    bien = isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100
    return (n.strip()[:40] if isinstance(n, str) and n.strip() else NOMBRE,
            float(v) if bien else TASA)


def configurar(ctx):
    nombre, tasa = ajustes_de(ctx.ajustes)
    r = ctx.pedir_datos(
        t("Impuesto sobre materiales"),
        [api.Dato("nombre", t("Nombre"), "texto", nombre),
         api.Dato("tasa", t("Tasa"), valor=tasa, maximo=100, decimales=4, sufijo="%")])
    if r is not None:
        ctx.guardar_ajustes(r)


def calcular(p, partida, tasa):
    """(materiales por unidad, impuesto por unidad, materiales, impuesto)"""
    d = p.decimales
    mat = api.redondear(sum(i.parcial for i in partida.acu_abierto
                            if i.tipo == "MAT"), d)
    imp = api.redondear(mat * tasa / 100, d)
    return mat, imp, p.importe(partida, mat), p.importe(partida, imp)


def reporte(p):
    partidas = p.hojas()
    if not partidas:
        raise api.ErrorComplemento(t("El presupuesto no tiene partidas."))
    nombre, tasa = ajustes_de(p.ajustes)
    d = p.decimales
    etiqueta = f"{nombre} ({tasa:g} %)"
    filas, mats, imps = [], 0.0, 0.0
    for x in partidas:
        mu, iu, m, i = calcular(p, x, tasa)
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
