# SPDX-License-Identifier: GPL-3.0-or-later
"""Materiales y mano de obra por partida (equipos dentro de la mano de obra)."""
import json
import re
from dataclasses import replace

from ingepresupuestos import api, piezas

from .textos import t


def registrar(app):
    app.accion("reparto", t("Reparto de subcontratos…"), configurar)
    app.reporte("mat-mo", t("Materiales y mano de obra"), reporte,
                ayuda=t("No altera precios ni totales"))


def clave(i):
    """Los ids cambian al llevar el proyecto a otro equipo; esto no."""
    return f"{i.codigo}|{i.descripcion}|{i.unidad}"


def subcontratos(p):
    """{clave: descripción} de los insumos SC de las partidas, en su orden."""
    out = {}
    for x in p.hojas():
        for i in x.acu_abierto:
            if i.tipo == "SC" and not i.es_subpartida:
                out.setdefault(clave(i), i.descripcion or i.codigo)
    return out


def propios(ajustes):
    """{clave: % de materiales} guardados; lo que no vale se ignora."""
    try:
        d = json.loads(ajustes.get("sc") or "{}")
    except (TypeError, ValueError, RecursionError):
        return {}
    return {k: float(v) for k, v in d.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
            and 0 <= v <= 100} if isinstance(d, dict) else {}


def leer_pct(texto):
    """None si está vacío (= el general)."""
    s = texto.strip().rstrip("%").strip()
    if not s:
        return None
    if not re.fullmatch(r"[0-9]{1,3}([.,][0-9]{1,4})?", s) \
            or float(s.replace(",", ".")) > 100:
        raise api.ErrorComplemento(t(
            "«{x}» no es un porcentaje de 0 a 100.").format(x=texto[:30]))
    return float(s.replace(",", "."))


def configurar(ctx):
    a, sc, guardados = ctx.ajustes, subcontratos(ctx.presupuesto), propios(ctx.ajustes)
    rotulos = {}                       # rótulo único: clave
    for k, desc in sc.items():
        r, n = desc[:70], 2
        while r in rotulos:
            r, n = f"{desc[:65]} ({n})", n + 1
        rotulos[r] = k
    campos = [
        api.Dato("repartir", t("Repartir los subcontratos"), "si_no",
                 a.get("repartir") is True),
        api.Dato("mat", t("Parte de materiales (general)"), sufijo="%", maximo=100,
                 valor=piezas.numero(a, "mat"))]
    if rotulos:
        campos.append(api.Dato(
            "sc", t("Porcentaje propio de un subcontrato"), "tabla",
            [{"insumo": r, "pct": f"{guardados[k]:g}" if k in guardados else ""}
             for r, k in rotulos.items()][:200],
            columnas=[
                api.Dato("insumo", t("Subcontrato"), "opcion",
                         opciones=tuple(rotulos)),
                api.Dato("pct", t("% materiales"), "texto",
                         ayuda=t("Vacío = el general"))]))
    while True:
        r = ctx.pedir_datos(
            t("Reparto de subcontratos"), campos,
            texto=t("El resto del subcontrato va a mano de obra. Sin repartir, quedan "
                    "en su propia columna."))
        if r is None:
            return
        campos = [replace(c, valor=r[c.clave]) for c in campos]
        try:
            nuevos = {k: v for k, v in guardados.items() if k in sc}
            vistos = set()
            for f in r.pop("sc", ()):
                k, v = rotulos[f["insumo"]], leer_pct(f["pct"])
                if k in vistos:
                    raise api.ErrorComplemento(t(
                        "«{x}» está dos veces.").format(x=f["insumo"]))
                vistos.add(k)
                nuevos.pop(k, None)
                if v is not None:
                    nuevos[k] = v
        except api.ErrorComplemento as e:
            ctx.avisar(str(e))
            continue
        # La fila que se quita vuelve al general.
        for k in list(rotulos.values())[:200]:
            if k not in vistos:
                nuevos.pop(k, None)
        ctx.guardar_ajustes({**r, "sc": json.dumps(nuevos, ensure_ascii=False)})
        return


def calcular(p, partida, pct_mat, propios=None):
    """{mat, mo, otros} por unidad; suman el precio unitario. `pct_mat` None =
    sin repartir; `propios`: {clave: %} de los subcontratos con el suyo."""
    v = {"mat": 0.0, "mo": 0.0, "otros": 0.0}
    for i in partida.acu_abierto:
        if i.tipo == "MAT":
            v["mat"] += i.parcial
        elif i.tipo in ("MO", "EQ"):
            v["mo"] += i.parcial
        elif pct_mat is None:
            v["otros"] += i.parcial
        else:
            m = (propios or {}).get(clave(i), pct_mat)
            v["mat"] += i.parcial * m / 100
            v["mo"] += i.parcial * (100 - m) / 100
    if not partida.acu:
        v["otros"] = partida.precio_unitario
    return piezas.cuadrar(v, partida.precio_unitario, p.decimales)


def reporte(p):
    hojas = p.hojas()
    if not hojas:
        raise api.ErrorComplemento(t("El presupuesto no tiene partidas."))
    repartir = p.ajustes.get("repartir") is True
    pm = piezas.numero(p.ajustes, "mat") if repartir else None
    d = p.decimales
    suyos = propios(p.ajustes) if repartir else {}
    v = {x.id: calcular(p, x, pm, suyos) for x in hojas}
    otros = any(c["otros"] for c in v.values())
    tit = piezas.sumar_titulos(p, {x.id: x.parcial for x in hojas})
    n = 7 + otros
    filas = []
    for x, sub in piezas.recorrer(p):
        if sub:
            filas.append(api.Fila([sub], "titulo"))
        if x.es_titulo:
            filas.append(api.Fila([x.item, x.descripcion, *[None] * (n - 2),
                                   tit[x.id]], "subtotal"))
            continue
        c = v[x.id]
        filas.append([x.item, x.descripcion, x.unidad, x.metrado, c["mat"], c["mo"],
                      *([c["otros"]] if otros else []), x.precio_unitario, x.parcial])
    filas.append(api.Fila([None, t("COSTO DIRECTO"), *[None] * (n - 2),
                           p.costo_directo], "subtotal"))
    cols = [api.Columna(t("Ítem"), 8), api.Columna(t("Descripción"), 32),
            api.Columna(t("Und."), 6, "centro"),
            api.Columna(t("Cantidad"), 10, "derecha", p.decimales_metrado)]
    cols += [api.Columna(x, 11, "derecha", d) for x in (
        t("Materiales"), t("Mano de obra"),
        *([t("Subcontratos y otros")] if otros else []), t("Parcial"), t("Total"))]
    notas = [t("Parcial = materiales + mano de obra. La mano de obra incluye los "
               "equipos.")]
    if repartir:
        sc = subcontratos(p)
        usados = {k: suyos.get(k, pm) for k in sc}
        if len(set(usados.values())) > 1:
            notas.append(t("Subcontratos repartidos con más de un porcentaje de "
                           "materiales (el resto es mano de obra): {que}.").format(
                que="; ".join(f"{sc[k][:50]} {piezas.pct(p, m)}"
                              for k, m in usados.items())))
        else:
            m = next(iter(usados.values()), pm)
            notas.append(t("Subcontratos repartidos: {a} materiales y {b} mano de "
                           "obra.").format(a=piezas.pct(p, m),
                                           b=piezas.pct(p, 100 - m)))
    elif otros:
        notas.append(t("Los subcontratos y las partidas sin análisis no se reparten."))
    notas.append(t("Reporte informativo: no altera los precios ni el total del "
                   "presupuesto."))
    return api.Documento(t("Materiales y mano de obra"), [
        api.Tabla(cols, filas), *[api.Parrafo(x) for x in notas]], horizontal=True)
