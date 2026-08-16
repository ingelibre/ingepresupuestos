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
> estudiarlo, modificarlo y redistribuirlo, también con fines comerciales y sin
> límite de equipos. En agosto de 2026 el proyecto estuvo una semana camino de
> volverse propietario; se revirtió antes de publicar ninguna versión cerrada.

---

![Pantalla de Proyectos de IngePresupuestos](docs/images/proyectos.png)

## ¿Qué hace?

- **Presupuestos** con árbol jerárquico, sub-presupuestos, **ACU** (Análisis de Costos Unitarios) editable y precios por proyecto.
- **Cronograma** completo estilo MS Project: **Gantt** interactivo con ruta crítica (CPM), Valorizado, **Curva S** y Adquisiciones. Exporta a PDF/Excel/Word/ODT/ODS y **MS Project (MSPDI XML)**.
- **Control de Obra**: requerimientos, almacén/kárdex, cuaderno de obra, valorizaciones y curva S real (programado vs reprogramado vs real).
- **Hoja de Metrados** con soporte de **acero** (diámetros peruanos, NTP 341.031 / ASTM A615).
- **Fórmula polinómica** (D.S. 011-79-VC) e **índices INEI**.
- **13 reportes** consistentes en **PDF · Excel · ODS · Word · ODT**.
- **Importadores nativos**: S10 (`.S2K`), PowerCost (`.prs`), Delphin (`.sqlite`), Excel, IFC y `.db` nativo.
- **Asistente IA (Tuxia)** y **«Sugerir partidas»** con búsqueda semántica local (RAG).

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
ni registro: proyectos, presupuestos, ACU, cronograma Gantt con ruta crítica,
metrados, fórmula polinómica, Control de Obra completo, los 13 reportes en todos
sus formatos (PDF · Excel · ODS · Word · ODT · MS Project), los importadores de
S10, PowerCost, Delphin, Excel, IFC y `.db`, y el asistente IA con la clave del
propio usuario.

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
