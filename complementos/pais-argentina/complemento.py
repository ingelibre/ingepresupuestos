# SPDX-License-Identifier: GPL-3.0-or-later
"""Materiales y mano de obra por partida (equipos dentro de la mano de obra)."""
import json
import re
from dataclasses import replace

from ingepresupuestos import api, piezas

from .textos import t


def registrar(app):
    app.accion("reparto", t("Reparto de subcontratos…"), configurar)
    app.reporte("acu", t("Análisis de precios con subtotales"), analisis,
                ayuda=t("No altera precios ni totales"))
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


def importes(ajustes):
    """{clave: (materiales, mano de obra)} escritos en moneda."""
    try:
        d = json.loads(ajustes.get("sc_importes") or "{}")
    except (TypeError, ValueError, RecursionError):
        return {}
    out = {}
    for k, v in d.items() if isinstance(d, dict) else ():
        if isinstance(v, list) and len(v) == 2 and all(
                isinstance(x, (int, float)) and not isinstance(x, bool)
                and 0 <= x <= 1e12 for x in v) and sum(v) > 0:
            out[k] = tuple(map(float, v))
    return out


def leer_importe(texto, moneda):
    """None si está vacío. Con los separadores de la moneda del proyecto."""
    s = re.sub(r"\s", "", texto)
    if not s:
        return None
    if moneda.simbolo and s.startswith(moneda.simbolo):
        s = s[len(moneda.simbolo):]
    mil, dec = re.escape(moneda.miles or ""), re.escape(moneda.decimal or ".")
    entero = rf"([0-9]{{1,3}}(?:{mil}[0-9]{{3}})+|[0-9]{{1,12}})" if mil else r"([0-9]{1,12})"
    m = re.fullmatch(rf"{entero}(?:{dec}([0-9]{{1,4}}))?", s)
    if not m or len(re.sub(r"\D", "", m[1])) > 12:
        raise api.ErrorComplemento(t("«{x}» no es un importe.").format(x=texto[:30]))
    return float(re.sub(r"\D", "", m[1]) + "." + (m[2] or "0"))


def precios(p):
    """{clave: (recurso_id, precio)} de los subcontratos del proyecto."""
    return {clave(i): (i.recurso_id, i.precio) for x in p.hojas()
            for i in x.acu_abierto
            if i.tipo == "SC" and not i.es_subpartida and not i.es_porcentaje}


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
    a, p = ctx.ajustes, ctx.presupuesto
    sc, guardados, dos = subcontratos(p), propios(a), importes(a)
    # Con el decimal con el que se vuelve a leer.
    def escribir(v):
        return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", p.moneda.decimal or ".")
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
            "sc", t("Porcentaje o importes propios de un subcontrato"), "tabla",
            [{"insumo": r,
              "pct": f"{guardados[k]:g}" if k in guardados and k not in dos else "",
              "mat": escribir(dos[k][0]) if k in dos else "",
              "mo": escribir(dos[k][1]) if k in dos else ""}
             for r, k in rotulos.items()][:200],
            columnas=[
                api.Dato("insumo", t("Subcontrato"), "opcion",
                         opciones=tuple(rotulos)),
                api.Dato("pct", t("% materiales"), "texto",
                         ayuda=t("Vacío = el general")),
                api.Dato("mat", t("Materiales"), "texto",
                         ayuda=t("Importe por unidad del subcontrato")),
                api.Dato("mo", t("Mano de obra"), "texto",
                         ayuda=t("Importe por unidad del subcontrato"))]))
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
            con_importe = {k: v for k, v in dos.items() if k in sc}
            vistos = set()
            for f in r.pop("sc", ()):
                k, v = rotulos[f["insumo"]], leer_pct(f["pct"])
                mm = [leer_importe(f.get(c, ""), p.moneda) for c in ("mat", "mo")]
                if v is not None and mm != [None, None]:
                    raise api.ErrorComplemento(t(
                        "«{x}»: pon el porcentaje o los importes, no los dos.").format(
                            x=f["insumo"]))
                if k in vistos:
                    raise api.ErrorComplemento(t(
                        "«{x}» está dos veces.").format(x=f["insumo"]))
                vistos.add(k)
                nuevos.pop(k, None)
                con_importe.pop(k, None)
                if mm != [None, None]:
                    mm = [x or 0.0 for x in mm]
                    if not sum(mm):
                        raise api.ErrorComplemento(t(
                            "«{x}» no es un importe.").format(x="0"))
                    con_importe[k] = mm
                    v = mm[0] / sum(mm) * 100
                if v is not None:
                    nuevos[k] = v
        except api.ErrorComplemento as e:
            ctx.avisar(str(e))
            continue
        # La fila que se quita vuelve al general.
        for k in list(rotulos.values())[:200]:
            if k not in vistos:
                nuevos.pop(k, None)
                con_importe.pop(k, None)
        guardar = {**r, "sc": json.dumps(nuevos, ensure_ascii=False)}
        if con_importe:
            guardar["sc_importes"] = json.dumps(con_importe, ensure_ascii=False)
            if {k: tuple(v) for k, v in con_importe.items()} != dos:
                guardar["repartir"] = True   # recién escritos: que se vean
        ctx.guardar_ajustes(guardar)
        ofrecer_precios(ctx, con_importe, sc)
        return


def ofrecer_precios(ctx, con_importe, sc):
    """El precio del subcontrato debe ser la suma de sus dos importes."""
    p = ctx.presupuesto
    actuales, cambios, lineas = precios(p), {}, []
    for k, v in con_importe.items():
        if k not in actuales:
            continue
        rid, antes = actuales[k]
        suma = api.redondear(sum(v), p.decimales)
        if abs(suma - antes) > 0.5 * 10 ** -p.decimales:
            cambios[rid] = suma
            lineas.append(f"{sc[k][:50]}: {p.moneda.formato(antes, p.decimales)} → "
                          f"{p.moneda.formato(suma, p.decimales)}")
    if cambios and ctx.preguntar(t(
            "Estos subcontratos no cuestan lo que suman sus importes. ¿Cambiar su "
            "precio en este proyecto?") + "\n" + "\n".join(lineas[:20])):
        ctx.editar.fijar_precios(cambios)


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
        actuales = precios(p)
        distintos = [sc[k][:50] for k, v in importes(p.ajustes).items()
                     if k in sc and k in actuales
                     and abs(actuales[k][1] - sum(v)) > 0.5 * 10 ** -d]
        if distintos:
            notas.append(t("El precio de estos subcontratos no es la suma de sus "
                           "importes; se reparte en proporción: {que}.").format(
                               que="; ".join(distintos)))
    elif otros:
        notas.append(t("Los subcontratos y las partidas sin análisis no se reparten."))
    notas.append(t("Reporte informativo: no altera los precios ni el total del "
                   "presupuesto."))
    return api.Documento(t("Materiales y mano de obra"), [
        api.Tabla(cols, filas), *[api.Parrafo(x) for x in notas]], horizontal=True)


GRUPOS = (("MO", "MANO DE OBRA"), ("MAT", "MATERIALES"), ("EQ", "EQUIPOS"),
          ("SC", "SUBCONTRATOS"))


def analisis(p):
    """El subtotal de cada grupo va debajo de sus insumos; el total, al final."""
    hojas = p.hojas()
    if not hojas:
        raise api.ErrorComplemento(t("El presupuesto no tiene partidas."))
    d = p.decimales
    cols = [api.Columna(t("Descripción"), 46), api.Columna(t("Und."), 9, "centro"),
            api.Columna(t("Cantidad"), 13, "derecha", 4),
            api.Columna(t("P. unitario"), 15, "derecha", d),
            api.Columna(t("Parcial"), 17, "derecha", d)]
    bloques = []
    for x in hojas:
        filas, suma = [], 0.0
        for nombre, ins in piezas.bloques_de(x, GRUPOS):
            filas.append(api.Fila([t(nombre)], "titulo"))
            filas += [[i.descripcion, i.unidad, i.cantidad, i.precio, i.parcial]
                      for i in ins]
            sub = api.redondear(sum(i.parcial for i in ins), d)
            suma += sub
            filas.append(api.Fila([t("Subtotal {x}").format(x=t(nombre).lower()),
                                   None, None, None, sub], "subtotal"))
        dif = api.redondear(x.precio_unitario - suma, d)
        if x.acu and dif:
            filas.append([t("Ajuste de redondeo"), None, None, None, dif])
        filas.append(api.Fila([t("TOTAL POR UNIDAD"), None, None, None,
                               x.precio_unitario], "subtotal"))
        bloques += [api.Titulo(f"{x.item}  {x.descripcion}", 2),
                    api.Campos([(t("Und."), x.unidad)]), api.Tabla(cols, filas)]
    return api.Documento(t("Análisis de precios"), bloques)
