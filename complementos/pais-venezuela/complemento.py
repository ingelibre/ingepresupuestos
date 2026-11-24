# SPDX-License-Identifier: GPL-3.0-or-later
"""APU de Venezuela y partidas con código COVENIN desde un Excel del usuario."""
import csv
import re
import unicodedata

from ingepresupuestos import api, piezas

from .textos import t

BLOQUES = (("MAT", "MATERIALES"), ("EQ", "EQUIPOS"), ("MO", "MANO DE OBRA"),
           ("SC", "OTROS"))
DIA = {"día", "dia", "días", "dias", "jor", "jornada"}
HORA = {"hh", "hm", "he", "h-h", "h-m", "h-e", "jph", "jh", "h", "hr"}
CODIGO = re.compile(r"\b[A-Z]\.(?:\d{3}\.)?(?:\d{3}\.\d{3}|S/C)(?!\w)", re.I)
MAX_FILAS, MAX_PARTIDAS = 20000, 500


def registrar(app):
    app.accion("datos", t("Datos del APU de Venezuela…"), configurar)
    app.reporte("apu", t("APU de Venezuela"), reporte,
                ayuda=t("No altera precios ni totales"))
    app.importador("partidas", t("Partidas con código COVENIN (Excel o CSV)"),
                   importar, extensiones=("xlsx", "csv"))


def datos(a):
    return {"fcas": piezas.numero(a, "fcas", maximo=2000),
            "bono": piezas.numero(a, "bono", maximo=1e9),
            "admin": piezas.numero(a, "admin"),
            "utilidad": piezas.numero(a, "utilidad")}


def configurar(ctx):
    v = datos(ctx.ajustes)
    r = ctx.pedir_datos(t("Datos del APU de Venezuela"), [
        api.Dato("fcas", t("Prestaciones sociales (FCAS)"), valor=v["fcas"],
                 maximo=2000, sufijo="%"),
        api.Dato("bono", t("Bono de alimentación por trabajador y día"),
                 valor=v["bono"], maximo=1e9),
        api.Dato("admin", t("Administración y gastos generales"), valor=v["admin"],
                 maximo=100, sufijo="%"),
        api.Dato("utilidad", t("Utilidad e imprevistos"), valor=v["utilidad"],
                 maximo=100, sufijo="%")],
        texto=t("El precio de la mano de obra del proyecto ya debe incluir las "
                "prestaciones y el bono: el reporte solo los muestra por separado."))
    if r is not None:
        ctx.guardar_ajustes(r)


def mano_de_obra(partida, total, v, dec):
    """{base, prestaciones, bono} por unidad, que suman `total`; y si el bono
    no se pudo separar."""
    n = sum(i.cuadrilla for i in partida.acu
            if i.tipo == "MO" and not i.es_porcentaje)
    bono = v["bono"] * n / partida.rendimiento if partida.rendimiento > 0 else 0.0
    falta = v["bono"] > 0 and not 0 < bono < total
    if falta:
        bono = 0.0
    base = (total - bono) / (1 + v["fcas"] / 100)
    return piezas.cuadrar({"base": base, "prestaciones": total - bono - base,
                           "bono": bono}, total, dec), falta


def calcular(p, x, v):
    """Los subtotales por unidad suman el precio unitario."""
    ins = piezas.bloques_de(x, BLOQUES)
    sub = piezas.cuadrar({n: sum(i.parcial for i in li) for n, li in ins},
                         x.precio_unitario, p.decimales)
    mo, falta = mano_de_obra(x, sub.get("MANO DE OBRA", 0.0), v, p.decimales)
    adm = api.redondear(x.precio_unitario * v["admin"] / 100, p.decimales)
    con_adm = api.redondear(x.precio_unitario + adm, p.decimales)
    uti = api.redondear(con_adm * v["utilidad"] / 100, p.decimales)
    return {"insumos": ins, "sub": sub, "mo": mo, "falta": falta, "adm": adm,
            "con_adm": con_adm, "uti": uti,
            "precio": api.redondear(con_adm + uti, p.decimales)}


def linea(i, p, x):
    """[descripción, unidad, cantidad, costo, total al día, por unidad]"""
    u = i.unidad.strip().rstrip(".").lower()
    if i.tipo in ("MO", "EQ") and i.cuadrilla > 0 and x.rendimiento > 0 \
            and not i.es_porcentaje and (u in DIA or u in HORA or "hora" in u):
        costo = i.precio * (1 if u in DIA else p.jornada)
        return [i.descripcion, t("día"), i.cuadrilla, costo, i.cuadrilla * costo,
                i.parcial]
    return [i.descripcion, i.unidad, i.cantidad, i.precio, None, i.parcial]


def separar(descripcion):
    """(código COVENIN o «», descripción sin él)"""
    m = CODIGO.search(descripcion)
    if not m:
        return "", descripcion
    resto = (descripcion[:m.start()] + descripcion[m.end():]).strip(" -–—.:")
    return m.group().upper(), resto or descripcion


def reporte(p):
    hojas = p.hojas()
    if not hojas:
        raise api.ErrorComplemento(t("El presupuesto no tiene partidas."))
    v, d = datos(p.ajustes), p.decimales
    cols = [api.Columna(t("Descripción"), 38), api.Columna(t("Und."), 8, "centro"),
            api.Columna(t("Cantidad"), 12, "derecha", 4),
            *(api.Columna(x, 14, "derecha", d) for x in (
                t("Costo"), t("Total al día"), t("Por unidad")))]
    bloques = []
    for n, x in enumerate(hojas):
        c = calcular(p, x, v)
        codigo, desc = separar(x.descripcion)
        campos = [(t("Código COVENIN"), codigo or "S/C"), (t("Und."), x.unidad),
                  (t("Cantidad"), p.moneda.numero(x.metrado, p.decimales_metrado))]
        if x.rendimiento > 0:
            campos.append((t("Rendimiento"), t("{n} {u}/día").format(
                n=p.moneda.numero(x.rendimiento, 2), u=x.unidad)))
        filas = []
        for nombre, ins in c["insumos"]:
            filas.append(api.Fila([t(nombre)], "titulo"))
            filas += [linea(i, p, x) for i in ins]
            if nombre == "MANO DE OBRA" and (c["mo"]["prestaciones"] or c["mo"]["bono"]):
                for rotulo, k in (
                        (t("De ello: mano de obra directa"), "base"),
                        (t("Prestaciones sociales ({x})").format(
                            x=piezas.pct(p, v["fcas"])), "prestaciones"),
                        (t("Bono de alimentación"), "bono")):
                    if c["mo"][k]:
                        filas.append([rotulo, *[None] * 4, c["mo"][k]])
            filas.append(api.Fila([t("Unitario"), *[None] * 4, c["sub"][nombre]],
                                  "subtotal"))
        filas.append(api.Fila([t("COSTO DIRECTO POR UNIDAD"), *[None] * 4,
                               x.precio_unitario], "subtotal"))
        if c["precio"] != x.precio_unitario:
            filas += [
                [t("Administración y gastos generales ({x})").format(
                    x=piezas.pct(p, v["admin"])), *[None] * 4, c["adm"]],
                [t("Utilidad e imprevistos ({x})").format(
                    x=piezas.pct(p, v["utilidad"])), *[None] * 4, c["uti"]]]
            filas.append(api.Fila([t("PRECIO UNITARIO"), *[None] * 4, c["precio"]],
                                  "subtotal"))
        bloques += ([api.SaltoPagina()] if n else []) + [
            api.Titulo(f"{x.item}  {desc}", 2), api.Campos(campos),
            api.Tabla(cols, filas)]
        if c["falta"]:
            bloques.append(api.Parrafo(t(
                "El bono no se separó: falta el rendimiento o la cuadrilla, o supera "
                "la mano de obra.")))
    if v["admin"] or v["utilidad"]:
        bloques.append(api.Parrafo(t(
            "La administración y la utilidad son las de este reporte, no las del pie "
            "del presupuesto.")))
    bloques.append(api.Parrafo(t(
        "Reporte informativo: no altera los precios ni el total del presupuesto.")))
    return api.Documento(t("Análisis de precios unitarios"), bloques)


# ── Importar partidas ────────────────────────────────────────────────────────

def _norma(s):
    s = unicodedata.normalize("NFD", str(s if s is not None else ""))
    return "".join(c for c in s if not unicodedata.combining(c)).strip().lower()


def _hojas(ruta):
    """Las filas de cada hoja."""
    if ruta.lower().endswith(".csv"):
        with open(ruta, "rb") as f:
            crudo = f.read(20_000_000)
        try:
            txt = crudo.decode("utf-8-sig")
        except UnicodeDecodeError:
            txt = crudo.decode("cp1252", "replace")
        sep = max(";\t,", key=txt[:4000].count)
        return [list(csv.reader(txt.splitlines(), delimiter=sep))[:MAX_FILAS]]
    from openpyxl import load_workbook
    try:
        wb = load_workbook(ruta, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 — el lector lanza de todo
        raise api.ErrorComplemento(t("No se pudo leer el archivo.")) from None
    try:
        return [list(ws.iter_rows(values_only=True, max_row=MAX_FILAS))
                for ws in wb.worksheets]
    finally:
        wb.close()


def leer(ruta):
    """[(código, descripción, unidad)], sin repetidas."""
    out = {}
    for filas in _hojas(ruta):
        cols = None
        for f in filas:
            if cols is None:
                r = [_norma(c) for c in f]
                cols = [next((i for i, c in enumerate(r) if c.startswith(k)), None)
                        for k in ("codigo", "descripcion", "unidad")]
                if None in cols:
                    cols = None
                continue
            c, desc, und = (" ".join(str(f[i]).split()) if i < len(f)
                            and f[i] is not None else "" for i in cols)
            if desc and CODIGO.fullmatch(c):
                out[c.upper(), desc] = (c.upper(), desc, und.lower())
    return list(out.values())


def filtrar(partidas, inicio, contiene):
    ini, palabras = inicio.strip().upper(), _norma(contiene).split()
    return [x for x in partidas if x[0].startswith(ini)
            and all(w in _norma(x[1]) for w in palabras)]


def importar(ruta, ctx):
    todas = leer(ruta)
    if not todas:
        raise api.ErrorComplemento(t(
            "No hay partidas: se espera una fila con «Código», «Descripción» y "
            "«Unidad», y códigos como E.111.110.000."))
    inicio = contiene = ""
    while True:
        r = ctx.pedir_datos(t("Partidas con código COVENIN"), [
            api.Dato("inicio", t("El código empieza por"), "texto", inicio,
                     ayuda=t("Vacío = todos")),
            api.Dato("contiene", t("La descripción contiene"), "texto", contiene,
                     ayuda=t("Vacío = todas"))],
            texto=t("{n} partidas en el archivo. Entran sin metrado, sin precio y sin "
                    "análisis.").format(n=len(todas)))
        if r is None:
            return []
        inicio, contiene = r["inicio"], r["contiene"]
        elegidas = filtrar(todas, inicio, contiene)
        if 0 < len(elegidas) <= MAX_PARTIDAS:
            return [api.PartidaNueva(f"{c} {desc}"[:500], und)
                    for c, desc, und in elegidas]
        ctx.avisar(t("Salen {n} partidas; se admiten de 1 a {m} por vez.").format(
            n=len(elegidas), m=MAX_PARTIDAS))
