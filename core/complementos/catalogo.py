# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""El catálogo de complementos del repositorio. Sin Qt. Es lo ÚNICO de los
complementos que usa la red.

    <repositorio>/catalogo.json     {"formato": 1, "complementos": [
                                       {"id", "version", "sha256", "api"}]}
    <repositorio>/zips/<id>-<version>.zip

Sincronizar solo copia los .zip a `complementos/catalogo/` y comprueba su
huella: no instala, no activa y no ejecuta nada. Se ofrecen en «Explorar» y
se instalan como cualquier otro, apagados y con el consentimiento de siempre.
No se envía ningún dato del usuario.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from core.complementos import esquema, gestor, paquete
from core.complementos.gestor import ErrorGestor
from core.complementos.paquete import ErrorPaquete, Paquete

URL = ('https://raw.githubusercontent.com/ingelibre/'
       'ingepresupuestos-complementos/main/')
ESPERA = 15
MAX_CATALOGO = 1_000_000
MAX_ENTRADAS = 200
MAX_DESCARGA = 60_000_000        # de una vez; lo que falte, en la siguiente
HORAS = 24
_SHA = re.compile(r'[0-9a-f]{64}')


def carpeta() -> Path:
    return gestor.raiz() / 'catalogo'


def disponible() -> bool:
    """La Microsoft Store actualiza por su cuenta y no admite otra vía."""
    from core.update_manager import es_msix
    return not es_msix()


def _pedir(ruta: str, tope: int) -> bytes:
    import ssl
    try:
        import certifi
        tls = ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        tls = ssl.create_default_context()
    try:
        with urllib.request.urlopen(
                urllib.request.Request(URL + ruta, headers={
                    'User-Agent': 'IngePresupuestos'}),
                timeout=ESPERA, context=tls) as r:
            if not r.geturl().startswith('https://'):
                raise ErrorGestor("la descarga no es segura (https)")
            b = r.read(tope + 1)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ErrorGestor(f"no se pudo descargar {ruta} ({e})") from None
    if len(b) > tope:
        raise ErrorGestor(f"{ruta}: demasiado grande")
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
        if not isinstance(x, dict):
            continue
        id_, v, sha, pide = (x.get(k) for k in ('id', 'version', 'sha256', 'api'))
        if (isinstance(id_, str) and esquema.RE_ID.fullmatch(id_)
                and isinstance(v, str) and re.fullmatch(r'[0-9A-Za-z.+-]{1,32}', v)
                and isinstance(sha, str) and _SHA.fullmatch(sha)
                and type(pide) is int and pide <= API_VERSION):
            out[id_] = {'id': id_, 'version': v, 'sha256': sha, 'api': pide}
    return list(out.values())


def _zip(x: dict) -> Path:
    # La huella va en el nombre: nunca se confunde con otra copia.
    return carpeta() / f"{x['id']}-{x['sha256'][:16]}.zip"


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
    if (p.id, p.manifiesto['version']) != (x['id'], x['version']):
        raise ErrorPaquete("no es lo que dice el catálogo")
    return p


def _guardadas() -> list[dict]:
    try:
        return leer_catalogo((carpeta() / 'catalogo.json').read_bytes())
    except (OSError, ErrorGestor):
        return []


def ofrecidos() -> list[tuple[Path, Paquete]]:
    """Lo ya sincronizado, sin red."""
    out = []
    for x in _guardadas():
        try:
            out.append((_zip(x), _comprobado(x)))
        except ErrorPaquete:
            continue
    return out


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


def sincronizar(seguir=lambda: True) -> dict:
    """{'nuevos': [id], 'fallos': [texto]}. `seguir()` falso = dejarlo."""
    if not disponible():
        raise ErrorGestor("los complementos se actualizan con el programa")
    b = _pedir('catalogo.json', MAX_CATALOGO)
    entradas = leer_catalogo(b)
    res, bajado = {'nuevos': [], 'fallos': []}, 0
    try:
        carpeta().mkdir(parents=True, exist_ok=True, mode=0o700)
        for x in entradas:
            if not seguir():
                return res
            try:
                _comprobado(x)
                continue
            except ErrorPaquete:
                pass
            if bajado > MAX_DESCARGA:
                break
            try:
                z = _pedir(f"zips/{x['id']}-{x['version']}.zip", paquete.MAX_ZIP)
                bajado += len(z)
                if hashlib.sha256(z).hexdigest() != x['sha256']:
                    raise ErrorPaquete("la huella no es la del catálogo")
                _escribir(_zip(x), z)
                _comprobado(x)
                res['nuevos'].append(x['id'])
            except (ErrorGestor, ErrorPaquete) as e:
                _zip(x).unlink(missing_ok=True)
                res['fallos'].append(f"{x['id']}: {e}")
        _escribir(carpeta() / 'catalogo.json', b)
        vigentes = {_zip(x).name for x in entradas}
        for f in carpeta().glob('*.zip'):
            if f.name not in vigentes:
                f.unlink(missing_ok=True)
    except OSError as e:
        raise ErrorGestor(f"no se pudo guardar ({e})") from None
    return res


def publicar(origen, destino) -> int:
    """Para quien mantiene el repositorio: carpetas de complementos → catálogo."""
    destino = Path(destino)
    (destino / 'zips').mkdir(parents=True, exist_ok=True)
    entradas = []
    for d in sorted(Path(origen).iterdir()):
        if not (d / esquema.ARCHIVO).is_file():
            continue
        p = paquete.leer_carpeta(d)
        m = p.manifiesto
        z = destino / 'zips' / f"{p.id}-{m['version']}.zip"
        nuevo = destino / 'zips' / f".{p.id}.zip"
        paquete.empaquetar(d, nuevo)
        # La misma versión es siempre el mismo contenido.
        if z.exists() and paquete.leer_zip(z).huella != p.huella:
            nuevo.unlink()
            raise ErrorGestor(f"{p.id}: cambió sin subir la versión {m['version']}")
        if z.exists():
            nuevo.unlink()
        else:
            os.replace(nuevo, z)
        entradas.append({'id': p.id, 'version': m['version'],
                         'sha256': hashlib.sha256(z.read_bytes()).hexdigest(),
                         'api': m['api_version'] or 1})
    (destino / 'catalogo.json').write_text(
        json.dumps({'formato': 1, 'complementos': entradas}, ensure_ascii=False,
                   indent=1) + '\n', encoding='utf-8')
    return len(entradas)
