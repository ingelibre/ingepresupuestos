# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Instalar, activar y desinstalar complementos. Sin Qt.

    USER_DATA_DIR/complementos/
        instalados/<id>/      los archivos, tal como vinieron
        datos/<id>/           lo que importa el usuario (índices); sobrevive
                              a desinstalar
        estado.json           qué está activo y con qué huella
        cargando.json         centinela: qué se estaba cargando

El consentimiento es por CONTENIDO: se guarda la huella de lo que el usuario
aceptó y, si los archivos cambian, el complemento deja de cargarse hasta que
se vuelva a activar. El estado vive fuera de la base de datos a propósito:
restaurar una copia o recibir un .db no activa nada.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from core.complementos import esquema, paquete
from core.complementos.paquete import ErrorPaquete, Paquete

VARIABLE_SEGURO = 'INGEPPTO_SIN_COMPLEMENTOS'
OPCION_SEGURO = '--sin-complementos'


class ErrorGestor(Exception):
    """Un texto para el usuario."""


def raiz() -> Path:
    from core.config import USER_DATA_DIR
    return Path(USER_DATA_DIR) / 'complementos'


def carpeta_de(id_: str) -> Path:
    if not esquema.RE_ID.match(id_ or ''):
        raise ErrorGestor(f"identificador no válido: {id_!r}")
    return raiz() / 'instalados' / id_


def modo_seguro() -> bool:
    return (os.environ.get(VARIABLE_SEGURO) == '1'
            or OPCION_SEGURO in sys.argv[1:])


def puede_gestionar() -> bool:
    """Solo un administrador: un complemento ve los datos de todos."""
    from utils.auth import usuario_actual
    u = usuario_actual()
    return u is None or bool(u.es_admin)


def _exigir_permiso():
    if not puede_gestionar():
        raise ErrorGestor("solo un administrador puede gestionar complementos")


# ── Estado ───────────────────────────────────────────────────────────────────

def _escribir_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix='.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _estado() -> dict:
    """{id: {activo, huella, orden, error, origen}}. Ilegible = nada activo."""
    try:
        d = json.loads((raiz() / 'estado.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    d = d.get('complementos') if isinstance(d, dict) else None
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items()
            if esquema.RE_ID.match(k) and isinstance(v, dict)}


def _guardar_estado(d: dict) -> None:
    _escribir_json(raiz() / 'estado.json', {'version': 1, 'complementos': d})


def _poner(id_: str, **campos) -> None:
    d = _estado()
    d.setdefault(id_, {}).update(campos)
    _guardar_estado(d)
    invalidar()


# ── Qué hay ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Info:
    id: str
    paquete: Paquete | None       # None = no se puede leer
    activo: bool                  # activo Y con la huella aceptada
    estado: str                   # activo | apagado | cambiado | error | dañado
    error: str
    origen: str                   # carpeta desde la que se instaló, o ''

    @property
    def nombre(self) -> str:
        return self.paquete.manifiesto['nombre'] if self.paquete else self.id


def _info(id_: str, e: dict) -> Info:
    error = str(e.get('error') or '')
    origen = str(e.get('origen') or '')
    try:
        p = paquete.leer_carpeta(carpeta_de(id_))
        if p.id != id_:
            raise ErrorPaquete(f"la carpeta «{id_}» contiene «{p.id}»")
    except ErrorPaquete as x:
        return Info(id_, None, False, 'dañado', str(x), origen)
    if not e.get('activo'):
        return Info(id_, p, False, 'error' if error else 'apagado', error, origen)
    if e.get('huella') != p.huella:
        return Info(id_, p, False, 'cambiado', '', origen)
    from ingepresupuestos.api import API_VERSION
    if (p.manifiesto['api_version'] or 1) > API_VERSION:
        return Info(id_, p, False, 'error',
                    _texto_api(p.manifiesto['api_version']), origen)
    return Info(id_, p, True, 'activo', '', origen)


def _texto_api(pide) -> str:
    from ingepresupuestos.api import API_VERSION
    return (f"necesita la API {pide} y este IngePresupuestos tiene la "
            f"{API_VERSION}: hay que actualizar el programa")


def instalados() -> list[Info]:
    est = _estado()
    try:
        ids = sorted(d.name for d in (raiz() / 'instalados').iterdir()
                     if d.is_dir() and esquema.RE_ID.match(d.name))
    except OSError:
        return []
    return [_info(i, est.get(i, {})) for i in ids]


def uno(id_: str) -> Info | None:
    return next((i for i in instalados() if i.id == id_), None)


_activos: list[Info] | None = None


def activos() -> list[Info]:
    """Los activos, en el orden en que se activaron (el último manda). Con
    caché: lo consulta `tr()`."""
    global _activos
    if _activos is None:
        try:
            if modo_seguro():
                _activos = []
            else:
                est = _estado()
                _activos = sorted((i for i in instalados() if i.activo),
                                  key=lambda i: est[i.id].get('orden') or 0)
        except Exception:  # noqa: BLE001 — nunca estorba al programa
            _activos = []
    return list(_activos)


def invalidar() -> None:
    """Olvida lo leído: vuelve a mirar el disco."""
    global _activos
    _activos = None
    from core.complementos import registro
    registro.invalidar()
    from utils import i18n
    i18n.olvidar_vocabulario()


# ── Operaciones ──────────────────────────────────────────────────────────────

def instalar(ruta) -> Info:
    """De un .zip o carpeta. Queda APAGADO, también al actualizar."""
    _exigir_permiso()
    ruta = Path(ruta)
    p = paquete.leer(ruta)
    destino = carpeta_de(p.id)
    destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = Path(tempfile.mkdtemp(dir=destino.parent, prefix='.nuevo-'))
    viejo = Path(tempfile.mkdtemp(dir=destino.parent, prefix='.viejo-'))
    try:
        paquete.escribir(p, tmp / 'x')
        # Apagado ANTES de cambiar los archivos: si algo se corta a medias,
        # no queda nada activo con contenido nuevo.
        origen = ''
        if ruta.is_dir() and not str(ruta.resolve()).startswith(
                str(destino.resolve())):
            origen = str(ruta.resolve())
        _descargar(p.id)
        _poner(p.id, activo=False, huella='', error='', origen=origen)
        if destino.exists():
            os.replace(destino, viejo / 'x')
        try:
            os.replace(tmp / 'x', destino)
        except OSError:
            if (viejo / 'x').exists():
                os.replace(viejo / 'x', destino)
            raise
    except OSError as e:
        raise ErrorGestor(f"no se pudo instalar ({e})") from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(viejo, ignore_errors=True)
        invalidar()
    return uno(p.id)


def conflictos(p: Paquete) -> list[str]:
    """Lo que este paquete cambiaría de los datos de fábrica, del usuario o de
    otro complemento activo. Vacío = no pisa nada."""
    from core import config, paises
    from core.complementos import registro
    m, out = p.manifiesto, []
    otros = [i for i in activos() if i.id != p.id]
    de_otro = {x['iso']: i.nombre for i in otros
               for x in i.paquete.manifiesto['paises']}
    for x in m['paises']:
        if x['iso'] in de_otro:
            out.append(f"País {x['nombre']}: reemplaza el de «{de_otro[x['iso']]}»")
        elif x['iso'] in paises.PAISES:
            base = paises.PAISES[x['iso']]
            cambia = [k for k, v in registro.perfil_de(x).items()
                      if k != 'iso' and base.get(k) != v
                      and not (k == 'pie' and paises.pie_de(base) == v)
                      and not (k == 'indirectos' and v == (
                          base.get(k) or paises.INDIRECTOS_GENERAL))]
            if cambia:
                nombres = {'id': "identificación tributaria", 'imp': "impuesto",
                           'indirectos': "gastos y utilidad"}
                out.append(f"País {x['nombre']}: cambia respecto del de fábrica — "
                           + ", ".join(nombres.get(c, c) for c in cambia))
    for x in m['monedas']:
        hay = config.monedas().get(x['nombre'])
        nueva = {k: x[k] for k in ('simbolo', 'sep_miles', 'sep_dec')}
        if hay and hay != nueva:
            out.append(f"Moneda {x['nombre']}: ya existe con otro formato; se "
                       "conserva la que hay")
    vocab = {(v['idioma'], k): i.nombre for i in otros
             for v in i.paquete.manifiesto['vocabulario'] for k in v['textos']}
    n = sum((v['idioma'], k) in vocab
            for v in m['vocabulario'] for k in v['textos'])
    if n:
        out.append(f"Vocabulario: {n} textos que también cambia otro complemento")
    claves = {x['nombre'] for i in otros
              for x in i.paquete.manifiesto['importadores_excel']}
    for x in m['importadores_excel']:
        if x['nombre'] in claves:
            out.append(f"Formato de Excel «{x['nombre']}»: también lo trae otro "
                       "complemento")
    return out


def activar(id_: str, huella: str) -> Info:
    """`huella` es la del contenido que se ENSEÑÓ al usuario: si entre tanto
    cambió, no se activa."""
    _exigir_permiso()
    i = uno(id_)
    if i is None:
        raise ErrorGestor(f"no está instalado: {id_}")
    if i.paquete is None:
        raise ErrorGestor(i.error)
    if i.paquete.huella != huella:
        raise ErrorGestor("los archivos cambiaron mientras tanto; revísalos otra vez")
    from ingepresupuestos.api import API_VERSION
    if (i.paquete.manifiesto['api_version'] or 1) > API_VERSION:
        raise ErrorGestor(_texto_api(i.paquete.manifiesto['api_version']))
    _conservar_monedas(i.paquete)
    orden = max([int(e.get('orden') or 0) for e in _estado().values()] + [0]) + 1
    _poner(id_, activo=True, huella=huella, error='', orden=orden)
    return uno(id_)


def _conservar_monedas(p: Paquete) -> None:
    """Las monedas del paquete pasan a ser monedas del usuario: un proyecto
    guarda solo su nombre, y tiene que seguir imprimiendo igual cuando el
    complemento se quite. Lo que ya existe no se toca."""
    from core import config
    nuevas = {x['nombre']: {k: x[k] for k in ('simbolo', 'sep_miles', 'sep_dec')}
              for x in p.manifiesto['monedas']
              if x['nombre'] not in config.monedas()}
    if nuevas:
        config.guardar_monedas_propias({**config.monedas_propias(), **nuevas})


def _descargar(id_: str) -> None:
    from core.complementos import cargador
    cargador.descargar(id_)


def desactivar(id_: str, error: str = '') -> None:
    if not error:
        _exigir_permiso()
    _descargar(id_)
    _poner(id_, activo=False, huella='', error=error[:2000])


def desinstalar(id_: str) -> None:
    """Quita los archivos. Lo que el usuario importó (índices) se conserva."""
    _exigir_permiso()
    destino = carpeta_de(id_)
    _descargar(id_)
    d = _estado()
    d.pop(id_, None)
    _guardar_estado(d)
    try:
        if destino.is_symlink():
            destino.unlink()
        elif destino.exists():
            # Primero fuera de la vista: si el borrado se corta, no queda
            # medio complemento.
            fuera = Path(tempfile.mkdtemp(dir=destino.parent, prefix='.viejo-'))
            os.replace(destino, fuera / 'x')
            shutil.rmtree(fuera, ignore_errors=True)
    except OSError as e:
        raise ErrorGestor(f"no se pudo borrar ({e})") from None
    finally:
        invalidar()


def recargar(id_: str) -> Info:
    """Desarrollo: vuelve a copiar de la carpeta de origen. Si algo cambió,
    queda apagado y hay que activarlo otra vez."""
    _exigir_permiso()
    i = uno(id_)
    if i is None or not i.origen:
        raise ErrorGestor("no se instaló desde una carpeta: vuelve a instalarlo")
    p = paquete.leer_carpeta(i.origen)
    if p.id != id_:
        raise ErrorGestor(f"{i.origen} ahora contiene «{p.id}»")
    if i.paquete is not None and p.huella == i.paquete.huella:
        _descargar(id_)
        invalidar()
        return uno(id_)
    return instalar(i.origen)


def incluidos() -> list[Path]:
    """Los que vienen con el programa, para instalar sin descargar nada."""
    from core.config import BASE_DIR
    base = Path(BASE_DIR) / 'complementos'
    try:
        return sorted(d for d in base.iterdir()
                      if (d / esquema.ARCHIVO).is_file())
    except OSError:
        return []


# ── Centinela de carga ───────────────────────────────────────────────────────

def _centinela() -> Path:
    return raiz() / 'cargando.json'


def empezar_carga(id_: str) -> None:
    _escribir_json(_centinela(), {'id': id_, 'cuando': time.time()})


def terminar_carga() -> None:
    try:
        _centinela().unlink()
    except OSError:
        pass


def recuperar_de_un_cierre() -> str | None:
    """Si la vez anterior el programa murió MIENTRAS cargaba un complemento,
    lo apaga. Devuelve su id."""
    try:
        d = json.loads(_centinela().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        terminar_carga()
        return None
    terminar_carga()
    id_ = d.get('id') if isinstance(d, dict) else None
    if not isinstance(id_, str) or id_ not in _estado():
        return None
    desactivar(id_, "el programa se cerró mientras lo cargaba")
    return id_


# ── Índices del usuario ──────────────────────────────────────────────────────

def _ruta_indice(id_: str, clave: str) -> Path:
    carpeta_de(id_)                                  # valida el id
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,24}', clave or ''):
        raise ErrorGestor(f"clave de índice no válida: {clave!r}")
    return raiz() / 'datos' / id_ / 'indices' / f'{clave}.json'


def leer_csv_indice(texto: str) -> list[tuple[str, float]]:
    """Dos columnas —periodo y valor— separadas por «;» o tabulador. El
    periodo es AAAA-MM o MM/AAAA; el valor admite coma o punto decimal."""
    from utils.formatting import parse_num_opt
    out: dict[str, float] = {}
    for n, linea in enumerate(texto.splitlines(), 1):
        if not linea.strip():
            continue
        if n > 5000:
            raise ErrorGestor("más de 5000 líneas")
        celdas = [c.strip().strip('"') for c in re.split(r'[;\t]', linea)]
        m = re.fullmatch(r'(\d{4})-(0[1-9]|1[0-2])(?:-\d\d)?', celdas[0])
        per = f"{m[1]}-{m[2]}" if m else ''
        if not per:
            m = re.fullmatch(r'(0?[1-9]|1[0-2])/(\d{4})', celdas[0])
            per = f"{m[2]}-{int(m[1]):02d}" if m else ''
        if not per:
            if not out:
                continue                             # títulos
            raise ErrorGestor(f"línea {n}: el periodo debe ser AAAA-MM o MM/AAAA")
        v = parse_num_opt(celdas[1]) if len(celdas) > 1 else None
        if v is None or not v > 0:
            raise ErrorGestor(f"línea {n}: falta el valor")
        if per in out:
            raise ErrorGestor(f"línea {n}: {per} está repetido")
        out[per] = v
    if not out:
        raise ErrorGestor("no hay ninguna fila «periodo; valor»")
    return sorted(out.items())


def importar_indice(id_: str, clave: str, ruta) -> int:
    _exigir_permiso()
    i = uno(id_)
    if i is None or i.paquete is None or clave not in {
            x['clave'] for x in i.paquete.manifiesto['indices']}:
        raise ErrorGestor(f"{id_} no declara el índice {clave}")
    try:
        b = Path(ruta).read_bytes()[:2_000_001]
    except OSError as e:
        raise ErrorGestor(str(e)) from None
    if len(b) > 2_000_000:
        raise ErrorGestor("el archivo pesa más de 2 MB")
    try:
        texto = b.decode('utf-8-sig')
    except UnicodeDecodeError:
        texto = b.decode('latin-1')
    valores = leer_csv_indice(texto)
    _escribir_json(_ruta_indice(id_, clave), {'valores': valores})
    return len(valores)


def indice(id_: str, clave: str) -> list[tuple[str, float]]:
    """Lo que importó el usuario o, si no hay, lo que trae el paquete."""
    try:
        d = json.loads(_ruta_indice(id_, clave).read_text(encoding='utf-8'))
        return [(str(p), float(v)) for p, v in d['valores']]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    i = uno(id_)
    if i is None or i.paquete is None:
        return []
    return next((list(x['valores']) for x in i.paquete.manifiesto['indices']
                 if x['clave'] == clave), [])
