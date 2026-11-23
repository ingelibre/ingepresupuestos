# SPDX-License-Identifier: GPL-3.0-or-later
"""Impuesto sobre los materiales, por partida y en total (issue #57). Solo reporte."""
from ingepresupuestos import api, piezas

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


def reporte(p):
    return piezas.impuesto_materiales(p, *ajustes_de(p.ajustes))
