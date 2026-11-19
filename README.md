# CercaSalud MAD

Herramienta de código abierto para planificar el acceso territorial a recursos de salud en la Comunidad de Madrid con datos abiertos. Proyecto presentado a DATAMAD 2026.

Responde a una pregunta de planificación: **quién tiene lejos su centro de atención primaria, a pie o en transporte público, y, con calor, un refugio climático; y qué actuaciones cambian esa situación.**

- **A:** atención primaria pública, a pie y en transporte público.
- **B:** refugios climáticos oficiales, a pie (componente HeatShield).
- **C:** carencias coincidentes de A y B.

## Demo

La carpeta [`demo/`](demo/) es una página web estática con los resultados ya calculados. No calcula nada en el navegador ni pide nada a servicios externos. Se recorre en tres pasos:

1. **Diagnosticar:** mapa de minutos hasta el centro de primaria por sección censal, con buscador de municipio o distrito y desglose en 3D de la zona elegida (población, red y recursos, minutos a pie y en transporte, renta y, en Madrid capital, horas con refugio climático).
2. **Comparar:** carteras de zonas donde estudiar nuevos centros, con la capa «qué cambia» (quién gana opción y quién sigue sin ella).
3. **Ficha:** ficha de decisión imprimible y descargas.

Para abrirla en local, sirve la carpeta con un servidor estático, por ejemplo `python3 -m http.server --directory demo` (en Windows, `py -3 -m http.server --directory demo`), y abre `http://127.0.0.1:8000`. Su contenido y sus atribuciones están en [`demo/LEEME.md`](demo/LEEME.md).

## Qué mide y qué no

Mide la **proximidad física potencial** con supuestos declarados: umbral, velocidad y franja horaria. No mide citas, capacidad, listas de espera, calidad asistencial ni efectos sobre la salud.

- «Sin opción verificada» no significa «sin acceso»: significa que, con los supuestos indicados, no hay un recurso verificado dentro del umbral.
- Lo que no se puede evaluar se marca como «no evaluable», con su motivo, y nunca como «sin acceso».
- A y B no se suman como beneficio. La unión de ambos se calcula sin duplicar personas.

Supuestos de la versión base (en [`config/base.toml`](config/base.toml); son supuestos, no estándares):

| Componente | Supuesto |
|---|---|
| Ir a pie | 3,0 km/h |
| Primaria a pie | 15 min |
| Primaria en transporte público | 30 min puerta a puerta, laborable de 9 a 13 h (también se calcula de 16 a 20 h) |
| Refugios | 10 min a pie, de 12 a 21 h, en laborable de julio, laborable de agosto y fin de semana |

## Estado

Resultados calculados con la versión de datos `20261113T190802Z` y publicados en `demo/` (19/11/2026).

- **A** cubre los 179 municipios de la Comunidad de Madrid, con 422 centros de primaria pública.
- **B** cubre solo Madrid capital, la única con una lista oficial verificada: los 43 mercados municipales con aire acondicionado en zonas comunes. Que en el resto no haya lista verificada no significa que no haya refugios. Los mercados no declaran el acceso a la zona climatizada: el resultado central lo supone durante el horario comercial y, sin ese supuesto, la cobertura acreditable es nula (cobertura documental insuficiente, no ausencia de servicio).
- Las actuaciones (nuevos centros de primaria y mercados como refugio) se comparan con un solver MILP.

Los límites, los supuestos con más peso y lo que queda fuera están en [`docs/limites.md`](docs/limites.md). Léelos antes de citar una cifra.

## Entorno y cómo reproducirlo

Requiere [uv](https://docs.astral.sh/uv/). uv instala CPython 3.12 y las versiones exactas de las dependencias fijadas en `uv.lock`.

```
uv sync
uv run pytest
uv run ruff check .
```

Los datos de las fuentes no se incluyen en el repositorio. Se guardan en local, en la carpeta `datos/` hermana del repositorio o en la que indique la variable `CERCASALUD_DATOS`:

```
uv run cercasalud fetch                        # descarga y crea una versión fechada (usa la red)
uv run cercasalud verify --snapshot <ID>       # recalcula los SHA-256 de esa versión
uv run cercasalud build --snapshot <ID>        # calcula sin red todas las etapas (o --etapa E)
# Las etapas cuyas entradas, código y configuración no cambiaron se omiten (R-ARQ-03); --forzar las recalcula.
# Etapas: primaria, poblacion, demanda, acceso_pie, acceso, refugios_pie, refugios, renta, candidatos_pie,
#         actuaciones, capas_app, contexto
uv run cercasalud web [--exportar CARPETA]     # página web en 127.0.0.1 desde los resultados guardados; --exportar crea el paquete publicable (demo/)
uv run cercasalud app                          # app local de respaldo (Streamlit) en 127.0.0.1, sin conexión
```

Las etapas `acceso_pie`, `refugios_pie` y `candidatos_pie` usan R5 (r5py) y necesitan Java 21. La matriz de transporte público es un cálculo de horas que se lanza aparte y que `build` lee si existe; si no existe, el transporte queda «no evaluable (motor)». Las órdenes `web` y `app` solo leen resultados ya calculados: sin ellos no hay nada que mostrar, y por eso la demo se publica ya generada.

## Licencias y atribuciones

- **Código:** MIT (ver `LICENSE`).
- **Datos de las fuentes:** este repositorio no los contiene; cada fuente conserva su licencia y la orden `fetch` los descarga en local. Solo incluye pequeñas tablas curadas en `curado/` (ver `curado/README.md`): las derivadas de OpenStreetMap van bajo ODbL.
- **Resultados de `demo/`:** son una base de datos derivada. Los valores por sección se calculan con la red peatonal y los edificios de OpenStreetMap, así que se distribuyen bajo la ODbL 1.0, no bajo MIT.
- Fichas de fuentes y licencias: `docs/fuentes.md`. Caso de uso: `docs/caso_de_uso.md`.

### Atribuciones

- Datos de © [OpenStreetMap](https://www.openstreetmap.org/copyright) y sus colaboradores, disponibles bajo la [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/1-0/).
- Powered by [CRTM](http://www.crtm.es/). Los horarios GTFS se usan explotados (cálculo de rutas), no en bruto. El CRTM no respalda este proyecto.
- Elaboración propia con datos extraídos del sitio web del INE: www.ine.es. El INE no respalda este proyecto.
- Fuente de los datos: Comunidad de Madrid ([datos.comunidad.madrid](http://datos.comunidad.madrid)).
- Origen de los datos: Ayuntamiento de Madrid. El Ayuntamiento no patrocina este proyecto.
- Fuentes CC BY 4.0: [licencia](https://creativecommons.org/licenses/by/4.0/legalcode.es). Las modificaciones se indican en la tabla.
- Las citas de `docs/caso_de_uso.md` indican su fuente (Comunidad de Madrid y ayuntamientos de Madrid, Coslada y Getafe), su fecha y su enlace. Fuente: Ayuntamiento de Madrid, CALORMAD 2026.

### Fuentes que usa el código

| Fuente | Organismo | Licencia | Modificaciones |
|---|---|---|---|
| Registro de centros, servicios y establecimientos sanitarios | Comunidad de Madrid | CC BY 4.0 | Se elimina la columna personal `NIF` al leerlo. Se filtran los centros de salud y consultorios dependientes del servicio de salud regional |
| Población por sección censal, sexo y edad (tabla 69213) | INE | CC BY 4.0 | Periodo 2025 y sexo «Total». Se agrega en mayores de 65, 75 y 85 años |
| Secciones censales 2025 (polígonos) | INE | CC BY 4.0 | Solo polígonos de tipo sección |
| Horarios GTFS de Metro, Metro Ligero, Cercanías, EMT, autobuses interurbanos y urbanos | CRTM (catálogo de datos abiertos de la Comunidad de Madrid) | Licencia de datos abiertos del CRTM | Calendario de Metro extendido hasta el periodo de cálculo: es un supuesto declarado («horario tipo de Metro») |
| Extracto de OpenStreetMap de la Comunidad de Madrid | Colaboradores de OpenStreetMap (extracto de Geofabrik) | ODbL 1.0 | Red viaria para el cálculo de rutas. Edificios y suelo residencial para repartir la población dentro de cada sección |
| Mercados municipales con aire acondicionado en zonas comunes y su horario (lista de madrid.es y equipamientos municipales) | Ayuntamiento de Madrid | Aviso legal de madrid.es y CC BY 4.0 | Horario comercial curado a mano, sin teléfonos ni correos (`curado/refugios_mercados_madrid.csv`) |
| Recursos de Protección Civil | Ayuntamiento de Madrid | Condiciones generales de reutilización del Ayuntamiento de Madrid | Se descarga; todavía no se usa en ningún cálculo |
| Zonas básicas de salud | Comunidad de Madrid | CC BY 4.0 | Se descarga; no se usa en ningún cálculo |

La fecha de descarga de cada archivo consta en el manifiesto de la versión (`datos/snapshots/<ID>.json`) y en el `.source.json` de cada archivo.

### Licencias de las bases derivadas

- Las bases de datos derivadas de OpenStreetMap que se publiquen se distribuyen bajo ODbL, no bajo MIT.
- Los datos del Catastro no se usan.
- Los datos de Coslada están documentados, pero no se usan en el cálculo público hasta aclarar su licencia.
- La licencia del CRTM exige mantener actualizada la información mostrada. Cómo se cumple está pendiente de definir.
