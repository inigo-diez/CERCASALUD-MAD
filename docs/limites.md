# Límites de CercaSalud MAD

**Fecha:** 14/11/2026. **Versión de datos:** `20261113T190802Z`. Este documento reúne lo que la herramienta **no** mide, lo que queda fuera de la entrega y los supuestos con más peso en los resultados. Cada cifra que se cita tiene su archivo de origen en `datos/procesados/20261113T190802Z/`.

## Qué mide y qué no

- **Mide la proximidad física potencial** a un centro de primaria pública y, con calor, a un refugio climático abierto.
- **No mide** citas, capacidad, listas de espera, calidad asistencial, uso real ni efectos sobre la salud. Ninguna salida habla de pacientes, de salud ni de mortalidad.
- **«Sin opción verificada» no es «sin acceso».** Significa que, con los supuestos indicados, no hay un recurso verificado dentro del umbral.
- **«No evaluable»** lleva siempre su motivo:
  - `conexion`: la unidad no engancha a la red;
  - `inventario`: no hay lista oficial de refugios verificada;
  - `horario`: el horario no consta;
  - `motor`: sin cálculo de transporte.

## Demanda

- **Población:** INE 2025 por sección y edad. Los totales se conservan con tolerancia 10⁻⁶.
- **Posición dentro de la sección:** es una estimación, con la población repartida por la superficie de planta residencial de OpenStreetMap. No son hogares.
- **Edificios mal clasificados:** 1.557 edificios claramente no residenciales (culto, enseñanza, deporte, administración…) y 278 ambiguos cuentan como vivienda por estar en zona residencial. Recalculada toda la cadena sin ellos (escenarios del 15/11), las zonas propuestas de primaria son las mismas o la celda contigua, con beneficios que varían menos de un 0,3 %, y los totales cambian en cientos de personas. Pueden deformar casos locales (p. ej., el Palacio de Liria). La corrección está calculada, pero no aplicada a la base (`fases/H2_demanda_red/edificios_no_residenciales/INFORME.md`).
- **Elección de mercados en B1** (comparación dentro de cada escenario, 15/11):
  - **Población total, cartera de 3:** estable (Pacífico, Prosperidad y Villaverde Alto en la base y en los dos escenarios de edificios); el siguiente mercado, Maravillas, queda entre un 1,5 % y un 3,0 % por debajo de la ganancia en la peor hora. El reparto de horas entre Pacífico y Villaverde Alto es indiferente.
  - **75+, un solo mercado:** empate entre Pacífico y Prosperidad (0,6 %); pequeñas perturbaciones los alternan.
  - **75+, cartera de 3:** el tercer mercado es un empate entre Santa María de la Cabeza y Argüelles (0,3 %).
  - Las diferencias de unos pocos puntos no se han comparado con la incertidumbre de los supuestos de B.
- **Transporte:** se calcula desde el centro de gravedad residencial de cada sección, no desde cada unidad.

## Primaria (A)

- **Inventario:** filtro de la SPEC (R-DAT-02), con 422 centros.
  - **Coordenadas:** 8 vienen de OSM. Dos consultorios rurales (Villar del Olmo y Gargantilla del Lozoya) tienen precisión de calle.
  - **Centros públicos fuera del filtro:** cinco centros con dependencia patrimonial del Servicio Madrileño de Salud quedan fuera por la dependencia funcional; figuran como centros del SERMAS en funcionamiento en las fichas oficiales consultadas el 14/11. Sevilla la Nueva sale entera sin opción por esa causa. El escenario «inventario ampliado» lleva los cinco desde el 15/11: a pie, 19.131 personas más con acceso que con tres, todas en Madrid capital; en transporte no cambia. La ampliación (A2) se aceptó el 15/11, pero la base sigue con 422 centros hasta que se recalcule. Coordenadas de los cinco: las del registro; en CS17064 y CS19640 difieren 376 m y 195 m de la ficha oficial.
- **Horario de los centros:** se supone que abren en la franja calculada. No se ha contrastado con una muestra de fichas (F-05).
- **Franjas de transporte:** laborable de 9 a 13 h (base de las cifras) y de 16 a 20 h (escenario `franja_16_20` y criterio estricto `ambas_franjas`). La de tarde se incorporó el 14/11 y sus resultados dependen de que termine su cálculo.
- **Metro:** horario tipo con el calendario extendido (D-27). Es un supuesto declarado.
- **Matriz de transporte en Madrid capital:** puede ser algo optimista. Reconstruidos con los horarios GTFS completos (frecuencias incluidas) y hasta un transbordo, los 4 casos urbanos más dudosos quedan de 0,3 a 3,4 min por encima de la matriz, sin cambiar ningún estado (la mediana más alta, 21,4 min, frente a un umbral de 30). Se publican escenarios de +2, +4 y +6 min. Una primera comprobación del 14/11 no leía las frecuencias y exageraba la diferencia.
- **El modo transporte incluye ir andando.**
- **Borde regional:** no hay centros de comunidades limítrofes en los datos (P-23).
- **Métrica de zona básica de salud (P-07):** fuera de la entrega. La cartografía disponible es de 2020–2022.
- **Rutas frente a línea recta:** medir en línea recta sobrestimaría en 1,02 millones de personas el acceso a pie (cociente red/recta: mediana de 1,32).
- **Mapa de minutos (pantalla 2, P-27):** en transporte, todas las celdas de una sección comparten el tiempo de su centro residencial. En las secciones sin matriz de transporte (todas sus unidades llegan a pie en 20 min o menos) vale el tiempo a pie: el transporte podría acortarlo, así que las clases por debajo de 20 min pueden ser algo pesimistas. El reparto por clases no cambia ningún estado: en las unidades evaluables, «minutos ≤ umbral» coincide con «con acceso» en todas (comprobado al preparar las capas: 0 discrepancias en las tres variables). La población de cada celda es una estimación (reparto por edificios residenciales).
- **Mapa de la página web (P-28), por secciones:** cada sección se colorea con la mediana de minutos de su población (ponderada), así que dentro de una sección grande puede haber zonas más cerca y más lejos que el color. Las barras de la leyenda cuentan la población exacta por tramo. «Qué cambia» marca las secciones donde alguien gana opción, no cuánta gente: la tarjeta da las personas.
- **Refugios en el desglose en 3D:** horas al día (12 a 21 h, laborable de julio, cota central) con refugio a 10 min, media de la sección. Supone acceso en horario comercial (D-33).
- **Método de demanda:** con el punto interior de cada sección en vez de la malla residencial, 520 de 4.518 secciones cambian de estado (R-DEM-04).

## Refugios (B)

- **Territorio:** solo Madrid capital (43 mercados municipales con aire acondicionado en zonas comunes).
  - Coslada está documentada, pero queda fuera del cálculo público hasta aclarar su licencia (D-30).
  - En el resto de municipios, B es no evaluable (inventario). **Que no haya lista verificada no significa que no haya refugios.**
- **Acceso a la zona climatizada:** no consta en ninguno de los 43 mercados.
  - El resultado central supone acceso durante el horario comercial (D-33).
  - Sin ese supuesto, la cobertura acreditable es nula. Es **cobertura documental insuficiente**, no ausencia de servicio.
- **Horarios:**
  - **Origen y revisión:** son de las fichas municipales, con una segunda lectura del mismo agente. La segunda codificación independiente del 20 % (R-TMP-01) está pendiente del usuario.
  - **Agosto:** las fichas no declaran cierres, así que el laborable de julio y el de agosto usan el mismo horario.
  - **Domingo:** casi siempre «no figura». El fin de semana queda sobre todo pendiente, y por eso tiene cotas tan separadas.
- **Laborable:** cuenta como abierto solo si abre de lunes a viernes; manda el día más restrictivo.

## Carencias coincidentes (C)

- Solo donde A y B son evaluables en la misma unidad, es decir, en Madrid capital.
- La franja de referencia de B es la peor hora del laborable de julio (cota central).
- **C apenas depende de la hora elegida para B.** Con A en transporte, son 25.300 personas en todas las horas y tipos de día.
- **Prueba de integración (R-BCH-02):** C prioriza casi los mismos barrios que A sola (Jaccard de 0,82 a 1,00), porque la cobertura de B es baja a cualquier hora. Con los datos actuales, la integración no cambia el orden de prioridades.
- **Renta (ADRH 2024):** quintiles de población por sección; es estratificación, no causa. El porcentaje sin acceso en transporte sube con la renta. El año de referencia de los ingresos no figura en la capa.
- **Capas de contexto (personas solas por barrio e IGUALA por distrito):** solo contexto; no intervienen en ningún cálculo.

## Actuaciones (H5)

- **Zonas de búsqueda de A:** son celdas de 250 m con población residencial, no solares ni edificios.
- **Presupuesto:** se cuenta en número de actuaciones, no en euros. No se compara coste ni efectividad.
- **A en transporte:** la cartera de 5 zonas elige una en Sevilla la Nueva por el filtro de inventario; con el inventario ampliado, su ganancia baja de 68.807 a 60.917. Reoptimizada con ese inventario, cambia esa zona por una segunda en Boadilla del Monte y gana 68.754. Con el p80 o con márgenes de 4–6 min, la ganancia de las carteras de 3 y 5 zonas baja entre un 25 y un 40 %.
- **Fuera de la entrega:** B2 (activar candidatos; D-34). El contraste con la enumeración exhaustiva se hizo en 168 instancias reales pequeñas a pie, no en transporte.
- **Robustez con otras velocidades:** reescala los tiempos a pie de 3,0 km/h (R5 calcula distancia / velocidad), lo que es una aproximación por el redondeo a minutos. A 2,4 km/h la ganancia es una cota inferior.

## Verificación pendiente (H7)

- Revisión geográfica de 11 rutas a pie con incidencias y de 4 casos urbanos en transporte con más de 4 min de diferencia: en curso (`fases/H7_validacion_documentacion/revision_rutas_20261114/`).
- Reproducción completa del transporte: solo se repite a pie.
- **App sin conexión:** comprobada registrando las peticiones de red del navegador (solo 127.0.0.1), no desconectando la red.
