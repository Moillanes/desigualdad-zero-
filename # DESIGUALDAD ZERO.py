# PROYECTO FUNDAMENTOS DE TECNOLOGÍAS DIGITALES APLICADAS A LOS NEGOCIOS


# PROYECTO FUNDAMENTOS DE TECNOLOGÍAS DIGITALES APLICADAS A LOS NEGOCIOS

# IMPORTACIÓN DE LIBRERÍAS

# Pandas para carga, limpieza y transformación de datos
import pandas as pd
# NumPy para operaciones numéricas y gestión de valores Nan
import numpy as np
# Pathlib para manejar rutas de archivos de forma robusta
from pathlib import Path

import re
# Librería estandar para leer archivos JSON
import json
# Librerías de visualización
from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon
import matplotlib as mpl

# =========================
#  RENTA (INE) - DISTRITO/AÑO
# =========================

# Cargamos el CSV del INE con los datos de renta
# El archivo usa separador tabulador y codificación latin1
df_ine = pd.read_csv(
    "renta_ine_sevilla.csv",
    sep="\t",
    encoding="latin1"
)

# Convertir celdas en blanco de la columna Distritos a Nan
# Esto permite filtrar correctamente solo las filas con información de distrito
df_ine["Distritos"] = df_ine["Distritos"].replace(r"^\s*$", np.nan, regex=True)


# Filtamos únicamente el municipio de Sevilla
# El código 41091 corresponde al municipio de Sevilla
df_ine_sevilla = df_ine[df_ine["Municipios"].str.contains(r"^41091\s+Sevilla", na=False)].copy()

# Nos quedamos solo con las filas que tienen distrito (excluimos nivel municipio)
df_ine_sevilla = df_ine_sevilla[df_ine_sevilla["Distritos"].notna()].copy()

# Seleccionamos:
# - Indicador: Mediana de la renta por unidad de consumo
# - Periodo: 2020 a 2023
df_renta = df_ine_sevilla[
    (df_ine_sevilla["Indicadores de renta media y mediana"] == "Mediana de la renta por unidad de consumo") &
    (df_ine_sevilla["Periodo"].between(2020, 2023))
].copy()

# Nos quedamos solo con las columnas necesarias
df_renta = df_renta[["Distritos", "Periodo", "Total"]].copy()
# Renombramos columnas para mayor claridad semántica
df_renta.rename(columns={
    "Distritos": "distrito",
    "Periodo": "year",
    "Total": "renta_mediana_uc"
}, inplace=True)

# Convertimos la renta a formato numérico:
# - Eliminamos separadores de miles
# - Convertimos coma decimal a punto
df_renta["renta_mediana_uc"] = pd.to_numeric(
    df_renta["renta_mediana_uc"].astype(str).str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
    errors="coerce"
)

#  NOS QUEDAMOS CON 1 FILA POR DISTRITO-AÑO (clave)
df_renta = (
    df_renta.dropna(subset=["renta_mediana_uc"])
            .groupby(["distrito", "year"], as_index=False)["renta_mediana_uc"]
            .median()   # o .mean()
)

#  Normalización y riesgo (0-1) sobre el panel ya limpio
r_min, r_max = df_renta["renta_mediana_uc"].min(), df_renta["renta_mediana_uc"].max()
df_renta["renta_norm"] = (df_renta["renta_mediana_uc"] - r_min) / (r_max - r_min)
# Convertimos renta en riesgo:
# A menor renta estructural, mayor riesgo social
df_renta["renta_riesgo"] = 1 - df_renta["renta_norm"]

# Comprobación rápida
print(df_renta.head(20))
print("Filas esperadas (11 distritos x 4 años = 44):", len(df_renta))


# =========================
# 2. DATOS PARO (SEPE) - MUNICIPIO/AÑO
# =========================

# Ruta donde se encuentran los CSV anuales del SEPE
ruta = Path(r"Proyecto")
# Seleccionamos todos los archivos de paro por municipio
archivos = sorted(ruta.glob("Paro_por_municipios_*.csv"))

lista_paro = []

# Iteramos por cada archivo anual
for archivo in archivos:
    # Cargamos el CSV del SEPE
    # skiprows=1 elimina la fila descriptiva del archivo
    df_sepe = pd.read_csv(
        archivo,
        sep=";",
        encoding="latin1",
        skiprows=1
    )

    # Limpiar nombres de columnas (quita espacios y saltos de línea)
    df_sepe.columns = df_sepe.columns.str.strip().str.replace("\n", "", regex=False)

    # Normalizamos texto para evitar errores de comparación
    df_sepe["Provincia"] = df_sepe["Provincia"].astype(str).str.upper().str.strip()
    df_sepe["Municipio"] = df_sepe["Municipio"].astype(str).str.upper().str.strip()

    # Filtramos únicamente Sevilla capital
    sev = df_sepe[
        (df_sepe["Provincia"] == "SEVILLA") &
        (df_sepe["Municipio"] == "SEVILLA")
    ].copy()

    # Extraemos el año desde el código mensual (YYYYMM)
    codigo_mes_col = "Código mes"  # tras strip() quedará así
    sev["year"] = sev[codigo_mes_col].astype(str).str[:4].astype(int)

    # Convertimos el paro total a numérico
    sev["total Paro Registrado"] = pd.to_numeric(sev["total Paro Registrado"], errors="coerce")

    # Agregar (promedio anual) — si solo hay enero, será ese valor
    paro_anual = sev.groupby("year", as_index=False)["total Paro Registrado"].mean()
    paro_anual.rename(columns={"total Paro Registrado": "paro_total"}, inplace=True)
    # Añadimos a la lista
    lista_paro.append(paro_anual)

# Unimos todos los años en un solo DataFrame
paro_sevilla = pd.concat(lista_paro, ignore_index=True)

# Por seguridad: nos quedamos con el periodo relevante (2020-2024)
paro_sevilla = paro_sevilla[paro_sevilla["year"].between(2020, 2024)].copy()

# Normalización Min-Max del paro (0-1)
p_min = paro_sevilla["paro_total"].min()
p_max = paro_sevilla["paro_total"].max()
paro_sevilla["paro_norm"] = (paro_sevilla["paro_total"] - p_min) / (p_max - p_min)

# Ordenamos por año
print(paro_sevilla.sort_values("year"))

# =========================
# 3. CONSTRUCCIÓN DEL ÍNDICE DE RIESGO SOCIAL (IRS) Y ALERTAS
# =========================

# Unimos renta (distrito-año) con paro (municipio-año) usando el año como clave
# Merge por año (paro municipal se aplica a todos los distritos ese año)
df_base = df_renta.merge(
    paro_sevilla[["year", "paro_norm"]],
    on="year",
    how="left"
)

# Definición del IRS:
#- 70% componente estructural (renta riesgo)
#- 30% componente coyuntural (paro normalizado)
df_base["IRS"] = (
    0.7 * df_base["renta_riesgo"] +
    0.3 * df_base["paro_norm"]
    )

# Ordenamos por distrito y año
df_base = df_base.sort_values(["distrito", "year"]).reset_index(drop=True)
# Calculamos el IRS del año anterior (shift) para cada distrito
df_base["IRS_prev"] = df_base.groupby("distrito")["IRS"].shift(1)
# Variación porcentual interanual del IRS
df_base["IRS_var_pct"] = (df_base["IRS"] / df_base["IRS_prev"]) - 1

# Definimos alerta roja si el IRS aumenta más de un 20%
df_base["alerta_roja"] = df_base["IRS_var_pct"] > 0.20
# Nivel de alerta final
df_base["nivel_alerta"] = df_base["alerta_roja"].map({True: "ROJA", False: "OK"})

# Comprobaciones rápidas
print(df_base.head(20))
# 20 distritos con mayor aumento porcentual del IRS
print(df_base[df_base["alerta_roja"]].sort_values(["year", "IRS_var_pct"], ascending=[True, False]).head(20))

print("Distritos:", df_base["distrito"].nunique())  # debería ser 11
print("Años:", sorted(df_base["year"].unique()))    # 2020-2023 (renta) y paro 2020-2024
print(df_base.isna().sum()[["paro_norm", "IRS"]])   # debería ser 0 en IRS
print(df_base.groupby("year")["distrito"].nunique())

# Visualización 1: Ranking IRS por distrito (año 2023)

import matplotlib.pyplot as plt

df_2023 = df_base[df_base["year"] == 2023].copy()
# Ordenamos por IRS descendente
df_2023 = df_2023.sort_values("IRS", ascending=False)
# Gráfico de barras horizontales
plt.figure()
plt.barh(df_2023["distrito"], df_2023["IRS"])
plt.title("IRS por distrito (Sevilla) - 2023")
plt.xlabel("IRS (0-1)")
plt.ylabel("Distrito")
plt.gca().invert_yaxis()
plt.tight_layout()
plt.savefig("fig1_ranking_IRS_2023.png", dpi=200)
plt.show()

# Visualización 2: Serie temporal IRS (2020-2023) para 6 distritos

print(df_2023[["distrito", "IRS"]])
# Distritos seleccionados para la serie temporal
distritos_focus = [
    "4109102 Sevilla distrito 02",
    "4109104 Sevilla distrito 04",
    "4109105 Sevilla distrito 05",
    "4109108 Sevilla distrito 08",
    "4109103 Sevilla distrito 03",
    "4109111 Sevilla distrito 11"
]

plt.figure()

# Iteramos por cada distrito y dibujamos su serie temporal
# Gráfico de líneas con marcadores
for d in distritos_focus:
    tmp = df_base[df_base["distrito"] == d].sort_values("year")
    plt.plot(tmp["year"], tmp["IRS"], marker="o", label=d)
plt.title("Evolución del IRS (Sevilla) - Distritos seleccionados (2020-2023)")
plt.xlabel("Año")
plt.ylabel("IRS (0-1)")
plt.xticks([2020, 2021, 2022, 2023])
plt.legend(fontsize=7)
plt.tight_layout()
plt.savefig("fig2_serie_IRS_2020_2023.png", dpi=200)
plt.show()

# Visualización 3: Tabla (tipo "semáforo") de variación anual

df_tabla = df_base.copy()
# Convertimos variación a porcentaje
df_tabla["IRS_var_pct"] = df_tabla["IRS_var_pct"] * 100 

# Filtramos años 2021-2023 (ya que 2020 no tiene variación)
tabla_2021_2023 = df_tabla[df_tabla["year"].between(2021,2023)].copy()
# Ordenamos por año y variación porcentual
tabla_2021_2023 = tabla_2021_2023.sort_values(["year", "IRS_var_pct"])

# Guardamos la tabla como imagen simple

plt.figure(figsize=(10, 6))
plt.axis("off")

# Mostramos solo las columnas relevantes y primeras 20 filas
tabla_show = tabla_2021_2023[["distrito", "year", "IRS", "IRS_var_pct", "nivel_alerta"]].head(20)

# Creamos la tabla
tbl = plt.table(
    cellText=tabla_show.values,
    colLabels=tabla_show.columns,
    loc="center"
)

# Ajustes de formato
tbl.auto_set_font_size(False)
tbl.set_fontsize(8)
tbl.scale(1, 1.3)

plt.title("Variación anual del IRS (top 20 filas por mayor caída) - 2021 a 2023")
plt.tight_layout()
plt.savefig("fig3_tabla_variacion_IRS.png", dpi=200)
plt.show()



# =========================
# 4. MAPA DEL IRS POR DISTRITO (AÑO 2023)
# =========================

# Ruta al archivo GeoJSON de los distritos de Sevilla
GEOJSON_PATH = "Proyecto/Distritos_de_Sevilla_7789076463007029926.geojson"
YEAR_MAP = 2023 # año del mapa (nuestra renta llega a 2023)

# Prepararamos DATA IRS (df_base) --> IRS por distrito (nombre) en un año

# Extraemos número de distrito "01"... "11" desde la columna df_base["distrito"]
df_map = df_base[df_base["year"] == YEAR_MAP].copy()

# Extraemos número de distrito y convertimos a entero
df_map["distrito_num"] = df_map["distrito"].str.extract(r"distrito\s+(\d+)", expand=False)
df_map["distrito_num"] = df_map["distrito_num"].astype(int)

# Mapa número -> NOMBRE (Distri_11D del GeoJSON)

# Diccionario de mapeo
num_to_name = {
    1: "Casco Antiguo",
    2: "Macarena",
    3: "Nervión",
    4: "Cerro - Amate",
    5: "Sur",
    6: "Triana",
    7: "Este - Alcosa - Torreblanca",
    8: "San Pablo - Santa Justa",
    9: "Los Remedios",
    10: "Bellavista - La Palmera",
    11: "Norte"
}

# Creamos columna con nombre del distrito
df_map["distrito_name"] = df_map["distrito_num"].map(num_to_name)

# Por seguridad: si hubiera duplicados, nos quedaremos con un valor por distrito
df_map = df_map.groupby("distrito_name", as_index=False)["IRS"].mean()

# Leer GEOJSON

with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
    geo = json.load(f)

# Extraemos las features (distritos)
features = geo["features"]

# Dibujamos el mapa

fig, ax = plt.subplots(figsize=(10, 8))
ax.set_aspect("equal")
ax.axis("off")

vals = df_map["IRS"].values
vmin, vmax = 0, 1
norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
cmap = plt.cm.viridis

patches = []
colors = []

# Iteramos por cada distrito en el GeoJSON
for feat in features:
    distrito_geo = feat["properties"]["Distri_11D"]

    # Buscar IRS del distrito

    row = df_map[df_map["distrito_name"] == distrito_geo]
    irs_value = row["IRS"].values[0] if not row.empty else np.nan
    
    # Extraemos geometría y dibujamos 
    geom = feat["geometry"]
    geom_type = geom["type"]
    coords = geom["coordinates"]

    # Si es Polygon o MultiPolygon iteramos sobre sus partes
    if geom_type == "Polygon":
        polygons = [coords]
    elif geom_type == "MultiPolygon":
        polygons = coords
    else:
        continue

    # Dibujamos cada polígono
    for poly in polygons:
        exterior = poly[0]
        xs = [p[0] for p in exterior]
        ys = [p[1] for p in exterior]
        cx, cy = sum(xs)/len(xs), sum(ys)/len(ys)
        ax.text(cx,cy, distrito_geo, fontsize=7, ha="center", va="center")
        polygon = Polygon(exterior, closed=True)
        patches.append(polygon)

        if not np.isnan(irs_value):
            colors.append(cmap(norm(irs_value)))
        else:
            colors.append((0.9, 0.9, 0.9, 1))

# Creamos colección de parches
pc = PatchCollection(patches, facecolor=colors, edgecolor="black", linewidths=0.6)
ax.add_collection(pc)
ax.autoscale()
ax.margins(0.03)

# Colorbar
sm = mpl.cm.ScalarMappable(norm=norm, cmap=cmap)
sm.set_array([])
cbar = fig.colorbar(sm, ax=ax, fraction=0.035, pad=0.02)
cbar.set_label("IRS (0-1)")

ax.set_title(f"Índice de Riesgo Social (IRS) por distrito - Sevilla ({YEAR_MAP})")
plt.tight_layout()
plt.savefig(f"fig4_mapa_IRS_Sevilla_{YEAR_MAP}.png", dpi=300, bbox_inches="tight")
plt.show()
