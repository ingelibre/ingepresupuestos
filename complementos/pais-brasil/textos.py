# SPDX-License-Identifier: GPL-3.0-or-later
"""Textos en inglés y portugués; el español es la clave."""
from ingepresupuestos import api

TEXTOS = {
    "en": {
        "No altera precios ni totales": "Does not change prices or totals",
        "Aplicar el BDI en": "Apply the BDI to",
        "BDI dentro de las referencias": "BDI within the references",
        "Calcular BDI (TCU Ac. 2622/2013)": "Calculate BDI (TCU Ac. 2622/2013)",
        "Calcular BDI (TCU Ac. 2622/2013)…": "Calculate BDI (TCU Ac. 2622/2013)…",
        "Cópialo a mano en el pie del presupuesto.": "Copy it by hand into the budget footer.",
        "Los valores iniciales son los de un ejemplo: revísalos. La ayuda de cada campo trae el 1.º cuartil, el medio y el 3.º.": "The initial values come from an example: check them. Each field's help shows the 1st quartile, the average and the 3rd.",
        "Primero calcula el BDI en Complementos.": "Calculate the BDI first, in Add-ons.",
        "{que}: {v} % está fuera de la referencia ({a} a {b} %).": "{que}: {v}% is outside the reference ({a} to {b}%)."
    },
    "pt_BR": {
        "No altera precios ni totales": "Não altera preços nem totais",
        "Aplicar el BDI en": "Aplicar o BDI em",
        "BDI dentro de las referencias": "BDI dentro das referências",
        "Calcular BDI (TCU Ac. 2622/2013)": "Calcular BDI (TCU Ac. 2622/2013)",
        "Calcular BDI (TCU Ac. 2622/2013)…": "Calcular BDI (TCU Ac. 2622/2013)…",
        "Cópialo a mano en el pie del presupuesto.": "Copie-o à mão no fechamento do orçamento.",
        "Los valores iniciales son los de un ejemplo: revísalos. La ayuda de cada campo trae el 1.º cuartil, el medio y el 3.º.": "Os valores iniciais são de um exemplo: revise-os. A ajuda de cada campo traz o 1.º quartil, o médio e o 3.º.",
        "Primero calcula el BDI en Complementos.": "Primeiro calcule o BDI em Complementos.",
        "{que}: {v} % está fuera de la referencia ({a} a {b} %).": "{que}: {v} % está fora da referência ({a} a {b} %)."
    }
}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
