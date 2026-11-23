# SPDX-License-Identifier: GPL-3.0-or-later
"""Presupuesto que empieza con los datos del proyecto (issue #62)."""
from ingepresupuestos import api

from .textos import t

#: Lo que el proyecto no guarda y se escribe aquí: (clave, rótulo).
PROPIOS = (("numero", "Presupuesto n.º"), ("fecha", "Fecha"),
           ("contacto", "Contacto"), ("descripcion", "Descripción"))


def registrar(app):
    app.accion("datos", t("Datos de la primera página…"), configurar)
    app.reporte("presupuesto", t("Presupuesto con datos del proyecto"), reporte)


def configurar(ctx):
    r = ctx.pedir_datos(
        t("Datos de la primera página"),
        [api.Dato(c, t(n), "texto", _texto(ctx.ajustes, c)) for c, n in PROPIOS],
        texto=t("El cliente, la ubicación y el plazo salen de los datos del proyecto. "
                "Lo que dejes vacío no se imprime."))
    if r is not None:
        ctx.guardar_ajustes(r)


def _texto(ajustes, clave):
    v = ajustes.get(clave)
    return v.strip()[:1000] if isinstance(v, str) else ""


def datos(p):
    a = {c: _texto(p.ajustes, c) for c, _n in PROPIOS}
    pares = [(t("Proyecto"), p.nombre), (t("Presupuesto n.º"), a["numero"]),
             (t("Cliente"), p.cliente), (t("Contacto"), a["contacto"]),
             (t("Ubicación"), p.ubicacion), (t("Fecha"), a["fecha"]),
             (t("Costos al"), p.fecha_costos),
             (t("Plazo"), t("{n} días").format(n=p.plazo_dias) if p.plazo_dias else ""),
             (t("Moneda"), p.moneda.nombre), (t("Descripción"), a["descripcion"])]
    return [(k, v) for k, v in pares if v]


def reporte(p):
    if not p.partidas:
        raise api.ErrorComplemento(t("El presupuesto no tiene partidas."))
    d = p.decimales
    filas, sub = [], None
    varios = len({x.sub_presupuesto for x in p.partidas}) > 1
    for x in p.partidas:
        if varios and x.sub_presupuesto != sub:
            sub = x.sub_presupuesto
            filas.append(api.Fila([sub or t("Presupuesto")], "titulo"))
        if x.es_titulo:
            filas.append(api.Fila([x.item, x.descripcion, None, None, None, x.parcial],
                                  "subtotal"))
        else:
            filas.append([x.item, x.descripcion, x.unidad, x.metrado,
                          x.precio_unitario, x.parcial])
    total = p.nombre_total or t("PRESUPUESTO TOTAL")
    pie = [api.Fila([t("COSTO DIRECTO"), p.costo_directo], "subtotal")]
    pie += [api.Fila([l.etiqueta or l.nombre, l.valor],
                     "subtotal" if l.tipo == "subtotal" else "normal") for l in p.pie]
    pie.append(api.Fila([f"{total} ({p.moneda.simbolo})", p.total], "subtotal"))
    return api.Documento(t("Presupuesto"), [
        api.Titulo(t("Datos del proyecto"), 2), api.Campos(datos(p)),
        api.Titulo(t("Presupuesto"), 2),
        api.Tabla([api.Columna(t("Ítem"), 10), api.Columna(t("Descripción"), 43),
                   api.Columna(t("Und."), 7, "centro"),
                   api.Columna(t("Metrado"), 12, "derecha", p.decimales_metrado),
                   api.Columna(t("P. unitario"), 13, "derecha", d),
                   api.Columna(t("Parcial"), 15, "derecha", d)], filas),
        api.Tabla([api.Columna("", 80, "derecha"), api.Columna("", 20, "derecha", d)], pie,
                  cabecera=False)])
