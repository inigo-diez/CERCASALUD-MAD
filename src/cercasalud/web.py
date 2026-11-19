"""Exportador de la página web al estilo WikiBarrio (SPEC P-28; plan
`fases/H6_app/PLAN_PRODUCTO_FINAL_REVISADO_20261117.md`).

Python prepara todos los datos y textos que la página enseña; el JavaScript solo dibuja
(R-UI-01). Todo sale de las tablas y capas que ya escribió `build`; este módulo **no escribe
nada** en `datos/procesados/`: solo lee de allí y escribe en `web/datos/` (o en la carpeta que
se le pida).

La única operación que no es puro formato es la capa «qué cambia» (decisión del usuario del
17/11/2026): para cada cartera ya elegida, qué unidades pasan de «sin opción verificada» a
tener un centro dentro del umbral. Usa las mismas funciones con las que `build` evaluó la
ganancia (`construccion.problema_a_transporte`, `actuaciones.conjuntos_cobertura`), y un test
comprueba que la población de esas unidades es igual a la ganancia de la tabla.
"""

import ast
import datetime
import hashlib
import itertools
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

from . import acceso, actuaciones, app_datos, construccion, vista_mapa, vista_resultados
from .capas_mapa import ETIQUETAS_PCT_SIN, ETIQUETAS_QUINTIL
from .ingesta import leer_snapshot

VERSION_DEMO = "20261113T190802Z"  # base vigente (422 centros, sin S1); fijada por nombre, no «la última»
CARPETA_WEB = Path(__file__).resolve().parents[2] / "web"
ARCHIVOS_PAGINA = ("index.html", "app.js", "estilo.css")
COMPONENTES = {"a_transporte": "Nuevos centros: transporte público (incluido ir andando)",
               "a_pie": "Nuevos centros: a pie", "b1": "Refugios: ampliar el horario de los mercados"}
TABLAS_CARTERA = {"a_pie": "carteras_a_pie.csv", "a_transporte": "carteras_a_transporte.csv",
                  "b1": "b1_ampliar_horas.csv"}
MODO_DE_VARIABLE = {"min_tp_9_13": "transporte", "min_tp_16_20": "transporte_16_20", "min_pie": "pie",
                    "quintil_renta": "transporte", "pct_sin_transporte": "transporte", "pct_sin_pie": "pie"}
AVISO_ODBL = ("Los valores por sección (minutos, población con y sin opción) se calculan con la red peatonal y los "
              "edificios residenciales de OpenStreetMap, que reparten la población del INE dentro de cada sección. "
              "Como base de datos derivada de OSM, la capa de secciones se distribuye bajo la Open Database License "
              "(ODbL 1.0), https://opendatacommons.org/licenses/odbl/1-0/.")
TEXTO_MIDE = ("Mide proximidad física potencial con supuestos declarados (umbral, velocidad, franja). No mide citas, "
              "capacidad, listas de espera ni efectos sobre la salud.")
TRANSFORMADOR = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)


# ------------------------------------------------------------------ utilidades


def escribir_json(ruta: Path, datos) -> int:
    """Escribe JSON compacto en UTF-8 y devuelve su tamaño en bytes."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(datos, ensure_ascii=False, separators=(",", ":"), default=str)
    ruta.write_text(texto, encoding="utf-8")
    return ruta.stat().st_size


def sha256_archivo(ruta: Path) -> str:
    """SHA-256 de un archivo de origen, para el manifiesto de la página."""
    resumen = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def a_wgs84(x, y) -> tuple:
    """EPSG:25830 → (lon, lat) en WGS84 (cálculo en 25830, visualización en WGS84)."""
    return TRANSFORMADOR.transform(x, y)


def lista_elegidos(valor) -> list[str]:
    """Las carteras se guardan en CSV como texto «['z1', 'z2']»; esto las devuelve como lista."""
    if isinstance(valor, list):
        return valor
    return list(ast.literal_eval(valor)) if isinstance(valor, str) and valor.strip() else []


# ------------------------------------------------------------------ mapa: variables, territorios y leyendas


def variables_mapa(catalogo: dict) -> dict:
    """«¿Qué quieres colorear?»: una variable cada vez (no hay índice compuesto), con su paleta y su nota."""
    variables = {}
    for clave in ("min_tp_9_13", "min_tp_16_20", "min_pie"):
        datos = catalogo[clave]
        variables[clave] = {"titulo": datos["titulo"], "escala": "celdas", "paleta": list(AZUL_ROJO_UMBRAL),
                            "etiquetas": datos["etiquetas"], "umbral_tras": 2, "umbral": datos["umbral"],
                            "ultimo_limite": datos["limites"][-1], "modo": MODO_DE_VARIABLE[clave]}
    variables["quintil_renta"] = {"titulo": "Renta neta media por persona de la sección (quintil, ADRH 2024)",
                                  "escala": "celdas", "paleta": list(vista_mapa.ROJO_AZUL_5),
                                  "etiquetas": list(ETIQUETAS_QUINTIL), "umbral_tras": None, "modo": "transporte"}
    for modo, texto in (("transporte", "a pie o en transporte público, de 9 a 13 h"), ("pie", "a pie")):
        variables[f"pct_sin_{modo}"] = {"titulo": f"Por municipio: % sin opción verificada, {texto}",
                                        "escala": "municipios", "paleta": list(vista_mapa.AMARILLO_ROJO),
                                        "etiquetas": list(ETIQUETAS_PCT_SIN), "umbral_tras": None, "modo": modo}
    for clave, datos in variables.items():
        datos["nota"] = nota_web(clave)
    return variables


NOTA_SECCION = ("Cada sección censal se colorea con la mediana de su población: la mitad de sus habitantes está a ese "
                "tiempo o menos del centro de atención primaria pública más cercano, por la red. La población se "
                "reparte dentro de la sección con los edificios residenciales de OpenStreetMap. Las barras de la "
                "leyenda cuentan la población exacta de cada tramo (unidades de 100 m), no las secciones. No mide "
                "citas ni capacidad.")
NOTA_TRANSPORTE = ("En transporte cuenta también ir andando, con la mediana de las salidas de la franja (martes "
                   "laborable).")


def nota_web(variable: str) -> str:
    """Cómo leer el mapa de la página (por secciones; la app de Streamlit usa celdas y tiene su propia nota)."""
    if variable.startswith("pct_sin") or variable == "quintil_renta":
        return vista_mapa.nota_mapa(variable)
    return NOTA_SECCION + (" " + NOTA_TRANSPORTE if variable.startswith("min_tp") else "")


def etiquetas_modo(catalogo: dict) -> dict[str, str]:
    """Nombre de cada modo en el panel, con su umbral."""
    pie, tp = catalogo["min_pie"], catalogo["min_tp_9_13"]
    return {"transporte": f"A pie o en transporte, de 9 a 13 h ({tp['umbral']} min)",
            "transporte_16_20": f"A pie o en transporte, de 16 a 20 h ({tp['umbral']} min)",
            "pie": f"A pie ({pie['umbral']} min, {pie['titulo'].split('(')[1].rstrip(')')})"}


def cifras_modo(fila: dict, modo: str) -> dict:
    """Con acceso (%), sin opción verificada y no evaluable de un territorio y un modo, ya formateados."""
    con, sin, no_eval = (float(fila[f"{modo}_{e}"]) for e in ("con_acceso", "sin_opcion_verificada", "no_evaluable"))
    total = con + sin + no_eval
    return {"con_acceso": vista_mapa.porcentaje(100 * con / total) if total else "—",
            "sin_opcion": vista_mapa.personas(sin), "sin_opcion_pct": vista_mapa.porcentaje(100 * sin / total) if total else "—",
            "no_evaluable": vista_mapa.personas(no_eval)}


def territorios_buscador(territorios: pd.DataFrame, modos: dict[str, str]) -> list[dict]:
    """Comunidad, 179 municipios y 21 distritos: nombre, encuadre y cifras de cada modo."""
    filas = []
    for fila in territorios.to_dict("records"):
        tipo, codigo = fila["tipo"], str(fila["codigo"])
        nombre = fila["nombre"] + (" (distrito de Madrid)" if tipo == "distrito" else "")
        filas.append({"clave": f"{tipo}:{codigo}", "tipo": tipo, "nombre": fila["nombre"], "buscar": nombre,
                      "poblacion": vista_mapa.personas(fila["poblacion"]),
                      "caja": [round(fila["lon_min"], 5), round(fila["lat_min"], 5), round(fila["lon_max"], 5),
                               round(fila["lat_max"], 5)],
                      "centro": [round(fila["lon"], 5), round(fila["lat"], 5)],
                      "modos": {modo: {"etiqueta": etiqueta, **cifras_modo(fila, modo)} for modo, etiqueta in modos.items()}})
    orden = {"comunidad": 0, "municipio": 1, "distrito": 2}
    return sorted(filas, key=lambda f: (orden[f["tipo"]], f["nombre"]))


def leyenda_celdas(tramos: pd.DataFrame, variable: str, datos: dict) -> dict:
    """Filas de la leyenda de una variable de celdas en un territorio: % de la población evaluable."""
    filas, no_eval = vista_mapa.filas_tramos(tramos, datos["etiquetas"], tuple(datos["paleta"]))
    falta = "Sin dato de renta" if variable == "quintil_renta" else "No evaluable"
    return {"filas": [{"etiqueta": e, "color": c, "pct": round(p, 2), "texto": vista_mapa.porcentaje(p)} for e, c, p in filas],
            "extra": [{"etiqueta": falta, "color": vista_mapa.NO_EVALUABLE, "texto": vista_mapa.porcentaje(no_eval)},
                      {"etiqueta": "Sin población residencial", "color": vista_mapa.TERRITORIO, "texto": ""}]}


def leyendas(tramos: pd.DataFrame, territorios: pd.DataFrame, variables: dict) -> dict:
    """Leyenda de cada territorio y variable. Las variables por municipio cuentan municipios por clase."""
    resultado: dict = {}
    tramos = tramos.assign(codigo=tramos["codigo"].astype(str))
    for (tipo, codigo, variable), grupo in tramos.groupby(["tipo", "codigo", "variable"]):
        if variable in variables:
            resultado.setdefault(f"{tipo}:{codigo}", {})[variable] = leyenda_celdas(grupo, variable, variables[variable])
    municipios = territorios[territorios["tipo"] == "municipio"]
    for variable, datos in variables.items():
        if datos["escala"] != "municipios":
            continue
        cuantos = municipios[f"clase_{variable}"].value_counts()
        resultado.setdefault("municipios", {})[variable] = {
            "filas": [{"etiqueta": f"{e} · {int(cuantos.get(i, 0))} mun.", "color": c, "pct": None, "texto": ""}
                      for i, (e, c) in enumerate(zip(datos["etiquetas"], datos["paleta"], strict=True))], "extra": []}
    return resultado


def rotulos_por_zoom(territorios: pd.DataFrame, zooms=range(8, 16)) -> dict[str, list]:
    """Rótulos que caben sin pisarse a cada zoom entero (se quitan los que se solapan, por población).

    A partir de zoom 11 se rotulan los distritos de Madrid en lugar del municipio.
    """
    municipios = territorios[territorios["tipo"] == "municipio"].sort_values("poblacion", ascending=False)
    distritos = territorios[territorios["tipo"] == "distrito"].sort_values("poblacion", ascending=False)
    resultado = {}
    for zoom in zooms:
        lista = municipios if zoom < 11 else pd.concat([distritos, municipios[municipios["codigo"].astype(str) != "28079"]])
        tamano = [20 if str(c) == "28079" else (13 if t == "distrito" else 14)
                  for c, t in zip(lista["codigo"], lista["tipo"], strict=True)]
        candidatos = pd.DataFrame({"lon": lista["lon"].to_numpy(), "lat": lista["lat"].to_numpy(),
                                   "nombre": lista["nombre"].to_numpy(), "tamano": tamano})
        quedan = vista_mapa.rotulos_sin_solape(candidatos, zoom)
        resultado[str(zoom)] = [[round(f["lon"], 5), round(f["lat"], 5), f["nombre"], int(f["tamano"])]
                                for f in quedan.to_dict("records")]
    return resultado


# ------------------------------------------------------------------ capas: celdas compactas y municipios


def nombre_de_territorio(cusec: pd.Series, territorios: pd.DataFrame) -> pd.Series:
    """Distrito (en Madrid capital) o municipio de cada sección."""
    capital = cusec.str.startswith("28079")
    clave = ("municipio:" + cusec.str[:5]).where(~capital, "distrito:" + cusec.str[5:7])
    nombres = pd.Series(territorios["nombre"].to_numpy(), index=territorios["tipo"] + ":" + territorios["codigo"].astype(str))
    return clave.map(nombres).fillna("")


def codificar_contorno(puntos: list) -> list[int]:
    """Contorno en enteros de 1e-5 grados: el primer vértice entero y los demás como diferencias.

    Los contornos ya vienen redondeados a 5 decimales (`capas_mapa`), así que no se pierde nada;
    las diferencias entre vértices de una celda de 100 m son números de 2 o 3 cifras, y el archivo
    pesa la mitad. La página deshace la codificación al dibujar (`decodificar_contorno` lo comprueba).
    """
    enteros = [(round(lon * 1e5), round(lat * 1e5)) for lon, lat in puntos]
    plano = [enteros[0][0], enteros[0][1]]
    for (x0, y0), (x1, y1) in itertools.pairwise(enteros):
        plano += [x1 - x0, y1 - y0]
    return plano


def decodificar_contorno(plano: list[int]) -> list[list[float]]:
    """Inverso de `codificar_contorno` (mismo algoritmo que la página), para los tests."""
    x, y, puntos = plano[0], plano[1], [[plano[0] / 1e5, plano[1] / 1e5]]
    for dx, dy in zip(plano[2::2], plano[3::2], strict=True):
        x, y = x + dx, y + dy
        puntos.append([x / 1e5, y / 1e5])
    return puntos


def app_datos_calidad(codigo: str) -> str:
    """Texto de la calidad del dato de renta («dato del INE», «media de la comarca agraria»…)."""
    from .capas_deck import CALIDAD_RENTA
    return CALIDAD_RENTA.get(codigo, codigo)


# ------------------------------------------------------------------ puntos


def puntos_centros(proc: Path) -> list[dict]:
    """Los centros de primaria de la base (422), en WGS84, con tipo, municipio y dirección institucional."""
    centros = pd.read_parquet(proc / "primaria" / "centros_primaria.parquet")
    lon, lat = a_wgs84(centros["x"].to_numpy(), centros["y"].to_numpy())
    direccion = (centros["direccion_vial_tipo"].fillna("").str.capitalize() + " " + centros["direccion_vial_nombre"].fillna("")
                 + " " + centros["direccion_vial_nro"].fillna("")).str.strip()
    return [{"lon": round(x, 6), "lat": round(y, 6), "nombre": f"{t} · {m}", "detalle": d}
            for x, y, t, m, d in zip(lon, lat, centros["centro_tipo"], centros["municipio_nombre"], direccion, strict=True)]


def puntos_mercados() -> list[dict]:
    """Los 43 mercados municipales con aire acondicionado en zonas comunes (Madrid capital), con su horario."""
    mercados = construccion.leer_refugios()
    lon, lat = a_wgs84(mercados["x"].to_numpy(), mercados["y"].to_numpy())
    return [{"lon": round(x, 6), "lat": round(y, 6), "nombre": app_datos.nombre_mercado_corto(n),
             "detalle": f"Mercado municipal · laborables {h}. Acceso a la zona climatizada: no consta (D-33)."}
            for x, y, n, h in zip(lon, lat, mercados["nombre"], mercados["laborables_comercial"], strict=True)]


# ------------------------------------------------------------------ qué cambia con cada cartera


def unidades_con_tiempos(proc: Path) -> pd.DataFrame:
    """Unidades de demanda con sus tiempos a pie, como las usa la etapa `actuaciones`."""
    return pd.read_parquet(proc / "demanda" / "unidades_demanda.parquet").merge(
        pd.read_parquet(proc / "acceso_pie" / "tiempos_pie.parquet"), on="unidad", validate="one_to_one")


def cobertura_a_pie(proc: Path, unidades: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, list[frozenset]]:
    """Unidades sin opción a pie y, para cada una, los candidatos a menos del umbral (como `carteras_a`)."""
    estados = pd.read_parquet(proc / "acceso" / "estados_base.parquet")
    estado_pie = unidades[["unidad"]].merge(estados, on="unidad", how="left")["estado_pie"]
    sin = unidades[(estado_pie == acceso.SIN).to_numpy()]
    pares = pd.read_parquet(proc / "candidatos_pie" / "pares.parquet")
    return sin, actuaciones.conjuntos_cobertura(pares, sin["unidad"], config["primaria"]["pie"]["umbral_min"])


def cobertura_en_transporte(proc: Path, unidades: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, list[frozenset]] | None:
    """Unidades sin opción en transporte (9 a 13 h) y sus candidatos, con la misma función que `build`."""
    pares_tp = {"9_13": construccion.leer_candidatos_tp(proc, "9_13")}
    if pares_tp["9_13"] is None:
        return None
    matrices = {"9_13": construccion.leer_matriz_transporte(proc)}
    pares_pie = pd.read_parquet(proc / "candidatos_pie" / "pares.parquet")
    escenario = construccion.escenarios_tp_actuaciones(config, False)[0]
    return construccion.problema_a_transporte(unidades, matrices, pares_pie, pares_tp, escenario, config)


def unidades_que_ganan(sin: pd.DataFrame, cubre: list[frozenset], elegidos: list[str]) -> pd.DataFrame:
    """Unidades sin opción que tendrían un centro dentro del umbral con la cartera (cada una, una vez)."""
    elegido = set(elegidos)
    gana = [bool(conjunto & elegido) for conjunto in cubre]
    return sin.loc[gana]


def que_cambia(proc: Path, config: dict) -> dict[str, dict]:
    """Por cartera de A: unidades que ganan opción y población que ganan en total y 65+.

    La clave es «componente|objetivo|k». La ganancia del objetivo debe coincidir con `milp_ganancia`
    (lo comprueba el test y `exportar`).
    """
    unidades = unidades_con_tiempos(proc)
    problemas = {"a_pie": cobertura_a_pie(proc, unidades, config),
                 "a_transporte": cobertura_en_transporte(proc, unidades, config)}
    resultado = {}
    for componente, problema in problemas.items():
        ruta = proc / "actuaciones" / TABLAS_CARTERA[componente]
        if problema is None or not ruta.exists():
            continue
        sin, cubre = problema
        for fila in pd.read_csv(ruta).to_dict("records"):
            ganan = unidades_que_ganan(sin, cubre, lista_elegidos(fila["milp_elegidos"]))
            columna = "poblacion_total" if fila["objetivo"] == "total" else "poblacion_65_mas"
            resultado[f"{componente}|{fila['objetivo']}|{int(fila['k'])}"] = {
                "unidades": ganan["unidad"].tolist(), "ganancia_objetivo": float(ganan[columna].sum()),
                "ganancia_tabla": float(fila["milp_ganancia"])}
    return resultado


# Colores del modo «qué cambia» (idea del mapa de diferencias de Conveyal): las celdas que ganan opción en
# azul fuerte y las demás en tonos que no se confunden con él (ColorBrewer RdBu, apta para daltonismo).
LEYENDA_CAMBIA = [
    {"etiqueta": "Secciones donde alguien pasa a tener un centro dentro del umbral", "color": "#2166AC"},
    {"etiqueta": "Secciones donde aún queda gente sin opción verificada", "color": "#F4A582"},
    {"etiqueta": "Secciones sin nadie sin opción", "color": "#E6E6E6"},
]


def caja_de(celdas: pd.DataFrame, indices: list[int], zonas: list[dict]) -> list[float]:
    """Encuadre [lon_min, lat_min, lon_max, lat_max] de las celdas que ganan opción y de las zonas elegidas."""
    puntos = [(z["lon"], z["lat"]) for z in zonas]
    for i in indices:
        puntos += [tuple(v) for v in json.loads(celdas["contorno"].iloc[i])]
    if not puntos:
        return []
    lons, lats = [p[0] for p in puntos], [p[1] for p in puntos]
    return [round(min(lons), 5), round(min(lats), 5), round(max(lons), 5), round(max(lats), 5)]


def indices_de_celdas(celdas: pd.DataFrame, unidades: list[str]) -> list[int]:
    """Posición, en la capa de celdas, de las piezas de esas unidades (una unidad puede tener varias)."""
    conjunto = set(unidades)
    return [i for i, u in enumerate(celdas["unidad"]) if u in conjunto]


# ------------------------------------------------------------------ carteras, ficha y descargas


def nombres_municipios(territorios: pd.DataFrame) -> dict[str, str]:
    """Código INE → nombre del municipio."""
    municipios = territorios[territorios["tipo"] == "municipio"]
    return dict(zip(municipios["codigo"].astype(str), municipios["nombre"], strict=True))


def condiciones_de(proc: Path, componente: str) -> str:
    """Supuestos de la comparación, de la configuración copiada en los resultados."""
    primaria = json.loads((proc / "acceso" / "resumen.json").read_text(encoding="utf-8"))["config"]["primaria"]
    ruta_b = proc / "refugios" / "resumen.json"
    refugios = json.loads(ruta_b.read_text(encoding="utf-8")).get("config_refugios") if ruta_b.exists() else None
    return vista_resultados.condiciones(componente, primaria, refugios)


def barras_texto(fila: dict, componente: str) -> list[dict]:
    """Barras del comparador (nunca apiladas), con largo relativo a la mayor y cifra formateada."""
    barras = vista_resultados.barras_comparacion(fila, componente)
    mayor = max(float(barras["Personas"].max()), 1.0)
    return [{"etiqueta": b["Opción"], "fraccion": round(float(b["Personas"]) / mayor, 4),
             "texto": vista_mapa.personas(b["Personas"]), "color": vista_resultados.GRISES_BARRAS.get(b["Opción"], "#9E9E9E")}
            for b in barras.sort_values("orden").to_dict("records")]


def tabla_texto(tabla: pd.DataFrame) -> dict:
    """Tabla con cabeceras y celdas ya en texto (punto de miles; «—» si falta)."""
    if tabla is None or tabla.empty:
        return {"columnas": [], "filas": []}
    tabla = tabla.copy()
    for columna in ("Longitud", "Latitud"):  # coordenadas con 4 decimales (unos 10 m), no redondeadas a 1
        if columna in tabla.columns:
            tabla[columna] = tabla[columna].map(lambda v: "—" if pd.isna(v) else f"{v:.4f}".replace(".", ","))
    legible = vista_resultados.para_mostrar(tabla)
    return {"columnas": [str(c) for c in legible.columns],
            "filas": [["—" if pd.isna(v) else str(v) for v in fila] for fila in legible.itertuples(index=False)]}


def clave_cartera(componente: str, fila: dict) -> str:
    """«a_transporte|total|3» o «b1|75+|3_12»."""
    if componente == "b1":
        return f"b1|{fila['objetivo']}|{int(fila['max_centros'])}_{int(fila['max_centro_horas'])}"
    return f"{componente}|{fila['objetivo']}|{int(fila['k'])}"


def nombre_opcion(componente: str, fila: dict) -> str:
    """«3 zonas» o «3 mercados, 12 horas»."""
    if componente == "b1":
        c, h = int(fila["max_centros"]), int(fila["max_centro_horas"])
        return f"{c} mercado{'s' if c != 1 else ''}, {h} horas"
    k = int(fila["k"])
    return f"{k} zona{'s' if k != 1 else ''}"


def zonas_cartera(detalle: pd.DataFrame, componente: str, fila: dict, nombres: dict) -> pd.DataFrame:
    """Zonas elegidas de una cartera de A (vacío en B1)."""
    if componente == "b1" or detalle is None:
        return pd.DataFrame()
    return detalle[(detalle["componente"] == componente) & (detalle["objetivo"] == fila["objetivo"])
                   & (detalle["k"] == fila["k"])].sort_values("orden").assign(
        nombre=lambda t: t["municipio"].astype(str).map(nombres))


def supuestos_manifiesto(proc: Path, componente: str, fila: dict) -> dict:
    """Supuestos de la actuación para el manifiesto reproducible."""
    primaria = json.loads((proc / "acceso" / "resumen.json").read_text(encoding="utf-8"))["config"]["primaria"]
    if componente != "b1":
        return primaria["pie" if componente == "a_pie" else "transporte"]
    ruta_b = proc / "refugios" / "resumen.json"
    refugios = json.loads(ruta_b.read_text(encoding="utf-8")).get("config_refugios", {}) if ruta_b.exists() else {}
    return {"tipo_dia": fila["tipo_dia"], "umbral_min": refugios.get("umbral_min"),
            "velocidad_kmh": primaria["pie"]["velocidad_kmh"], "supuesto_acceso": "D-33"}


def no_evaluables_base(proc: Path) -> dict:
    """No evaluables por motivo del escenario base de A en transporte (Comunidad, población total)."""
    resumen = pd.read_csv(proc / "acceso" / "resumen_acceso.csv")
    fila = resumen[(resumen["escenario"] == "base") & (resumen["modo"] == "transporte")
                   & (resumen["territorio"] == "comunidad") & (resumen["grupo_edad"] == "total")]
    return json.loads(fila["no_evaluable_por_motivo"].iloc[0]) if len(fila) else {}


def escribir_descargas(carpeta: Path, nombre: str, titulo: str, manifiesto: dict, legible: pd.DataFrame,
                       detalle: pd.DataFrame, alternativas: pd.DataFrame, resumen: list, limites: str) -> dict[str, str]:
    """Ficha HTML, CSV, GeoJSON (si hay coordenadas) y manifiesto JSON de una cartera."""
    carpeta.mkdir(parents=True, exist_ok=True)
    archivos = {"ficha": f"{nombre}.html", "csv": f"{nombre}.csv", "json": f"{nombre}.json"}
    tabla = legible if len(legible) else detalle
    (carpeta / archivos["ficha"]).write_text(
        app_datos.ficha_html(titulo, manifiesto, tabla, alternativas, resumen, limites), encoding="utf-8")
    app_datos.sin_campos_personales(detalle).to_csv(carpeta / archivos["csv"], index=False, encoding="utf-8")
    (carpeta / archivos["json"]).write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2, default=str),
                                            encoding="utf-8")
    if {"lon", "lat"} <= set(detalle.columns) and len(detalle):
        archivos["geojson"] = f"{nombre}.geojson"
        (carpeta / archivos["geojson"]).write_text(
            json.dumps(app_datos.geojson_zonas(detalle.drop(columns=["nombre"], errors="ignore")), ensure_ascii=False,
                       default=str), encoding="utf-8")
    return {clave: f"datos/descargas/{archivo}" for clave, archivo in archivos.items()}


def ficha_cartera(proc: Path, version: str, componente: str, fila: dict, detalle: pd.DataFrame, nombres: dict,
                  descargas: Path) -> dict:
    """Todo lo que la página enseña de una cartera: cifras, barras, escenarios, ficha, zonas y descargas."""
    objetivo_texto = app_datos.texto_objetivo(fila["objetivo"])
    texto_condiciones = condiciones_de(proc, componente)
    zonas = zonas_cartera(detalle, componente, fila, nombres)
    manifiesto = app_datos.manifiesto_escenario(version, componente, fila, supuestos_manifiesto(proc, componente, fila),
                                                no_evaluables_base(proc))
    resumen = vista_resultados.resumen_ficha(fila, componente, texto_condiciones, objetivo_texto)
    resumen.append(("Responsable propuesto", manifiesto["responsable_propuesto"]))
    limites = vista_resultados.LIMITES_FICHA[componente]
    if componente == "b1":
        legible, alternativas = vista_resultados.bloques_b1_legibles(fila), app_datos.tabla_alternativas_b1(fila)
        datos_descarga = pd.DataFrame(json.loads(fila.get("milp_bloques_detalle") or "[]"))
    else:
        legible, alternativas = vista_resultados.detalle_zonas_legible(zonas.drop(columns="nombre"), nombres), pd.DataFrame()
        datos_descarga = zonas.drop(columns="nombre")
    clave = clave_cartera(componente, fila)
    nombre_archivo = "ficha_" + clave.replace("|", "_").replace("+", "mas")
    titulo = f"Ficha de decisión - {COMPONENTES[componente]} - {objetivo_texto} - {nombre_opcion(componente, fila)}"
    return {"clave": clave, "componente": componente, "objetivo": fila["objetivo"], "objetivo_texto": objetivo_texto,
            "opcion": nombre_opcion(componente, fila), "titulo": titulo, "condiciones": texto_condiciones,
            "estado": vista_resultados.texto_estado(fila["milp_estado"]),
            "barras": barras_texto(fila, componente), "resumen": [[c, v] for c, v in resumen], "limites": limites,
            "escenarios": tabla_texto(vista_resultados.escenarios_cartera(fila, componente)) if componente != "b1" else None,
            "tabla": tabla_texto(legible), "alternativas": tabla_texto(alternativas),
            "texto_alternativas": app_datos.TEXTO_ALTERNATIVAS_B1 if len(alternativas) else "",
            "zonas": [{"orden": int(z["orden"]), "lon": round(float(z["lon"]), 6), "lat": round(float(z["lat"]), 6),
                       "municipio": z["nombre"] if isinstance(z["nombre"], str) else str(z["municipio"]),
                       "zona": z["zona"]} for z in zonas.to_dict("records")],
            "municipios_zonas": vista_resultados.municipios_de_zonas(zonas, nombres) if len(zonas) else "",
            "descargas": escribir_descargas(descargas, nombre_archivo, titulo, manifiesto, legible, datos_descarga,
                                            alternativas, resumen, limites)}


def datos_carteras(proc: Path, version: str, territorios: pd.DataFrame, descargas: Path) -> dict:
    """Carteras de los tres componentes, en el orden de la demo (transporte primero)."""
    detalle_ruta = proc / "actuaciones" / "carteras_detalle.csv"
    detalle = pd.read_csv(detalle_ruta) if detalle_ruta.exists() else None
    nombres = nombres_municipios(territorios)
    resultado = {"componentes": [], "carteras": {}}
    for componente, nombre_componente in COMPONENTES.items():
        ruta = proc / "actuaciones" / TABLAS_CARTERA[componente]
        if not ruta.exists():
            continue
        tabla = pd.read_csv(ruta)
        objetivos = app_datos.ordenar_objetivos(tabla["objetivo"])
        opciones = {}
        for objetivo in objetivos:
            for fila in tabla[tabla["objetivo"] == objetivo].to_dict("records"):
                ficha = ficha_cartera(proc, version, componente, fila, detalle, nombres, descargas)
                resultado["carteras"][ficha["clave"]] = ficha
                opciones.setdefault(objetivo, []).append([ficha["clave"], ficha["opcion"]])
        resultado["componentes"].append({"clave": componente, "nombre": nombre_componente,
                                         "objetivos": [[o, app_datos.texto_objetivo(o)] for o in objetivos],
                                         "opciones": opciones})
    return resultado


# ------------------------------------------------------------------ inicio, B y C, fuentes


def datos_inicio(proc: Path) -> dict:
    """Las tres cifras de partida (Comunidad, transporte de 9 a 13 h) y el caso de la demo."""
    resumen = pd.read_csv(proc / "acceso" / "resumen_acceso.csv")
    base = resumen[(resumen["escenario"] == "base") & (resumen["territorio"] == "comunidad")
                   & (resumen["grupo_edad"] == "total") & (resumen["modo"] == "transporte")].iloc[0]
    carteras = pd.read_csv(proc / "actuaciones" / "carteras_a_transporte.csv")
    caso = carteras[(carteras["objetivo"] == "total") & (carteras["k"] == 3)].iloc[0]
    return {"titulo": "Dónde cuesta llegar al centro de salud y qué actuaciones conviene estudiar",
            "cifras": [
                {"valor": vista_mapa.porcentaje(base["pct_con_acceso_sobre_total"]),
                 "texto": "de la población de la Comunidad tiene un centro de atención primaria a 30 min o menos, a pie o "
                          "en transporte público, de 9 a 13 h"},
                {"valor": vista_mapa.personas(base["sin_opcion_verificada"]),
                 "texto": "personas sin opción verificada con esos supuestos (no significa «sin atención»)"},
                {"valor": vista_mapa.personas(caso["milp_ganancia"]),
                 "texto": f"pasarían a tener opción con 3 zonas de estudio elegidas por el cálculo, frente a "
                          f"{vista_mapa.personas(caso['regla_simple_ganancia'])} con una regla simple del mismo tamaño"}],
            "caso": "a_transporte|total|3", "mide": TEXTO_MIDE, "demo": PASOS_DEMO}


# Capas del desglose en 3D de un territorio (de abajo arriba), con lo que enseña cada una.
GRISES_DENSIDAD = ("#E0E0E0", "#BDBDBD", "#969696", "#636363", "#252525")
DESGLOSE = [
    {"capa": "densidad", "nombre": "Población", "texto": "Habitantes por km² de cada sección (INE 2025)."},
    {"capa": "red", "nombre": "Red y recursos",
     "texto": "Vías principales (OSM), centros de atención primaria (puntos negros) y mercados climatizados (círculos)."},
    {"capa": "min_pie", "nombre": "Minutos a pie", "texto": "Mediana de la sección al centro más cercano, a 3,0 km/h."},
    {"capa": "min_tp_9_13", "nombre": "Minutos en transporte",
     "texto": "Mediana de la sección, a pie o en transporte público de 9 a 13 h."},
    {"capa": "quintil_renta", "nombre": "Renta (contexto)",
     "texto": "Quintil de renta neta media por persona (ADRH 2024). Es estratificación, no causa."},
]

# Atajos «Ir a»: la Comunidad, Madrid y los municipios del guion (códigos INE comprobados en
# `territorios_mapa.csv` el 17/11/2026).
IR_A = ["comunidad:28", "municipio:28079", "municipio:28022", "municipio:28115", "municipio:28123"]

# Recorrido de la demo (botones «Siguiente», «Atrás» y «Reiniciar»): qué paso, territorio, variable y
# cartera enseña cada parada. Son las paradas del guion (`fases/H6_app/demo_20261116/GUION_DEMO.md`).
PASOS_DEMO = [
    {"titulo": "Punto de partida", "paso": "inicio"},
    {"titulo": "Diagnóstico: minutos al centro de salud en transporte público", "paso": "diagnosticar",
     "territorio": "comunidad:28", "variable": "min_tp_9_13"},
    {"titulo": "Una zona con dificultades: Boadilla del Monte", "paso": "diagnosticar",
     "territorio": "municipio:28022", "variable": "min_tp_9_13"},
    {"titulo": "Boadilla del Monte en 3D: las capas que explican el resultado", "paso": "desglose",
     "territorio": "municipio:28022"},
    {"titulo": "Comparar: 3 zonas de estudio frente a una regla simple", "paso": "comparar",
     "cartera": "a_transporte|total|3"},
    {"titulo": "Qué cambia: quién pasa a tener un centro a 30 min", "paso": "comparar",
     "cartera": "a_transporte|total|3", "que_cambia": True},
    {"titulo": "Ficha de decisión para llevarse", "paso": "ficha", "cartera": "a_transporte|total|3"},
]


def datos_b_c(proc: Path) -> dict:
    """Resumen de refugios (B) y carencias coincidentes (C) con resultados ya calculados (sin capa nueva)."""
    b = pd.read_csv(proc / "refugios" / "b_resumen.csv")
    capital = b[(b["territorio"] == "madrid_capital") & (b["grupo_edad"] == "total") & (b["tipo_dia"] == "laborable_julio")]
    central = capital[capital["nombre"] == "base_central"].iloc[0]
    acreditable = capital[capital["nombre"] == "base_acreditable"].iloc[0]
    c = pd.read_csv(proc / "refugios" / "c_resumen.csv")
    c_tp = c[(c["modo_a"] == "transporte") & (c["grupo_edad"] == "total")].iloc[0]
    hora = int(central["peor_hora"])
    texto_b = [
        ("Solo Madrid capital: lista oficial de 43 mercados municipales con aire acondicionado en zonas comunes "
         "(refugio a 10 min a pie). En el resto de la Comunidad, B es no evaluable por inventario: que no haya lista "
         "verificada no significa que no haya refugios."),
        (f"Peor hora del laborable de julio ({hora} a {hora + 1} h): "
         f"{vista_mapa.personas(central['con_acceso_peor_hora'])} personas con un mercado abierto a 10 min (estimada, "
         "cota central, con el supuesto de acceso en horario comercial, D-33)."),
        (f"Sin ese supuesto, la cobertura acreditable es {vista_mapa.personas(acreditable['con_acceso_peor_hora'])}: "
         "es cobertura documental insuficiente (ninguna ficha acredita el acceso a la zona climatizada), no ausencia "
         "de servicio.")]
    texto_c = [
        ("Carencias coincidentes (sin primaria a 30 min en transporte y sin refugio en la peor hora), solo donde A "
         f"y B son evaluables a la vez: {vista_mapa.personas(c_tp['carencia_coincidente'])} personas. A y B no se "
         "suman: la unión cuenta a cada persona una vez."),
        ("Con los datos actuales, C prioriza casi los mismos barrios que A sola, porque la cobertura de B es baja a "
         "cualquier hora.")]
    return {"b": texto_b, "c": texto_c}


# Qué aporta cada fuente al cálculo y qué se le hace (las licencias CC BY piden indicar las modificaciones).
APORTA = {
    "sanidad": ("Registro de centros sanitarios: los 422 centros de atención primaria pública de la base (filtro "
                "R-DAT-02). Se elimina la columna NIF y se unifican las filas de cada centro."),
    "ine_69213": "Población por sección censal y edad (2025): la demanda. Se reparte por celdas de 100 m.",
    "ine_secciones_2025": "Polígonos de las secciones censales: dónde vive cada población.",
    "crtm_gtfs": ("Horarios de las seis redes (Metro, EMT, interurbanos, urbanos, metro ligero y Cercanías): tiempos "
                  "en transporte público por franja, un martes laborable."),
    "osm": ("Red peatonal y edificios residenciales: tiempos a pie y reparto de la población dentro de cada "
            "sección; coordenadas de 8 centros y de un mercado sin coordenada oficial."),
    "madrid_proteccion_civil": "Solo candidatos a refugio (B2, aplazado): no interviene en estas cifras.",
}
CONJUNTOS_EXTRA = [
    {"fuente": "madrid_mercados", "nombre": "Mercados con aire acondicionado en zonas comunes (43)",
     "organismo": "Ayuntamiento de Madrid", "licencia": "Aviso legal de madrid.es (citar fuente y autor)", "fecha": "",
     "url": "https://www.madrid.es", "aporta": ("Lista oficial de refugios de partida en Madrid capital. Horarios "
                                                "comerciales curados de las fichas municipales.")},
    {"fuente": "madrid_equipamientos", "nombre": "Equipamientos municipales (horarios de los mercados)",
     "organismo": "Ayuntamiento de Madrid", "licencia": "CC BY 4.0", "fecha": "",
     "url": "https://datos.madrid.es/dataset/300331-0-equipamientos-municipales",
     "aporta": "Horario y coordenadas de cada mercado, codificados por franjas (D-33)."},
    {"fuente": "ine_adrh_2024", "nombre": "Atlas de Distribución de Renta de los Hogares 2024", "organismo": "INE",
     "licencia": "CC BY 4.0", "fecha": "", "url": "https://www.ine.es",
     "aporta": "Renta neta media por persona de la sección, en quintiles: solo estratificación."},
]

PARA_QUIEN = [
    ("Planificación de atención primaria (Consejería de Sanidad, Servicio Madrileño de Salud): dónde estudiar nuevos "
     "centros. El 22/07/2026 la Comunidad aprobó adjudicar las obras de tres centros de salud (Carabanchel, Alcorcón "
     "y Rivas-Vaciamadrid) y el 15/09/2026 abrió uno en Móstoles para responder al crecimiento de la población del PAU-4."),
    ("Salud pública regional: el Plan de Actuación ante Episodios de Altas Temperaturas 2026 pide a cada centro de "
     "salud identificar a las personas en riesgo por calor, y cuenta el número de refugios climáticos como indicador "
     "del Ayuntamiento de Madrid."),
    ("Ayuntamientos: Madrid (CALORMAD 2026) y Coslada publican la ubicación u horario de sus refugios climáticos; "
     "Getafe anunció extender su red hasta que cada barrio tenga al menos uno."),
    ("Precedente: AccessMod, caja de herramientas presentada por la OMS para ayudar a los países a examinar los "
     "aspectos geográficos de su sistema sanitario, simula cómo ampliar la red de centros para aumentar la población "
     "cubierta, añadiendo los centros de uno en uno. CercaSalud aplica esa idea a Madrid con transporte público por "
     "horario y elige todas las zonas de la cartera a la vez."),
    ("Límite: estas fuentes muestran que esos organismos toman decisiones sobre la ubicación, el horario o la "
     "cobertura de recursos de salud. No muestran que ninguno necesite ni vaya a usar CercaSalud: no se ha "
     "contactado con ningún organismo."),
]
FUENTES_PARA_QUIEN = [
    ("Comunidad de Madrid, nota del 22/07/2026 (tres centros de salud)",
     ("https://www.comunidad.madrid/noticias/2026/07/22/comunidad-madrid-invertira-424-millones-euros-tres-nuevos-"
     "centros-salud-atencion-primaria-capital-alcorcon-rivas-vaciamadrid")),
    ("Comunidad de Madrid, nota del 15/09/2026 (Móstoles)",
     ("https://www.comunidad.madrid/notas-prensa/2026/09/15/comunidad-madrid-abre-decimo-centro-salud-mostoles-atender-"
     "7700-vecinos")),
    ("Plan de Actuación ante Episodios de Altas Temperaturas 2026",
     "https://www.comunidad.madrid/docs/2026-05/web-plan-contra-el-calor_cm_2026.vf_.pdf"),
    ("OMS, AccessMod", "https://www.who.int/tools/accessmod-geographic-access-to-health-care"),
    ("AccessMod, apéndice 7 (cálculo del análisis de ampliación)",
     "https://accessmod.atlassian.net/wiki/spaces/EN/pages/4326096/Appendix+7+-+Calculation+details+-+Scaling+up+analysis"),
]
VIABILIDAD = [
    "Funciona en un portátil, sin servicios de pago ni conexión: esta página es estática y no calcula nada.",
    ("Reproducible: la orden «uv run cercasalud web» regenera esta página desde los resultados guardados; el cálculo completo "
     "(«uv run cercasalud build» y la matriz de transporte) está documentado en el repositorio, con sus tiempos."),
    "Código abierto con licencia MIT, en Python con bibliotecas libres; el mapa usa deck.gl (MIT).",
]


def datos_fuentes(raiz: Path, version: str) -> dict:
    """Conjuntos usados con lo que aporta cada uno, atribuciones literales, aviso ODbL, viabilidad y «para quién»."""
    archivos = leer_snapshot(raiz, version)["archivos"]
    usados = [a for a in archivos if a["fuente"] in APORTA]  # zonas básicas de salud: sin uso (P-07)
    conjuntos = [{"fuente": a["fuente"], "nombre": a["nombre"], "organismo": a["organismo"], "licencia": a["licencia"],
                  "fecha": str(a["fecha_adquisicion"])[:10], "url": a["url"], "aporta": APORTA[a["fuente"]]}
                 for a in usados]
    return {"conjuntos": conjuntos + CONJUNTOS_EXTRA,
            "atribuciones": list(app_datos.ATRIBUCIONES), "odbl": AVISO_ODBL,
            "codigo": "Código bajo licencia MIT. deck.gl 9.3.12 (MIT) copiado en el repositorio.",
            "viabilidad": VIABILIDAD, "para_quien": PARA_QUIEN,
            "fuentes_para_quien": [{"texto": t, "url": u} for t, u in FUENTES_PARA_QUIEN],
            "version": version, "fecha_version": app_datos.fecha_version(version)}


# ------------------------------------------------------------------ mapa por secciones (estilo WikiBarrio, 17/11)
# El usuario pidió el 17/11, con una captura de WikiBarrio, zonas que se distingan: secciones censales enteras
# con borde blanco. Cada sección muestra una agregación de lo ya calculado para sus unidades de 100 m:
# mediana de minutos ponderada por población, % sin opción y quintil de renta. No hay cálculo nuevo de acceso.

# ColorBrewer RdBu sin el tono neutro: tres azules hasta el umbral y cuatro rojos por encima.
AZUL_ROJO_UMBRAL = ("#2166AC", "#67A9CF", "#D1E5F0", "#FDDBC7", "#F4A582", "#D6604D", "#B2182B")
TOLERANCIA_SECCIONES_M = 6  # simplificación de los contornos de sección (no cambia qué sección es cada una)
MODOS_SECCION = ("transporte", "transporte_16_20", "pie")


def mediana_ponderada(valores: np.ndarray, pesos: np.ndarray) -> float:
    """Valor en el que se alcanza la mitad del peso (población) al ordenar de menor a mayor; NaN si no hay."""
    if len(valores) == 0 or pesos.sum() <= 0:
        return float("nan")
    orden = np.argsort(valores, kind="stable")
    acumulado = np.cumsum(pesos[orden])
    return float(valores[orden][np.searchsorted(acumulado, acumulado[-1] / 2)])


def minutos_por_seccion(celdas: pd.DataFrame, variable: str) -> pd.Series:
    """Mediana de minutos de cada sección, ponderada por la población de sus unidades evaluables.

    Una unidad evaluable sin ruta dentro del radio cuenta como «más de» (infinito), igual que en
    `capas_mapa.clase`. Una sección sin unidades evaluables queda en NaN (no evaluable).
    """
    evaluable = celdas[f"clase_{variable}"] >= 0
    tabla = celdas.loc[evaluable, ["cusec", variable, "poblacion_total"]].copy()
    tabla[variable] = tabla[variable].fillna(np.inf)
    medianas = {cusec: mediana_ponderada(g[variable].to_numpy(dtype=float), g["poblacion_total"].to_numpy(dtype=float))
                for cusec, g in tabla.groupby("cusec")}
    return pd.Series(medianas, dtype=float).reindex(sorted(celdas["cusec"].unique()))


def valores_secciones(celdas: pd.DataFrame, catalogo: dict) -> pd.DataFrame:
    """Una fila por sección: población, mediana y clase de minutos de cada variable, % sin opción y renta.

    `celdas_mapa` tiene una fila por pieza de dibujo y repite la población de una unidad partida en varias
    piezas: aquí se usa una fila por unidad (REGISTRO-FALLOS 44).
    """
    from . import capas_mapa
    celdas = celdas.drop_duplicates("unidad")
    poblacion = celdas.groupby("cusec")["poblacion_total"].sum()
    tabla = pd.DataFrame({"poblacion": poblacion})
    for variable, datos in catalogo.items():
        mediana = minutos_por_seccion(celdas, variable).reindex(tabla.index)
        tabla[f"m_{variable}"] = mediana
        tabla[f"k_{variable}"] = capas_mapa.clase(mediana, datos["limites"], mediana.notna())
    recuentos = capas_mapa.recuentos_estado(celdas, celdas["cusec"]).reindex(tabla.index).fillna(0.0)
    for modo in MODOS_SECCION:
        total = sum(recuentos[f"{modo}_{e}"] for e in acceso.ESTADOS)
        tabla[f"sin_{modo}"] = np.where(total > 0, 100 * recuentos[f"{modo}_{acceso.SIN}"] / total.where(total > 0, 1), 0.0)
        tabla[f"sin_personas_{modo}"] = recuentos[f"{modo}_{acceso.SIN}"]
    renta = celdas.drop_duplicates("cusec").set_index("cusec")
    tabla["quintil"] = renta["quintil_renta"].reindex(tabla.index)
    tabla["k_quintil_renta"] = renta["clase_quintil_renta"].reindex(tabla.index).fillna(-1).astype(int)
    tabla["calidad_renta"] = renta["calidad_renta"].reindex(tabla.index).fillna("")
    return tabla


def contornos_secciones(raiz: Path, version: str, cusecs: set[str]) -> pd.DataFrame:
    """Polígonos de las secciones con población (INE 2025, tipo SECCIONADO), simplificados y en WGS84.

    Una fila por parte: las secciones con varias partes (multipolígonos) dan varias filas.
    """
    snapshot = leer_snapshot(raiz, version)
    ruta = construccion.ruta_en_snapshot(raiz, snapshot, *construccion.ARCHIVO_SECCIONES)
    import pyogrio
    capa = pyogrio.read_dataframe(ruta, columns=["CUSEC", "TIPO"])
    capa = capa[(capa["TIPO"] == "SECCIONADO") & capa["CUSEC"].isin(cusecs)].to_crs("EPSG:25830")
    capa["area_km2"] = capa.geometry.area / 1e6  # superficie de la sección entera, antes de simplificar
    capa["geometry"] = capa.geometry.simplify(TOLERANCIA_SECCIONES_M, preserve_topology=True)
    partes = capa.to_crs("EPSG:4326").explode(index_parts=False)
    return partes.rename(columns={"CUSEC": "cusec"})[["cusec", "area_km2", "geometry"]].reset_index(drop=True)


def codificar_poligono(poligono) -> list[list[int]]:
    """Anillos de un polígono (exterior y huecos) con `codificar_contorno`, en grados con 5 decimales."""
    anillos = [poligono.exterior, *poligono.interiors]
    return [codificar_contorno([[round(x, 5), round(y, 5)] for x, y in anillo.coords]) for anillo in anillos]


def clave_territorio(cusec: pd.Series) -> pd.Series:
    """«distrito:05» en Madrid capital y «municipio:28022» en el resto: el territorio de cada sección."""
    capital = cusec.str.startswith("28079")
    return ("municipio:" + cusec.str[:5]).where(~capital, "distrito:" + cusec.str[5:7])


def densidad_por_clases(densidad: pd.Series) -> tuple[list[int], list[str]]:
    """Cinco clases de densidad (hab/km²) por quintiles de las secciones, con sus etiquetas."""
    limites = [float(v) for v in densidad.quantile([0.2, 0.4, 0.6, 0.8])]
    redondeo = [round(v, -2) if v >= 1000 else round(v, -1) for v in limites]
    etiquetas = [f"< {vista_mapa.personas(redondeo[0])}",
                 *[f"{vista_mapa.personas(a)}–{vista_mapa.personas(b)}" for a, b in itertools.pairwise(redondeo)],
                 f"> {vista_mapa.personas(redondeo[-1])} hab/km²"]
    return [int(c) for c in np.searchsorted(limites, densidad.to_numpy())], etiquetas


def capa_secciones(valores: pd.DataFrame, partes: pd.DataFrame, territorios: pd.DataFrame, catalogo: dict) -> dict:
    """Secciones en columnas: partes (contornos) que apuntan a su sección, y los valores de cada sección."""
    cusecs = list(valores.index)
    posicion = {c: i for i, c in enumerate(cusecs)}
    lugar = nombre_de_territorio(pd.Series(cusecs), territorios)
    lugares = sorted(set(lugar))
    columnas = {"n": len(cusecs), "cusec": cusecs, "lugares": lugares,
                "t": [lugares.index(n) for n in lugar], "g": [round(float(p)) for p in valores["poblacion"]],
                "partes": [codificar_poligono(g) for g in partes.geometry],
                "seccion_de_parte": [posicion[c] for c in partes["cusec"]],
                "territorio": clave_territorio(pd.Series(cusecs)).tolist()}
    area = partes.drop_duplicates("cusec").set_index("cusec")["area_km2"].reindex(cusecs)
    densidad = (valores["poblacion"] / area.where(area > 0)).fillna(0.0)
    columnas["densidad"] = [round(float(d)) for d in densidad]
    columnas["k_densidad"], columnas["etiquetas_densidad"] = densidad_por_clases(densidad)
    for variable in catalogo:
        columnas[f"k_{variable}"] = valores[f"k_{variable}"].astype(int).tolist()
        columnas[f"m_{variable}"] = [None if not np.isfinite(m) else round(float(m)) for m in valores[f"m_{variable}"]]
    for modo in MODOS_SECCION:
        columnas[f"sin_{modo}"] = [round(float(v), 1) for v in valores[f"sin_{modo}"]]
        columnas[f"sinp_{modo}"] = [round(float(v)) for v in valores[f"sin_personas_{modo}"]]
    columnas["k_quintil_renta"] = valores["k_quintil_renta"].tolist()
    columnas["q"] = [None if pd.isna(q) else int(q) for q in valores["quintil"]]
    calidades = sorted(set(valores["calidad_renta"]))
    columnas["calidades"] = [app_datos_calidad(c) for c in calidades]
    columnas["cq"] = [calidades.index(c) for c in valores["calidad_renta"]]
    return columnas


def textos_secciones(catalogo: dict) -> dict:
    """Textos de la tarjeta de una sección (la página solo los junta con las cifras)."""
    return {"seccion": "Sección", "mediana": {v: f"mediana de la sección · {d['titulo'].lower()}" for v, d in catalogo.items()},
            "mas_de": {v: f"más de {d['limites'][-1]:g} min" for v, d in catalogo.items()},
            "no_evaluable": "no evaluable", "habitantes": "habitantes (INE 2025)",
            "sin": {"transporte": "sin opción verificada en transporte (9 a 13 h)",
                    "transporte_16_20": "sin opción verificada en transporte (16 a 20 h)",
                    "pie": "sin opción verificada a pie"},
            "renta": "Quintil de renta de la sección", "sin_renta": "sin dato de renta"}


# Refugios (B) por sección, solo donde hay lista oficial verificada (Madrid capital): horas al día, de 12 a
# 21 h de un laborable de julio, con un mercado climatizado abierto a 10 min a pie (cota central, supuesto de
# acceso D-33), media de la sección ponderada por población. Sale de la tabla hora a hora de la etapa
# `refugios` (`b_estados_base_central.parquet`); no hay cálculo nuevo de acceso.
AZULES_REFUGIO = ("#EFF3FF", "#BDD7E7", "#6BAED6", "#3182BD", "#08519C")
LIMITES_REFUGIO = (0.0, 2.0, 4.0, 6.0)
ETIQUETAS_REFUGIO = ["0 h", "hasta 2 h", "2–4 h", "4–6 h", "más de 6 h"]


def horas_refugio_por_unidad(proc: Path, unidades: pd.DataFrame) -> pd.DataFrame:
    """Por unidad evaluable en B: horas del laborable de julio con refugio a 10 min, sección y población."""
    horas = pd.read_parquet(proc / "refugios" / "b_estados_base_central.parquet")
    julio = horas[horas["tipo_dia"] == "laborable_julio"].assign(
        con=lambda x: x["estado"] == acceso.CON, evaluable=lambda x: x["estado"] != acceso.NO_EVAL)
    por_unidad = julio.groupby("unidad").agg(horas=("con", "sum"), evaluable=("evaluable", "any")).reset_index()
    por_unidad = por_unidad[por_unidad["evaluable"]]
    return por_unidad.merge(unidades[["unidad", "cusec", "poblacion_total"]], on="unidad", how="inner",
                            validate="one_to_one")


def refugio_por_seccion(horas: pd.DataFrame, cusecs: list[str]) -> tuple[pd.Series, pd.Series]:
    """Horas medias con refugio (ponderadas por población) y su clase, por sección; NaN fuera de Madrid capital."""
    from . import capas_mapa
    suma = (horas["horas"] * horas["poblacion_total"]).groupby(horas["cusec"]).sum()
    media = (suma / horas.groupby("cusec")["poblacion_total"].sum()).reindex(cusecs)
    return media, capas_mapa.clase(media, LIMITES_REFUGIO, media.notna())


def refugio_por_territorio(horas: pd.DataFrame) -> dict[str, str]:
    """Texto de la capa de refugios del desglose para Madrid capital y cada distrito: personas con refugio
    a alguna hora de 12 a 21 h (cada persona una vez)."""
    claves = clave_territorio(horas["cusec"])
    textos = {}
    for clave, grupo in [("municipio:28079", horas), *horas.groupby(claves)]:
        con = grupo.loc[grupo["horas"] > 0, "poblacion_total"].sum()
        pct = 100 * con / grupo["poblacion_total"].sum()
        textos[clave] = f"{vista_mapa.personas(con)} personas ({vista_mapa.porcentaje(pct)}) con refugio a alguna hora"
    return textos


def cambia_por_seccion(cambios: dict, unidades: pd.DataFrame, cusecs: list[str]) -> dict[str, dict]:
    """Por cartera: secciones donde alguien gana opción (2), donde aún queda gente sin opción (1) y personas que ganan.

    `unidades`: estados base y poblaciones por unidad (`app/unidades_mapa.parquet`). Solo se guardan las
    secciones con clase 1 o 2; el resto es 0 (nadie sin opción antes de la cartera).
    """
    posicion = {c: i for i, c in enumerate(cusecs)}
    resultado = {}
    for clave, datos in cambios.items():
        componente, objetivo, _ = clave.split("|")
        modo = "pie" if componente == "a_pie" else "transporte"
        columna = "poblacion_total" if objetivo == "total" else "poblacion_65_mas"
        sin = unidades[unidades[f"estado_{modo}"] == acceso.SIN]
        ganan = sin[sin["unidad"].isin(set(datos["unidades"]))]
        antes = sin.groupby("cusec")[columna].sum()
        gana = ganan.groupby("cusec")[columna].sum().reindex(antes.index, fill_value=0.0)
        filas = [[posicion[c], 2 if gana[c] > 0 else 1, round(float(gana[c])), round(float(antes[c] - gana[c]))]
                 for c in antes.index if c in posicion and antes[c] > 0]
        resultado[clave] = {"secciones": filas, "suma_ganan": float(gana.sum())}
    return resultado


# ------------------------------------------------------------------ exportación


def leer_capas(proc: Path) -> dict:
    """Tablas del mapa que preparó la etapa `capas_app`."""
    app = proc / "app"
    return {"celdas": pd.read_parquet(app / "celdas_mapa.parquet"),
            "territorios": pd.read_csv(app / "territorios_mapa.csv", dtype={"codigo": str}),
            "tramos": pd.read_csv(app / "tramos_mapa.csv", dtype={"codigo": str}),
            "catalogo": json.loads((app / "resumen.json").read_text(encoding="utf-8"))["variables_minutos"]}


def copiar_capas_deck(proc: Path, destino: Path) -> dict[str, int]:
    """Municipios y líneas de deck.gl tal como los escribió `build` (ya son pequeños)."""
    pesos = {}
    for origen in sorted((proc / "app" / "deck").glob("*.json")):
        if origen.stem == "celdas":
            continue  # las celdas se escriben compactas (`celdas_compactas`)
        shutil.copyfile(origen, destino / origen.name)
        pesos[origen.name] = origen.stat().st_size
    return pesos


def vaciar_destino(destino: Path) -> None:
    """Borra la carpeta de datos de la página solo si la generó este exportador (lleva su `manifiesto.json`)
    o está vacía. Cualquier otra carpeta se deja intacta y se avisa: nunca se borra algo ajeno."""
    if not destino.exists():
        return
    if any(destino.iterdir()) and not (destino / "manifiesto.json").exists():
        raise ValueError(f"{destino} no es una carpeta de datos de la página (no tiene manifiesto.json): no se borra.")
    shutil.rmtree(destino)


def comprobar_que_cambia(cambios: dict) -> list[str]:
    """Carteras cuya población que gana no coincide con la ganancia de la tabla (tolerancia de 0,5 personas)."""
    return [clave for clave, d in cambios.items() if abs(d["ganancia_objetivo"] - d["ganancia_tabla"]) > 0.5]


def exportar(raiz: Path, version: str, destino: Path, config: dict) -> dict:
    """Escribe en `destino` (normalmente `web/datos/`) todos los datos de la página. Devuelve un resumen."""
    proc = raiz / "procesados" / version
    capas_dir = destino / "capas"
    vaciar_destino(destino)
    capas_dir.mkdir(parents=True)
    capas = leer_capas(proc)
    territorios, catalogo = capas["territorios"], capas["catalogo"]
    variables = variables_mapa(catalogo)
    pesos = copiar_capas_deck(proc, capas_dir)
    valores = valores_secciones(capas["celdas"], catalogo)
    secciones = capa_secciones(valores, contornos_secciones(raiz, version, set(valores.index)), territorios, catalogo)
    cambios = que_cambia(proc, config)
    discrepancias = comprobar_que_cambia(cambios)
    if discrepancias:
        raise ValueError(f"La capa «qué cambia» no cuadra con la ganancia de la tabla en: {discrepancias}")
    carteras = datos_carteras(proc, version, territorios, destino / "descargas")
    unidades_mapa = pd.read_parquet(proc / "app" / "unidades_mapa.parquet")
    horas_b = horas_refugio_por_unidad(proc, unidades_mapa)
    media_b, clase_b = refugio_por_seccion(horas_b, secciones["cusec"])
    secciones["refugio"] = [None if pd.isna(v) else round(float(v), 1) for v in media_b]
    secciones["k_refugio"] = [int(k) for k in clase_b]
    pesos["secciones.json"] = escribir_json(capas_dir / "secciones.json", secciones)
    hora_b = int(json.loads((proc / "refugios" / "resumen.json").read_text(encoding="utf-8"))["franja_referencia_c"])
    por_seccion = cambia_por_seccion(cambios, unidades_mapa, secciones["cusec"])
    descuadres = [c for c, d in por_seccion.items() if abs(d["suma_ganan"] - cambios[c]["ganancia_objetivo"]) > 0.5]
    if descuadres:
        raise ValueError(f"«Qué cambia» por sección no suma la ganancia de la cartera en: {descuadres}")
    for clave, ficha in carteras["carteras"].items():
        if clave in cambios:
            indices = indices_de_celdas(capas["celdas"], cambios[clave]["unidades"])
            ficha["ganan"] = {"secciones": por_seccion[clave]["secciones"],
                              "texto": vista_mapa.personas(cambios[clave]["ganancia_objetivo"]),
                              "caja": caja_de(capas["celdas"], indices, ficha["zonas"])}
    mapa = {"variables": variables, "modos": etiquetas_modo(catalogo),
            "territorios": territorios_buscador(territorios, etiquetas_modo(catalogo)),
            "leyendas": leyendas(capas["tramos"], territorios, variables), "rotulos": rotulos_por_zoom(territorios),
            "textos_secciones": textos_secciones(catalogo), "inicial": "comunidad:28", "variable_inicial": "min_tp_9_13",
            "ir_a": IR_A, "leyenda_cambia": LEYENDA_CAMBIA, "desglose": DESGLOSE,
            "grises_densidad": list(GRISES_DENSIDAD),
            "desglose_refugio": {"capa": "refugio", "nombre": "Refugio climático",
                                 "texto": ("Horas al día, de 12 a 21 h de un laborable de julio, con un mercado "
                                           "climatizado abierto a 10 min a pie (media de la sección). Supone acceso "
                                           f"en horario comercial (D-33); la peor hora es de {hora_b} a {hora_b + 1} h. "
                                           "Sin ese supuesto, la cobertura acreditable es 0: cobertura documental "
                                           "insuficiente, no ausencia de servicio."),
                                 "paleta": list(AZULES_REFUGIO), "etiquetas": ETIQUETAS_REFUGIO,
                                 "por_territorio": refugio_por_territorio(horas_b)}}
    pesos["mapa.json"] = escribir_json(destino / "mapa.json", mapa)
    pesos["carteras.json"] = escribir_json(destino / "carteras.json", carteras)
    pesos["puntos.json"] = escribir_json(destino / "puntos.json", {"centros": puntos_centros(proc),
                                                                   "mercados": puntos_mercados()})
    esquema = copiar_esquema(destino)
    pesos["textos.json"] = escribir_json(destino / "textos.json", {"inicio": datos_inicio(proc), "b_c": datos_b_c(proc),
                                                                   "fuentes": datos_fuentes(raiz, version),
                                                                   "esquema_png": esquema})
    manifiesto = {"version_datos": version, "creado_utc": datetime.datetime.now(datetime.UTC).isoformat(),
                  "origen": {str(r.relative_to(proc)).replace("\\", "/"): sha256_archivo(r) for r in fuentes_exportadas(proc)},
                  "pesos_bytes": pesos, "carteras": len(carteras["carteras"]), "que_cambia": len(cambios)}
    escribir_json(destino / "manifiesto.json", manifiesto)
    return manifiesto


ESQUEMA_PNG = CARPETA_WEB.parents[1] / "fases" / "H6_app" / "esquema_capas" / "esquema_capas.png"


def copiar_esquema(destino: Path) -> str | None:
    """Copia la imagen del esquema de capas (`fases/H6_app/esquema_capas/`, regenerable) si está en el equipo."""
    if not ESQUEMA_PNG.exists():
        return None
    shutil.copyfile(ESQUEMA_PNG, destino / "esquema_capas.png")
    return "datos/esquema_capas.png"


def fuentes_exportadas(proc: Path) -> list[Path]:
    """Archivos de `datos/procesados/<versión>/` de los que sale la página (para el manifiesto)."""
    relativas = ["app/celdas_mapa.parquet", "app/territorios_mapa.csv", "app/tramos_mapa.csv", "app/resumen.json",
                 "acceso/resumen_acceso.csv", "acceso/estados_base.parquet", "actuaciones/carteras_a_pie.csv",
                 "actuaciones/carteras_a_transporte.csv", "actuaciones/carteras_detalle.csv",
                 "actuaciones/b1_ampliar_horas.csv", "refugios/b_resumen.csv", "refugios/c_resumen.csv",
                 "primaria/centros_primaria.parquet", "candidatos_pie/pares.parquet"]
    return [proc / r for r in relativas if (proc / r).exists()]


def servir(carpeta: Path, puerto: int, abrir: bool) -> None:
    """Sirve la página solo en 127.0.0.1 con la biblioteca estándar (los navegadores no leen JSON desde file://)."""
    import functools
    import http.server
    import webbrowser

    manejador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(carpeta))
    with http.server.ThreadingHTTPServer(("127.0.0.1", puerto), manejador) as servidor:
        direccion = f"http://127.0.0.1:{puerto}/"
        print(f"Página en {direccion} (Ctrl+C para parar). Solo en este equipo; no usa internet.")
        if abrir:
            webbrowser.open(direccion)
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("Parado.")


def exportar_paquete(origen: Path, destino: Path) -> list[str]:
    """Copia la página, las librerías y los datos a una carpeta autónoma que se puede publicar tal cual."""
    faltan = [n for n in (*ARCHIVOS_PAGINA, "LEEME_PUBLICACION.md", "vendor", "datos/manifiesto.json")
              if not (origen / n).exists()]
    if faltan:
        raise ValueError(f"Falta {', '.join(faltan)} en {origen}: genera los datos y la página antes de exportar.")
    if destino.exists() and any(destino.iterdir()):
        raise ValueError(f"La carpeta {destino} no está vacía: elige una vacía para no mezclar versiones.")
    destino.mkdir(parents=True, exist_ok=True)
    copiados = []
    for nombre in ARCHIVOS_PAGINA:
        shutil.copyfile(origen / nombre, destino / nombre)
        copiados.append(nombre)
    for carpeta in ("vendor", "datos"):
        shutil.copytree(origen / carpeta, destino / carpeta)
        copiados.append(carpeta + "/")
    # Qué contiene el paquete, licencias y aviso ODbL, para quien lo publique o lo descargue.
    shutil.copyfile(origen / "LEEME_PUBLICACION.md", destino / "LEEME.md")
    copiados.append("LEEME.md")
    return copiados
