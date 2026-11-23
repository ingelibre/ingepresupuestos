# SPDX-License-Identifier: GPL-3.0-or-later
"""Materiales por m3 de concreto por volúmenes absolutos, a partir de los datos
que da el usuario. No hay ninguna tabla de resistencias."""
import math

from ingepresupuestos import api, piezas

from .textos import t

AVISO = ("No sustituye un diseño de mezcla en laboratorio ni asegura una resistencia. "
         "Los valores iniciales son un EJEMPLO: pon los tuyos.")


def registrar(app):
    app.accion("dosificar", t("Dosificación de concreto…"), agregar,
               ayuda=t("Materiales por m3, por tanda y proporción"))
    app.reporte("dosificar", t("Dosificación de concreto"), reporte)


def agregar(ctx):
    piezas.metrar(ctx, t("Dosificación de concreto"), campos(), calcular, t(AVISO))


def reporte(p):
    return piezas.reporte_metrado(p, t("Dosificación de concreto"), campos(), calcular,
                                  t(AVISO))


def campos():
    def m(clave, titulo, v=0.0, sufijo="", minimo=0.0, maximo=10000.0, dec=2):
        return api.Dato(clave, t(titulo), "numero", v, minimo, maximo, dec, sufijo=sufijo)
    vol = [api.Dato("nombre", t("Elemento"), "texto"), m("m3", "Volumen", 0.0, "m3")]
    return [api.Dato("vol", t("Concreto que se va a preparar"), "tabla", [{}],
                     columnas=vol),
            m("cemento", "Cemento por m3", 350.0, "kg", 50, 900),
            m("ac", "Agua / cemento", 0.5, "", 0.1, 2, 3),
            m("aire", "Aire", 2.0, "%", 0, 20),
            m("fino", "Arena en el volumen de agregados", 45.0, "%", 1, 99),
            m("pec", "Peso específico del cemento", 3150.0, "kg/m3", 1000, 6000, 0),
            m("pea", "Peso específico seco de la arena", 2650.0, "kg/m3", 1000, 6000, 0),
            m("pep", "Peso específico seco de la piedra", 2650.0, "kg/m3", 1000, 6000, 0),
            m("wa", "Humedad de la arena", 0.0, "%", 0, 30),
            m("aba", "Absorción de la arena", 0.0, "%", 0, 30),
            m("wp", "Humedad de la piedra", 0.0, "%", 0, 30),
            m("abp", "Absorción de la piedra", 0.0, "%", 0, 30),
            m("adit", "Aditivo (% del peso del cemento)", 0.0, "%", 0, 20, 3),
            m("ped", "Peso específico del aditivo", 1100.0, "kg/m3", 500, 4000, 0),
            m("puc", "Peso suelto del cemento", 1500.0, "kg/m3", 300, 4000, 0),
            m("pua", "Peso suelto seco de la arena", 1600.0, "kg/m3", 300, 4000, 0),
            m("pup", "Peso suelto seco de la piedra", 1500.0, "kg/m3", 300, 4000, 0),
            m("bolsa", "Bolsa de cemento", 42.5, "kg", 1, 100),
            m("tanda", "Bolsas por tanda", 1.0, "", 0.1, 100),
            m("desp", "Desperdicio de materiales", 0.0, "%", 0, 50)]


def mezcla(v):
    """Por m3. Los agregados en peso húmedo; el agua ya corregida."""
    c = v["cemento"]
    agua, adit = c * v["ac"], c * v["adit"] / 100
    vol = {"c": c / v["pec"], "w": agua / 1000, "aire": v["aire"] / 100,
           "adit": adit / v["ped"]}
    agr = 1 - sum(vol.values())
    if agr <= 0:
        raise api.ErrorComplemento(t(
            "El cemento, el agua y el aire ya pasan de 1 m3: no queda sitio para los "
            "agregados."))
    vol["a"], vol["p"] = agr * v["fino"] / 100, agr * (1 - v["fino"] / 100)
    as_, ps = vol["a"] * v["pea"], vol["p"] * v["pep"]
    aporte = as_ * (v["wa"] - v["aba"]) / 100 + ps * (v["wp"] - v["abp"]) / 100
    neta = agua - aporte
    if neta <= 0:
        raise api.ErrorComplemento(t("La humedad de los agregados aporta más agua que "
                                     "la de la mezcla."))
    return {"vol": vol, "agr": agr, "agua": agua, "cemento": c, "adit": adit,
            "arena_s": as_, "piedra_s": ps, "aporte": aporte, "neta": neta,
            "arena": as_ * (1 + v["wa"] / 100), "piedra": ps * (1 + v["wp"] / 100),
            "bolsas": c / v["bolsa"], "rinde": v["bolsa"] / c,
            "arena_m3": as_ / v["pua"], "piedra_m3": ps / v["pup"],
            "prop": (as_ / v["pua"] / (c / v["puc"]), ps / v["pup"] / (c / v["puc"]))}


def calcular(v):
    x = mezcla(v)
    vol = x["vol"]
    f = [f"{t('Agua')}: {v['cemento']:g} × {v['ac']:g} = {x['agua']:.1f} kg",
         f"{t('Volúmenes absolutos')} (m3): {t('cemento')} {v['cemento']:g} / {v['pec']:g}"
         f" = {vol['c']:.4f}; {t('agua')} {vol['w']:.4f}; {t('aire')} {vol['aire']:.4f}; "
         f"{t('aditivo')} {vol['adit']:.4f}",
         f"{t('Agregados')}: 1 − {1 - x['agr']:.4f} = {x['agr']:.4f}; {t('arena')} "
         f"{v['fino']:g} % = {vol['a']:.4f}; {t('piedra')} {vol['p']:.4f}; "
         f"{t('suma')} {sum(vol.values()):.4f}",
         f"{t('Peso seco')}: {t('arena')} {vol['a']:.4f} × {v['pea']:g} = "
         f"{x['arena_s']:.1f} kg; {t('piedra')} {vol['p']:.4f} × {v['pep']:g} = "
         f"{x['piedra_s']:.1f} kg",
         f"{t('Humedad − absorción')}: {x['aporte']:.1f} kg; {t('agua de mezcla')}: "
         f"{x['agua']:.1f} − {x['aporte']:.1f} = {x['neta']:.1f} L",
         f"{t('Por m3')}: {x['bolsas']:.2f} {t('bolsas')}, {t('arena')} "
         f"{x['arena']:.1f} kg, {t('piedra')} {x['piedra']:.1f} kg, {t('agua')} "
         f"{x['neta']:.1f} L, {t('aditivo')} {x['adit']:.2f} kg",
         f"{t('Proporción en volumen suelto seco')}: 1 : {x['prop'][0]:.2f} : "
         f"{x['prop'][1]:.2f}; {t('una bolsa rinde')} {x['rinde']:.4f} m3"]
    total, filas = 0.0, []
    for n, r in enumerate(v["vol"], 1):
        if r.get("m3"):
            filas.append(api.FilaMetrado(r["nombre"].strip() or str(n), area=r["m3"]))
            total += api.redondear(r["m3"], 2)
    total = api.redondear(total, 2)
    k = total * (1 + v["desp"] / 100)
    tanda = v["tanda"] * x["rinde"]
    nombres = ((t("Cemento"), t("bolsas"), x["bolsas"]),
               (t("Arena (húmeda)"), "kg", x["arena"]),
               (t("Piedra (húmeda)"), "kg", x["piedra"]),
               (t("Arena (suelta seca)"), "m3", x["arena_m3"]),
               (t("Piedra (suelta seca)"), "m3", x["piedra_m3"]),
               (t("Agua"), "L", x["neta"]), (t("Aditivo"), "kg", x["adit"]))
    filas_t = [[a, u, q, q * tanda, q * k] for a, u, q in nombres
               if q or a != t("Aditivo")]
    f.append(f"{t('Tanda')}: {v['tanda']:g} {t('bolsas')} = {tanda:.4f} m3: "
             + ", ".join(f"{a} {q * tanda:.2f} {u}" for a, u, q in nombres
                         if q or a != t("Aditivo")))
    if total:
        f.append(f"{t('Total')} ({total:.2f} m3, {t('desperdicio')} {v['desp']:g} %): "
                 + ", ".join(f"{a} {q * k:.2f} {u}" for a, u, q in nombres
                             if q or a != t("Aditivo")))
        f.append(f"{t('Tandas')}: {math.ceil(k / tanda - 1e-9)}")
    tabla = api.Tabla([api.Columna(t("Material"), 32), api.Columna("", 10, "centro"),
                       api.Columna(t("Por m3"), 18, "derecha", 3),
                       api.Columna(t("Por tanda"), 18, "derecha", 3),
                       api.Columna(t("Total"), 22, "derecha", 2)], filas_t)
    partes = [piezas.Parte(t("CONCRETO"), "m3", filas, total)] if total else []
    return piezas.Calculo(partes, f, [], [tabla])
