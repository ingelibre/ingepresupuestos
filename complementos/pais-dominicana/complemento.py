# SPDX-License-Identifier: GPL-3.0-or-later
"""ITBIS sobre los materiales; la cuenta es la de «Impuesto sobre materiales»."""
from ingepresupuestos import api, piezas

from .textos import t

TASA = 18.0


def registrar(app):
    app.accion("itbis", t("Tasa del ITBIS…"), configurar)
    app.reporte("itbis", t("ITBIS sobre materiales"), reporte,
                ayuda=t("No altera precios ni totales"))


def configurar(ctx):
    r = ctx.pedir_datos(t("Tasa del ITBIS"), [api.Dato(
        "tasa", "ITBIS", valor=piezas.numero(ctx.ajustes, "tasa", TASA), maximo=100,
        decimales=4, sufijo="%")])
    if r is not None:
        ctx.guardar_ajustes(r)


def reporte(p):
    return piezas.impuesto_materiales(
        p, "ITBIS", piezas.numero(p.ajustes, "tasa", TASA))
