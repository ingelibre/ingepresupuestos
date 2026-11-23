# SPDX-License-Identifier: GPL-3.0-or-later
"""Acero de columnas y vigas con la distribución de estribos escrita en el plano.

Solo mide: no diseña ni verifica la estructura. La gramática está en
`leer_distribucion`; lo que no se entiende se dice, nunca se adivina.
"""
import math
import re
from fractions import Fraction

from ingepresupuestos import api, piezas

from .textos import t

DENSIDAD = 7850.0
EPS = 1e-6


def registrar(app):
    app.accion("acero", t("Acero de columnas y vigas…"), agregar,
               ayuda=t("Estribos y barras, como salen en el plano"))
    app.reporte("acero", t("Metrado de acero"), reporte)


def agregar(ctx):
    piezas.metrar(ctx, t("Acero de columnas y vigas"), campos(), calcular, t(AVISO))


def reporte(p):
    return piezas.reporte_metrado(p, t("Metrado de acero"), campos(), calcular,
                                  t(AVISO))


AVISO = ("Solo mide: no diseña ni verifica la estructura. Ganchos, anclajes y "
         "traslapes son los que escribes tú (empiezan en 0).")
AMBOS, UNO = "Ambos extremos", "Un extremo"


def campos():
    def m(clave, titulo, v=0.0, maximo=1000.0, sufijo="m", dec=3, ayuda=""):
        return api.Dato(clave, t(titulo), "numero", v, 0.0, maximo, dec, sufijo=sufijo,
                        ayuda=t(ayuda) if ayuda else "")

    def e(clave, titulo, v=1, minimo=0, ayuda=""):
        return api.Dato(clave, t(titulo), "entero", v, minimo, 100000,
                        ayuda=t(ayuda) if ayuda else "")

    def s(clave, titulo, v="", ayuda=""):
        return api.Dato(clave, t(titulo), "texto", v, ayuda=t(ayuda) if ayuda else "")
    est = [s("nombre", "Elemento"), e("n", "Iguales", 1, 1),
           e("tramos", "Tramos o pisos", 1, 1), m("luz", "Luz libre"),
           m("b", "b", 25.0, 500, "cm", 2), m("h", "h", 25.0, 500, "cm", 2),
           m("recub", "Recubrimiento", 4.0, 50, "cm", 2),
           s("dist", "Distribución", "", "Por ejemplo: 3/8\" 1@.05, 8@.10, R@.20 c/ext"),
           s("diam", "Ø", "", "Solo si no está en la distribución: 3/8\", 8 mm…"),
           api.Dato("ext", t("Si no dice c/ext"), "opcion", t(AMBOS),
                    opciones=(t(AMBOS), t(UNO))),
           m("gancho", "Gancho", 0.0, 2, ayuda="Cada estribo lleva dos"),
           e("grapas", "Grapas por estribo", 0), m("lgrapa", "Largo de grapa", 0.0, 10)]
    lon = [s("nombre", "Elemento"), e("n", "Iguales", 1, 1), e("barras", "Barras", 4, 1),
           s("diam", "Ø"), m("largo", "Longitud"),
           m("ancla", "Anclajes (total)", 0.0, 50), e("ntras", "Traslapes", 0),
           m("ltras", "Largo de traslape", 0.0, 10)]
    return [api.Dato("estribos", t("Estribos"), "tabla", [{}], columnas=est),
            api.Dato("barras", t("Barras longitudinales"), "tabla", [], columnas=lon),
            m("varilla", "Largo de la varilla", 9.0, 30),
            m("desp", "Desperdicio", 0.0, 50, "%", 2)]


# ── Lo que se lee ────────────────────────────────────────────────────────────

# En «1@5,8@.10» la coma separa grupos: un decimal no va seguido de «@».
_NUM = r"(?:\d+(?:[.,]\d+(?!\d*\s*(?:@|(?:a|c/)\s*[\d.,])))?|[.,]\d+)"
_FRAC = r"\d+\s*[- ]\s*\d+/\d+|\d+/\d+|\d+(?=\s*(?:\"|''|”))"
_DIAM = rf"(?:[øØφΦ]?\s*(?P<pulg>{_FRAC})\s*(?:\"|''|”)?" \
        rf"|[øØφΦ]\s*(?P<mm1>\d+)(?:\s*mm)?|(?P<mm2>\d+)\s*mm)"
_GRUPO = rf"(?:\d+|r(?:esto|to)?\.?)\s*(?:@|a|c/)\s*{_NUM}\s*(?:cm|mm|m)?"
_SEP = r"\s*(?:[,;+]|\s)\s*"
_EXT = r"(?P<ext>c/?\s*e(?:xt(?:remo)?)?\.?|c\.\s*ext\.?|(?:en\s+)?cada\s+extremo" \
       r"|(?:en\s+)?ambos\s+extremos|(?P<uno>(?:en\s+)?un\s+extremo))"
_TODO = re.compile(
    rf"(?:(?P<juegos>\d+)\s*(?=\[|□))?(?:estribos?|est\.|\[\s*\]|□)?\s*"
    rf"(?:estribos?\s*)?(?:{_DIAM}(?:\s*[:,;]\s*|\s+|(?<=[\"”'])))?"
    rf"[:]?\s*(?P<grupos>{_GRUPO}(?:{_SEP}{_GRUPO})*)(?:[\s,;]*{_EXT})?\s*\.?",
    re.IGNORECASE)


def _n(s):
    return float(s.replace(",", "."))


def leer_diametro(texto):
    """'1/2"' | '10' (mm), como en la planilla. Un 1 suelto no se adivina."""
    s = texto.strip().lower()
    m = re.fullmatch(_DIAM, s, re.IGNORECASE)
    if m and (m["pulg"]):
        return _pulgadas(m["pulg"])
    mm = (m and (m["mm1"] or m["mm2"])) or (
        s if re.fullmatch(r"\d+", s) else None)
    if mm and 4 <= int(mm) <= 60:
        return str(int(mm))
    raise api.ErrorComplemento(t(
        "No se entiende el diámetro «{x}». Escribe 3/8\", 1\", 8 mm o Ø10.").format(
            x=texto[:40]))


def _pulgadas(s):
    s = re.sub(r"\s*[- ]\s*", "-", s.strip())
    mm = _mm(s + '"') if not s.endswith("/0") else 0
    if not 4 <= mm <= 60:
        raise api.ErrorComplemento(t(
            "No se entiende el diámetro «{x}». Escribe 3/8\", 1\", 8 mm o Ø10.").format(
                x=s))
    return s + '"'


def _mm(d):
    if not d.endswith('"'):
        return float(d)
    partes = d[:-1].split("-")
    return float(sum(Fraction(x) for x in partes)) * 25.4


def peso(d):
    """(kg/m, True si es de la tabla del programa)"""
    k = api.acero_kg_m(d)
    if k:
        return k, True
    return math.pi / 4 * (_mm(d) / 1000) ** 2 * DENSIDAD, False


def leer_distribucion(texto):
    """{juegos, diam, grupos [(n, m)], resto m|None, ext 'ambos'|'uno'|None}

        [N][] Ø : n@s, n@s, R@s  c/ext

    `@` puede ser «a» o «c/»; el separador, coma, punto y coma, + o espacio; el
    decimal, punto o coma. Sin unidad, `s` va en metros (hasta 1). «R», «resto»
    va al final y una sola vez."""
    original = " ".join((texto or "").split())

    def mal(por=""):
        return api.ErrorComplemento(t(
            "No se entiende «{x}». {por}Ejemplo: 3/8\" 1@.05, 8@.10, R@.20 c/ext").format(
                x=original[:80], por=por + " " if por else ""))
    if not original or len(original) > 200:
        raise mal()
    m = _TODO.fullmatch(original)
    if not m:
        raise mal()
    pulg, mm = m["pulg"], m["mm1"] or m["mm2"]
    diam = _pulgadas(pulg) if pulg else leer_diametro(mm + " mm") if mm else None
    grupos, resto = [], None
    for g in re.finditer(rf"(\d+|r[a-z]*\.?)\s*(?:@|a|c/)\s*({_NUM})\s*(cm|mm|m)?",
                         m["grupos"], re.IGNORECASE):
        s = _n(g[2]) / {"cm": 100, "mm": 1000}.get((g[3] or "").lower(), 1)
        if s > 1 and not g[3]:
            raise mal(t("{s} sin unidad serían metros: escribe «{s} cm».").format(s=g[2]))
        if not 0.005 <= s <= 1:
            raise mal(t("La separación debe estar entre 0,5 cm y 1 m."))
        if resto is not None:
            raise mal(t("El resto va al final y una sola vez."))
        if g[1][0].isdigit():
            if not 1 <= int(g[1]) <= 500:
                raise mal(t("La cantidad debe estar entre 1 y 500."))
            grupos.append((int(g[1]), s))
        else:
            resto = s
    juegos = int(m["juegos"] or 1)
    if not 1 <= juegos <= 20:
        raise mal()
    return {"juegos": juegos, "diam": diam, "grupos": grupos, "resto": resto,
            "ext": None if not m["ext"] else "uno" if m["uno"] else "ambos"}


def posiciones(luz, grupos, resto, ambos):
    """Distancias desde la cara, en m. El resto va en espacios iguales no mayores
    que `resto`. En el centro, dos estribos coincidentes cuentan uno."""
    ini, x = [], 0.0
    for n, s in grupos:
        for _ in range(n):
            x += s
            ini.append(x)
    ocupa = 2 * x if ambos else x
    if ocupa > luz + EPS:
        raise api.ErrorComplemento(t(
            "Los estribos fijos ocupan {a} m y la luz es de {b} m: no caben. Cambia la "
            "distribución.").format(a=f"{ocupa:.3f}", b=f"{luz:.3f}"))
    fin = [luz - v for v in reversed(ini)] if ambos else []
    if fin and abs(fin[0] - ini[-1]) < EPS:
        fin = fin[1:]
    medio = []
    hueco = luz - ocupa
    if resto and hueco > EPS:
        k = math.ceil(hueco / resto - EPS)
        medio = [x + hueco * i / k for i in range(1, k)]
        if len(medio) > 5000:
            raise api.ErrorComplemento(t("Son demasiados estribos: revisa la luz."))
    return ini + medio + fin


# ── Las cuentas ──────────────────────────────────────────────────────────────

def calcular(v):
    formulas, avisos, filas, resumen = [], [], [], {}

    def anotar(desc, d, est, ele, veces, largo):
        k, _tabla = peso(d)
        filas.append(api.FilaMetrado(desc, est, ele, veces, largo=largo, diametro=d,
                                     kg_m=k))
        r = resumen.setdefault(d, [0.0, 0.0])
        total = est * (ele or 1) * veces * largo
        r[0] += total
        r[1] += api.redondear(api.redondear(total, 4) * k, 4)
        return total * k

    for n, f in enumerate(v["estribos"], 1):
        if not f.get("dist", "").strip() and not f.get("luz"):
            continue                                    # fila en blanco
        nombre = f["nombre"].strip() or str(n)
        try:
            formulas += _estribos(f, nombre, anotar, avisos)
        except api.ErrorComplemento as e:
            raise api.ErrorComplemento(f"{t('Estribos')} «{nombre}»: {e}") from None
    for n, f in enumerate(v["barras"], 1):
        if not f.get("diam", "").strip() and not f.get("largo"):
            continue
        nombre = f["nombre"].strip() or str(n)
        try:
            d = leer_diametro(f["diam"])
        except api.ErrorComplemento as e:
            raise api.ErrorComplemento(f"{t('Barras')} «{nombre}»: {e}") from None
        largo = f["largo"] + f["ancla"] + f["ntras"] * f["ltras"]
        if largo <= 0:
            raise api.ErrorComplemento(f"{t('Barras')} «{nombre}»: "
                                       + t("falta la longitud."))
        kg = anotar(f"{nombre} {t('longitudinal')}", d, f["n"], None, f["barras"], largo)
        formulas.append(
            f"{nombre}: {f['n']} × {f['barras']} Ø{d} × ({f['largo']:g} + {f['ancla']:g}"
            f" + {f['ntras']} × {f['ltras']:g}) = {f['n'] * f['barras']} × {largo:.3f} m"
            f" = {kg:.2f} kg")
        piezas_ = math.ceil(largo / v["varilla"] - EPS) if v["varilla"] else 1
        if piezas_ - 1 > f["ntras"]:
            avisos.append(t("{x}: la barra de {l} m necesita {n} piezas de varilla y "
                            "hay {k} traslapes.").format(
                x=nombre, l=f"{largo:.2f}", n=piezas_, k=f["ntras"]))
    if not filas:
        raise api.ErrorComplemento(t("Escribe al menos un estribo o una barra."))
    if not v["varilla"]:
        raise api.ErrorComplemento(t("Falta el largo de la varilla."))
    orden = sorted(resumen, key=_mm)
    tabla, total, con = [], 0.0, 0.0
    for d in orden:
        m, kg = resumen[d]
        k, de_tabla = peso(d)
        total += kg
        ckg = kg * (1 + v["desp"] / 100)
        con += ckg
        var = math.ceil(m * (1 + v["desp"] / 100) / v["varilla"] - EPS)
        origen = t("tabla del programa") if de_tabla else "π/4·d²·7850"
        tabla.append(["Ø" + d, m, k, origen, kg, ckg, var])
        formulas.append(f"Ø{d}: {m:.2f} m × {k:.4f} kg/m ({origen}) = {kg:.2f} kg; "
                        + t("con {p} % de desperdicio, {kg} kg = {n} varillas de {l} m")
                        .format(p=f"{v['desp']:g}", kg=f"{ckg:.2f}", n=var,
                                l=f"{v['varilla']:g}"))
    tabla.append(api.Fila([t("TOTAL"), None, None, None, total, con, None], "subtotal"))
    avisos.append(t("Las varillas salen de los metros, sin optimizar el corte. El "
                    "desperdicio no entra en la planilla."))
    total = api.redondear(total, 2)
    formulas.append(f"{t('TOTAL')}: {total:.2f} kg")
    bloque = api.Tabla([api.Columna("Ø", 12), api.Columna("m", 14, "derecha", 2),
                        api.Columna("kg/m", 12, "derecha", 4),
                        api.Columna(t("Origen del peso"), 22),
                        api.Columna("kg", 14, "derecha", 2),
                        api.Columna(t("kg con desperdicio"), 14, "derecha", 2),
                        api.Columna(t("Varillas"), 12, "derecha", 0)], tabla)
    return piezas.Calculo([piezas.Parte(t("ACERO DE REFUERZO"), "kg", filas, total)],
                          formulas, avisos, [bloque])


def _estribos(f, nombre, anotar, avisos):
    x = leer_distribucion(f["dist"])
    d = leer_diametro(f["diam"]) if f["diam"].strip() else None
    if x["diam"] and d and x["diam"] != d:
        raise api.ErrorComplemento(t(
            "la distribución dice Ø{a} y la columna Ø dice {b}.").format(a=x["diam"], b=d))
    d = x["diam"] or d
    if not d:
        raise api.ErrorComplemento(t("falta el diámetro del estribo."))
    if f["luz"] <= 0:
        raise api.ErrorComplemento(t("falta la luz libre."))
    b, h, r = f["b"] / 100, f["h"] / 100, f["recub"] / 100
    if 2 * r >= min(b, h):
        raise api.ErrorComplemento(t("el recubrimiento no cabe en la sección."))
    ambos = x["ext"] == "ambos" if x["ext"] else f["ext"] != t(UNO)
    pos = posiciones(f["luz"], x["grupos"], x["resto"], ambos)
    if x["resto"] is None:
        avisos.append(t("{x}: sin «resto», entre los extremos no hay estribos.").format(
            x=nombre) if ambos else t(
            "{x}: sin «resto», tras el último grupo no hay estribos.").format(x=nombre))
    if not pos:
        raise api.ErrorComplemento(t("en esa luz no cabe ningún estribo."))
    largo = 2 * (b - 2 * r) + 2 * (h - 2 * r) + 2 * f["gancho"]
    veces = len(pos) * x["juegos"]
    kg = anotar(f"{nombre} {t('estribos')}", d, f["n"], f["tramos"], veces, largo)
    out = [f"{nombre}: {t(AMBOS) if ambos else t(UNO)}, {t('luz')} {f['luz']:g} m → "
           f"{len(pos)} {t('estribos')}"
           + (f" × {x['juegos']}" if x["juegos"] > 1 else ""),
           f"   {t('Posiciones')} (m): " + ", ".join(f"{p:.3f}" for p in pos),
           f"   {t('Largo')}: 2 × ({b:g} − 2 × {r:g}) + 2 × ({h:g} − 2 × {r:g}) + 2 × "
           f"{f['gancho']:g} = {largo:.3f} m",
           f"   {f['n']} × {f['tramos']} × {veces} Ø{d} × {largo:.3f} m = {kg:.2f} kg"]
    if f["grapas"]:
        if f["lgrapa"] <= 0:
            raise api.ErrorComplemento(t("falta el largo de la grapa."))
        g = len(pos) * f["grapas"]
        kg = anotar(f"{nombre} {t('grapas')}", d, f["n"], f["tramos"], g, f["lgrapa"])
        out.append(f"   {t('grapas')}: {f['n']} × {f['tramos']} × {g} Ø{d} × "
                   f"{f['lgrapa']:g} m = {kg:.2f} kg")
    return out
