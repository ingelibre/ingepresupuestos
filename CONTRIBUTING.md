# Cómo contribuir a IngePresupuestos

Gracias por el interés. Este es un proyecto de **una sola persona** que lo
desarrolla en sus ratos libres, así que lo más útil que puedes hacer no es
necesariamente escribir código.

## Lo que más ayuda (y no requiere programar)

- **Reportar errores** con pasos para reproducirlos. Si puedes, adjunta el
  archivo `.db` del proyecto donde falla (o uno reducido que lo reproduzca).
- **Contar cómo lo usas.** Qué te falta, qué te sobra, qué reporte imprimes y
  luego corriges a mano. Eso vale más que una lista de funciones deseadas.
- **Probar con software real.** Archivos `.prs` de PowerCost, `.sqlite` de
  Delphin, `.S2K` de S10 que no importen bien. Los importadores se rompen con
  la variedad del mundo real, no en el laboratorio.
- **Hacer un tutorial.** El proyecto es libre justamente para que cualquiera
  pueda enseñarlo sin pedir permiso.

## Si vas a mandar código

1. **Abre un *issue* antes** de ponerte a trabajar en algo grande. Puede que
   ya esté hecho, en camino, o descartado por una razón que no se ve.
2. **Lee `CLAUDE.md`.** Documenta las reglas de negocio que no se pueden
   romper (cálculo de cantidades en ACU, coherencia de totales, numeración
   del cronograma) y las trampas ya aprendidas de Qt. Ahorra mucho tiempo.
3. **Corre los tests** antes de enviar:
   ```bash
   QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_reglas_negocio.py
   venv/bin/python3 tests/test_core.py
   ```
4. **Acepta el CLA** — solo la primera vez. Ver abajo.

### Estilo

- Español para nombres de UI y mensajes al usuario; comentarios en español.
- Iconos: ver `resources/icons/PROCEDENCIA.md`. Todo icono nuevo debe ser
  compatible con GPL-3.0-or-later y quedar anotado ahí.
- Sin dependencias nuevas salvo que haga falta de verdad: cada paquete que se
  suma hay que empaquetarlo en Windows, Linux, Flatpak y MSIX.

## El CLA

Antes de aceptar tu primer pull request necesito que aceptes el
[Acuerdo de Licencia de Contribuyente](CLA.md). **Conservas el copyright de
tu trabajo**; lo que concedes es una licencia amplia que permite mantener la
libertad de decidir sobre la licencia del proyecto en el futuro.

Para aceptarlo, añade tu línea a [`CONTRIBUTORS.md`](CONTRIBUTORS.md) dentro
de tu propio pull request. Eso es todo: el commit queda con tu autoría y
fecha en el historial de git.

Si el CLA no te convence, **no pasa nada**: los reportes de errores, las
ideas y los *issues* no requieren aceptarlo, y son igual de bienvenidos.

## Licencia

Al contribuir aceptas que tu aporte se distribuya bajo
[GPL-3.0-or-later](LICENSE), igual que el resto del proyecto.
