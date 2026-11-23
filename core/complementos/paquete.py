# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Leer un complemento (.zip o carpeta) sin fiarse de él.

Todo se lee a memoria con topes y se valida ANTES de escribir nada: rutas
absolutas, «..», enlaces, nombres que chocan en Windows o macOS, archivos que
no son de datos o de código legible y bombas de compresión se rechazan.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

from core.complementos import esquema

MAX_ARCHIVOS = 200
MAX_ARCHIVO = 5_000_000
MAX_TOTAL = 20_000_000
MAX_ZIP = 20_000_000
MAX_RATIO = 200
MAX_RUTA = 150
MAX_NIVELES = 6

EXT_DATOS = {'.json', '.csv', '.txt', '.md', '.png', '.jpg', '.jpeg'}
EXT_CODIGO = {'.py'}
SIN_EXT = {'LICENSE', 'LICENCIA', 'COPYING', 'README', 'LEEME'}
#: Restos que deja el sistema o un editor: se saltan, no se rechazan.
_BASURA = {'__pycache__', '.git', '.ds_store', 'thumbs.db', '__macosx',
           '.pytest_cache', '.gitignore', '.idea', '.vscode'}
_RESERVADOS = {'con', 'prn', 'aux', 'nul',
               *(f'{p}{n}' for p in ('com', 'lpt') for n in range(1, 10))}
_RE_MALOS = re.compile(r'[<>:"|?*\x00-\x1f\x7f]')


class ErrorPaquete(Exception):
    """Un texto para el usuario."""


@dataclass(frozen=True)
class Paquete:
    manifiesto: dict
    archivos: dict            # ruta «a/b.py» → bytes
    huella: str

    @property
    def id(self) -> str:
        return self.manifiesto['id']

    @property
    def con_codigo(self) -> bool:
        return bool(self.manifiesto['codigo'])


def huella(archivos: dict) -> str:
    h = hashlib.sha256()
    for ruta in sorted(archivos):
        b = archivos[ruta]
        n = ruta.encode('utf-8')
        h.update(len(n).to_bytes(4, 'big') + n + len(b).to_bytes(8, 'big') + b)
    return h.hexdigest()


def _es_basura(partes) -> bool:
    return any(p.lower() in _BASURA or p.startswith('._') for p in partes)


def ruta_segura(nombre: str) -> str:
    """La ruta normalizada «a/b», o `ErrorPaquete`."""
    def mal(que):
        raise ErrorPaquete(f"ruta no admitida ({que}): {nombre[:80]!r}")
    if not nombre or len(nombre) > MAX_RUTA:
        mal("vacía o larga")
    if '\\' in nombre:
        mal("barra invertida")
    if nombre.startswith('/') or _RE_MALOS.search(nombre):
        mal("absoluta o con caracteres no admitidos")
    if unicodedata.normalize('NFC', nombre) != nombre:
        mal("caracteres no normalizados")
    partes = nombre.split('/')
    if len(partes) > MAX_NIVELES:
        mal("demasiados niveles")
    for p in partes:
        if p in ('', '.', '..'):
            mal("«.», «..» o vacía")
        if p != p.strip() or p.endswith('.'):
            mal("espacio o punto al final")
        if p.split('.')[0].lower() in _RESERVADOS:
            mal("nombre reservado de Windows")
    return nombre


def _armar(archivos: dict) -> Paquete:
    """{ruta: bytes} con `complemento.json` en la raíz → Paquete."""
    if esquema.ARCHIVO not in archivos:
        raise ErrorPaquete(f"no trae {esquema.ARCHIVO} en la raíz")
    if len(archivos) > MAX_ARCHIVOS:
        raise ErrorPaquete(f"más de {MAX_ARCHIVOS} archivos")
    vistos = set()
    for r in archivos:
        if r.lower() in vistos:
            raise ErrorPaquete(f"dos archivos se llaman igual: {r}")
        vistos.add(r.lower())
    for r in archivos:
        partes = r.lower().split('/')
        for i in range(1, len(partes)):
            if '/'.join(partes[:i]) in vistos:
                raise ErrorPaquete(f"{r}: su carpeta también es un archivo")
    try:
        m = esquema.leer(archivos[esquema.ARCHIVO])
    except esquema.ErrorEsquema as e:
        raise ErrorPaquete("\n".join(e.errores)) from None
    permitidas = EXT_DATOS | (EXT_CODIGO if m['codigo'] else set())
    for r in archivos:
        nombre = r.rsplit('/', 1)[-1]
        ext = os.path.splitext(nombre)[1].lower()
        if ext in permitidas or nombre in SIN_EXT:
            continue
        if ext in EXT_CODIGO:
            raise ErrorPaquete(f"{r}: hay código, pero {esquema.ARCHIVO} no "
                               "declara «codigo»")
        raise ErrorPaquete(f"{r}: tipo de archivo no admitido")
    if m['codigo'] and m['codigo'] not in archivos:
        raise ErrorPaquete(f"falta el archivo de código {m['codigo']}")
    return Paquete(m, dict(archivos), huella(archivos))


class _Topes:
    def __init__(self):
        self.total = 0

    def sumar(self, ruta, n):
        if n > MAX_ARCHIVO:
            raise ErrorPaquete(f"{ruta}: más de {MAX_ARCHIVO // 1_000_000} MB")
        self.total += n
        if self.total > MAX_TOTAL:
            raise ErrorPaquete(f"ocupa más de {MAX_TOTAL // 1_000_000} MB")


def leer_zip(ruta) -> Paquete:
    ruta = Path(ruta)
    try:
        if ruta.stat().st_size > MAX_ZIP:
            raise ErrorPaquete(f"el .zip pesa más de {MAX_ZIP // 1_000_000} MB")
        zf = zipfile.ZipFile(ruta)
    except (OSError, zipfile.BadZipFile) as e:
        raise ErrorPaquete(f"no se puede abrir el .zip ({e})") from None
    archivos, topes = {}, _Topes()
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ARCHIVOS * 3:
            raise ErrorPaquete("demasiadas entradas en el .zip")
        for i in infos:
            # `orig_filename`: zipfile ya corta en el NUL y cambia separadores.
            nombre = i.orig_filename.rstrip('/') if i.is_dir() else i.orig_filename
            if _es_basura(nombre.replace('\\', '/').split('/')):
                continue
            modo = i.external_attr >> 16
            if stat.S_IFMT(modo) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ErrorPaquete(f"enlace o archivo especial: {nombre[:80]!r}")
            ruta_segura(nombre)
            if i.is_dir():
                continue
            if i.flag_bits & 1:
                raise ErrorPaquete("el .zip está cifrado")
            if i.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ErrorPaquete(f"{nombre}: compresión no admitida")
            if i.file_size > 100_000 and \
                    i.file_size > MAX_RATIO * max(i.compress_size, 1):
                raise ErrorPaquete(f"{nombre}: compresión sospechosa")
            if nombre in archivos:
                raise ErrorPaquete(f"entrada repetida: {nombre}")
            # Se lee con tope: el tamaño declarado puede mentir.
            try:
                with zf.open(i) as fh:
                    b = fh.read(MAX_ARCHIVO + 1)
            except (OSError, RuntimeError, zipfile.BadZipFile, EOFError,
                    NotImplementedError, ValueError) as e:
                raise ErrorPaquete(f"{nombre}: no se puede leer ({e})") from None
            except Exception as e:  # noqa: BLE001 — zlib.error y parientes
                raise ErrorPaquete(f"{nombre}: dañado ({e})") from None
            topes.sumar(nombre, len(b))
            archivos[nombre] = b
    # Un zip de «la carpeta» trae una sola raíz: se quita.
    if esquema.ARCHIVO not in archivos:
        raices = {r.split('/', 1)[0] for r in archivos}
        if len(raices) == 1 and all('/' in r for r in archivos):
            archivos = {r.split('/', 1)[1]: b for r, b in archivos.items()}
    return _armar(archivos)


def leer_carpeta(ruta) -> Paquete:
    base = Path(ruta)
    if base.is_symlink() or not base.is_dir():
        raise ErrorPaquete(f"no es una carpeta: {base}")
    archivos, topes = {}, _Topes()

    def recorrer(d: Path, prefijo: str):
        try:
            entradas = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError as e:
            raise ErrorPaquete(f"no se puede leer la carpeta ({e})") from None
        for e in entradas:
            if _es_basura([e.name]):
                continue
            rel = ruta_segura(prefijo + e.name)
            if e.is_symlink():
                raise ErrorPaquete(f"enlace: {rel}")
            if e.is_dir(follow_symlinks=False):
                recorrer(Path(e.path), rel + '/')
            elif e.is_file(follow_symlinks=False):
                if len(archivos) >= MAX_ARCHIVOS:
                    raise ErrorPaquete(f"más de {MAX_ARCHIVOS} archivos")
                try:
                    with open(e.path, 'rb') as fh:
                        b = fh.read(MAX_ARCHIVO + 1)
                except OSError as err:
                    raise ErrorPaquete(f"{rel}: {err}") from None
                topes.sumar(rel, len(b))
                archivos[rel] = b
            else:
                raise ErrorPaquete(f"archivo especial: {rel}")
    recorrer(base, '')
    return _armar(archivos)


def leer(ruta) -> Paquete:
    """De un .zip o de una carpeta."""
    ruta = Path(ruta)
    return leer_carpeta(ruta) if ruta.is_dir() else leer_zip(ruta)


def escribir(paq: Paquete, destino: Path) -> None:
    """Los archivos a una carpeta NUEVA."""
    destino.mkdir(parents=True, mode=0o700)
    for rel, b in paq.archivos.items():
        f = destino.joinpath(*rel.split('/'))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b)


def empaquetar(carpeta, destino) -> Path:
    """Carpeta → .zip instalable (reproducible: mismas fechas y orden)."""
    paq = leer_carpeta(carpeta)
    destino = Path(destino)
    with zipfile.ZipFile(destino, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(paq.archivos):
            i = zipfile.ZipInfo(f"{paq.id}/{rel}", (2026, 1, 1, 0, 0, 0))
            i.external_attr = 0o644 << 16
            i.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(i, paq.archivos[rel])
    leer_zip(destino)
    return destino
