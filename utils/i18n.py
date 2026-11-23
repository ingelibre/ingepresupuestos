# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Internacionalización de la interfaz.

Uso:
    from utils.i18n import tr
    label.setText(tr("Guardar"))
    msg = tr("Se importaron {n} partidas").format(n=total)

El español es el idioma base: el texto que se pasa a `tr()` ES la clave.
Cada idioma tiene un archivo `resources/i18n/<código>.json` con
{texto_español: traducción}; se lee una sola vez, la primera vez que hace
falta. Si falta la clave (o el archivo), `tr()` devuelve el español.

El idioma activo se lee de configuracion.idioma ('es' | 'en' | 'pt_BR').
Los REPORTES no pasan por aquí: salen en el idioma del proyecto.

Para saber qué cadenas faltan en cada JSON: `python3 scripts/i18n_faltantes.py`.
"""

import json
from pathlib import Path

from core.config import BASE_DIR

# (código, nombre y descripción escritos EN ese idioma: no pasan por tr())
IDIOMAS: tuple[tuple[str, str, str], ...] = (
    ('es', "Español (Perú)", "Idioma principal de la aplicación"),
    ('en', "English", "Interface in English"),
    ('pt_BR', "Português (Brasil)", "Interface em português do Brasil"),
)

DIR_I18N = Path(BASE_DIR) / "resources" / "i18n"

_idioma_actual: str | None = None
_catalogos: dict[str, dict[str, str]] = {}


def _catalogo(codigo: str) -> dict[str, str]:
    """Carga (una vez) el JSON del idioma. Un archivo roto o ausente = {}."""
    cat = _catalogos.get(codigo)
    if cat is None:
        try:
            with open(DIR_I18N / f"{codigo}.json", encoding="utf-8") as fh:
                cat = json.load(fh)
            if not isinstance(cat, dict):
                cat = {}
        except (OSError, ValueError):
            cat = {}
        _catalogos[codigo] = cat
    return cat


def _get_idioma() -> str:
    global _idioma_actual
    if _idioma_actual is None:
        # Import perezoso: utils.theme importa N_ de aquí y no debe arrastrar
        # la base de datos.
        from core.database import get_config
        _idioma_actual = get_config('idioma', 'es') or 'es'
    return _idioma_actual


def idioma_actual() -> str:
    """Código del idioma de la interfaz ('es' | 'en' | 'pt_BR')."""
    return _get_idioma()


def set_idioma(codigo: str):
    """Cambia el idioma en memoria (para la sesión actual tras guardar config)."""
    global _idioma_actual
    _idioma_actual = codigo


def tr(texto: str) -> str:
    """Traduce un texto. Si no hay traducción o el idioma es 'es', devuelve el original."""
    idioma = _get_idioma()
    if idioma == 'es':
        return texto
    trad = _catalogo(idioma).get(texto)
    return trad if trad else texto


def N_(texto: str) -> str:
    """Marca un texto para traducir SIN traducirlo todavía.

    Para constantes de módulo o de clase (`_SECCIONES`, `COLS_…`): se evalúan
    al importar, antes de saber el idioma, así que ahí no puede ir `tr()`.
    `N_` devuelve el texto tal cual y sirve para que
    `scripts/i18n_faltantes.py` lo encuentre; donde se MUESTRA se llama
    `tr(variable)`.
    """
    return texto
