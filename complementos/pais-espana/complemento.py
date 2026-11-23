# SPDX-License-Identifier: GPL-3.0-or-later
"""Presupuesto y mediciones, con resumen por capítulos, IVA y condiciones."""
from ingepresupuestos import api, piezas

from .textos import t

#: Lo que el proyecto no guarda: (clave, rótulo, tipo).
PROPIOS = (("situacion", "Situación", "texto"), ("fecha", "Fecha", "texto"),
           ("dirigido", "Administrador / dirigido a", "texto"),
           ("condiciones", "Condiciones generales", "parrafo"))


def registrar(app):
    app.accion("datos", t("Presupuesto y mediciones: datos e IVA…"), configurar)
    app.reporte("mediciones", t("Presupuesto y mediciones"), reporte,
                ayuda=t("No altera precios ni totales"))
    app.reporte("condiciones", t("Condiciones generales"), condiciones)


def configurar(ctx):
    a = ctx.ajustes
    r = ctx.pedir_datos(
        t("Presupuesto y mediciones"),
        [api.Dato(c, t(n), tipo, piezas.texto(a, c, maximo=5000))
         for c, n, tipo in PROPIOS]
        + [api.Dato("iva", t("IVA"), valor=piezas.numero(a, "iva", 21.0), maximo=100,
                    sufijo="%", ayuda=t("Por ejemplo, 10 o 21"))],
        texto=t("Si la situación queda vacía se usa la ubicación del proyecto."))
    if r is not None:
        ctx.guardar_ajustes(r)


def _condiciones(p):
    return [api.Parrafo(x) for x in piezas.texto(
        p.ajustes, "condiciones", maximo=5000).split("\n") if x.strip()]


def condiciones(p):
    b = _condiciones(p)
    if not b:
        raise api.ErrorComplemento(t(
            "Escribe antes el texto en Complementos → Presupuesto y mediciones: datos "
            "e IVA."))
    return api.Documento(t("Condiciones generales"), b)


def resumen(p):
    """(capítulos, líneas del pie sin impuesto, base, IVA, total)"""
    d = p.decimales
    caps = piezas.capitulos(p, {x.id: x.parcial for x in p.hojas()})
    pie = [l for l in p.pie if l.tipo != "subtotal" and not l.es_impuesto and l.valor]
    base = api.redondear(p.costo_directo + sum(l.valor for l in pie), d)
    iva = api.redondear(base * piezas.numero(p.ajustes, "iva", 21.0) / 100, d)
    return caps, pie, base, iva, api.redondear(base + iva, d)


def reporte(p):
    hojas = p.hojas()
    if not hojas:
        raise api.ErrorComplemento(t("El presupuesto no tiene partidas."))
    a, d = p.ajustes, p.decimales
    datos = [(t("Proyecto"), p.nombre),
             (t("Situación"), piezas.texto(a, "situacion", p.ubicacion)),
             (t("Fecha"), piezas.texto(a, "fecha", p.fecha_costos)),
             (t("Administrador / dirigido a"), piezas.texto(a, "dirigido", p.cliente))]
    tabla = piezas.mediciones(
        p, {x.id: x.precio_unitario for x in hojas}, {x.id: x.parcial for x in hojas},
        [t("Código"), t("Resumen"), t("Uds."), t("Largo"), t("Ancho"), t("Alto"),
         t("Parcial"), t("Cantidad"), t("Precio"), t("Importe")])
    caps, pie, base, iva, total = resumen(p)
    tasa = piezas.pct(p, piezas.numero(a, "iva", 21.0))
    filas = [[i, n, v, v / p.costo_directo * 100 if p.costo_directo else 0.0]
             for i, n, v in caps]
    filas.append(api.Fila([None, t("Total de capítulos"), p.costo_directo, None],
                          "subtotal"))
    filas += [[None, l.etiqueta or l.nombre, l.valor, None] for l in pie]
    filas += [api.Fila([None, t("Base imponible"), base, None], "subtotal"),
              [None, f"{t('IVA')} ({tasa})", iva, None],
              api.Fila([None, t("TOTAL CON IVA"), total, None], "subtotal")]
    bloques = [
        api.Campos([x for x in datos if x[1]]), tabla, api.SaltoPagina(),
        api.Titulo(t("Resumen por capítulos"), 2),
        api.Tabla([api.Columna("", 10), api.Columna(t("Capítulo"), 55),
                   api.Columna(t("Importe"), 20, "derecha", d),
                   api.Columna("%", 15, "derecha", 2)], filas),
        api.Parrafo(t("Reporte informativo: no altera los precios ni el total del "
                      "presupuesto."))]
    if total != api.redondear(p.total, d):
        bloques.append(api.Parrafo(t(
            "El total del presupuesto en el programa es {v}: su pie lleva otro "
            "impuesto o ninguno.").format(v=p.moneda.formato(p.total, d))))
    c = _condiciones(p)
    if c:
        bloques += [api.Titulo(t("Condiciones generales"), 2), *c]
    return api.Documento(t("Presupuesto y mediciones"), bloques)
