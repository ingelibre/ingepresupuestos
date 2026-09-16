<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Marco Sumari
-->

# IngePresupuestos

**Software de presupuestos de obra civil** — nativo, multiplataforma (Linux · Windows · macOS), pensado para ingenieros, arquitectos y contratistas peruanos.

**Autor:** Ing. Marco Sumari · **Sumari · Arquitectura + Ingeniería**
**Licencia:** [GPL-3.0-or-later](LICENSE) — software libre
**Web:** https://ingepresupuestos.com · **Manual:** https://docs.ingepresupuestos.com

> **Software libre.** Todo el código está bajo GPL-3.0-or-later: puedes usarlo,
> estudiarlo, modificarlo y redistribuirlo.

---

![Pantalla de Proyectos de IngePresupuestos](docs/images/proyectos.png)

## ¿Qué hace?

- **Presupuestos** con árbol jerárquico, sub-presupuestos, **ACU** (Análisis de Costos Unitarios) editable y precios por proyecto. Cada proyecto guarda sus propios precios; el botón **«Precios del catálogo»** muestra cuáles cambiaron en el catálogo y deja elegir cuáles traer, con vista previa.
- **Catálogo de insumos** y **biblioteca de costos unitarios** reutilizables entre proyectos, con edición y duplicado de insumos sin salir del ACU.
- **Cronograma** completo estilo MS Project: **Gantt** interactivo con ruta crítica (CPM), colores por nivel, Valorizado, **Curva S** y Adquisiciones.
- **Ida y vuelta con Microsoft Project**: exporta el cronograma como XML, edítalo en Project y el botón **«Desde Project»** trae las duraciones y predecesoras que cambiaron, mostrando los cambios antes de aplicarlos. Cada partida viaja con su identificador, así que las dependencias se traducen a la numeración correcta.
- **Control de Obra**: requerimientos, almacén/kárdex, cuaderno de obra, valorizaciones con reajuste por fórmula polinómica y curva S real (programado vs reprogramado vs real).
- **Hoja de Metrados** con soporte de **acero** (diámetros peruanos, NTP 341.031 / ASTM A615).
- **Fórmula polinómica** (D.S. 011-79-VC) por **índices unificados del INEI**, con las dos bases vigentes (Julio 1992 y Diciembre 2025 = 100, R.J. 016-2026-INEI), el Diccionario de Elementos de la Construcción y el histórico de índices actualizado cada mes desde el propio repositorio.
- **13 reportes** consistentes en **PDF · Excel · ODS · Word · ODT**, con formato configurable: logo y razón social, márgenes, tamaño del texto, encabezado y pie, y **esquemas de colores para los títulos** de fábrica o propios.
- **Importadores nativos**: S10 (`.S2K`), PowerCost (`.prs`), Delphin (`.sqlite`), Excel, IFC y `.db` nativo.
- **Asistente IA (Tuxia)** con la clave del propio usuario —Groq, Gemini y OpenRouter tienen plan gratuito; Ollama corre sin internet— y **«Sugerir partidas»** con búsqueda semántica local (RAG). Sin clave, el asistente sigue respondiendo con análisis locales del proyecto.

Las novedades de cada versión están en [Releases](https://github.com/ingelibre/ingepresupuestos/releases); la 3.0.8, la 3.0.10, la 3.0.12 y la 3.0.14 (septiembre de 2026) salieron de las observaciones que envió un usuario, David Ramos López.

## Instalación

Descárgalo desde **https://ingepresupuestos.com**:

- **Windows** — instalador `.exe` o desde la **Microsoft Store**.
- **Linux** — AppImage o Flatpak.
- **macOS** — próximamente.

## Ejecutar desde el código fuente

Requiere **Python 3.11+**.

```bash
git clone https://github.com/ingelibre/ingepresupuestos.git
cd ingepresupuestos
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 main.py
```

> **Linux:** para exportar ODT/ODS se usa LibreOffice headless (`sudo apt install libreoffice`). Para importar `.prs` de PowerCost: `sudo apt install -y mdbtools`.

## Tecnología

| Capa | Tecnología |
|------|-----------|
| Interfaz | PySide6 6.11 (Qt 6) |
| Backend | Python 3 puro |
| Base de datos | SQLite 3 |
| Reportes | QTextDocument + QPdfWriter · python-docx · openpyxl · LibreOffice (ODT/ODS) |

## Qué incluye

**Todo.** No hay versión de pago, ni funciones bloqueadas, ni período de prueba,
ni registro: proyectos, presupuestos, ACU, cronograma Gantt con ruta crítica y
sincronización con MS Project, metrados, fórmula polinómica con índices INEI al
día, Control de Obra completo, los 13 reportes en todos sus formatos (PDF ·
Excel · ODS · Word · ODT · MS Project) con formato y colores configurables, los
importadores de S10, PowerCost, Delphin, Excel, IFC y `.db`, y el asistente IA
con la clave del propio usuario.

Si el programa te sirve y estás en condiciones de aportar, eso es lo que lo
mantiene vivo: <https://ingepresupuestos.com/apoyar>

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md). Los reportes de errores y las ideas se
agradecen tanto como el código, y no requieren firmar nada. Para enviar código
hace falta aceptar el [CLA](CLA.md) una sola vez.

## Reportar un problema

Bugs y sugerencias a ing.sumari@gmail.com o por WhatsApp al +51 998 839 090.

## Licencia

IngePresupuestos es **software libre**: puedes usarlo, estudiarlo, modificarlo y
redistribuirlo bajo los términos de la **Licencia Pública General de GNU, versión 3
o posterior**. Se distribuye sin ninguna garantía; ver [LICENSE](LICENSE) para el
texto completo y [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt) para los
componentes de terceros.

© 2026 Marco Sumari
