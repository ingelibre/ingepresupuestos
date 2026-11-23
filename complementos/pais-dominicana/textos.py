# SPDX-License-Identifier: GPL-3.0-or-later
"""Textos en inglés y portugués; el español es la clave."""
from ingepresupuestos import api

TEXTOS = {
    "en": {
        "No altera precios ni totales": "Does not change prices or totals",
        "ITBIS sobre materiales": "ITBIS on materials",
        "Tasa del ITBIS": "ITBIS rate",
        "Tasa del ITBIS…": "ITBIS rate…"
    },
    "pt_BR": {
        "No altera precios ni totales": "Não altera preços nem totais",
        "ITBIS sobre materiales": "ITBIS sobre materiais",
        "Tasa del ITBIS": "Alíquota do ITBIS",
        "Tasa del ITBIS…": "Alíquota do ITBIS…"
    }
}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
