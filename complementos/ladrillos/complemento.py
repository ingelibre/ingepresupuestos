# SPDX-License-Identifier: GPL-3.0-or-later
"""Ladrillos y mortero de muros, con vanos y desperdicios por separado.

No diseña ni verifica el muro.
"""
import math

from ingepresupuestos import api, piezas

from .textos import t

#: aparejo: (largo de cara, alto de cara, espesor) según L, A, H del ladrillo.
APAREJOS = {"Soga": ("l", "h", "a"), "Cabeza": ("a", "h", "l"), "Canto": ("l", "a", "h")}
AVISO = ("Solo mide: no diseña ni verifica el muro. Las medidas y pesos iniciales son "
         "un ejemplo: pon los de tu ladrillo y tu mortero. Un ladrillo hueco se cuenta "
         "como macizo (el mortero que entra en los huecos no se suma).")


def registrar(app):
    app.accion("ladrillos", t("Ladrillos y mortero…"), agregar,
               ayuda=t("Muros con vanos y desperdicio"))
    app.reporte("ladrillos", t("Ladrillos y mortero"), reporte)


def agregar(ctx):
    piezas.metrar(ctx, t("Ladrillos y mortero"), campos(), calcular, t(AVISO))


def reporte(p):
    return piezas.reporte_metrado(p, t("Ladrillos y mortero"), campos(), calcular,
                                  t(AVISO))


def campos():
    def m(clave, titulo, v=0.0, sufijo="m", minimo=0.0, maximo=10000.0, dec=2):
        return api.Dato(clave, t(titulo), "numero", v, minimo, maximo, dec, sufijo=sufijo)
    muros = [api.Dato("nombre", t("Muro"), "texto"),
             api.Dato("n", t("Iguales"), "entero", 1, 1, 10000), m("largo", "Largo"),
             m("alto", "Alto")]
    vanos = [api.Dato("muro", t("Muro"), "texto", ayuda=t("El nombre del muro")),
             api.Dato("n", t("Vanos en cada muro"), "entero", 1, 1, 10000),
             m("largo", "Ancho"), m("alto", "Alto")]
    nombres = tuple(t(x) for x in APAREJOS)
    return [api.Dato("muros", t("Muros"), "tabla", [{}], columnas=muros),
            api.Dato("vanos", t("Vanos"), "tabla", [], columnas=vanos),
            api.Dato("aparejo", t("Aparejo"), "opcion", nombres[0], opciones=nombres),
            m("l", "Largo del ladrillo", 24.0, "cm", 1, 100),
            m("a", "Ancho del ladrillo", 13.0, "cm", 1, 100),
            m("h", "Alto del ladrillo", 9.0, "cm", 1, 100),
            m("jh", "Junta horizontal", 1.5, "cm", 0, 10),
            m("jv", "Junta vertical", 1.5, "cm", 0, 10),
            m("dl", "Desperdicio de ladrillo", 0.0, "%", 0, 100),
            m("dm", "Desperdicio de mortero", 0.0, "%", 0, 100),
            m("prop", "Mortero 1 : arena", 4.0, "", 0.5, 20),
            m("ac", "Agua / cemento del mortero", 0.8, "", 0.1, 3),
            m("pec", "Peso específico del cemento", 3150.0, "kg/m3", 1000, 6000, 0),
            m("pea", "Peso específico de la arena", 2600.0, "kg/m3", 1000, 6000, 0),
            m("puc", "Peso suelto del cemento", 1500.0, "kg/m3", 300, 4000, 0),
            m("pua", "Peso suelto de la arena", 1600.0, "kg/m3", 300, 4000, 0),
            m("bolsa", "Bolsa de cemento", 42.5, "kg", 1, 100)]


def por_m2(v):
    """(ladrillos/m2, mortero m3/m2, espesor m, fórmulas)"""
    aparejo = next(k for k in APAREJOS if t(k) == v["aparejo"])
    c, k, e = (v[x] / 100 for x in APAREJOS[aparejo])
    jv, jh = v["jv"] / 100, v["jh"] / 100
    n = 1 / ((c + jv) * (k + jh))
    vol = v["l"] * v["a"] * v["h"] / 1e6
    mort = max(e - n * vol, 0.0)
    return n, mort, e, [
        f"{v['aparejo']}: 1 / (({c:g} + {jv:g}) × ({k:g} + {jh:g})) = {n:.2f} "
        f"{t('ladrillos por m2')}",
        f"{t('Mortero')}: {e:g} − {n:.4f} × {vol:.6f} = {mort:.4f} m3/m2"]


def mortero(v):
    """Por m3 de mortero: (kg de cemento, m3 de arena suelta, litros, fórmulas).
    Volúmenes absolutos de 1 m3 suelto de cemento con `prop` de arena."""
    vc = v["puc"] / v["pec"]
    va = v["prop"] * v["pua"] / v["pea"]
    vw = v["ac"] * v["puc"] / 1000
    rinde = vc + va + vw
    kg = v["puc"] / rinde
    return kg, v["prop"] / rinde, v["ac"] * kg, [
        t("Volúmenes absolutos de 1 m3 suelto de cemento y {n} de arena:").format(
            n=f"{v['prop']:g}"),
        f"   {t('cemento')} {v['puc']:g} / {v['pec']:g} = {vc:.4f}; {t('arena')} "
        f"{v['prop']:g} × {v['pua']:g} / {v['pea']:g} = {va:.4f}; {t('agua')} "
        f"{v['ac']:g} × {v['puc']:g} / 1000 = {vw:.4f}; {t('rinde')} {rinde:.4f} m3",
        f"   1 m3: {v['puc']:g} / {rinde:.4f} = {kg:.2f} kg ({kg / v['bolsa']:.2f} "
        f"{t('bolsas')}); {t('arena')} {v['prop']:g} / {rinde:.4f} = "
        f"{v['prop'] / rinde:.4f} m3"]


def calcular(v):
    F = api.FilaMetrado
    formulas, filas, areas, veces = [], [], {}, {}
    for n, f in enumerate(v["muros"], 1):
        if not f.get("largo") and not f.get("alto"):
            continue
        nombre = f["nombre"].strip() or str(n)
        if f["largo"] <= 0 or f["alto"] <= 0:
            raise api.ErrorComplemento(t("«{x}»: faltan el largo o el alto.").format(
                x=nombre))
        if nombre.lower() in areas:
            raise api.ErrorComplemento(t("El muro «{x}» está repetido.").format(x=nombre))
        areas[nombre.lower()] = f["largo"] * f["alto"]
        veces[nombre.lower()] = f["n"]
        filas.append(F(nombre, f["n"], largo=f["largo"], alto=f["alto"]))
        formulas.append(f"{nombre}: {f['n']} × {f['largo']:g} × {f['alto']:g} = "
                        f"{f['n'] * f['largo'] * f['alto']:.2f} m2")
    if not areas:
        raise api.ErrorComplemento(t("Escribe al menos un muro."))
    quita = dict.fromkeys(areas, 0.0)
    for f in v["vanos"]:
        if not f.get("largo") and not f.get("alto"):
            continue
        k = f["muro"].strip().lower()
        if k not in areas:
            raise api.ErrorComplemento(t("El vano dice «{x}», que no es ningún "
                                         "muro.").format(x=f["muro"].strip()))
        if f["largo"] <= 0 or f["alto"] <= 0:
            raise api.ErrorComplemento(t("«{x}»: faltan el largo o el alto.").format(
                x=f["muro"].strip()))
        quita[k] += f["n"] * f["largo"] * f["alto"]
        filas.append(F(f"{t('Vano')} {f['muro'].strip()}", -veces[k], f["n"],
                       largo=f["largo"], alto=f["alto"]))
        formulas.append(f"{t('Vano')} {f['muro'].strip()}: −{veces[k]} × {f['n']} × "
                        f"{f['largo']:g} × {f['alto']:g} = "
                        f"−{veces[k] * f['n'] * f['largo'] * f['alto']:.2f} m2")
    for k, q in quita.items():
        if q > areas[k] + 1e-9:
            raise api.ErrorComplemento(t("Los vanos de «{x}» son más grandes que el "
                                         "muro.").format(x=k))
    area = api.redondear(sum((areas[k] - quita[k]) * veces[k] for k in areas), 2)
    n, mort, _e, f1 = por_m2(v)
    kg, arena, litros, f2 = mortero(v)
    ladr = area * n
    ladr_d = ladr * (1 + v["dl"] / 100)
    vm = area * mort
    vm_d = vm * (1 + v["dm"] / 100)
    uds = math.ceil(ladr_d - 1e-6)
    cemento, m3a = api.redondear(vm_d * kg / v["bolsa"], 2), api.redondear(vm_d * arena, 2)
    formulas += [f"{t('Área neta')}: {area:.2f} m2", *f1, *f2,
                 f"{t('Ladrillos')}: {area:.2f} × {n:.4f} = {ladr:.1f}; × (1 + "
                 f"{v['dl']:g} %) = {uds}",
                 f"{t('Mortero')}: {area:.2f} × {mort:.4f} = {vm:.3f} m3; × (1 + "
                 f"{v['dm']:g} %) = {vm_d:.3f} m3",
                 f"{t('Cemento')}: {vm_d:.3f} × {kg:.2f} / {v['bolsa']:g} = {cemento:.2f} "
                 f"{t('bolsas')}; {t('arena')} {m3a:.2f} m3; {t('agua')} "
                 f"{vm_d * litros:.0f} L"]
    P = piezas.Parte
    q = t("Cantidad calculada")
    partes = [P(t("MURO DE LADRILLO"), "m2", filas, area),
              P(t("LADRILLOS"), "und", [F(q, uds)], uds),
              P(t("MORTERO"), "m3", [F(q, area=vm_d)], api.redondear(vm_d, 2)),
              P(t("CEMENTO PARA MORTERO"), "bls", [F(q, cemento)], cemento),
              P(t("ARENA PARA MORTERO"), "m3", [F(q, area=m3a)], m3a)]
    return piezas.Calculo([x for x in partes if x.cantidad], formulas,
                          [t("El mortero es el volumen del muro menos el de los "
                             "ladrillos.")])
