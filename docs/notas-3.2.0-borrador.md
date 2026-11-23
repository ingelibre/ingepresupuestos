# IngePresupuestos 3.2.0 — borrador de notas de versión

> Borrador. Sin publicar; falta probar y revisar.

## Lo principal

- **Sub-partidas.** Un mortero o un concreto se analiza una vez y entra como una línea en otros análisis. Si cambia, cambian todas las partidas que lo usan. Insumos, adquisiciones, requerimientos y fórmula polinómica bajan hasta los insumos reales.
- **Modelo BIM.** Lector IFC nuevo: respeta las unidades del archivo, prefiere la cantidad neta y no inventa metrados. Muestra los elementos antes de importar, los vincula con sus partidas y, cuando el modelo cambia, enseña qué se movería antes de aplicarlo. Lo escrito a mano no se toca.
- **Vista 3D del modelo** (beta): clic en un elemento lleva a su partida y al revés. Necesita aceleración gráfica.
- **IngeTrazo.** «Traer de IngeTrazo abierto…» lee el metrado del modelo y «Mostrar en IngeTrazo» señala los elementos. Sin IA; necesita IngeTrazo 0.6.3.3 o posterior. Con una versión anterior, exporta el modelo a IFC.
- **Conexión con IA (MCP).** Claude, Codex, Gemini, Cursor o VS Code pueden consultar y editar tus presupuestos con el programa abierto. Apagada por defecto, con deshacer.

- **Complementos.** Se instalan y activan por proyecto desde el menú Complementos; vienen 20:
  - Países: Argentina, Brasil, Chile, España, Honduras, Italia, México y República Dominicana.
  - Metrados: Acero fácil, Ladrillos y mortero, Movimiento de tierras, Dosificación de concreto y Zapatas.
  - Reportes y precios: ajustar a un total, precios con indirectos incluidos, impuesto sobre materiales, datos del proyecto en el presupuesto, dos temas de reporte y un ejemplo para hacer el tuyo.
- **Deshacer y Rehacer** (Ctrl+Z, Ctrl+Y) y menús Editar, Reportes, Metrados, Pie, BIM, IA y Complementos. «Guardar copia (.db)» en Archivo.
- **Temas de reportes**, elegibles por proyecto y con editor.

## Presupuesto y pie

- Los subtotales del pie del ACU llevan su nombre completo y el pie del árbol dice «Costo directo».

- Las partidas con precio 1.00, sin precio o sin análisis se marcan en rojo, y se avisa antes de imprimir o exportar si hay precios 1.00 o en cero (se puede apagar).
- Nombre propio para el total final, líneas de monto fijo a la vista y separadores destacados.
- Lista desplegable de unidades y una herramienta para unir «M2», «m2» y «m²».
- Grupos de más de 99 partidas: los códigos pasan a tres dígitos y ordenan bien.
- País Brasil: Real, CNPJ, impuesto editable en 0 % y pie con BDI.
- «Sugerir partidas» con IA aprovecha las respuestas cortadas o con texto de más y explica qué pasó.

## Reportes

- Los números siguen los separadores de la moneda del proyecto en PDF, Word, Excel y pantalla.
- Columnas de mano de obra, materiales, equipos y subcontratos en el presupuesto, y la especificación bajo cada partida (opcionales).
- Montos de miles de millones: ya no falla el monto en letras ni se parten los números. Escala «Compacto máximo» (75 %).
- El Excel de la fórmula polinómica lista todos los monomios. Clic derecho → «Editar símbolo».

- Herramientas manuales con solo el monto (opcional) y lista de títulos editable y restaurable.

## Cronograma

- El PDF del valorizado sigue el período elegido.

- Corte a fin de mes calendario en valorizado, adquisiciones y Curva S.
- Contraer y expandir títulos del Gantt, o mostrar hasta un nivel.
- MS Project conserva las predecesoras que apuntan a tareas de más abajo.

## Importar y cuentas

- Se importan los análisis (ACU) del Excel «Análisis de precios unitarios» de S10, también en .xlsx, y se avisa lo que no cuadra.
- Código de recuperación para la contraseña olvidada, sin internet.

## Correcciones

- En Windows, los títulos e insignias del ACU y el selector de recursos se veían pixelados.
- Abrir la planilla de acero ya no modifica el presupuesto.
- Los montos grandes caben en el ACU.

## Para revisar al actualizar

- **Haz una copia de tu base antes de actualizar** con «Exportar».

- **El pie impreso cambia en proyectos que nunca abrieron su pestaña «Pie»:** imprimían el costo directo como total; ahora llevan gastos generales, utilidad e impuesto, igual que en pantalla y en el monto en letras.
- Los proyectos en monedas de coma decimal verán sus números con el formato de su moneda.
- Los códigos de grupos de más de 99 partidas pueden pasar a tres dígitos.
