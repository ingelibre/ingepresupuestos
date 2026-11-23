# SPDX-License-Identifier: GPL-3.0-or-later
"""Excavación, relleno y eliminación, con el balance a la vista.

La eliminación es lo excavado que NO vuelve como relleno: nada se cuenta dos
veces. No diseña taludes ni entibados.
"""
from ingepresupuestos import api, piezas

from .textos import t

ZANJA, POZO = "Zanja (talud en 2 lados)", "Zapata o pozo (talud en 4 lados)"
AVISO = ("Solo mide: no diseña taludes ni entibados. Los factores de esponjamiento y "
         "compactación los pones tú; los iniciales no cambian nada.")


def registrar(app):
    app.accion("tierras", t("Movimiento de tierras…"), agregar,
               ayuda=t("Excavación, relleno y eliminación"))
    app.reporte("tierras", t("Movimiento de tierras"), reporte)


def agregar(ctx):
    piezas.metrar(ctx, t("Movimiento de tierras"), campos(), calcular, t(AVISO))


def reporte(p):
    return piezas.reporte_metrado(p, t("Movimiento de tierras"), campos(), calcular,
                                  t(AVISO))


def campos():
    def m(clave, titulo, v=0.0, sufijo="m", maximo=100000.0, dec=3, minimo=0.0):
        return api.Dato(clave, t(titulo), "numero", v, minimo, maximo, dec, sufijo=sufijo)
    exc = [api.Dato("nombre", t("Nombre"), "texto"),
           api.Dato("tipo", t("Tipo"), "opcion", t(ZANJA), opciones=(t(ZANJA), t(POZO))),
           api.Dato("n", t("Iguales"), "entero", 1, 1, 100000), m("largo", "Largo"),
           m("ancho", "Ancho de la estructura"), m("prof", "Profundidad", maximo=200),
           m("sobre", "Sobreancho por lado", maximo=20),
           m("talud", "Talud horizontal por 1 de alto", sufijo="", maximo=10),
           m("ocupado", "Ocupado por la estructura (c/u)", sufijo="m3")]
    sec = [m("prog", "Progresiva"), m("corte", "Área de corte", sufijo="m2"),
           m("relleno", "Área de relleno", sufijo="m2")]
    return [api.Dato("exc", t("Excavaciones"), "tabla", [{}], columnas=exc),
            api.Dato("sec", t("Secciones (camino, plataforma)"), "tabla", [],
                     columnas=sec),
            m("aprov", "Excavado que sirve para rellenar", 100.0, "%", 100, 2),
            m("banco", "m3 en banco por m3 compactado", 1.0, "", 3, 4, 0.5),
            m("esp", "Esponjamiento", 0.0, "%", 200, 2)]


def volumen(f):
    """(m3 de una, fórmula, área media, alto)"""
    s, z, h = f["sobre"], f["talud"], f["prof"]
    b = f["ancho"] + 2 * s
    if f["tipo"] == t(POZO):
        l = f["largo"] + 2 * s
        a1, a2 = l * b, (l + 2 * z * h) * (b + 2 * z * h)
        am = (l + z * h) * (b + z * h)
        media = (a1 + 4 * am + a2) / 6
        return (media * h, f"{h:g} / 6 × ({a1:.4f} + 4 × {am:.4f} + {a2:.4f})", media, h)
    area = (b + z * h) * h
    return (area * f["largo"], f"({b:g} + {z:g} × {h:g}) × {h:g} × {f['largo']:g}", area,
            f["largo"])


def tramos(sec):
    """[(desde, hasta, corte, relleno, fórmula, filas)] por media de áreas extremas.
    Si una sección es solo corte y la otra solo relleno, la línea de paso parte el
    tramo en proporción a las áreas y cada lado es una cuña."""
    out = []
    for a, b in zip(sec, sec[1:]):
        d = b["prog"] - a["prog"]
        if d <= 0:
            raise api.ErrorComplemento(t(
                "Las progresivas deben ir de menor a mayor: {a} y {b}.").format(
                    a=f"{a['prog']:g}", b=f"{b['prog']:g}"))
        ca, ra, cb, rb = a["corte"], a["relleno"], b["corte"], b["relleno"]
        for c0, r0, c1, r1 in ((ca, ra, cb, rb), (cb, rb, ca, ra)):
            if c0 > 0 and r0 == 0 and c1 == 0 and r1 > 0:   # de corte a relleno
                dc = d * c0 / (c0 + r1)
                dr = d - dc
                corte, rell = (c0 / 2, dc), (r1 / 2, dr)
                texto = (f"{c0:g} / 2 × {dc:.3f} | {r1:g} / 2 × {dr:.3f} "
                         f"({t('paso de corte a relleno')})")
                break
        else:
            corte, rell = ((ca + cb) / 2, d), ((ra + rb) / 2, d)
            texto = f"({ca:g} + {cb:g}) / 2 × {d:g} | ({ra:g} + {rb:g}) / 2 × {d:g}"
        out.append((a["prog"], b["prog"], corte, rell, texto))
    return out


def calcular(v):
    F = api.FilaMetrado
    formulas, avisos = [], []
    exc, rel = [], []
    tot_exc = tot_rel = 0.0

    def r2(x):
        return api.redondear(x, 2)
    for n, f in enumerate(v["exc"], 1):
        if not f.get("largo") and not f.get("ancho") and not f.get("prof"):
            continue
        nombre = f["nombre"].strip() or str(n)
        if min(f["largo"], f["ancho"], f["prof"]) <= 0:
            raise api.ErrorComplemento(t("«{x}»: faltan el largo, el ancho o la "
                                         "profundidad.").format(x=nombre))
        u, texto, area, alto = volumen(f)
        if f["ocupado"] > u + 1e-9:
            raise api.ErrorComplemento(t("«{x}»: la estructura ocupa más que lo "
                                         "excavado.").format(x=nombre))
        ve, vr = r2(f["n"] * u), r2(f["n"] * (u - f["ocupado"]))
        tot_exc += ve
        tot_rel += vr
        zanja = f["tipo"] != t(POZO)
        exc.append(F(nombre, f["n"], area=area, largo=alto if zanja else None,
                     alto=None if zanja else alto))
        formulas.append(f"{nombre}: {f['n']} × {texto} = {ve:.2f} m3")
        formulas.append(f"   {t('relleno')}: {f['n']} × ({u:.4f} − {f['ocupado']:g}) = "
                        f"{vr:.2f} m3")
        if vr:
            rel.append(F(f"{nombre} ({t('excavado − estructura')})", f["n"],
                         area=u - f["ocupado"]))
    if len(v["sec"]) == 1:
        raise api.ErrorComplemento(t("Hacen falta al menos dos secciones."))
    for a, b, c, r, texto in tramos(v["sec"]):
        vc, vr = r2(c[0] * c[1]), r2(r[0] * r[1])
        tot_exc += vc
        tot_rel += vr
        nombre = f"{a:g} – {b:g}"
        formulas.append(f"{nombre}: {t('corte | relleno')}: {texto} = {vc:.2f} | "
                        f"{vr:.2f} m3")
        if vc:
            exc.append(F(nombre, area=c[0], largo=c[1]))
        if vr:
            rel.append(F(nombre, area=r[0], largo=r[1]))
    tot_exc, tot_rel = r2(tot_exc), r2(tot_rel)
    if not tot_exc and not tot_rel:
        raise api.ErrorComplemento(t("Escribe al menos una excavación o dos secciones."))
    # Balance, en banco (volumen del terreno sin mover).
    pide = r2(tot_rel * v["banco"])
    propio = min(r2(tot_exc * v["aprov"] / 100), pide)
    prestamo, sobra = r2(pide - propio), r2(tot_exc - propio)
    elim = r2(sobra * (1 + v["esp"] / 100))
    formulas += [
        "", t("BALANCE (en banco)"),
        f"{t('Excavado')}: {tot_exc:.2f} m3",
        f"{t('El relleno pide')}: {tot_rel:.2f} × {v['banco']:g} = {pide:.2f} m3",
        f"{t('Sale de lo excavado')}: min({tot_exc:.2f} × {v['aprov']:g} %, {pide:.2f}) = "
        f"{propio:.2f} m3",
        f"{t('Préstamo')}: {pide:.2f} − {propio:.2f} = {prestamo:.2f} m3",
        f"{t('Se elimina')}: {tot_exc:.2f} − {propio:.2f} = {sobra:.2f} m3; "
        f"× (1 + {v['esp']:g} %) = {elim:.2f} m3 {t('sueltos')}",
        f"{t('Comprobación')}: {propio:.2f} + {sobra:.2f} = {tot_exc:.2f}"]
    if v["sec"]:
        avisos.append(t("Secciones por media de áreas extremas, con línea de paso solo "
                        "cuando una sección es toda de corte y la otra toda de relleno. "
                        "No corrige la curvatura."))
    P = piezas.Parte
    partes = [P(t("EXCAVACIÓN"), "m3", exc, tot_exc),
              P(t("RELLENO COMPACTADO"), "m3", rel, tot_rel),
              P(t("MATERIAL DE PRÉSTAMO (EN BANCO)"), "m3",
                [F(t("El relleno pide − lo excavado"), area=prestamo)], prestamo),
              P(t("ELIMINACIÓN DE MATERIAL EXCEDENTE (SUELTO)"), "m3",
                [F(t("Excedente × esponjamiento"), area=sobra,
                   alto=1 + v["esp"] / 100)], elim)]
    return piezas.Calculo([x for x in partes if x.cantidad], formulas, avisos)
