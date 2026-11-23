# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Geometría de un IFC para el visor BIM (sin Qt).

IfcOpenShell convierte el IFC en mallas en un PROCESO APARTE: un archivo mal
hecho puede tumbar el núcleo geométrico (código C++) y no debe llevarse la app
por delante. El resultado queda en una caché de `USER_DATA_DIR/bim_cache`, que
se abre con memoria mapeada, así que volver a abrir un modelo es inmediato.

Uso:
    if disponible():
        geo = convertir(ruta, progreso=lambda pct: ...)   # bloquea
    # o, desde Qt, QProcess con `comando(ruta)` y al terminar `abrir_cache(ruta)`.

Una «parte» es un trozo de un elemento con un solo color. Cada vértice lleva en
su UV el número de su parte: el visor pinta con una textura de un texel por
parte, y resaltar, aislar o volver transparente es cambiar esa textura.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# Sube al cambiar el formato en disco: invalida la caché vieja.
FORMATO = 1
# Tope para no agotar la memoria (el visor usa ~100 B por triángulo en RAM,
# más lo mismo en la tarjeta gráfica).
MAX_TRIANGULOS = 8_000_000
MAX_CACHE_BYTES = 1_000_000_000
ANCHO_PALETA = 1024          # texels por fila de la textura de colores
TRI_POR_BLOQUE = 400_000
CLASES_OCULTAS = {'IfcSpace', 'IfcSpatialZone'}
_CLASES_EXCLUIDAS = ('IfcOpeningElement', 'IfcVirtualElement', 'IfcGrid',
                     'IfcAnnotation')
OPCION_PROCESO = '--bim-geometria'     # la atiende main.py en el binario

_COLORES_CLASE = {
    'IfcWall': (214, 208, 196), 'IfcSlab': (178, 180, 182),
    'IfcColumn': (150, 158, 168), 'IfcBeam': (150, 158, 168),
    'IfcFooting': (140, 136, 130), 'IfcRoof': (168, 96, 78),
    'IfcDoor': (150, 106, 70), 'IfcWindow': (150, 190, 214),
    'IfcStair': (186, 180, 170), 'IfcRailing': (110, 116, 124),
    'IfcPipe': (80, 130, 190), 'IfcDuct': (120, 160, 170),
    'IfcFlow': (110, 150, 180), 'IfcReinforcing': (120, 80, 60),
}
_COLOR_DEFECTO = (196, 196, 192)


class ErrorGeometria(Exception):
    """Mensaje listo para mostrar al usuario (en español)."""


def disponible() -> bool:
    """¿Está IfcOpenShell? No lo importa: cargarlo cuesta y solo lo usa el
    proceso hijo."""
    import importlib.util
    try:
        return (importlib.util.find_spec('ifcopenshell') is not None
                and importlib.util.find_spec('numpy') is not None)
    except (ImportError, ValueError):
        return False


# ── Caché ────────────────────────────────────────────────────────────────────

def carpeta_cache() -> Path:
    from core.config import USER_DATA_DIR
    return USER_DATA_DIR / 'bim_cache'


def huella(ruta) -> str:
    h = hashlib.sha256(f'f{FORMATO}:'.encode())
    with open(ruta, 'rb') as fh:
        while bloque := fh.read(1 << 20):
            h.update(bloque)
    return h.hexdigest()[:32]


@dataclass
class ElementoGeo:
    global_id: str
    clase: str
    nombre: str
    piso: str
    partes: list[int] = field(default_factory=list)


class Geometria:
    """Mallas de un modelo, mapeadas en memoria desde la caché."""

    def __init__(self, carpeta: Path):
        import numpy as np
        self.carpeta = Path(carpeta)
        meta = json.loads((self.carpeta / 'meta.json').read_text('utf-8'))
        if meta.get('formato') != FORMATO:
            raise ErrorGeometria('La caché de geometría es de otra versión.')
        self.nombre = meta['nombre']
        self.avisos: list[str] = meta['avisos']
        self.centro = meta['centro']
        self.pisos: list[str] = meta['pisos']
        self.elementos = [ElementoGeo(*e) for e in meta['elementos']]
        self.por_id = {e.global_id: i for i, e in enumerate(self.elementos)}
        self.n_partes = meta['n_partes']
        self.n_vertices = meta['n_vertices']
        self.n_triangulos = meta['n_triangulos']
        forma = (self.n_vertices, 8)
        if self.n_vertices:
            self.vertices = np.memmap(self.carpeta / 'v.bin', np.float32, 'r', shape=forma)
            self.indices = np.memmap(self.carpeta / 'i.bin', np.uint32, 'r',
                                     shape=(self.n_triangulos, 3))
        else:
            self.vertices = np.zeros((0, 8), np.float32)
            self.indices = np.zeros((0, 3), np.uint32)
        # por parte: elemento, v0, nv, t0, nt / color RGBA / caja min-max
        self.partes = np.load(self.carpeta / 'partes.npy')
        self.colores = np.load(self.carpeta / 'colores.npy')
        self.cajas = np.load(self.carpeta / 'cajas.npy')

    @property
    def caja(self):
        if not len(self.cajas):
            return [0, 0, 0], [0, 0, 0]
        return self.cajas[:, :3].min(0).tolist(), self.cajas[:, 3:].max(0).tolist()

    def bloques(self, max_tri: int = TRI_POR_BLOQUE):
        """Trozos (vértices Nx8 float32, índices uint32 locales) para la GPU.

        Se parte por piso/parte contigua: cada bloque se descarta solo cuando
        queda fuera de cámara."""
        import numpy as np
        n, i = len(self.partes), 0
        while i < n:
            j, tri = i, 0
            while j < n and (j == i or tri + self.partes[j, 4] <= max_tri):
                tri += self.partes[j, 4]
                j += 1
            v0, t0 = int(self.partes[i, 1]), int(self.partes[i, 3])
            v1 = int(self.partes[j - 1, 1] + self.partes[j - 1, 2])
            t1 = int(self.partes[j - 1, 3] + self.partes[j - 1, 4])
            if t1 > t0:
                yield (self.vertices[v0:v1],
                       (np.asarray(self.indices[t0:t1]) - v0).astype(np.uint32))
            i = j

    def caja_de(self, global_ids):
        """(min, max) que abarca esos elementos, o None."""
        partes = [p for g in global_ids if g in self.por_id
                  for p in self.elementos[self.por_id[g]].partes]
        if not partes:
            return None
        c = self.cajas[partes]
        return c[:, :3].min(0).tolist(), c[:, 3:].max(0).tolist()

    def elemento_bajo_rayo(self, origen, direccion, visibles=None):
        """Índice del primer elemento que corta el rayo, o None.

        `visibles`: máscara booleana por parte (lo oculto no se puede tocar)."""
        import numpy as np
        if not len(self.partes):
            return None
        o = np.asarray(origen, np.float64)
        d = np.asarray(direccion, np.float64)
        with np.errstate(divide='ignore', invalid='ignore'):
            t1 = (self.cajas[:, :3] - 1e-4 - o) / d
            t2 = (self.cajas[:, 3:] + 1e-4 - o) / d
        # 0/0: rayo paralelo y sobre el plano de la caja: no limita
        cerca = np.nan_to_num(np.fmin(t1, t2), nan=-np.inf, posinf=np.inf, neginf=-np.inf).max(1)
        lejos = np.nan_to_num(np.fmax(t1, t2), nan=np.inf, posinf=np.inf, neginf=-np.inf).min(1)
        toca = (lejos >= np.maximum(cerca, 0))
        if visibles is not None:
            toca &= visibles
        cand = np.flatnonzero(toca)
        cand = cand[np.argsort(cerca[cand])]
        mejor, hallado = np.inf, None
        for p in cand:
            if cerca[p] > mejor:
                break
            el, v0, nv, t0, nt = (int(x) for x in self.partes[p])
            xyz = np.asarray(self.vertices[v0:v0 + nv, :3], np.float64)
            tri = xyz[np.asarray(self.indices[t0:t0 + nt], np.int64) - v0]
            a, e1, e2 = tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
            h = np.cross(d, e2)
            det = np.einsum('ij,ij->i', e1, h)
            with np.errstate(divide='ignore', invalid='ignore'):
                f = 1.0 / det
                s = o - a
                u = f * np.einsum('ij,ij->i', s, h)
                q = np.cross(s, e1)
                v = f * np.einsum('j,ij->i', d, q)
                t = f * np.einsum('ij,ij->i', e2, q)
                ok = (np.abs(det) > 1e-14) & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-6)
            if ok.any():
                tm = t[ok].min()
                if tm < mejor:
                    mejor, hallado = tm, el
        return hallado


def abrir_cache(ruta) -> Geometria | None:
    """Geometría ya convertida de ese archivo, o None si no está o está rota."""
    destino = carpeta_cache() / huella(ruta)
    if not (destino / 'meta.json').exists():
        return None
    try:
        geo = Geometria(destino)
        os.utime(destino)            # marca de uso para la limpieza
        return geo
    except Exception:
        shutil.rmtree(destino, ignore_errors=True)
        return None


def limpiar_cache(max_bytes: int = MAX_CACHE_BYTES, conservar=None):
    """Borra los modelos menos usados hasta bajar del tope."""
    base = carpeta_cache()
    if not base.is_dir():
        return
    dirs = []
    for d in base.iterdir():
        if d.is_dir() and d.name.startswith('tmp'):
            # restos de una conversión que se cortó
            if time.time() - d.stat().st_mtime > 86400:
                shutil.rmtree(d, ignore_errors=True)
        elif d.is_dir():
            peso = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
            dirs.append((d.stat().st_mtime, peso, d))
    total = sum(p for _m, p, _d in dirs)
    for _m, peso, d in sorted(dirs, key=lambda x: x[0]):
        if total <= max_bytes:
            break
        if conservar and d.name == conservar:
            continue
        shutil.rmtree(d, ignore_errors=True)
        total -= peso


# ── Proceso hijo ─────────────────────────────────────────────────────────────

def comando(ruta, destino) -> list[str]:
    """Orden que convierte `ruta` y deja el resultado en `destino`."""
    if getattr(sys, 'frozen', False):
        return [sys.executable, OPCION_PROCESO, str(ruta), str(destino)]
    return [sys.executable, str(Path(__file__).resolve()), str(ruta), str(destino)]


def preparar(ruta) -> Path:
    """Carpeta temporal (dentro de la caché) donde escribirá el hijo."""
    base = carpeta_cache()
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='tmp', dir=base))


def finalizar(ruta, temporal) -> Geometria:
    """Publica en la caché lo que dejó el hijo y lo abre."""
    clave = huella(ruta)
    destino = carpeta_cache() / clave
    if (destino / 'meta.json').exists():      # lo convirtió otra ventana
        shutil.rmtree(temporal, ignore_errors=True)
        return Geometria(destino)
    shutil.rmtree(destino, ignore_errors=True)
    try:
        os.replace(temporal, destino)
    except OSError:                           # Windows: restos en uso
        return Geometria(temporal)
    limpiar_cache(conservar=clave)
    return Geometria(destino)


def mensaje_de_salida(codigo: int, temporal=None) -> str:
    try:
        if texto := (Path(temporal) / 'error.txt').read_text('utf-8'):
            return texto
    except (OSError, TypeError):
        pass
    if codigo < 0 or codigo > 2:
        return ('El lector de geometría se cerró al procesar este archivo '
                '(está dañado o es demasiado grande).')
    return 'No se pudo leer la geometría de este archivo.'


def convertir(ruta, progreso=None, timeout: float | None = None) -> Geometria:
    """Convierte (o abre de la caché) y devuelve la geometría. Bloquea."""
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ErrorGeometria(f'No se encuentra el archivo {ruta.name}.')
    geo = abrir_cache(ruta)
    if geo is not None:
        return geo
    if not disponible():
        raise ErrorGeometria('Falta IfcOpenShell: esta instalación no puede '
                             'mostrar modelos en 3D.')
    tmp = preparar(ruta)
    extra = {}
    if sys.platform == 'win32':
        extra['creationflags'] = 0x08000000        # sin ventana de consola
    p = subprocess.Popen(comando(ruta, tmp), stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True,
                         encoding='utf-8', errors='replace', **extra)
    reloj = threading.Timer(timeout, p.kill) if timeout else None
    if reloj:
        reloj.start()
    try:
        for linea in p.stdout:
            pct = leer_progreso(linea)
            if pct is not None and progreso:
                progreso(pct)
        codigo = p.wait()
        if codigo != 0 or not (tmp / 'meta.json').exists():
            raise ErrorGeometria(mensaje_de_salida(codigo, tmp))
        return finalizar(ruta, tmp)
    finally:
        if reloj:
            reloj.cancel()
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdout.close()
        shutil.rmtree(tmp, ignore_errors=True)


def leer_progreso(linea: str) -> int | None:
    """Línea del hijo → porcentaje, o None si es otra cosa."""
    try:
        return int(json.loads(linea)['p'])
    except (ValueError, TypeError, KeyError):
        return None


def _emitir(**dato):
    if sys.stdout is None:          # binario de Windows: sin consola no hay tubería
        return
    sys.stdout.write(json.dumps(dato) + '\n')
    sys.stdout.flush()


def _color_clase(clase: str):
    for pref, c in _COLORES_CLASE.items():
        if clase.startswith(pref):
            return c
    return _COLOR_DEFECTO


def _pisos_de(f) -> dict:
    """{id de elemento: nombre de piso}, siguiendo contención y agregación."""
    padre = {}
    for r in f.by_type('IfcRelContainedInSpatialStructure'):
        for e in r.RelatedElements:
            padre[e.id()] = r.RelatingStructure
    for r in f.by_type('IfcRelAggregates'):
        for e in r.RelatedObjects:
            padre.setdefault(e.id(), r.RelatingObject)
    # puertas y ventanas sin contención propia: el piso del muro que las aloja
    hueco = {r.RelatedOpeningElement.id(): r.RelatingBuildingElement
             for r in f.by_type('IfcRelVoidsElement')}
    for r in f.by_type('IfcRelFillsElement'):
        muro = hueco.get(r.RelatingOpeningElement.id())
        if muro is not None:
            padre.setdefault(r.RelatedBuildingElement.id(), muro)
    nombres = {}

    def piso(pid):
        vistos = set()
        while pid in padre and pid not in vistos:
            vistos.add(pid)
            p = padre[pid]
            if p.is_a('IfcBuildingStorey'):
                return p.Name or p.LongName or p.GlobalId
            pid = p.id()
        return ''
    for pid in padre:
        nombres[pid] = piso(pid)
    return nombres


def _hijo(ruta: str, destino: str) -> int:
    """Conversión propiamente dicha. Corre en el proceso aparte."""
    import multiprocessing

    import ifcopenshell
    import ifcopenshell.geom
    import numpy as np

    if getattr(sys, 'frozen', False) and hasattr(ifcopenshell, 'set_plugin_search_paths'):
        # En el binario, la biblioteca se carga por un enlace de la carpeta de
        # arriba y buscaría sus núcleos allí, no junto al paquete.
        ifcopenshell.set_plugin_search_paths([Path(ifcopenshell.__file__).parent])

    destino = Path(destino)
    try:
        f = ifcopenshell.open(ruta)
    except Exception:
        raise ErrorGeometria('El archivo no es un IFC válido o está dañado.')
    pisos = _pisos_de(f)
    orden_pisos = sorted(f.by_type('IfcBuildingStorey'),
                         key=lambda s: (s.Elevation or 0.0))
    lista_pisos = list(dict.fromkeys(
        (s.Name or s.LongName or s.GlobalId) for s in orden_pisos))

    ajustes = ifcopenshell.geom.settings()
    ajustes.set('use-world-coords', False)
    ajustes.set('weld-vertices', False)
    ajustes.set('apply-default-materials', False)
    excluir = []
    for c in _CLASES_EXCLUIDAS:
        try:
            excluir += f.by_type(c)
        except RuntimeError:
            pass                       # la clase no existe en este esquema
    hilos = max(1, min(4, multiprocessing.cpu_count() - 1))
    it = ifcopenshell.geom.iterator(ajustes, f, hilos, exclude=excluir or None)

    elementos, partes, colores, cajas, avisos = [], [], [], [], []
    por_id = {}
    nv = nt = 0
    centro = None
    ultimo = -1
    recortado = False
    with open(destino / 'v.bin', 'wb') as fv, open(destino / 'i.bin', 'wb') as fi:
        sigue = it.initialize()
        while sigue:
            forma = it.get()
            geom = forma.geometry
            verts = np.frombuffer(geom.verts_buffer, np.float64).reshape(-1, 3)
            caras = np.frombuffer(geom.faces_buffer, np.int32).reshape(-1, 3)
            if len(caras) and len(verts):
                if nt + len(caras) > MAX_TRIANGULOS:
                    recortado = True
                    break
                m = np.frombuffer(forma.transformation_buffer, np.float64
                                  ).reshape(4, 4, order='F')
                xyz = verts @ m[:3, :3].T + m[:3, 3]
                if centro is None:      # georreferenciados: float32 pierde cm
                    centro = np.round((xyz.min(0) + xyz.max(0)) / 2)
                # IFC es Z arriba; Qt Quick 3D es Y arriba
                xyz = xyz - centro
                xyz = np.column_stack((xyz[:, 0], xyz[:, 2], -xyz[:, 1]))
                tri = xyz[caras]
                n_tri = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
                mats = np.frombuffer(geom.material_ids_buffer, np.int32)
                if len(mats) != len(caras):
                    mats = np.full(len(caras), -1, np.int32)
                prod = f.by_id(forma.id)
                gid = prod.GlobalId
                k = por_id.get(gid)
                if k is None:
                    k = por_id[gid] = len(elementos)
                    elementos.append([gid, prod.is_a(), prod.Name or '',
                                      pisos.get(prod.id(), ''), []])
                base = _color_clase(prod.is_a())
                materiales = geom.materials
                for mid in np.unique(mats):
                    sel = mats == mid
                    c, n_c = caras[sel], n_tri[sel]
                    usados, inv = np.unique(c, return_inverse=True)
                    inv = inv.reshape(-1, 3)
                    # normal del vértice = suma de las de sus caras (los
                    # vértices ya vienen partidos en las aristas vivas)
                    nor = np.zeros((len(usados), 3))
                    for e in range(3):
                        np.add.at(nor, inv[:, e], n_c)
                    largo = np.linalg.norm(nor, axis=1, keepdims=True)
                    nor = np.divide(nor, largo, out=np.zeros_like(nor), where=largo > 0)
                    num = len(partes)
                    buf = np.empty((len(usados), 8), np.float32)
                    buf[:, :3] = p = xyz[usados]
                    buf[:, 3:6] = nor
                    buf[:, 6] = num          # se normaliza al final
                    buf[:, 7] = 0
                    fv.write(buf.tobytes())
                    fi.write((inv + nv).astype(np.uint32).tobytes())
                    partes.append((k, nv, len(usados), nt, len(c)))
                    elementos[k][4].append(num)
                    cajas.append(np.concatenate((buf[:, :3].min(0), buf[:, :3].max(0))))
                    rgba = (*base, 255)
                    if 0 <= mid < len(materiales):
                        mat = materiales[int(mid)]
                        try:
                            d = mat.diffuse
                            if d.r() == d.r() and d.r() >= 0:
                                a = 1.0 - (mat.transparency if mat.has_transparency() else 0.0)
                                rgba = tuple(int(255 * min(1, max(0, x)))
                                             for x in (d.r(), d.g(), d.b(), max(a, .15)))
                        except (AttributeError, TypeError):
                            pass
                    elif prod.is_a().startswith('IfcWindow'):
                        rgba = (*base, 110)
                    colores.append(rgba)
                    nv += len(usados)
                    nt += len(c)
            pct = it.progress()
            if pct != ultimo:
                ultimo = pct
                _emitir(p=pct)
            sigue = it.next()
    if not partes:
        raise ErrorGeometria('El archivo no trae geometría 3D.')
    if recortado:
        avisos.append(f'Modelo muy grande: solo se muestran los primeros '
                      f'{MAX_TRIANGULOS:,} triángulos.')
    # UV de cada vértice = centro del texel de su parte
    filas = -(-len(partes) // ANCHO_PALETA)
    vv = np.memmap(destino / 'v.bin', np.float32, 'r+', shape=(nv, 8))
    paso = 1_000_000
    for i in range(0, nv, paso):
        n = vv[i:i + paso, 6].astype(np.int64)
        vv[i:i + paso, 6] = (n % ANCHO_PALETA + .5) / ANCHO_PALETA
        vv[i:i + paso, 7] = (n // ANCHO_PALETA + .5) / filas
    vv.flush()
    del vv
    np.save(destino / 'partes.npy', np.asarray(partes, np.int64))
    np.save(destino / 'colores.npy', np.asarray(colores, np.uint8))
    np.save(destino / 'cajas.npy', np.asarray(cajas, np.float32))
    meta = {'formato': FORMATO, 'nombre': Path(ruta).name, 'avisos': avisos,
            'centro': centro.tolist(), 'pisos': lista_pisos,
            'elementos': elementos, 'n_partes': len(partes),
            'n_vertices': nv, 'n_triangulos': nt}
    # el último: su presencia significa «completo»
    (destino / 'meta.json').write_text(json.dumps(meta), 'utf-8')
    return 0


def proceso_hijo(args: list[str]):
    """Punto de entrada del proceso aparte: [ruta, destino]. No vuelve."""
    codigo, error = 2, ''
    try:
        codigo = _hijo(args[0], args[1])
    except ErrorGeometria as exc:
        error = str(exc)
    except MemoryError:
        error = 'No hay memoria suficiente para este modelo.'
    except Exception as exc:                       # noqa: BLE001
        error = f'No se pudo leer la geometría: {exc}'
    if error:
        # A un archivo y no por la tubería: el binario de Windows no tiene stdout
        try:
            (Path(args[1]) / 'error.txt').write_text(error, 'utf-8')
        except OSError:
            pass
    # Sin pasar por el cierre del intérprete: el iterador de IfcOpenShell, si
    # quedó a medias, revienta al destruirse (violación de segmento, 0.9.0).
    if sys.stdout is not None:
        sys.stdout.flush()
    os._exit(codigo)


if __name__ == '__main__':
    # Ejecutado como script, sys.path[0] es core/: quitarlo evita que un módulo
    # de core tape a uno de la biblioteca estándar.
    sys.path[0] = str(Path(__file__).resolve().parent.parent)
    proceso_hijo(sys.argv[1:])
