# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""API pública de complementos.

Lo que hay en este archivo es lo ÚNICO que un complemento debe importar del
programa; `core`, `views` y la base de datos cambian sin aviso.

Un complemento con código define, en el archivo que dice su `complemento.json`:

    from ingepresupuestos import api

    def registrar(app):
        app.reporte("mi-reporte", "Mi reporte", generar)

    def generar(p):                 # p: api.Presupuesto
        return api.Documento("Mi reporte", [api.Parrafo(p.nombre)])

Los datos llegan ya calculados y de solo lectura. Para cambiar el proyecto
está `ctx.editar`: cada llamada es una transacción que se puede deshacer.

`API_VERSION` sube cuando se AÑADE algo. Lo que existe no se quita ni cambia
de significado dentro de la misma versión mayor del programa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Sequence

API_VERSION = 1


class ErrorComplemento(Exception):
    """Un error con un texto pensado para el usuario: se le muestra tal cual."""


def redondear(valor: float, decimales: int = 2) -> float:
    """Redondeo comercial (0,5 hacia arriba), el mismo del programa."""
    q = Decimal(10) ** -decimales
    return float(Decimal(f'{float(valor or 0):.10f}').quantize(q, ROUND_HALF_UP))


# ── Datos del presupuesto (solo lectura, ya calculados) ──────────────────────

@dataclass(frozen=True)
class Moneda:
    nombre: str
    simbolo: str
    miles: str
    decimal: str

    def numero(self, valor: float, decimales: int = 2) -> str:
        """Número con los separadores de la moneda, sin símbolo."""
        t = f'{redondear(valor, decimales):,.{decimales}f}'
        return t.translate({ord(','): self.miles, ord('.'): self.decimal})

    def formato(self, valor: float, decimales: int = 2) -> str:
        return f'{self.simbolo} {self.numero(valor, decimales)}'


@dataclass(frozen=True)
class Insumo:
    """Una línea del análisis (ACU) de una partida."""
    recurso_id: int
    codigo: str
    descripcion: str
    tipo: str                    # 'MO' | 'MAT' | 'EQ' | 'SC'
    unidad: str
    cuadrilla: float
    cantidad: float              # por unidad de partida
    precio: float
    parcial: float               # ya redondeado; en un «%» no es cantidad × precio
    es_subpartida: bool = False

    @property
    def es_porcentaje(self) -> bool:
        return self.unidad.startswith('%')


@dataclass(frozen=True)
class Partida:
    id: int
    item: str
    descripcion: str
    nivel: int
    es_titulo: bool
    unidad: str
    metrado: float
    precio_unitario: float
    parcial: float               # en un título, la suma de lo que cuelga de él
    rendimiento: float           # 0 = no aplica
    sub_presupuesto: str
    acu: tuple[Insumo, ...] = ()


@dataclass(frozen=True)
class LineaPie:
    nombre: str
    codigo: str
    tipo: str                    # rubro | pct_cd | pct_sub | pct_util | subtotal
    pct: float
    valor: float
    es_impuesto: bool


@dataclass(frozen=True)
class InsumoTotal:
    """Un insumo sumado en todo el proyecto."""
    recurso_id: int
    codigo: str
    descripcion: str
    tipo: str
    unidad: str
    precio: float
    cantidad: float
    parcial: float


@dataclass(frozen=True)
class Presupuesto:
    id: int
    nombre: str
    cliente: str
    ubicacion: str
    fecha_costos: str
    plazo_dias: int
    jornada: float
    estado: str
    moneda: Moneda
    decimales: int               # de los montos
    partidas: tuple[Partida, ...]    # títulos y partidas, en orden
    pie: tuple[LineaPie, ...]
    insumos: tuple[InsumoTotal, ...]
    costo_directo: float
    total: float

    def hojas(self) -> list[Partida]:
        """Solo las partidas (sin títulos)."""
        return [p for p in self.partidas if not p.es_titulo]


# ── Documentos: lo que devuelve un reporte ───────────────────────────────────
# El programa lo convierte en PDF o en Excel; el complemento no maneja ninguno.

@dataclass(frozen=True)
class Titulo:
    texto: str
    nivel: int = 1               # 1 a 3


@dataclass(frozen=True)
class Parrafo:
    texto: str
    negrita: bool = False
    alinear: str = 'izquierda'   # izquierda | centro | derecha


@dataclass(frozen=True)
class Campos:
    """Pares etiqueta/valor, como la cabecera de una ficha."""
    pares: Sequence[tuple[str, str]]


@dataclass(frozen=True)
class Columna:
    titulo: str
    ancho: int = 0               # % del ancho; 0 = automático
    alinear: str = 'izquierda'
    decimales: int | None = None  # números de la columna; None = 2


@dataclass(frozen=True)
class Fila:
    celdas: Sequence[Any]        # textos, números o None
    estilo: str = 'normal'       # normal | titulo | subtotal


@dataclass(frozen=True)
class Tabla:
    columnas: Sequence[Columna]
    filas: Sequence[Fila | Sequence[Any]]
    cabecera: bool = True


@dataclass(frozen=True)
class SaltoPagina:
    pass


@dataclass(frozen=True)
class Documento:
    titulo: str
    bloques: Sequence[Any]
    horizontal: bool = False


# ── Importadores y validadores ───────────────────────────────────────────────

@dataclass(frozen=True)
class PartidaNueva:
    """Lo que devuelve un importador, en orden. `item` fija el código
    («01.02»); sin él se toma el siguiente libre bajo `padre`."""
    descripcion: str = ''
    unidad: str = ''
    metrado: float | None = None
    es_titulo: bool = False
    item: str = ''
    padre: str = ''
    biblioteca_id: int | None = None


@dataclass(frozen=True)
class Aviso:
    texto: str
    nivel: str = 'aviso'         # aviso | error
    partida_id: int | None = None


# ── Lo que el complemento recibe en `registrar(app)` ─────────────────────────

@dataclass(frozen=True)
class _Registro:
    clase: str                   # accion | reporte | importador | validador
    clave: str
    titulo: str
    funcion: Callable
    extra: dict = field(default_factory=dict)


class Aplicacion:
    """Registra lo que el complemento añade. Solo vale dentro de `registrar`."""

    api_version = API_VERSION

    def __init__(self, complemento_id: str):
        self.id = complemento_id
        self._registros: list[_Registro] = []
        self._abierta = True

    def _poner(self, clase, clave, titulo, funcion, **extra):
        if not self._abierta:
            raise ErrorComplemento(
                "solo se puede registrar dentro de registrar(app)")
        if not isinstance(clave, str) or not clave.strip() \
                or not isinstance(titulo, str) or not titulo.strip():
            raise ErrorComplemento("la clave y el título son textos obligatorios")
        if not callable(funcion):
            raise ErrorComplemento(f"«{titulo}»: falta la función")
        if any(r.clase == clase and r.clave == clave for r in self._registros):
            raise ErrorComplemento(f"«{clave}» está registrado dos veces")
        self._registros.append(_Registro(clase, clave, titulo.strip()[:80],
                                         funcion, extra))

    def accion(self, clave: str, titulo: str, funcion: Callable, *,
               ayuda: str = '') -> None:
        """Entrada de menú. `funcion(ctx)`."""
        self._poner('accion', clave, titulo, funcion, ayuda=str(ayuda))

    def reporte(self, clave: str, titulo: str, funcion: Callable, *,
                formatos: Sequence[str] = ('pdf', 'xlsx'),
                ayuda: str = '') -> None:
        """`funcion(presupuesto) -> Documento`."""
        fs = tuple(formatos)
        if not fs or set(fs) - {'pdf', 'xlsx'}:
            raise ErrorComplemento("formatos: 'pdf', 'xlsx' o los dos")
        self._poner('reporte', clave, titulo, funcion, formatos=fs,
                    ayuda=str(ayuda))

    def importador(self, clave: str, titulo: str, funcion: Callable, *,
                   extensiones: Sequence[str], ayuda: str = '') -> None:
        """`funcion(ruta, ctx) -> lista de PartidaNueva`. El programa enseña
        cuántas son, pide confirmación y las agrega de una sola vez."""
        exts = tuple(str(e).lower().lstrip('.') for e in extensiones)
        if not exts or not all(e.isalnum() for e in exts):
            raise ErrorComplemento("extensiones: por ejemplo ('csv', 'txt')")
        self._poner('importador', clave, titulo, funcion, extensiones=exts,
                    ayuda=str(ayuda))

    def validador(self, clave: str, titulo: str, funcion: Callable, *,
                  ayuda: str = '') -> None:
        """`funcion(presupuesto) -> lista de Aviso`."""
        self._poner('validador', clave, titulo, funcion, ayuda=str(ayuda))


class Editor:
    """Escritura del proyecto (`ctx.editar`). Cada método es UNA transacción:
    si falla no queda nada, y se puede deshacer. Respeta los permisos del
    usuario y el estado del proyecto."""

    def agregar(self, partidas: Sequence[PartidaNueva], *,
                sub_presupuesto_id: int = 0) -> list[int]:
        """Agrega títulos y partidas, en orden. Devuelve sus ids."""
        raise NotImplementedError

    def fijar_metrado(self, partida_id: int, cantidad: float, *,
                      reemplazar_planilla: bool = False) -> None:
        raise NotImplementedError

    def fijar_precio(self, recurso_id: int, precio: float) -> None:
        """El precio de un insumo EN ESTE PROYECTO (no en el catálogo)."""
        raise NotImplementedError

    def renombrar(self, partida_id: int, descripcion: str) -> None:
        raise NotImplementedError


class Contexto:
    """Lo que recibe una acción o un importador."""

    complemento: str
    editar: Editor

    @property
    def presupuesto(self) -> Presupuesto:
        """Foto del proyecto abierto, recalculada cada vez que se pide."""
        raise NotImplementedError

    def recurso(self, ruta: str) -> bytes:
        """Un archivo del propio complemento («datos/tabla.csv»)."""
        raise NotImplementedError

    def indice(self, clave: str) -> list[tuple[str, float]]:
        """[(«AAAA-MM», valor)] de un índice declarado en complemento.json:
        lo que importó el usuario o, si no importó nada, lo que trae el paquete."""
        raise NotImplementedError

    def avisar(self, texto: str) -> None:
        raise NotImplementedError

    def preguntar(self, texto: str) -> bool:
        raise NotImplementedError

    def pedir_archivo(self, extensiones: Sequence[str] = ()) -> str | None:
        """Ruta de un archivo que elige el usuario, o None."""
        raise NotImplementedError


__all__ = [
    'API_VERSION', 'Aplicacion', 'Aviso', 'Campos', 'Columna', 'Contexto',
    'Documento', 'Editor', 'ErrorComplemento', 'Fila', 'Insumo', 'InsumoTotal',
    'LineaPie', 'Moneda', 'Parrafo', 'Partida', 'PartidaNueva', 'Presupuesto',
    'SaltoPagina', 'Tabla', 'Titulo', 'redondear',
]
