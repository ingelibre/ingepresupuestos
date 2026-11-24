# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""El catálogo de complementos que publican los usuarios. Sin Qt. Es lo ÚNICO
de los complementos que usa la red.

    <repositorio>/catalogo.json     {"formato": 1, "complementos": [
        {"ficha", "repositorio", "descarga", "sha256", "huella", "revisado"}]}

Es un directorio, no una tienda: cada .zip está en el repositorio de su autor y
solo se descarga, a `complementos/catalogo/` y comprobando su huella, cuando el
usuario lo pide. Sincronizar solo trae la lista. Nada se instala, se activa ni se
ejecuta aquí, y no se envía ningún dato del usuario.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from core.complementos import esquema, gestor, paquete
from core.complementos.gestor import ErrorGestor
from core.complementos.paquete import ErrorPaquete, Paquete

URL = ('https://raw.githubusercontent.com/ingelibre/'
       'ingepresupuestos-complementos/main/')
ESPERA = 15
MAX_CATALOGO = 4_000_000
MAX_ENTRADAS = 1000
HORAS = 24
_SHA = re.compile(r'[0-9a-f]{64}')
_HTTPS = re.compile(r'https://[A-Za-z0-9.-]+/[!-~]{1,400}')
_REPO = re.compile(r'https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)'
                   r'(?:\.git)?/?')
#: Lo que hace falta para la tarjeta; lo demás llega con el .zip.
CAMPOS_FICHA = ('esquema', 'id', 'nombre', 'version', 'autor', 'licencia',
                'descripcion', 'web', 'api_version', 'codigo', 'categorias',
                'traducciones')


def carpeta() -> Path:
    return gestor.raiz() / 'catalogo'


def disponible() -> bool:
    """La Microsoft Store actualiza por su cuenta y no admite otra vía."""
    from core.update_manager import es_msix
    return not es_msix()


def _pedir(url: str, tope: int) -> bytes:
    import ssl
    try:
        import certifi
        tls = ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        tls = ssl.create_default_context()
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers={
                    'User-Agent': 'IngePresupuestos'}),
                timeout=ESPERA, context=tls) as r:
            if not r.geturl().startswith('https://'):
                raise ErrorGestor("la descarga no es segura (https)")
            b = r.read(tope + 1)
    except (urllib.error.URLError, http.client.HTTPException, OSError,
            ValueError) as e:
        raise ErrorGestor(f"no se pudo descargar {url} ({e})") from None
    if len(b) > tope:
        raise ErrorGestor(f"{url}: demasiado grande")
    return b


def leer_catalogo(b: bytes) -> list[dict]:
    """Las entradas válidas; una mala se salta. ErrorGestor si no es un catálogo."""
    try:
        d = json.loads(b.decode('utf-8'))
    except (ValueError, RecursionError):
        raise ErrorGestor("el catálogo no se puede leer") from None
    if not isinstance(d, dict) or d.get('formato') != 1 \
            or not isinstance(d.get('complementos'), list):
        raise ErrorGestor("el catálogo es de otro formato: actualiza el programa")
    from ingepresupuestos.api import API_VERSION
    out = {}
    for x in d['complementos'][:MAX_ENTRADAS]:
        if not isinstance(x, dict) or not isinstance(x.get('ficha'), dict):
            continue
        try:
            m = esquema.validar({k: x['ficha'][k] for k in CAMPOS_FICHA
                                 if k in x['ficha']})
        except esquema.ErrorEsquema:
            continue
        if ((m['api_version'] or 1) <= API_VERSION
                and all(isinstance(x.get(k), str) and r.fullmatch(x[k]) for k, r in (
                    ('descarga', _HTTPS), ('repositorio', _HTTPS),
                    ('sha256', _SHA), ('huella', _SHA)))):
            out[m['id']] = {
                'ficha': m, 'revisado': x.get('revisado') is True,
                **{k: x[k] for k in ('descarga', 'repositorio', 'sha256', 'huella')}}
    return list(out.values())


def _zip(x: dict) -> Path:
    # La huella va en el nombre: nunca se confunde con otra copia.
    return carpeta() / f"{x['ficha']['id']}-{x['sha256'][:16]}.zip"


def _comprobado(x: dict) -> Paquete:
    """El paquete de la copia local, si es exactamente el del catálogo."""
    f = _zip(x)
    try:
        if f.is_symlink() or f.stat().st_size > paquete.MAX_ZIP:
            raise ErrorPaquete("copia no válida")
        if hashlib.sha256(f.read_bytes()).hexdigest() != x['sha256']:
            raise ErrorPaquete("la huella no es la del catálogo")
    except OSError as e:
        raise ErrorPaquete(str(e)) from None
    p = paquete.leer_zip(f)
    if p.huella != x['huella'] or any(
            p.manifiesto[k] != v for k, v in x['ficha'].items() if k in CAMPOS_FICHA):
        raise ErrorPaquete("no es lo que dice el catálogo")
    return p


def _guardadas() -> list[dict]:
    try:
        return leer_catalogo((carpeta() / 'catalogo.json').read_bytes())
    except (OSError, ErrorGestor):
        return []


def ofrecidos() -> list[tuple[dict, Paquete]]:
    """La lista ya sincronizada, sin red. Lo que no se ha descargado es un
    paquete sin archivos: sirve para la tarjeta, no para instalar."""
    out = []
    for x in _guardadas():
        try:
            out.append((x, _comprobado(x)))
        except ErrorPaquete:
            out.append((x, Paquete(x['ficha'], {}, x['huella'])))
    return out


def revisados() -> set[str]:
    """Las huellas que leyó alguien del proyecto: de ESE contenido exacto."""
    return {x['huella'] for x in _guardadas() if x['revisado']}


def descargar(x: dict) -> Path:
    """El .zip de su autor, comprobado. No lo instala."""
    if not disponible():
        raise ErrorGestor("los complementos se actualizan con el programa")
    f = _zip(x)
    try:
        _comprobado(x)
        return f
    except ErrorPaquete:
        pass
    z = _pedir(x['descarga'], paquete.MAX_ZIP)
    if hashlib.sha256(z).hexdigest() != x['sha256']:
        raise ErrorGestor("el archivo del autor no es el que se publicó en el "
                          "catálogo (cambió su huella): no se instala")
    try:
        carpeta().mkdir(parents=True, exist_ok=True, mode=0o700)
        _escribir(f, z)
        _comprobado(x)
    except (OSError, ErrorPaquete) as e:
        f.unlink(missing_ok=True)
        raise ErrorGestor(str(e)) from None
    return f


def toca() -> bool:
    try:
        edad = time.time() - (carpeta() / 'catalogo.json').stat().st_mtime
    except OSError:
        return True
    return not 0 <= edad < HORAS * 3600


def _escribir(destino: Path, b: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=destino.parent, prefix='.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(b)
        os.replace(tmp, destino)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def sincronizar() -> int:
    """Trae la lista. Cuántos complementos o versiones son nuevos."""
    if not disponible():
        raise ErrorGestor("los complementos se actualizan con el programa")
    antes = {x['sha256'] for x in _guardadas()}
    b = _pedir(URL + 'catalogo.json', MAX_CATALOGO)
    entradas = leer_catalogo(b)
    try:
        carpeta().mkdir(parents=True, exist_ok=True, mode=0o700)
        _escribir(carpeta() / 'catalogo.json', b)
        vigentes = {_zip(x).name for x in entradas}
        for f in carpeta().glob('*.zip'):
            if f.name not in vigentes:
                f.unlink(missing_ok=True)
    except OSError as e:
        raise ErrorGestor(f"no se pudo guardar ({e})") from None
    return len({x['sha256'] for x in entradas} - antes)


# ── Publicar el propio ───────────────────────────────────────────────────────

REPOSITORIO = 'https://github.com/ingelibre/ingepresupuestos-complementos'


def publicacion(p: Paquete, repositorio: str, zip_: Path) -> dict:
    """{'descarga', 'ficha', 'pagina'}: lo que el autor manda al catálogo."""
    r = _REPO.fullmatch(repositorio.strip())
    if not r:
        raise ErrorGestor("la dirección debe ser https://github.com/cuenta/repositorio")
    cuenta, repo = r.groups()
    v = p.manifiesto['version']
    repositorio = f'https://github.com/{cuenta}/{repo}'
    descarga = f"{repositorio}/releases/download/v{v}/{p.id}-{v}.zip"
    ficha = "\n".join(f'{k} = "{t}"' for k, t in (
        ('id', p.id), ('cuenta', cuenta), ('repositorio', repositorio),
        ('descarga', descarga),
        ('sha256', hashlib.sha256(zip_.read_bytes()).hexdigest()))) + "\n"
    if any(x['ficha']['id'] == p.id for x in _guardadas()):
        pagina = f'{REPOSITORIO}/edit/main/fichas/{p.id}.toml'
    else:
        pagina = f'{REPOSITORIO}/new/main/fichas?' + urllib.parse.urlencode(
            {'filename': f'{p.id}.toml', 'value': ficha})
    return {'descarga': descarga, 'ficha': ficha, 'pagina': pagina,
            'version': f"{repositorio}/releases/new?"
                       + urllib.parse.urlencode({'tag': f'v{v}', 'title': f'v{v}'})}
