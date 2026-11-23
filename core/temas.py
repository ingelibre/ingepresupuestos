# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Temas de los reportes: el aspecto, como datos (sección `temas` de un
complemento). Sin Qt salvo para mirar qué tipografías hay.

Un tema NO es otro formato: se traduce a las mismas claves `rep_*` de
`pdf_reports.FORMATO_CLAVES` (así lo entienden también Excel, Word y el
Gantt). Lo que esas claves no expresan —tipografía, columnas, firmas, textos
del encabezado— va en `formato['_tema']` y solo lo mira el PDF.

Sin tema, `aplicar` no se llama y el formato es el de siempre.
"""
from __future__ import annotations

import base64
import copy
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

CLAVE_GLOBAL = 'rep_tema'
#: En `proyectos.tema_reporte`: '' = el de todos los proyectos.
DE_FABRICA = '-'
PREFIJO_PROPIO = 'mi-tema-'

MARCADORES = ('proyecto', 'cliente', 'ubicacion', 'costo_al', 'modalidad',
              'moneda', 'empresa', 'fecha', 'titulo', 'pagina', 'paginas')
_RE_MARCADOR = re.compile(r'\{(' + '|'.join(MARCADORES) + r')\}')

#: Grosor de las líneas de las tablas, en px: QTextDocument no dibuja los
#: bordes en pt (por eso los de fábrica no se ven).
BORDES = {'ninguno': 0, 'finos': 0.5, 'normales': 1, 'gruesos': 2}
COLUMNAS = {
    'presupuesto': {'descripcion': "Descripción", 'unidad': "Und",
                    'cantidad': "Cantidad", 'desglose': "", 'precio': "Precio",
                    'parcial': "Parcial"},
    'insumos': {'codigo': "Código", 'descripcion': "Descripción", 'unidad': "Und",
                'cantidad': "Cantidad", 'precio': "Precio", 'parcial': "Parcial"},
}


@dataclass(frozen=True)
class Tema:
    ref: str                        # «id-del-complemento/clave»
    nombre: str
    datos: dict
    logo: bytes | None = None
    complemento: str = ''
    avisos: tuple = field(default=())

    @property
    def propio(self) -> bool:
        return self.complemento.startswith(PREFIJO_PROPIO)


# ── Cuáles hay y cuál manda ──────────────────────────────────────────────────

def disponibles() -> dict[str, Tema]:
    from core.complementos import gestor
    out = {}
    for i in gestor.activos():
        for d in i.paquete.manifiesto['temas']:
            ref = f"{i.id}/{d['clave']}"
            archivo = (d.get('logo') or {}).get('archivo')
            out[ref] = Tema(ref, d['nombre'], d,
                            i.paquete.archivos.get(archivo) if archivo else None,
                            i.id)
    return out


def global_() -> str:
    from core.database import get_config
    return get_config(CLAVE_GLOBAL, '') or ''


def del_proyecto(pid) -> str:
    """'' = el de todos; `DE_FABRICA`; o la referencia de un tema."""
    from core.database import get_db
    if not pid:
        return ''
    conn = get_db()
    try:
        f = conn.execute("SELECT tema_reporte FROM proyectos WHERE id=?",
                         (pid,)).fetchone()
    finally:
        conn.close()
    return (f[0] if f else '') or ''


def elegir_global(ref: str) -> None:
    from core.database import set_config
    set_config(CLAVE_GLOBAL, ref or '')


def elegir_proyecto(pid: int, ref: str) -> None:
    from core.database import get_db
    conn = get_db()
    try:
        conn.execute("UPDATE proyectos SET tema_reporte=? WHERE id=?",
                     (ref or '', pid))
        conn.commit()
    finally:
        conn.close()


_previa: ContextVar = ContextVar('tema_en_vista_previa', default=None)


@contextmanager
def usando(tema: Tema | None):
    """Mientras dura, el tema es ese (None = de fábrica)."""
    ficha = _previa.set((tema,))
    try:
        yield
    finally:
        _previa.reset(ficha)


def elegido(pid=None) -> str:
    ref = del_proyecto(pid) or global_()
    return '' if ref == DE_FABRICA else ref


def activo(pid=None) -> Tema | None:
    """El tema que rige para el proyecto, o None (de fábrica). Nunca lanza."""
    p = _previa.get()
    if p is not None:
        return p[0]
    try:
        ref = elegido(pid)
        return disponibles().get(ref) if ref else None
    except Exception:  # noqa: BLE001 — un reporte sale aunque el tema falle
        return None


def aviso(pid=None) -> str:
    """Por qué el reporte no sale con el tema elegido; '' si todo va bien."""
    ref = elegido(pid)
    if not ref:
        return ''
    t = disponibles().get(ref)
    if t is None:
        return ref
    return ''


# ── Aplicar ──────────────────────────────────────────────────────────────────

def familia(datos: dict) -> str:
    """La tipografía del tema; si no está instalada, su sustituta; si
    tampoco, la del programa."""
    tip = datos.get('tipografia') or {}
    quiere = [tip.get('familia'), tip.get('sustituta')]
    if not any(quiere):
        return 'Inter'
    from PySide6.QtGui import QFontDatabase
    hay = {f.lower(): f for f in QFontDatabase.families()}
    for f in quiere:
        if f and f.lower() in hay:
            return hay[f.lower()]
    return 'Inter'


def expandir(texto: str, valores: dict) -> str:
    return _RE_MARCADOR.sub(lambda m: str(valores.get(m[1], '') or ''), texto)


def valores_de(proy: dict, formato: dict, **mas) -> dict:
    from core.pdf_reports import _clean_costo_al, _hoy_formateado
    return {'proyecto': proy.get('nombre') or '', 'cliente': proy.get('cliente') or '',
            'ubicacion': proy.get('ubicacion') or '',
            'costo_al': _clean_costo_al(proy.get('costo_al')),
            'modalidad': proy.get('modalidad') or '',
            'moneda': proy.get('moneda') or '',
            'empresa': formato.get('rep_empresa_nombre') or '',
            'fecha': _hoy_formateado(), **mas}


def aplicar(formato: dict, tema: Tema, proy: dict | None = None) -> dict:
    """El formato `rep_*` con el tema encima (no modifica `formato`)."""
    f, d = dict(formato), tema.datos
    col = d.get('colores') or {}
    if col.get('marca'):
        f['rep_color_marca'] = col['marca']
        f['rep_color_marca_dk'] = col.get('marca_oscuro') or col['marca']
    if col.get('titulos') or col.get('subpresupuesto'):
        from core import pdf_reports as pr
        actuales = pr.colores_titulos(formato)
        niveles = list(col.get('titulos') or [])
        niveles += [actuales[n] for n in range(len(niveles) + 1, pr.N_NIVELES + 1)]
        f['rep_esquemas_titulos'] = json.dumps({'_tema': {
            'nombre': tema.nombre, 'colores': niveles,
            'sub': col.get('subpresupuesto') or actuales[0]}})
        f['rep_esquema_titulos'] = '_tema'
    tip = d.get('tipografia') or {}
    if 'escala' in tip:
        f['rep_escala_texto'] = str(tip['escala'])
    for k, v in (d.get('margenes') or {}).items():
        f['rep_margen_' + k[:3]] = f"{v:g}"
    if tema.logo:
        f['rep_logo_b64'] = base64.b64encode(tema.logo).decode('ascii')
    if 'escala' in (d.get('logo') or {}):
        f['rep_logo_escala'] = str(d['logo']['escala'])
    val = valores_de(proy or {}, f)
    if 'encabezado' in d:
        e = d['encabezado']
        f['rep_cabecera_img_b64'] = ''
        if 'mostrar' in e:
            f['rep_encabezado_oculto'] = '0' if e['mostrar'] else '1'
        if e.get('subtitulo'):
            f['rep_empresa_subtitulo'] = expandir(e['subtitulo'], val)
    if 'pie' in d:
        p = d['pie']
        f['rep_pie_img_b64'] = ''
        if 'mostrar' in p:
            f['rep_pie_oculto'] = '0' if p['mostrar'] else '1'
        if 'linea' in p:
            f['rep_pie_linea_oculta'] = '0' if p['linea'] else '1'
        for k, largo, corto in (('izquierda', 'izquierdo', 'izq'),
                                ('centro', 'central', 'cen'),
                                ('derecha', 'derecho', 'der')):
            if k not in p:
                continue
            t = p[k]
            f[f'rep_pie_{corto}_oculto'] = '0' if t else '1'
            # Excel, Word y el Gantt numeran las páginas a su modo.
            f[f'rep_pie_{largo}'] = '' if re.search(
                r'\{(paginas?|titulo)\}', t) else expandir(t, val)
    f['_tema'] = {**d, '_familia': familia(d)}
    return f


def columnas(formato: dict, reporte: str) -> list[dict]:
    """[{campo, titulo, ancho}] del reporte, o las de fábrica."""
    de_tema = ((formato.get('_tema') or {}).get('columnas') or {}).get(reporte)
    if de_tema:
        return [{'campo': c['campo'], 'ancho': c.get('ancho'),
                 'titulo': c.get('titulo') or COLUMNAS[reporte][c['campo']]}
                for c in de_tema]
    return [{'campo': k, 'titulo': t, 'ancho': None}
            for k, t in COLUMNAS[reporte].items()]


# ── Crear, editar, exportar ──────────────────────────────────────────────────

def desde_actual(pid=None) -> tuple[dict, bytes | None]:
    """El aspecto actual como datos de tema (sin clave ni nombre)."""
    from core import pdf_reports as pr
    t = activo(pid)
    base = copy.deepcopy(t.datos) if t else {}
    f = pr.get_formato(pid)
    ct, mm = pr.colores_titulos(f), pr.margenes_mm(f)
    o, od, os_ = pr._brand_colors(f)

    def limpio(x):
        return str(x or '').replace('{', '(').replace('}', ')')[:200]
    d = {'colores': {
            'marca': f['rep_color_marca'], 'marca_oscuro': f['rep_color_marca_dk'],
            'acento': o, 'acento_oscuro': od, 'suave': os_,
            'titulos': [ct[n] for n in range(1, pr.N_NIVELES + 1)],
            'subpresupuesto': ct[0]},
         'tipografia': {'familia': 'Inter',
                        'escala': int(round(pr.texto_escala(f) * 100))},
         'margenes': {'superior': mm['sup'], 'inferior': mm['inf'],
                      'izquierdo': mm['izq'], 'derecho': mm['der']},
         'encabezado': {'mostrar': not pr.encabezado_oculto(f)},
         'pie': {'mostrar': not pr.pie_oculto(f),
                 'linea': not pr.pie_linea_oculta(f)}}
    pie = d['pie']
    for k, largo, corto, normal in (
            ('izquierda', 'izquierdo', 'izq', ''), ('centro', 'central', 'cen', ''),
            ('derecha', 'derecho', 'der', '')):
        if pr._oculto(f, f'rep_pie_{corto}_oculto'):
            pie[k] = ''
        elif f[f'rep_pie_{largo}'] and not t:
            pie[k] = limpio(f[f'rep_pie_{largo}'])
    for c in ('marca', 'marca_oscuro', 'acento', 'acento_oscuro', 'suave'):
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}', d['colores'][c] or ''):
            del d['colores'][c]
    for k, v in base.items():
        if k in ('clave', 'nombre', 'logo'):
            continue
        d[k] = {**d[k], **v} if isinstance(v, dict) and isinstance(d.get(k), dict) else v
    logo = None
    if f['rep_logo_b64']:
        try:
            logo = base64.b64decode(f['rep_logo_b64'])
        except ValueError:
            pass
        d['logo'] = {'escala': int(round(pr.logo_escala(f) * 100))}
    return d, logo


def _archivos(id_: str, nombre: str, datos: dict, logo: bytes | None) -> dict:
    from core.complementos import esquema
    d = {'clave': 'tema', 'nombre': nombre,
         **{k: v for k, v in datos.items() if k not in ('clave', 'nombre')}}
    d['logo'] = dict(d.get('logo') or {})
    out = {}
    if logo:
        ext = esquema.tipo_imagen(logo)
        if ext is None:
            raise ValueError("el logo debe ser PNG o JPG, de hasta 1 MB y 4000 px")
        d['logo']['archivo'] = 'logo.' + ext
        out[d['logo']['archivo']] = logo
    else:
        d['logo'].pop('archivo', None)
    if not d['logo']:
        del d['logo']
    m = {'esquema': esquema.ESQUEMA, 'id': id_, 'nombre': nombre, 'version': '1.0.0',
         'autor': 'Creado en este equipo', 'licencia': 'Sin declarar',
         'descripcion': 'Tema de reportes.', 'temas': [d]}
    out[esquema.ARCHIVO] = json.dumps(m, ensure_ascii=False, indent=2).encode('utf-8')
    return out


def revisar(nombre: str, datos: dict, logo: bytes | None) -> Tema:
    """Pasa por el mismo esquema que un paquete ajeno. Lanza ErrorPaquete."""
    from core.complementos import paquete
    p = paquete._armar(_archivos(PREFIJO_PROPIO + 'previa', nombre, datos, logo))
    d = p.manifiesto['temas'][0]
    return Tema('previa/tema', nombre, d, logo, 'previa')


def guardar(nombre: str, datos: dict, logo: bytes | None, ref: str = '') -> str:
    """Crea el tema o, con `ref` de uno propio, lo reemplaza. Queda activo: es
    solo datos y lo acaba de escribir quien lo guarda."""
    import shutil
    import tempfile
    from pathlib import Path
    from core.complementos import gestor, paquete
    from core.complementos.plantilla import id_de
    revisar(nombre, datos, logo)
    if ref:
        id_ = ref.split('/')[0]
        if not id_.startswith(PREFIJO_PROPIO):
            raise ValueError("solo se edita un tema creado aquí; haz una copia")
    else:
        base = PREFIJO_PROPIO + (id_de(nombre)[:24].strip('-') or 'tema')
        usados = {i.id for i in gestor.instalados()}
        id_, n = base, 2
        while id_ in usados:
            id_, n = f"{base}-{n}", n + 1
    tmp = Path(tempfile.mkdtemp(prefix='tema-'))
    try:
        for r, b in _archivos(id_, nombre, datos, logo).items():
            (tmp / r).write_bytes(b)
        p = paquete.leer_carpeta(tmp)
        i = gestor.instalar(tmp)
        gestor._poner(id_, origen='')           # la carpeta es temporal
        gestor.activar(i.id, p.huella)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return f"{id_}/tema"


def exportar(ref: str, ruta):
    """El tema como .zip instalable. Si viene en un complemento con más cosas,
    solo el tema."""
    import shutil
    import tempfile
    from pathlib import Path
    from core.complementos import gestor, paquete
    t = disponibles()[ref]
    m = gestor.uno(t.complemento).paquete.manifiesto
    tmp = Path(tempfile.mkdtemp(prefix='tema-'))
    try:
        archivos = _archivos(f"{t.complemento}"[:40], t.nombre, t.datos, t.logo)
        crudo = json.loads(archivos['complemento.json'])
        crudo.update(version=m['version'], autor=m['autor'], licencia=m['licencia'])
        archivos['complemento.json'] = json.dumps(
            crudo, ensure_ascii=False, indent=2).encode('utf-8')
        for r, b in archivos.items():
            (tmp / r).write_bytes(b)
        return paquete.empaquetar(tmp, ruta)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
