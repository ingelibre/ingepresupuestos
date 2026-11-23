# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""`complemento.json`: validación estricta, sin dependencias ni efectos.

Un campo desconocido se rechaza (no se ignora): una errata en «pais» no debe
dejar un paquete a medias sin que nadie se entere.
"""
from __future__ import annotations

import json
import math
import re
import string

ESQUEMA = 1
ARCHIVO = 'complemento.json'

RE_ID = re.compile(r'[a-z][a-z0-9]*(-[a-z0-9]+)*\Z')
_RE_VERSION = re.compile(r'\d{1,5}(\.\d{1,5}){0,3}([-+][0-9A-Za-z.]{1,20})?\Z')
_RE_PERIODO = re.compile(r'(\d{4})-(0[1-9]|1[0-2])\Z')
_RE_CLAVE = re.compile(r'[A-Za-z0-9_-]{1,24}\Z')
_RE_PY = re.compile(r'[a-z_][a-z0-9_]*\.py\Z')
_RE_ETIQUETA = re.compile(r'</?\w[^>]*>')

CAMPOS_EXCEL = ('codigo', 'descripcion', 'unidad', 'precio', 'tipo', 'inei')
TIPOS_INSUMO = ('MO', 'MAT', 'EQ', 'SC')
TIPOS_PIE = ('rubro', 'pct_cd', 'pct_sub', 'pct_util', 'subtotal')
#: Valores del pie que salen del proyecto o del impuesto del país.
PCT_PIE = ('gastos_generales', 'utilidad', 'impuesto')
IDIOMAS = ('es', 'en', 'pt_BR')
SEPARADORES = ((',', '.'), ('.', ','), (' ', ','), ("'", '.'))

MAX_JSON = 1_000_000


class ErrorEsquema(Exception):
    """`errores`: lista de «dónde: qué»."""

    def __init__(self, errores):
        self.errores = list(errores)
        super().__init__("\n".join(self.errores))


class _V:
    def __init__(self):
        self.err: list[str] = []

    def mal(self, donde, que):
        if len(self.err) < 50:
            self.err.append(f"{donde}: {que}")

    def obj(self, x, donde, campos: dict, oblig=()):
        """dict con solo `campos`; devuelve {} si no lo es."""
        if not isinstance(x, dict):
            self.mal(donde, "debe ser un objeto {…}")
            return {}
        for k in x:
            if k not in campos:
                self.mal(donde, f"campo desconocido «{str(k)[:40]}»")
        for k in oblig:
            if k not in x:
                self.mal(donde, f"falta «{k}»")
        return {k: v for k, v in x.items() if k in campos}

    def texto(self, x, donde, maximo=200, vacio=False, multilinea=False):
        if not isinstance(x, str):
            self.mal(donde, "debe ser un texto")
            return ''
        if not vacio and not x.strip():
            self.mal(donde, "está vacío")
        if len(x) > maximo:
            self.mal(donde, f"más de {maximo} caracteres")
        if any(ord(c) < 32 and not (multilinea and c in '\n\t') for c in x):
            self.mal(donde, "tiene caracteres de control")
        return x

    def num(self, x, donde, minimo=0.0, maximo=1e12):
        if isinstance(x, bool) or not isinstance(x, (int, float)) \
                or not math.isfinite(x):
            self.mal(donde, "debe ser un número")
            return 0.0
        if not minimo <= x <= maximo:
            self.mal(donde, f"debe estar entre {minimo:g} y {maximo:g}")
        return float(x)

    def lista(self, x, donde, maximo, minimo=0):
        if not isinstance(x, list):
            self.mal(donde, "debe ser una lista […]")
            return []
        if not minimo <= len(x) <= maximo:
            self.mal(donde, f"debe tener entre {minimo} y {maximo} elementos")
            return x[:maximo]
        return x

    def de(self, x, donde, opciones):
        if not isinstance(x, str) or x not in opciones:
            self.mal(donde, "debe ser uno de: " + ", ".join(opciones))
            return opciones[0]
        return x

    def logico(self, x, donde):
        if not isinstance(x, bool):
            self.mal(donde, "debe ser true o false")
        return bool(x)

    def textos(self, x, donde, maximo, largo=200, minimo=0):
        out = []
        for i, t in enumerate(self.lista(x, donde, maximo, minimo)):
            out.append(self.texto(t, f"{donde}[{i}]", largo))
        if len(set(out)) != len(out):
            self.mal(donde, "hay textos repetidos")
        return out


def marcadores(texto: str) -> set | None:
    """Los «{n}» de un texto; None si las llaves no cuadran."""
    try:
        out = set()
        for _l, campo, spec, conv in string.Formatter().parse(texto):
            if campo is not None:
                out.add((campo, spec, conv))
        return out
    except ValueError:
        return None


def _pais(v: _V, x, d):
    x = v.obj(x, d, dict.fromkeys((
        'iso', 'nombre', 'moneda', 'identificacion', 'impuesto', 'centro',
        'indirectos', 'pie')),
        ('iso', 'nombre', 'moneda', 'identificacion', 'impuesto'))
    out = {}
    iso = v.texto(x.get('iso', 'XX'), f"{d}.iso", 2)
    if not re.fullmatch(r'[A-Z]{2}', iso):
        v.mal(f"{d}.iso", "dos letras mayúsculas (ISO 3166-1), p. ej. «AR»")
    out['iso'] = iso
    out['nombre'] = v.texto(x.get('nombre', '-'), f"{d}.nombre", 60)
    out['moneda'] = v.texto(x.get('moneda', '-'), f"{d}.moneda", 40)
    out['id'] = v.texto(x.get('identificacion', '-'), f"{d}.identificacion", 30)
    imp = v.obj(x.get('impuesto', {}), f"{d}.impuesto",
                dict.fromkeys(('nombre', 'pct')), ('nombre', 'pct'))
    out['imp'] = (v.texto(imp.get('nombre', '-'), f"{d}.impuesto.nombre", 30),
                  v.num(imp.get('pct', 0), f"{d}.impuesto.pct", 0, 50))
    if 'centro' in x:
        c = v.lista(x['centro'], f"{d}.centro", 2, 2)
        if len(c) == 2:
            out['centro'] = (v.num(c[0], f"{d}.centro[0]", -90, 90),
                             v.num(c[1], f"{d}.centro[1]", -180, 180))
    if 'indirectos' in x:
        i = v.obj(x['indirectos'], f"{d}.indirectos",
                  dict.fromkeys(('gastos_generales', 'utilidad')),
                  ('gastos_generales', 'utilidad'))
        out['indirectos'] = tuple(
            v.num(i.get(k, 0), f"{d}.indirectos.{k}", 0, 100)
            for k in ('gastos_generales', 'utilidad'))
    if 'pie' in x:
        out['pie'] = _pie(v, x['pie'], f"{d}.pie")
    return out


def _pie(v: _V, x, d):
    out, codigos = [], set()
    for i, l in enumerate(v.lista(x, d, 30, 1)):
        dl = f"{d}[{i}]"
        l = v.obj(l, dl, dict.fromkeys(
            ('codigo', 'nombre', 'tipo', 'pct', 'activo', 'mostrar_pct')),
            ('codigo', 'nombre', 'tipo'))
        cod = v.texto(l.get('codigo', '-'), f"{dl}.codigo", 12)
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*', cod):
            v.mal(f"{dl}.codigo", "mayúsculas y números, p. ej. «GG»")
        if cod in codigos:
            v.mal(f"{dl}.codigo", "repetido")
        codigos.add(cod)
        pct = l.get('pct', 0)
        if isinstance(pct, str):
            pct = v.de(pct, f"{dl}.pct", PCT_PIE)
        else:
            pct = v.num(pct, f"{dl}.pct", 0, 1000)
        nombre = v.texto(l.get('nombre', '-'), f"{dl}.nombre", 80)
        m = marcadores(nombre)
        if m is None or {c for c, _s, _v in m} - {'impuesto', 'impuesto_pct'} \
                or any(s or c for _n, s, c in m):
            v.mal(f"{dl}.nombre", "solo admite {impuesto} e {impuesto_pct}")
        out.append({
            'codigo': cod, 'nombre': nombre,
            'tipo': v.de(l.get('tipo', 'pct_cd'), f"{dl}.tipo", TIPOS_PIE),
            'pct': pct,
            'activo': v.logico(l.get('activo', True), f"{dl}.activo"),
            'mostrar_pct': v.logico(l.get('mostrar_pct', True),
                                    f"{dl}.mostrar_pct")})
    return out


def _moneda(v: _V, x, d):
    x = v.obj(x, d, dict.fromkeys(('nombre', 'simbolo', 'miles', 'decimal')),
              ('nombre', 'simbolo', 'miles', 'decimal'))
    out = {'nombre': v.texto(x.get('nombre', '-'), f"{d}.nombre", 40),
           'simbolo': v.texto(x.get('simbolo', '-'), f"{d}.simbolo", 8),
           'sep_miles': x.get('miles', ','), 'sep_dec': x.get('decimal', '.')}
    if (out['sep_miles'], out['sep_dec']) not in SEPARADORES:
        v.mal(d, "separadores (miles, decimal) no admitidos; hay: "
              + "  ".join(f"«{a}»«{b}»" for a, b in SEPARADORES))
    return out


def _vocabulario(v: _V, x, d):
    x = v.obj(x, d, dict.fromkeys(('idioma', 'pais', 'textos')), ('textos',))
    out = {'idioma': v.de(x.get('idioma', 'es'), f"{d}.idioma", IDIOMAS),
           'pais': None, 'textos': {}}
    if 'pais' in x:
        out['pais'] = v.texto(x['pais'], f"{d}.pais", 2)
    t = x.get('textos', {})
    if not isinstance(t, dict) or len(t) > 3000:
        v.mal(f"{d}.textos", "debe ser un objeto de hasta 3000 textos")
        return out
    for k, val in t.items():
        dk = f"{d}.textos[«{k[:30]}»]"
        val = v.texto(val, dk, 1000, multilinea=True)
        if len(k) > 1000:
            v.mal(dk, "clave demasiado larga")
        if marcadores(k) != marcadores(val):
            v.mal(dk, "debe conservar los marcadores {…} del original")
        if _RE_ETIQUETA.findall(k) != _RE_ETIQUETA.findall(val):
            v.mal(dk, "debe conservar las etiquetas <…> del original")
        out['textos'][k] = val
    return out


def _excel(v: _V, x, d):
    x = v.obj(x, d, dict.fromkeys((
        'nombre', 'pais', 'detectar', 'columnas', 'tipos', 'tipo_fijo', 'prefijo',
        'omitir_sin_precio', 'cantidad_en_unidad', 'quitar_impuesto_pct',
        'aviso')), ('nombre', 'detectar', 'columnas'))
    out = {'nombre': v.texto(x.get('nombre', '-'), f"{d}.nombre", 80),
           'pais': None, 'tipos': {}, 'tipo_fijo': None, 'prefijo': '',
           'omitir_sin_precio': True, 'cantidad_en_unidad': False,
           'quitar_impuesto_pct': None, 'aviso': ''}
    if 'pais' in x:
        out['pais'] = v.texto(x['pais'], f"{d}.pais", 2)
    out['detectar'] = v.textos(x.get('detectar', ['a', 'b']), f"{d}.detectar",
                               10, 80, 2)
    cols = v.obj(x.get('columnas', {}), f"{d}.columnas",
                 dict.fromkeys(CAMPOS_EXCEL))
    out['columnas'] = {k: v.textos(c, f"{d}.columnas.{k}", 20, 80, 1)
                       for k, c in cols.items()}
    if 'descripcion' not in cols:
        v.mal(f"{d}.columnas", "falta «descripcion»")
    tipos = v.obj(x.get('tipos', {}), f"{d}.tipos", dict.fromkeys(TIPOS_INSUMO))
    out['tipos'] = {k: v.textos(t, f"{d}.tipos.{k}", 50, 80, 1)
                    for k, t in tipos.items()}
    if 'tipo_fijo' in x:
        out['tipo_fijo'] = v.de(x['tipo_fijo'], f"{d}.tipo_fijo", TIPOS_INSUMO)
    if 'prefijo' in x:
        out['prefijo'] = v.texto(x['prefijo'], f"{d}.prefijo", 12, vacio=True)
    for k in ('omitir_sin_precio', 'cantidad_en_unidad'):
        if k in x:
            out[k] = v.logico(x[k], f"{d}.{k}")
    if 'quitar_impuesto_pct' in x:
        out['quitar_impuesto_pct'] = v.num(x['quitar_impuesto_pct'],
                                           f"{d}.quitar_impuesto_pct", 0, 60)
    if 'aviso' in x:
        out['aviso'] = v.texto(x['aviso'], f"{d}.aviso", 500)
    return out


def valores_indice(v: _V, x, d, maximo=2000):
    out, vistos = [], set()
    for i, p in enumerate(v.lista(x, d, maximo)):
        dp = f"{d}[{i}]"
        p = v.obj(p, dp, dict.fromkeys(('periodo', 'valor')), ('periodo', 'valor'))
        per = p.get('periodo', '')
        if not isinstance(per, str) or not _RE_PERIODO.match(per):
            v.mal(f"{dp}.periodo", "debe ser «AAAA-MM»")
            continue
        if per in vistos:
            v.mal(f"{dp}.periodo", "repetido")
        vistos.add(per)
        out.append((per, v.num(p.get('valor', 0), f"{dp}.valor", 1e-9, 1e12)))
    return sorted(out)


def _indice(v: _V, x, d):
    x = v.obj(x, d, dict.fromkeys(('clave', 'nombre', 'valores')),
              ('clave', 'nombre'))
    clave = x.get('clave', 'X')
    if not isinstance(clave, str) or not _RE_CLAVE.match(clave):
        v.mal(f"{d}.clave", "letras, números, «-» y «_» (hasta 24)")
        clave = 'X'
    return {'clave': clave,
            'nombre': v.texto(x.get('nombre', '-'), f"{d}.nombre", 120),
            'valores': valores_indice(v, x.get('valores', []), f"{d}.valores")}


_LISTAS = {
    'paises': (_pais, 30, 'iso'), 'monedas': (_moneda, 30, 'nombre'),
    'vocabulario': (_vocabulario, 10, None),
    'importadores_excel': (_excel, 20, 'nombre'),
    'indices': (_indice, 50, 'clave'),
}
_CAMPOS = ('esquema', 'id', 'nombre', 'version', 'autor', 'licencia',
           'descripcion', 'web', 'api_version', 'codigo', 'titulos', 'unidades',
           *_LISTAS)


def validar(crudo) -> dict:
    """El manifiesto normalizado. Lanza `ErrorEsquema` con TODOS los errores."""
    v = _V()
    x = v.obj(crudo, ARCHIVO, dict.fromkeys(_CAMPOS),
              ('esquema', 'id', 'nombre', 'version', 'autor', 'licencia'))
    if not x:
        raise ErrorEsquema(v.err or [f"{ARCHIVO}: vacío"])
    if x.get('esquema') != ESQUEMA or isinstance(x.get('esquema'), bool):
        v.mal('esquema', f"debe ser {ESQUEMA}")
    out = {'esquema': ESQUEMA}
    out['id'] = v.texto(x.get('id', 'xxx'), 'id', 40)
    if not RE_ID.match(out['id']) or len(out['id']) < 3:
        v.mal('id', "minúsculas, números y guiones, de 3 a 40; p. ej. «pais-brasil»")
    out['nombre'] = v.texto(x.get('nombre', '-'), 'nombre', 60)
    out['version'] = v.texto(x.get('version', '0'), 'version', 30)
    if not _RE_VERSION.match(out['version']):
        v.mal('version', "p. ej. «1.0.0»")
    out['autor'] = v.texto(x.get('autor', '-'), 'autor', 100)
    out['licencia'] = v.texto(x.get('licencia', '-'), 'licencia', 60)
    out['descripcion'] = v.texto(x.get('descripcion', ''), 'descripcion', 1000,
                                 vacio=True, multilinea=True)
    out['web'] = v.texto(x.get('web', ''), 'web', 200, vacio=True)
    if out['web'] and not re.match(r'https://[^\s<>"]+\Z', out['web']):
        v.mal('web', "debe empezar con https://")
    api = x.get('api_version')
    if api is not None and (type(api) is not int or not 1 <= api <= 999):
        v.mal('api_version', "debe ser un entero desde 1")
        api = None
    out['api_version'] = api
    out['codigo'] = None
    if 'codigo' in x:
        c = v.texto(x['codigo'], 'codigo', 60)
        if not _RE_PY.match(c) or c == '__init__.py':
            v.mal('codigo', "el nombre de un .py en la raíz del paquete")
        out['codigo'] = c
        if api is None:
            v.mal('api_version', "falta: un complemento con código la necesita")
    for nombre, (fn, maximo, unico) in _LISTAS.items():
        out[nombre] = [fn(v, e, f"{nombre}[{i}]") for i, e in
                       enumerate(v.lista(x.get(nombre, []), nombre, maximo))]
        if unico:
            ks = [e.get(unico) for e in out[nombre]]
            if len(set(ks)) != len(ks):
                v.mal(nombre, f"«{unico}» repetido")
    out['titulos'] = v.textos(x.get('titulos', []), 'titulos', 2000)
    out['unidades'] = v.textos(x.get('unidades', []), 'unidades', 200, 15)
    if any(u.startswith('%') for u in out['unidades']):
        v.mal('unidades', "las unidades en % las define el programa")
    if v.err:
        raise ErrorEsquema(v.err)
    return out


def _sin_repetidos(pares):
    out = {}
    for k, val in pares:
        if k in out:
            raise ValueError(f"clave repetida «{k}»")
        out[k] = val
    return out


def _no_finito(x):
    raise ValueError(f"número no admitido: {x}")


def leer(datos: bytes) -> dict:
    """bytes de `complemento.json` → manifiesto validado."""
    if len(datos) > MAX_JSON:
        raise ErrorEsquema([f"{ARCHIVO}: más de {MAX_JSON // 1000} KB"])
    try:
        crudo = json.loads(datos.decode('utf-8-sig'),
                           object_pairs_hook=_sin_repetidos,
                           parse_constant=_no_finito)
    except (ValueError, RecursionError) as e:
        raise ErrorEsquema([f"{ARCHIVO}: no es un JSON válido ({e})"]) from None
    return validar(crudo)


def tiene_datos(m: dict) -> list[str]:
    """Qué secciones de datos trae (para enseñarlo)."""
    return [k for k in (*_LISTAS, 'titulos', 'unidades') if m.get(k)]
