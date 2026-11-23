# SPDX-License-Identifier: GPL-3.0-or-later
"""Análisis de precios sin cuadrilla, con la mano de obra en horas o jornales."""
from ingepresupuestos import api, piezas

from .textos import t

BLOQUES = (("MAT", "MATERIALES"), ("MO", "MANO DE OBRA"),
           ("EQ", "HERRAMIENTA Y EQUIPO"), ("SC", "SUBCONTRATOS Y OTROS"))
HORAS = {"hh", "h-h", "h", "hr", "hora", "horas"}


def registrar(app):
    app.accion("mano-de-obra", t("Mano de obra en horas o jornales…"), configurar)
    app.reporte("apu", t("Análisis de precios sin cuadrilla"), reporte,
                ayuda=t("No altera precios ni totales"))


def configurar(ctx):
    a, p = ctx.ajustes, ctx.presupuesto
    r = ctx.pedir_datos(
        t("Mano de obra en horas o jornales"),
        [api.Dato("jornales", t("Mostrar la mano de obra en jornales"), "si_no",
                  a.get("jornales") is True),
         api.Dato("horas", t("Horas por jornada"), minimo=0.5, maximo=24,
                  valor=piezas.numero(a, "horas", p.jornada, 0.5, 24))])
    if r is not None:
        ctx.guardar_ajustes(r)


def linea(i, jornales, horas, dec):
    """[descripción, unidad, cantidad, precio, importe]. El importe no cambia."""
    if jornales and i.tipo == "MO" and i.unidad.strip().lower() in HORAS:
        return [i.descripcion, t("jornal"), i.cantidad / horas,
                api.redondear(i.precio * horas, dec), i.parcial]
    return [i.descripcion, i.unidad, i.cantidad, i.precio, i.parcial]


def reporte(p):
    hojas = p.hojas()
    if not hojas:
        raise api.ErrorComplemento(t("El presupuesto no tiene partidas."))
    d = p.decimales
    jornales = p.ajustes.get("jornales") is True
    horas = piezas.numero(p.ajustes, "horas", p.jornada or 8.0, 0.5, 24)
    cols = [api.Columna(t("Descripción"), 46), api.Columna(t("Und."), 9, "centro"),
            api.Columna(t("Cantidad"), 13, "derecha", 4),
            api.Columna(t("P. unitario"), 15, "derecha", d),
            api.Columna(t("Importe"), 17, "derecha", d)]
    notas = [t("Reporte informativo: no altera los precios ni el total del "
               "presupuesto.")]
    if jornales:
        notas.insert(0, t("Mano de obra en jornales de {h} horas.").format(
            h=f"{horas:g}"))
    bloques = [api.Parrafo(x) for x in notas]
    for x in hojas:
        filas, suma = [], 0.0
        for nombre, ins in piezas.bloques_de(x, BLOQUES):
            filas.append(api.Fila([t(nombre)], "titulo"))
            filas += [linea(i, jornales, horas, d) for i in ins]
            sub = api.redondear(sum(i.parcial for i in ins), d)
            suma += sub
            filas.append(api.Fila([t("Subtotal"), None, None, None, sub], "subtotal"))
        dif = api.redondear(x.precio_unitario - suma, d)
        if x.acu and dif:
            filas.append([t("Ajuste de redondeo"), None, None, None, dif])
        filas.append(api.Fila([t("COSTO UNITARIO"), None, None, None,
                               x.precio_unitario], "subtotal"))
        bloques += [api.Titulo(f"{x.item}  {x.descripcion}", 2),
                    api.Campos([(t("Und."), x.unidad)]), api.Tabla(cols, filas)]
    return api.Documento(t("Análisis de precios"), bloques)
