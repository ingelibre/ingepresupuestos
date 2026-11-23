# SPDX-License-Identifier: GPL-3.0-or-later
"""Metrado de zapatas aisladas rectangulares por dimensiones (issue #27).

Solo cuenta cantidades: no diseña ni verifica la estructura.
"""
import math

from ingepresupuestos import api

from .textos import t

DENSIDAD = 7850.0       # kg/m³ del acero


def registrar(app):
    app.accion("zapata", t("Agregar zapatas…"), agregar,
               ayuda=t("Metrado por dimensiones, sin precios"))


def campos():
    def m(clave, titulo, defecto, minimo=0.0, maximo=20.0, sufijo="m", ayuda=""):
        return api.Dato(clave, t(titulo), "numero", defecto, minimo, maximo,
                        3 if sufijo == "m" else 2, sufijo=sufijo, ayuda=t(ayuda))
    return [
        api.Dato("nombre", t("Nombre"), "texto", "Z-1"),
        api.Dato("n", t("Cantidad de zapatas"), "entero", 1, 1, 10000),
        m("largo", "Largo", 1.0, 0.1), m("ancho", "Ancho", 1.0, 0.1),
        m("alto", "Alto", 0.5, 0.05),
        m("prof", "Profundidad de excavación", 0.0, ayuda="0 = el alto de la zapata"),
        m("sobre", "Sobreancho de excavación por lado", 0.0, maximo=5.0),
        m("recub", "Recubrimiento", 7.5, maximo=50.0, sufijo="cm"),
        api.Dato("nl", t("Varillas paralelas al largo"), "entero", 5, 0, 500),
        m("dl", "Diámetro de esas varillas", 12.0, 1.0, 60.0, "mm"),
        api.Dato("na", t("Varillas paralelas al ancho"), "entero", 5, 0, 500),
        m("da", "Diámetro de esas varillas (ancho)", 12.0, 1.0, 60.0, "mm"),
        m("desp", "Desperdicio de acero", 0.0, maximo=50.0, sufijo="%"),
    ]


def kg_por_m(diametro_mm):
    return math.pi / 4 * (diametro_mm / 1000) ** 2 * DENSIDAD


def calcular(x):
    """{excavacion, concreto, encofrado, acero} y las fórmulas con sus números."""
    n, l, a, h = x["n"], x["largo"], x["ancho"], x["alto"]
    prof, s, r = x["prof"] or h, x["sobre"], x["recub"] / 100
    if prof < h:
        raise api.ErrorComplemento(t(
            "La profundidad de excavación es menor que el alto de la zapata."))
    if 2 * r >= min(l, a) or 2 * r >= h:
        raise api.ErrorComplemento(t(
            "El recubrimiento no cabe en esas dimensiones."))
    if x["nl"] + x["na"] == 0:
        raise api.ErrorComplemento(t("Indica al menos una varilla."))
    ll, la = l - 2 * r, a - 2 * r
    pl, pa = kg_por_m(x["dl"]), kg_por_m(x["da"])
    acero = n * (x["nl"] * ll * pl + x["na"] * la * pa)
    res = {"excavacion": api.redondear(n * (l + 2 * s) * (a + 2 * s) * prof, 2),
           "concreto": api.redondear(n * l * a * h, 2),
           "encofrado": api.redondear(n * 2 * (l + a) * h, 2),
           "acero": api.redondear(acero * (1 + x["desp"] / 100), 2)}
    g = "{:g}".format
    formulas = [
        f"{t('Excavación')}: {n} × {g(l + 2 * s)} × {g(a + 2 * s)} × {g(prof)} = "
        f"{res['excavacion']:.2f} m3",
        f"{t('Concreto')}: {n} × {g(l)} × {g(a)} × {g(h)} = {res['concreto']:.2f} m3",
        f"{t('Encofrado')}: {n} × 2 × ({g(l)} + {g(a)}) × {g(h)} = "
        f"{res['encofrado']:.2f} m2",
        f"{t('Acero')}: {n} × ({x['nl']} × {g(ll)} × {pl:.4f} + {x['na']} × {g(la)} × "
        f"{pa:.4f}) × (1 + {g(x['desp'])} %) = {res['acero']:.2f} kg",
        t("Peso por metro: π/4 × diámetro² × 7850 kg/m³. Largo de varilla: lado − 2 × "
          "recubrimiento."),
    ]
    return res, formulas


def siguiente(p):
    """El primer ítem de título libre en la raíz («07»)."""
    raices = [int(x.item) for x in p.partidas
              if x.item.isascii() and x.item.isdigit()]
    return f"{max(raices, default=0) + 1:02d}"


def agregar(ctx):
    r = ctx.pedir_datos(t("Zapatas"), campos(), texto=t(AVISO))
    if r is None:
        return
    res, formulas = calcular(r)
    nombre = r["nombre"].strip()[:60]
    titulo = f"{t('ZAPATAS')} {nombre}".strip()
    nuevas = [(t("EXCAVACIÓN PARA ZAPATA"), "m3", res["excavacion"]),
              (t("CONCRETO EN ZAPATA"), "m3", res["concreto"]),
              (t("ENCOFRADO Y DESENCOFRADO DE ZAPATA"), "m2", res["encofrado"]),
              (t("ACERO DE REFUERZO EN ZAPATA"), "kg", res["acero"])]
    item = siguiente(ctx.presupuesto)
    texto = [*formulas, "", t("Se agregará el título {item} «{titulo}» con 4 partidas "
                              "sin precio.").format(item=item, titulo=titulo),
             t(AVISO), "", t("¿Agregar?")]
    if not ctx.preguntar("\n".join(texto)):
        return
    ctx.editar.agregar(
        [api.PartidaNueva(titulo, es_titulo=True, item=item)]
        + [api.PartidaNueva(d, u, q, padre=item) for d, u, q in nuevas])


AVISO = ("Solo mide zapatas rectangulares: no diseña ni verifica la estructura. No "
         "calcula ganchos, traslapes, arranques de columna, solado, relleno ni "
         "eliminación. El desperdicio se aplica solo al acero.")
