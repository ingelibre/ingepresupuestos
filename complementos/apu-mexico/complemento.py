# SPDX-License-Identifier: GPL-3.0-or-later
"""Matriz de precio unitario con sobrecosto en cascada (issue #30).

Cada cargo se calcula sobre lo acumulado y se redondea. Manda el PRECIO UNITARIO
REDONDEADO: el importe es cantidad × ese precio y el total, la suma de importes.
"""
from ingepresupuestos import api

from .textos import t

#: (clave, nombre, base). Los dos indirectos van sobre el costo directo.
CARGOS = (
    ("oficina", "Indirectos de oficina", "cd"),
    ("campo", "Indirectos de campo", "cd"),
    ("financiamiento", "Financiamiento", "acumulado"),
    ("utilidad", "Utilidad", "acumulado"),
    ("cargos", "Cargos adicionales", "acumulado"),
)
BLOQUES = (("MAT", "MATERIALES"), ("MO", "MANO DE OBRA"),
           ("EQ", "HERRAMIENTA Y EQUIPO"), ("SC", "SUBCONTRATOS Y OTROS"))


def registrar(app):
    app.accion("porcentajes", t("Porcentajes del sobrecosto…"), configurar,
               ayuda=t("Indirectos, financiamiento, utilidad y cargos de este proyecto"))
    app.reporte("matriz", t("Matriz de precio unitario"), reporte,
                ayuda=t("No cambia el total del presupuesto"))


def porcentajes(ajustes):
    out = {}
    for clave, _n, _b in CARGOS:
        v = ajustes.get(clave)
        bien = isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100
        out[clave] = float(v) if bien else 0.0
    return out


def configurar(ctx):
    pct = porcentajes(ctx.ajustes)
    r = ctx.pedir_datos(
        t("Porcentajes del sobrecosto"),
        [api.Dato(c, t(n), valor=pct[c], maximo=100, decimales=4, sufijo="%")
         for c, n, _b in CARGOS],
        texto=t("Escribe los porcentajes de tu contrato o licitación; el programa no "
                "propone ninguno. Los indirectos van sobre el costo directo; cada cargo "
                "siguiente, sobre lo acumulado."))
    if r is not None:
        ctx.guardar_ajustes(r)


def calcular(cd, pct, dec):
    """([(nombre, %, monto)], precio unitario redondeado)"""
    cd = api.redondear(cd, dec)
    acumulado, lineas = cd, []
    for clave, nombre, base in CARGOS:
        sobre = cd if base == "cd" else acumulado
        monto = api.redondear(sobre * pct[clave] / 100, dec)
        lineas.append((nombre, pct[clave], monto))
        acumulado = api.redondear(acumulado + monto, dec)
    return lineas, acumulado


def reporte(p):
    partidas = p.hojas()
    if not partidas:
        raise api.ErrorComplemento(t("El presupuesto no tiene partidas."))
    pct, d = porcentajes(p.ajustes), p.decimales

    def pc(v):
        return f"{p.moneda.numero(v, 4).rstrip('0').rstrip(p.moneda.decimal)} %"

    bloques = [api.Parrafo(t("Este reporte no cambia el presupuesto: muestra el "
                             "sobrecosto dentro de cada precio unitario."))]
    if not any(pct.values()):
        bloques.append(api.Parrafo(
            t("Todos los porcentajes están en 0. Escríbelos en Complementos → "
              "Porcentajes del sobrecosto."), negrita=True))
    catalogo, total = [], 0.0
    for x in partidas:
        lineas, pu = calcular(x.precio_unitario, pct, d)
        importe = p.importe(x, pu)
        total += importe
        catalogo.append([x.item, x.descripcion, x.unidad, x.metrado, pu, importe])
        filas, suma = [], 0.0
        tipos = {b[0] for b in BLOQUES}
        for tipo, nombre in BLOQUES:
            ins = [i for i in x.acu if i.tipo == tipo
                   or (tipo == "SC" and i.tipo not in tipos)]
            if not ins:
                continue
            filas.append(api.Fila([t(nombre)], "titulo"))
            sub = 0.0
            for i in ins:
                sub += i.parcial
                filas.append([i.codigo, i.descripcion, i.unidad, i.cantidad,
                              i.precio, i.parcial])
            sub = api.redondear(sub, d)
            suma += sub
            filas.append(api.Fila([None, t("Subtotal"), None, None, None, sub],
                                  "subtotal"))
        dif = api.redondear(x.precio_unitario - suma, d)
        if x.acu and dif:
            filas.append([None, t("Ajuste de redondeo"), None, None, None, dif])
        filas.append(api.Fila([None, t("COSTO DIRECTO"), None, None, None,
                               x.precio_unitario], "subtotal"))
        for nombre, v, monto in lineas:
            filas.append([None, f"{t(nombre)} ({pc(v)})", None, None, None, monto])
        filas.append(api.Fila([None, t("PRECIO UNITARIO"), None, None, None, pu],
                              "subtotal"))
        bloques += [
            api.Titulo(f"{x.item}  {x.descripcion}", 2),
            api.Campos([(t("Unidad"), x.unidad),
                        (t("Cantidad"), p.moneda.numero(x.metrado, p.decimales_metrado)),
                        (t("Importe"), p.moneda.formato(importe, d))]),
            api.Tabla(_columnas(d), filas)]
    total = api.redondear(total, d)
    catalogo.append(api.Fila([None, t("TOTAL"), None, None, None, total], "subtotal"))
    pie = api.redondear(p.costo_directo + sum(
        l.valor for l in p.pie if l.tipo != "subtotal" and not l.es_impuesto), d)
    bloques += [
        api.SaltoPagina(),
        api.Titulo(t("Catálogo de conceptos"), 2),
        api.Tabla([api.Columna(t("Clave"), 10), api.Columna(t("Concepto"), 42),
                   api.Columna(t("Unidad"), 9, "centro"),
                   api.Columna(t("Cantidad"), 12, "derecha", p.decimales_metrado),
                   api.Columna(t("P. unitario"), 13, "derecha", d),
                   api.Columna(t("Importe"), 14, "derecha", d)], catalogo),
        api.Parrafo(t("Manda el precio unitario redondeado: el total es la suma de los "
                      "importes.")),
        api.Campos([(t("Total del catálogo"), p.moneda.formato(total, d)),
                    (t("Pie del presupuesto sin impuestos"), p.moneda.formato(pie, d)),
                    (t("Diferencia"),
                     p.moneda.formato(api.redondear(total - pie, d), d))])]
    if total != pie:
        bloques.append(api.Parrafo(t(
            "La diferencia puede venir del redondeo o de que los porcentajes de este "
            "reporte no son los del pie.")))
    return api.Documento(t("Matriz de precio unitario"), bloques)


def _columnas(d):
    return [api.Columna(t("Clave"), 11), api.Columna(t("Concepto"), 41),
            api.Columna(t("Unidad"), 9, "centro"),
            api.Columna(t("Cantidad"), 12, "derecha", 4),
            api.Columna(t("Costo"), 13, "derecha", d),
            api.Columna(t("Importe"), 14, "derecha", d)]
