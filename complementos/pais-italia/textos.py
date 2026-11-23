# SPDX-License-Identifier: GPL-3.0-or-later
"""Textos en inglés y portugués; el español es la clave."""
from ingepresupuestos import api

TEXTOS = {
    "en": {
        "No altera precios ni totales": "Does not change prices or totals",
        "El presupuesto no tiene partidas.": "The budget has no items.",
        "Costi della sicurezza (no rebajables)": "Costi della sicurezza (not discountable)",
        "El IVA y los costes de seguridad empiezan en 0: escríbelos tú.": "VAT and safety costs start at 0: enter them yourself.",
        "Spese generali, utile, seguridad e IVA": "Spese generali, utile, safety and VAT",
        "Spese generali, utile, seguridad e IVA…": "Spese generali, utile, safety and VAT…"
    },
    "pt_BR": {
        "No altera precios ni totales": "Não altera preços nem totais",
        "El presupuesto no tiene partidas.": "O orçamento não tem itens.",
        "Costi della sicurezza (no rebajables)": "Costi della sicurezza (sem desconto)",
        "El IVA y los costes de seguridad empiezan en 0: escríbelos tú.": "O IVA e os custos de segurança começam em 0: informe-os.",
        "Spese generali, utile, seguridad e IVA": "Spese generali, utile, segurança e IVA",
        "Spese generali, utile, seguridad e IVA…": "Spese generali, utile, segurança e IVA…"
    }
}


def t(s):
    return TEXTOS.get(api.idioma(), {}).get(s, s)
