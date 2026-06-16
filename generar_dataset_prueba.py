"""
Genera un dataset de prueba con 1,500 tiendas simuladas en Lima Metropolitana
para probar el agrupamiento balanceado y el ruteo con datasets grandes.

Uso:
    python generar_dataset_prueba.py            -> crea tiendas_prueba_1500.csv
    python generar_dataset_prueba.py 3000       -> crea tiendas_prueba_3000.csv
"""
import sys
import numpy as np
import pandas as pd

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
rng = np.random.default_rng(42)

# Núcleos urbanos aproximados de Lima (lat, lon, peso)
nucleos = [
    (-12.046, -77.043, 0.20),  # Centro de Lima
    (-12.120, -77.030, 0.12),  # Miraflores / Surquillo
    (-12.200, -76.950, 0.15),  # Villa El Salvador / VMT
    (-11.990, -77.060, 0.13),  # Los Olivos / SMP
    (-12.050, -76.950, 0.12),  # Ate / Santa Anita
    (-12.160, -76.970, 0.10),  # SJM / Chorrillos
    (-11.940, -77.040, 0.08),  # Comas / Carabayllo
    (-12.070, -77.110, 0.10),  # Callao / San Miguel
]
pesos = np.array([p for _, _, p in nucleos])
pesos = pesos / pesos.sum()
asignacion = rng.choice(len(nucleos), size=N, p=pesos)

lats, lons = [], []
for i in asignacion:
    lat_c, lon_c, _ = nucleos[i]
    lats.append(lat_c + rng.normal(0, 0.018))
    lons.append(lon_c + rng.normal(0, 0.018))

df = pd.DataFrame({
    "codigo_sucursal": range(1, N + 1),
    "name_sucursal": [f"Tienda Sim {i:04d}" for i in range(1, N + 1)],
    "distrito": [f"Zona {asignacion[i] + 1}" for i in range(N)],
    "latitud": np.round(lats, 6),
    "longitud": np.round(lons, 6),
    # bultos que pide cada tienda (1 a 8) y ~3% de envíos prioritarios
    "cantidad_bultos": rng.integers(1, 9, N),
    "prioridad": np.where(rng.random(N) < 0.03, 1, 0),
})

# ~8% de tiendas con ventana horaria (mitad mañana, mitad tarde)
con_ventana = rng.random(N) < 0.08
manana = rng.random(N) < 0.5
df["hora_inicio"] = np.where(con_ventana, np.where(manana, "09:00", "14:00"), "")
df["hora_fin"] = np.where(con_ventana, np.where(manana, "13:00", "18:00"), "")

nombre = f"tiendas_prueba_{N}.csv"
df.to_csv(nombre, index=False)
print(f"OK -> {nombre} ({N} tiendas)")
