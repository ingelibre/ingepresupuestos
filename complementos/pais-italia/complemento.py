# SPDX-License-Identifier: GPL-3.0-or-later
"""Analisi dei prezzi, computo metrico, elenco prezzi e quadro economico.

Solo reportes: ni las spese generali ni el utile entran en el presupuesto.
"""
from ingepresupuestos import api, piezas

from .textos import t

BLOCCHI = (("MAT", "MATERIALI"), ("MO", "MANODOPERA"),
           ("EQ", "NOLI E TRASPORTI"), ("SC", "SUBAPPALTI E ALTRO"))
SG_MIN, SG_MAX, UTILE = 13.0, 17.0, 10.0
LIBERO = "Documento informativo: non modifica i prezzi né il totale del progetto."


def registrar(app):
    app.accion("datos", t("Spese generali, utile, seguridad e IVA…"), configurar)
    ayuda = t("No altera precios ni totales")
    app.reporte("analisi", "Analisi dei Prezzi", analisi, ayuda=ayuda)
    app.reporte("computo", "Computo Metrico Estimativo", computo, ayuda=ayuda)
    app.reporte("elenco", "Elenco Prezzi Unitari", elenco, ayuda=ayuda)
    app.reporte("quadro", "Quadro Economico", quadro, ayuda=ayuda)


def valores(a):
    return {"sg": piezas.numero(a, "sg", SG_MIN), "utile": piezas.numero(a, "utile", UTILE),
            "sicurezza": piezas.numero(a, "sicurezza", 0.0, 0, 1e12),
            "ribasso": piezas.numero(a, "ribasso"), "iva": piezas.numero(a, "iva")}


def configurar(ctx):
    v = valores(ctx.ajustes)
    r = ctx.pedir_datos(
        t("Spese generali, utile, seguridad e IVA"),
        [api.Dato("sg", "Spese generali", valor=v["sg"], maximo=100, sufijo="%",
                  ayuda="13–17 %"),
         api.Dato("utile", "Utile d'impresa", valor=v["utile"], maximo=100, sufijo="%"),
         api.Dato("sicurezza", t("Costi della sicurezza (no rebajables)"),
                  valor=v["sicurezza"], sufijo=ctx.presupuesto.moneda.simbolo),
         api.Dato("ribasso", "Ribasso", valor=v["ribasso"], maximo=100, decimales=4,
                  sufijo="%"),
         api.Dato("iva", "IVA", valor=v["iva"], maximo=100, sufijo="%")],
        texto=t("El IVA y los costes de seguridad empiezan en 0: escríbelos tú."))
    if r is not None:
        ctx.guardar_ajustes(r)


def prezzo(cd, v, dec):
    """(costo diretto, spese generali, utile, prezzo). L'utile va su costo + spese."""
    cd = api.redondear(cd, dec)
    sg = api.redondear(cd * v["sg"] / 100, dec)
    ut = api.redondear((cd + sg) * v["utile"] / 100, dec)
    return cd, sg, ut, api.redondear(cd + sg + ut, dec)


def prezzi(p):
    """{id: (prezzo, importo)}"""
    v = valores(p.ajustes)
    out = {}
    for x in p.hojas():
        pr = prezzo(x.precio_unitario, v, p.decimales)[3]
        out[x.id] = (pr, p.importe(x, pr))
    if not out:
        raise api.ErrorComplemento(t("El presupuesto no tiene partidas."))
    return out


def analisi(p):
    prezzi(p)
    v, d = valores(p.ajustes), p.decimales
    cols = [api.Columna("Descrizione", 46), api.Columna("U.M.", 9, "centro"),
            api.Columna("Quantità", 13, "derecha", 4),
            api.Columna("Prezzo", 15, "derecha", d),
            api.Columna("Importo", 17, "derecha", d)]
    bl = [api.Parrafo(LIBERO)]
    if not SG_MIN <= v["sg"] <= SG_MAX:
        bl.append(api.Parrafo("Attenzione: spese generali fuori dall'intervallo "
                              "13–17 %.", negrita=True))
    for x in p.hojas():
        cd, sg, ut, pr = prezzo(x.precio_unitario, v, d)
        filas, suma = [], 0.0
        for nombre, ins in piezas.bloques_de(x, BLOCCHI):
            filas.append(api.Fila([nombre], "titulo"))
            filas += [[i.descripcion, i.unidad, i.cantidad, i.precio, i.parcial]
                      for i in ins]
            suma += sum(i.parcial for i in ins)
        dif = api.redondear(cd - suma, d)
        if x.acu and dif:
            filas.append(["Arrotondamento", None, None, None, dif])
        filas += [api.Fila(["Costo diretto (A)", None, None, None, cd], "subtotal"),
                  [f"Spese generali ({piezas.pct(p, v['sg'])} di A) (B)",
                   None, None, None, sg],
                  [f"Utile d'impresa ({piezas.pct(p, v['utile'])} di A + B)",
                   None, None, None, ut],
                  api.Fila(["PREZZO UNITARIO", None, None, None, pr], "subtotal")]
        bl += [api.Titulo(f"{x.item}  {x.descripcion}", 2),
               api.Campos([("U.M.", x.unidad)]), api.Tabla(cols, filas)]
    return api.Documento("Analisi dei Prezzi", bl)


def computo(p):
    pr = prezzi(p)
    imp = {k: v[1] for k, v in pr.items()}
    d = p.decimales
    tot = api.redondear(sum(imp.values()), d)
    return api.Documento("Computo Metrico Estimativo", [
        piezas.mediciones(p, {k: v[0] for k, v in pr.items()}, imp,
                          ["Nr.", "Designazione", "Par.ug.", "Lung.", "Larg.",
                           "Alt.", "Parziale", "Quantità", "Prezzo", "Importo"]),
        api.Campos([("Importo dei lavori", p.moneda.formato(tot, d))]),
        api.Parrafo(LIBERO)])


def elenco(p):
    pr = prezzi(p)
    d = p.decimales
    filas = [[x.item, x.descripcion + ("\n" + x.especificacion if x.especificacion
                                       else ""), x.unidad, pr[x.id][0]]
             for x in p.hojas()]
    return api.Documento("Elenco Prezzi Unitari", [
        api.Tabla([api.Columna("Nr.", 10), api.Columna("Descrizione", 60),
                   api.Columna("U.M.", 10, "centro"),
                   api.Columna("Prezzo", 20, "derecha", d)], filas),
        api.Parrafo(LIBERO)])


def conti(p):
    """Le cifre del quadro economico."""
    v, d = valores(p.ajustes), p.decimales
    r = api.redondear
    lavori = r(sum(x[1] for x in prezzi(p).values()), d)
    sic = r(v["sicurezza"], d)
    rib = r(lavori * v["ribasso"] / 100, d)
    netto = r(lavori - rib, d)
    contratto = r(netto + sic, d)
    iva = r(contratto * v["iva"] / 100, d)
    return {"lavori": lavori, "sicurezza": sic, "base": r(lavori + sic, d),
            "ribasso": rib, "netto": netto, "contratto": contratto, "iva": iva,
            "totale": r(contratto + iva, d)}


def quadro(p):
    c, v, d = conti(p), valores(p.ajustes), p.decimales
    S = "subtotal"
    filas = [
        ["A.1", "Lavori soggetti a ribasso", c["lavori"]],
        ["A.2", "Costi della sicurezza non soggetti a ribasso", c["sicurezza"]],
        api.Fila(["A", "Importo a base d'asta", c["base"]], S),
        [None, f"Ribasso ({piezas.pct(p, v['ribasso'])} di A.1)", -c["ribasso"]],
        [None, "Lavori al netto del ribasso", c["netto"]],
        api.Fila([None, "Importo contrattuale (netto + sicurezza)", c["contratto"]], S),
        ["B", f"IVA ({piezas.pct(p, v['iva'])})", c["iva"]],
        api.Fila([None, "TOTALE (A netto + B)", c["totale"]], S)]
    return api.Documento("Quadro Economico", [
        api.Tabla([api.Columna("", 8), api.Columna("Voce", 67),
                   api.Columna("Importo", 25, "derecha", d)], filas),
        api.Parrafo("I costi della sicurezza si sommano ai lavori e non hanno ribasso."),
        api.Parrafo(LIBERO)])
