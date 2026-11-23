# SPDX-License-Identifier: GPL-3.0-or-later
"""BDI pela fórmula do Acórdão 2622/2013 do TCU e planilha orçamentária (issue #21).

O percentual se calcula aqui e se copia à mão no fechamento do orçamento: nada
disto altera o projeto.
"""
from ingepresupuestos import api, piezas

from .textos import t

#: (chave, nome, inicial, 1.º quartil, médio, 3.º quartil) do exemplo do issue.
PARCELAS = (
    ("ac", "Administração central (AC)", 3.0, 3.0, 4.0, 5.5),
    ("sg", "Seguros e garantias (S + G)", 0.8, 0.8, 0.8, 1.0),
    ("r", "Riscos (R)", 0.97, 0.97, 1.27, 1.27),
    ("df", "Despesas financeiras (DF)", 0.59, 0.59, 1.23, 1.39),
    ("l", "Lucro (L)", 7.4, 6.16, 7.4, 8.96),
)
TRIBUTOS = (("pis", "PIS", 0.65), ("cofins", "COFINS", 3.0), ("iss", "ISS", 3.0),
            ("cprb", "CPRB", 0.0))
NO_PU, NO_PARCIAL = "PU × (1 + BDI), arredondado", "(quantidade × PU) × (1 + BDI)"
LIVRE = ("Relatório informativo: não altera os preços nem o total do orçamento. O "
         "percentual se copia à mão no fechamento.")


def registrar(app):
    app.accion("bdi", t("Calcular BDI (TCU Ac. 2622/2013)…"), configurar)
    app.reporte("composicao", "Composição do BDI", composicao)
    app.reporte("planilha", "Planilha orçamentária com BDI", planilha,
                ayuda=t("No altera precios ni totales"))
    app.validador("bdi-faixa", t("BDI dentro de las referencias"), validar)


def valores(a):
    v = {c: piezas.numero(a, c, ini) for c, _n, ini, *_q in PARCELAS}
    v.update({c: piezas.numero(a, c, ini, 0, 20) for c, _n, ini in TRIBUTOS})
    v["modo"] = NO_PARCIAL if a.get("modo") == NO_PARCIAL else NO_PU
    v["feito"] = a.get("feito") is True
    return v


def calcular(v):
    """(BDI %, T %)"""
    f = {k: x / 100 for k, x in v.items() if not isinstance(x, (bool, str))}
    tributos = sum(f[c] for c, _n, _i in TRIBUTOS)
    bdi = ((1 + f["ac"] + f["sg"] + f["r"]) * (1 + f["df"]) * (1 + f["l"])
           / (1 - tributos) - 1)
    return api.redondear(bdi * 100, 2), api.redondear(tributos * 100, 4)


def configurar(ctx):
    v = valores(ctx.ajustes)
    r = ctx.pedir_datos(
        t("Calcular BDI (TCU Ac. 2622/2013)"),
        [api.Dato(c, n, valor=v[c], maximo=100, sufijo="%",
                  ayuda=f"{q1:g} / {q2:g} / {q3:g} %")
         for c, n, _i, q1, q2, q3 in PARCELAS]
        + [api.Dato(c, n, valor=v[c], maximo=20, sufijo="%") for c, n, _i in TRIBUTOS]
        + [api.Dato("modo", t("Aplicar el BDI en"), "opcion", v["modo"],
                    opciones=(NO_PU, NO_PARCIAL))],
        texto=t("Los valores iniciales son los de un ejemplo: revísalos. La ayuda de "
                "cada campo trae el 1.º cuartil, el medio y el 3.º."))
    if r is None:
        return
    r["feito"] = True
    ctx.guardar_ajustes(r)
    avisos = fora(valores(r))
    ctx.avisar("\n".join([
        f"BDI = {piezas.pct(ctx.presupuesto, calcular(valores(r))[0])}",
        t("Cópialo a mano en el pie del presupuesto."), *avisos]))


def fora(v):
    return [t("{que}: {v} % está fuera de la referencia ({a} a {b} %).").format(
        que=n, v=f"{v[c]:g}", a=f"{q1:g}", b=f"{q3:g}")
        for c, n, _i, q1, _q2, q3 in PARCELAS if not q1 <= v[c] <= q3]


def validar(p):
    v = valores(p.ajustes)
    return [api.Aviso(x) for x in fora(v)] if v["feito"] else []


def _prontos(p):
    v = valores(p.ajustes)
    if not v["feito"]:
        raise api.ErrorComplemento(t("Primero calcula el BDI en Complementos."))
    return v


def composicao(p):
    v = _prontos(p)
    bdi, trib = calcular(v)
    def g(x):
        return piezas.pct(p, x)

    filas = [[n, q1, q2, q3, v[c]] for c, n, _i, q1, q2, q3 in PARCELAS]
    filas += [[n, None, None, None, v[c]] for c, n, _i in TRIBUTOS]
    filas.append(api.Fila(["Tributos (T)", None, None, None, trib], "subtotal"))
    filas.append(api.Fila(["BDI", None, None, None, bdi], "subtotal"))
    pc = [api.Columna(x, 14, "derecha", 2)
          for x in ("1.º quartil (%)", "Médio (%)", "3.º quartil (%)", "Adotado (%)")]
    conta = (f"BDI = [(1 + {g(v['ac'])} + {g(v['sg'])} + {g(v['r'])}) × "
             f"(1 + {g(v['df'])}) × (1 + {g(v['l'])})] / (1 − {g(trib)}) − 1 = "
             f"{piezas.pct(p, bdi)}")
    return api.Documento("Composição do BDI", [
        api.Parrafo(LIVRE),
        api.Tabla([api.Columna("Parcela", 44), *pc], filas),
        api.Parrafo("BDI = [(1 + AC + S + R + G) × (1 + DF) × (1 + L)] / (1 − T) − 1"),
        api.Parrafo(conta, negrita=True),
        api.Parrafo("Fórmula do Acórdão 2622/2013 do TCU. Referências de um exemplo de "
                    "edital: confira as que valem para o seu tipo de obra."),
        *[api.Parrafo(x) for x in fora(v)]])


def linhas(p, v):
    """{id: (PU com BDI, total)} e o BDI."""
    bdi, _t = calcular(v)
    out = {}
    for x in p.hojas():
        pu = api.redondear(x.precio_unitario * (1 + bdi / 100), p.decimales)
        if v["modo"] == NO_PU:
            total = p.importe(x, pu)
        else:
            total = api.redondear(api.redondear(x.metrado, p.decimales_metrado)
                                  * x.precio_unitario * (1 + bdi / 100), p.decimales)
        out[x.id] = (pu, total)
    return out, bdi


def planilha(p):
    v = _prontos(p)
    lin, bdi = linhas(p, v)
    d = p.decimales
    totais = {k: x[1] for k, x in lin.items()}
    tit = piezas.sumar_titulos(p, totais)
    filas = []
    for x, sub in piezas.recorrer(p):
        if sub:
            filas.append(api.Fila([sub], "titulo"))
        if x.es_titulo:
            filas.append(api.Fila([x.item, x.descripcion, *[None] * 4, tit[x.id]],
                                  "subtotal"))
        else:
            filas.append([x.item, x.descripcion, x.unidad, x.metrado,
                          x.precio_unitario, *lin[x.id]])
    total = api.redondear(sum(totais.values()), d)
    filas.append(api.Fila([None, "TOTAL", *[None] * 4, total], "subtotal"))
    m = p.moneda.formato
    return api.Documento("Planilha orçamentária", [
        api.Parrafo(LIVRE),
        api.Campos([("BDI", piezas.pct(p, bdi)), ("Critério", v["modo"])]),
        api.Tabla([api.Columna("Item", 9), api.Columna("Descrição", 35),
                   api.Columna("Un.", 6, "centro"),
                   api.Columna("Quant.", 11, "derecha", p.decimales_metrado),
                   api.Columna("PU sem BDI", 12, "derecha", d),
                   api.Columna("PU com BDI", 12, "derecha", d),
                   api.Columna("Total", 15, "derecha", d)], filas),
        api.Campos([("Custo direto", m(p.costo_directo, d)),
                    ("Total da planilha", m(total, d)),
                    ("Total do orçamento", m(p.total, d)),
                    ("Diferença", m(api.redondear(total - p.total, d), d))])],
        horizontal=True)
