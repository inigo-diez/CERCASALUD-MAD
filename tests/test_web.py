"""Página web (SPEC P-28): el exportador solo da formato a resultados de `build`, la capa «qué
cambia» cuadra con la ganancia de las tablas y la página no lleva etiquetas prohibidas, datos
personales ni recursos de internet.

Las pruebas de integración leen la versión base de la demo si está en este equipo; si no, se omiten.
"""

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from cercasalud import web
from cercasalud.configuracion import leer_config
from cercasalud.rutas import raiz_datos

RAIZ = Path(__file__).resolve().parents[1]
ETIQUETAS_PROHIBIDAS = ("pacientes atendidos", "salud ganada", "muertes evitadas", "sin refugios")
# El texto de licencia del registro sanitario dice «la columna NIF se elimina en la ingesta»: se busca
# la columna (clave JSON o cabecera CSV), no la palabra.
CAMPOS_PERSONALES = ('"NIF"', "NIF,", ",NIF", "TITULARES_NOMBRE", "DATO PERSONAL")


def base_disponible() -> bool:
    """La versión base de la demo está calculada en este equipo."""
    try:
        return (raiz_datos() / "procesados" / web.VERSION_DEMO / "app" / "celdas_mapa.parquet").exists()
    except (OSError, ValueError):
        return False


# ------------------------------------------------------------------ unidades


def test_codificar_contorno_no_pierde_nada():
    """Contorno con 5 decimales → enteros con diferencias → el mismo contorno."""
    puntos = [[-3.62625, 41.08606], [-3.62626, 41.08696], [-3.62507, 41.08697], [-3.62506, 41.08607]]
    plano = web.codificar_contorno(puntos)
    assert plano[:2] == [-362625, 4108606] and plano[2:4] == [-1, 90]
    decodificado = web.decodificar_contorno(plano)
    assert [v for par in decodificado for v in par] == pytest.approx([v for par in puntos for v in par], abs=1e-9)


def test_unidades_que_ganan_cuentan_a_cada_unidad_una_vez():
    """Una unidad cubierta por dos zonas elegidas gana una sola vez; la que no cubre ninguna, no gana."""
    sin = pd.DataFrame({"unidad": ["u1", "u2", "u3"], "poblacion_total": [10.0, 20.0, 30.0]})
    cubre = [frozenset({"z1", "z2"}), frozenset({"z3"}), frozenset()]
    ganan = web.unidades_que_ganan(sin, cubre, ["z1", "z2"])
    assert ganan["unidad"].tolist() == ["u1"] and ganan["poblacion_total"].sum() == 10.0


def test_comprobar_que_cambia_detecta_una_discrepancia():
    cambios = {"a|total|1": {"ganancia_objetivo": 100.0, "ganancia_tabla": 100.2},
               "a|total|3": {"ganancia_objetivo": 90.0, "ganancia_tabla": 100.0}}
    assert web.comprobar_que_cambia(cambios) == ["a|total|3"]


def test_barras_de_la_pagina_no_se_suman():
    """Dos barras con su propia cifra y largo relativo a la mayor; ninguna es la suma de las otras."""
    fila = {"regla_simple_ganancia": 9421.0, "milp_ganancia": 51489.16}
    barras = web.barras_texto(fila, "a_transporte")
    assert [b["texto"] for b in barras] == ["9.421", "51.489"]
    assert barras[1]["fraccion"] == 1.0 and barras[0]["fraccion"] == pytest.approx(9421 / 51489.16, abs=1e-4)


def test_cifras_de_un_territorio_separan_no_evaluable():
    """«No evaluable» se da aparte y nunca se cuenta como «sin opción»."""
    fila = {"pie_con_acceso": 60.0, "pie_sin_opcion_verificada": 30.0, "pie_no_evaluable": 10.0}
    cifras = web.cifras_modo(fila, "pie")
    assert cifras == {"con_acceso": "60,0 %", "sin_opcion": "30", "sin_opcion_pct": "30,0 %", "no_evaluable": "10"}


def test_clave_y_nombre_de_cartera():
    assert web.clave_cartera("a_transporte", {"objetivo": "total", "k": 3}) == "a_transporte|total|3"
    assert web.clave_cartera("b1", {"objetivo": "75+", "max_centros": 3, "max_centro_horas": 12}) == "b1|75+|3_12"
    assert web.nombre_opcion("a_pie", {"k": 1}) == "1 zona"
    assert web.nombre_opcion("b1", {"max_centros": 1, "max_centro_horas": 12}) == "1 mercado, 12 horas"


def test_la_carteras_se_leen_de_su_texto_en_csv():
    assert web.lista_elegidos("['z1', 'z2']") == ["z1", "z2"]
    assert web.lista_elegidos("") == []


# ------------------------------------------------------------------ archivos de la página


def archivos_pagina() -> list[Path]:
    return [web.CARPETA_WEB / nombre for nombre in web.ARCHIVOS_PAGINA if (web.CARPETA_WEB / nombre).exists()]


def test_la_pagina_no_pide_nada_a_internet():
    """Ningún script, hoja de estilo, fuente ni petición apunta fuera del propio sitio.

    Los enlaces que el usuario puede pulsar (licencias, fuentes) sí pueden ir a internet: son
    `<a href>` que no se cargan solos. Aquí se buscan solo las cargas automáticas.
    """
    cargas = re.compile(r"""(src\s*=\s*["']https?:|<link[^>]+href\s*=\s*["']https?:|fetch\(\s*["']https?:|"""
                        r"""@import|url\(\s*["']?https?:)""", re.IGNORECASE)
    for archivo in archivos_pagina():
        texto = archivo.read_text(encoding="utf-8")
        assert not cargas.search(texto), archivo.name


def test_ninguna_etiqueta_prohibida_en_la_pagina():
    for archivo in [*archivos_pagina(), RAIZ / "src" / "cercasalud" / "web.py"]:
        texto = archivo.read_text(encoding="utf-8").lower()
        for etiqueta in ETIQUETAS_PROHIBIDAS:
            assert etiqueta not in texto, (archivo.name, etiqueta)


# ------------------------------------------------------------------ integración con la versión base


@pytest.fixture(scope="module")
def exportado(tmp_path_factory) -> Path:
    if not base_disponible():
        pytest.skip("La versión base de la demo no está en este equipo.")
    destino = tmp_path_factory.mktemp("web") / "datos"
    web.exportar(raiz_datos(), web.VERSION_DEMO, destino, leer_config())
    return destino


def leer(destino: Path, nombre: str):
    return json.loads((destino / nombre).read_text(encoding="utf-8"))


def test_caso_de_la_demo_con_las_cifras_de_la_tabla(exportado):
    """Transporte, población total, 3 zonas: 51.489 frente a 9.421 (carteras_a_transporte.csv), óptimo acreditado."""
    ficha = leer(exportado, "carteras.json")["carteras"]["a_transporte|total|3"]
    assert [b["texto"] for b in ficha["barras"]] == ["9.421", "51.489"]
    assert ficha["estado"].startswith("optimo (óptimo acreditado")
    assert [z["municipio"] for z in ficha["zonas"]] == ["Boadilla del Monte", "Alcobendas", "Rivas-Vaciamadrid"]
    assert ficha["ganan"]["texto"] == "51.489" and len(ficha["ganan"]["secciones"]) > 0
    inicio = leer(exportado, "textos.json")["inicio"]
    assert [c["valor"] for c in inicio["cifras"]][2] == "51.489"


def test_que_cambia_esta_en_todas_las_carteras_de_a(exportado):
    """Las 12 carteras de A (a pie y en transporte; total y 65+; 1, 3 y 5 zonas) llevan su capa; B1 no."""
    carteras = leer(exportado, "carteras.json")["carteras"]
    con_capa = sorted(c for c, f in carteras.items() if "ganan" in f)
    assert len(con_capa) == 12 and all(not c.startswith("b1") for c in con_capa)


def test_secciones_suman_la_poblacion_de_la_comunidad(exportado):
    """Una fila por unidad, no por pieza de dibujo: las secciones suman los 7.113.886 habitantes del INE
    (REGISTRO-FALLOS 44), y cada parte dibujada apunta a una sección existente."""
    secciones = leer(exportado, "capas/secciones.json")
    assert secciones["n"] == len(secciones["cusec"]) == len(secciones["k_min_tp_9_13"]) == 4518
    assert sum(secciones["g"]) == pytest.approx(7_113_886, abs=secciones["n"])
    assert max(secciones["seccion_de_parte"]) < secciones["n"] and len(secciones["partes"]) >= secciones["n"]
    assert all(t.startswith(("municipio:", "distrito:")) for t in secciones["territorio"])


def test_que_cambia_por_seccion_suma_la_ganancia(exportado):
    """Las personas que ganan opción, sumadas por sección, dan la ganancia de la tabla (51.489 en el caso)."""
    ficha = leer(exportado, "carteras.json")["carteras"]["a_transporte|total|3"]
    assert sum(fila[2] for fila in ficha["ganan"]["secciones"] if fila[1] == 2) == pytest.approx(51_489, abs=50)


def test_mediana_ponderada():
    import numpy as np
    assert web.mediana_ponderada(np.array([10.0, 20.0, 30.0]), np.array([1.0, 1.0, 10.0])) == 30.0
    assert web.mediana_ponderada(np.array([10.0, 20.0, 30.0]), np.array([5.0, 1.0, 1.0])) == 10.0


def test_la_comunidad_y_el_umbral_de_la_leyenda(exportado):
    """Leyenda de la Comunidad en transporte: 7 tramos, raya del umbral tras «20–30» y «No evaluable» aparte."""
    mapa = leer(exportado, "mapa.json")
    leyenda = mapa["leyendas"]["comunidad:28"]["min_tp_9_13"]
    assert len(leyenda["filas"]) == 7 and mapa["variables"]["min_tp_9_13"]["umbral_tras"] == 2
    assert leyenda["filas"][2]["etiqueta"] == "20–30" and leyenda["extra"][0]["etiqueta"] == "No evaluable"
    comunidad = next(t for t in mapa["territorios"] if t["clave"] == "comunidad:28")
    assert comunidad["modos"]["transporte"]["sin_opcion"] == "289.240"


def test_ningun_dato_personal_ni_etiqueta_prohibida_en_los_datos(exportado):
    for archivo in exportado.rglob("*"):
        if archivo.is_file() and archivo.suffix in {".json", ".html", ".csv", ".geojson"}:
            texto = archivo.read_text(encoding="utf-8")
            for campo in CAMPOS_PERSONALES:
                assert campo not in texto, (archivo.name, campo)
            for etiqueta in ETIQUETAS_PROHIBIDAS:
                assert etiqueta not in texto.lower(), (archivo.name, etiqueta)


def test_atribuciones_y_aviso_odbl(exportado):
    fuentes = leer(exportado, "textos.json")["fuentes"]
    texto = " ".join(fuentes["atribuciones"]) + fuentes["odbl"]
    for literal in ("Powered by CRTM", "www.ine.es", "Fuente de los datos: Comunidad de Madrid",
                    "Origen de los datos: Ayuntamiento de Madrid", "ODbL"):
        assert literal in texto
    assert fuentes["version"] == web.VERSION_DEMO


def test_el_exportador_no_borra_carpetas_ajenas(tmp_path):
    """Solo vacía una carpeta que generó él (con manifiesto.json) o una vacía; cualquier otra, la deja."""
    ajena = tmp_path / "ajena"
    ajena.mkdir()
    (ajena / "importante.txt").write_text("no borrar", encoding="utf-8")
    with pytest.raises(ValueError, match="no se borra"):
        web.vaciar_destino(ajena)
    assert (ajena / "importante.txt").exists()
    propia = tmp_path / "datos"
    propia.mkdir()
    (propia / "manifiesto.json").write_text("{}", encoding="utf-8")
    web.vaciar_destino(propia)
    assert not propia.exists()


def test_exportar_paquete_exige_la_pagina_antes_de_crear_nada(tmp_path):
    with pytest.raises(ValueError, match="Falta"):
        web.exportar_paquete(tmp_path / "sin_pagina", tmp_path / "destino")
    assert not (tmp_path / "destino").exists()


def test_los_pasos_de_la_demo_existen(exportado):
    """Cada parada de la demo apunta a un territorio, una variable y una cartera que existen en los datos."""
    textos, mapa = leer(exportado, "textos.json"), leer(exportado, "mapa.json")
    carteras = leer(exportado, "carteras.json")["carteras"]
    claves = {t["clave"] for t in mapa["territorios"]}
    for paso in textos["inicio"]["demo"]:
        assert paso.get("territorio", "comunidad:28") in claves
        assert paso.get("variable", "min_tp_9_13") in mapa["variables"]
        assert paso.get("cartera", "a_transporte|total|3") in carteras
    assert all(clave in claves for clave in mapa["ir_a"])


def test_para_quien_lleva_su_limite_y_la_viabilidad(exportado):
    """El bloque «Para quién» dice que no consta que nadie vaya a usarla, y la viabilidad no promete servicios de pago."""
    fuentes = leer(exportado, "textos.json")["fuentes"]
    assert any("no se ha contactado con ningún organismo" in t for t in fuentes["para_quien"])
    assert any("AccessMod" in t for t in fuentes["para_quien"])
    assert any("MIT" in t for t in fuentes["viabilidad"])
    assert all(c["aporta"] for c in fuentes["conjuntos"])


def test_coordenadas_de_las_zonas_con_cuatro_decimales():
    tabla = pd.DataFrame({"Orden": [1], "Longitud": [-3.89911216], "Latitud": [40.41482354]})
    filas = web.tabla_texto(tabla)["filas"]
    assert filas[0][1:] == ["-3,8991", "40,4148"]


def test_capa_de_refugios_coincide_con_la_tabla_de_b(exportado):
    """Personas con refugio a alguna hora en Madrid capital = `personas_unicas_con_alguna_hora` de `b_resumen.csv`
    (laborable de julio, cota central); y solo hay valor de refugio en secciones de Madrid capital."""
    refugio = leer(exportado, "mapa.json")["desglose_refugio"]
    b = pd.read_csv(raiz_datos() / "procesados" / web.VERSION_DEMO / "refugios" / "b_resumen.csv")
    fila = b[(b["territorio"] == "madrid_capital") & (b["nombre"] == "base_central") & (b["grupo_edad"] == "total")
             & (b["tipo_dia"] == "laborable_julio")].iloc[0]
    cifra = int(refugio["por_territorio"]["municipio:28079"].split(" personas")[0].replace(".", ""))
    assert cifra == round(fila["personas_unicas_con_alguna_hora"])
    secciones = leer(exportado, "capas/secciones.json")
    con_valor = {c[:5] for c, v in zip(secciones["cusec"], secciones["refugio"], strict=True) if v is not None}
    assert con_valor == {"28079"}
