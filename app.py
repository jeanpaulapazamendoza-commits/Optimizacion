"""
Proceso de Optimización — v2 (escalable a 1000+ tiendas)
Agrupación de tiendas por cercanía geográfica + Ruteo óptimo

Mejoras v2:
  - Clustering BALANCEADO por capacidad: cada grupo tiene como máximo N tiendas
    (ideal para asignar una ruta/vehículo por grupo). Escala a miles de puntos.
  - Proyección geográfica en metros (reemplaza StandardScaler, que distorsionaba
    las distancias reales entre latitud y longitud).
  - Ruteo local con Google OR-Tools (sin API, sin límites de requests):
      * Matriz Haversine  -> instantáneo, sin internet, distancia en línea recta.
      * Matriz OSRM       -> distancias por calles reales usando el servidor
                             público y gratuito de OSRM (router.project-osrm.org).
  - OpenRouteService se mantiene como motor opcional (requiere API Key,
    máx. ~50 tiendas por grupo en el plan gratuito).

Mejoras v3:
  - Columna opcional `cantidad_bultos` en la plantilla: cada ruta puede limitarse
    por número de tiendas O por bultos totales (capacidad real del vehículo).
  - Columna opcional `prioridad` (1 = más urgente): las tiendas prioritarias se
    visitan PRIMERO dentro de su ruta (1, luego 2, ... y al final las normales).
  - Editor de rutas: permite personalizar manualmente el orden de visita de
    cualquier ruta y recalcula distancia, duración y trazado en el mapa.
  - Flota personalizada: define tipos de vehículo (cantidad, capacidad en bultos
    y máx. de tiendas). El nº de rutas queda limitado por la flota; se pueden
    habilitar 2ª/3ª vueltas y las tiendas que no entran se reportan aparte
    (las prioritarias se asignan primero, nunca quedan fuera si hay cupo).

Autor:  Jean Paul Apaza Mendoza
Curso:  Fundamentos de Machine Learning
"""
import datetime as _dt
import math
import time
from io import BytesIO

import folium
import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from folium.plugins import AntPath, Draw, Fullscreen, MarkerCluster, MeasureControl, MiniMap
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from streamlit_folium import st_folium
from scipy.spatial import ConvexHull
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.metrics import davies_bouldin_score, pairwise_distances, silhouette_score

try:
    import openrouteservice as ors
    from openrouteservice import convert, optimization
    ORS_DISPONIBLE = True
except ImportError:
    ORS_DISPONIBLE = False

try:
    import qrcode
    QR_DISPONIBLE = True
except ImportError:
    QR_DISPONIBLE = False

try:
    import gspread
    from google.oauth2.service_account import Credentials as GCredentials
    GSHEETS_DISPONIBLE = True
except ImportError:
    GSHEETS_DISPONIBLE = False

try:
    import streamlit_authenticator as stauth
    AUTH_DISPONIBLE = True
except ImportError:
    AUTH_DISPONIBLE = False

# Módulo local: conversor de direcciones ↔ coordenadas (ver conversor.py).
try:
    from conversor import render_conversor
    CONVERSOR_DISPONIBLE = True
except Exception:
    CONVERSOR_DISPONIBLE = False

st.set_page_config(
    page_title="RuteoTiendas Planner — Ruteo óptimo de despacho",
    page_icon="🏪",
    layout="wide"
)

# ===========================================================
# ESTILO — capa visual profesional sobre el tema de config.toml
# (el tema define colores/fuentes; este CSS pule tarjetas, KPIs,
#  encabezado de marca, mapa y botones)
# ===========================================================
ESTILO_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* ---- Lienzo general ---- */
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stDecoration"] { display: none; }
[data-testid="stMainBlockContainer"] { padding-top: 1.1rem; padding-bottom: 3rem; }
[data-testid="stMain"] hr { margin: 1.4rem 0; border: none; border-top: 1px solid #E5EAF1; }

/* ---- Títulos de sección con barra de acento ---- */
[data-testid="stMain"] h2, [data-testid="stMain"] h3 {
  font-weight: 700; letter-spacing: -.01em; color: #1B2A3D;
}
[data-testid="stMain"] [data-testid="stHeading"] h3 {
  border-left: 4px solid #F2A33C; padding-left: .55rem;
}

/* ---- Sidebar oscuro: encabezados tipo panel de control ---- */
[data-testid="stSidebar"] [data-testid="stHeading"] h2,
[data-testid="stSidebar"] [data-testid="stHeading"] h3 {
  font-size: .82rem !important; text-transform: uppercase;
  letter-spacing: .08em; color: #F6C35C !important; font-weight: 700;
}
[data-testid="stSidebar"] hr { border: none; border-top: 1px solid rgba(255,255,255,.14); margin: 1rem 0; }
.rt-side-brand { color: #fff; font-size: 1.08rem; font-weight: 800; letter-spacing: -.01em;
  padding: 2px 0 10px 0; border-bottom: 2px solid rgba(242,163,60,.45); margin-bottom: 4px; }
.rt-side-brand b { color: #F2A33C; }
.rt-side-brand em { font-style: italic; font-weight: 600; color: #9FB4D0; font-size: .85rem; }

/* ---- Botones ---- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: 9px; font-weight: 600;
  box-shadow: 0 1px 2px rgba(16,42,67,.06); transition: all .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  transform: translateY(-1px); box-shadow: 0 4px 12px rgba(16,42,67,.16);
}
[data-testid="stBaseButton-primary"] { color: #33260B !important; font-weight: 700; }

/* ---- Tablas, expanders, alertas, tabs ---- */
[data-testid="stDataFrame"] { border: 1px solid #E3E8EF; border-radius: 10px; overflow: hidden; }
[data-testid="stMain"] [data-testid="stExpander"] {
  background: #fff; border: 1px solid #E3E8EF; border-radius: 12px; overflow: hidden;
}
[data-testid="stMain"] [data-testid="stExpander"] summary { font-weight: 600; }
[data-testid="stAlert"] { border-radius: 10px; }
button[data-baseweb="tab"] { font-weight: 600; }

/* ---- Mapa como tarjeta ---- */
iframe[title="streamlit_folium.st_folium"] {
  border: 1px solid #E3E8EF; border-radius: 14px;
  box-shadow: 0 6px 18px rgba(16,42,67,.08); background: #fff;
}

/* ---- Encabezado de marca ---- */
.rt-topbar { display: flex; flex-wrap: wrap; gap: 14px; align-items: center;
  justify-content: space-between;
  background: linear-gradient(115deg, #13223A 0%, #1E3658 78%, #27456E 100%);
  border-radius: 16px; border-bottom: 4px solid #F2A33C;
  padding: 20px 26px; margin-bottom: 10px;
  box-shadow: 0 10px 26px rgba(13,32,58,.22); }
.rt-brand { display: flex; align-items: center; gap: 14px; }
.rt-logo { width: 52px; height: 52px; border-radius: 14px; flex: 0 0 auto;
  background: linear-gradient(140deg, #F2A33C, #E0821B);
  display: flex; align-items: center; justify-content: center; font-size: 26px;
  box-shadow: inset 0 -2px 6px rgba(0,0,0,.18); }
.rt-title { color: #fff; font-size: 1.5rem; font-weight: 800; letter-spacing: -.02em; line-height: 1.1; }
.rt-title span { color: #F2A33C; }
.rt-title em { font-style: italic; font-weight: 600; color: #9FB4D0; font-size: 1.02rem; margin-left: 4px; }
.rt-sub { color: #A8BAD2; font-size: .85rem; margin-top: 3px; }
.rt-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.rt-pill { background: rgba(255,255,255,.09); border: 1px solid rgba(255,255,255,.16);
  color: #DDE7F3; padding: 5px 12px; border-radius: 999px; font-size: .78rem;
  font-weight: 500; text-decoration: none; }
a.rt-pill:hover { background: rgba(242,163,60,.25); border-color: #F2A33C; color: #fff; }

/* ---- Franja de KPIs ---- */
.rt-kpis { display: flex; flex-wrap: wrap; background: #fff;
  border: 1px solid #E3E8EF; border-radius: 14px; padding: 6px 10px;
  margin: .35rem 0 .5rem 0; box-shadow: 0 4px 14px rgba(16,42,67,.06); }
.rt-kpi { flex: 1 1 128px; display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; position: relative; }
.rt-kpi:not(:last-child)::after { content: ""; position: absolute; right: 0;
  top: 22%; height: 56%; width: 1px; background: #E8EDF3; }
.rt-kpi-ico { width: 34px; height: 34px; border-radius: 10px; flex: 0 0 auto;
  display: flex; align-items: center; justify-content: center; font-size: 17px; }
.rt-kpi-lbl { font-size: .65rem; font-weight: 700; letter-spacing: .07em;
  text-transform: uppercase; color: #7C8DA5; white-space: nowrap; }
.rt-kpi-val { font-size: 1.22rem; font-weight: 800; color: #1B2A3D; line-height: 1.15; }
.rt-kpi-bad { display: inline-block; margin-left: 6px; font-size: .68rem; font-weight: 700;
  color: #C03A3A; background: #FDEAEA; padding: 2px 7px; border-radius: 999px;
  vertical-align: middle; }

/* ---- Pie de página ---- */
.rt-foot { background: #13223A; color: #A8BAD2; border-radius: 14px;
  border-top: 3px solid #F2A33C; padding: 16px 22px;
  font-size: .8rem; line-height: 1.6; }
.rt-foot a { color: #F6C35C; }
.rt-foot b { color: #E8EEF6; }
</style>
"""
st.markdown(ESTILO_CSS, unsafe_allow_html=True)

# ===========================================================
# AUTENTICACIÓN (opcional) — login con usuario/contraseña
# Si NO existe la sección [auth] en los secrets, la app queda abierta
# (no bloquea a nadie hasta que decidas configurarlo). Ver SETUP_LOGIN.md.
# ===========================================================
def _a_dict_plano(obj):
    """st.secrets devuelve objetos de solo-lectura y anidados; los pasamos a
    dict mutable porque streamlit-authenticator modifica las credenciales."""
    if hasattr(obj, "items"):
        return {k: _a_dict_plano(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_a_dict_plano(v) for v in obj]
    return obj


usuario_actual = "anónimo"
auth_activo = False
try:
    _auth_cfg = st.secrets.get("auth", None)
except Exception:
    _auth_cfg = None

if AUTH_DISPONIBLE and _auth_cfg and _auth_cfg.get("credentials"):
    cfg = _a_dict_plano(_auth_cfg)
    authenticator = stauth.Authenticate(
        cfg["credentials"],
        cfg.get("cookie_name", "ruteo_auth"),
        cfg.get("cookie_key", "ruteo_cookie_key_cambia_esto"),
        float(cfg.get("cookie_expiry_days", 30)),
    )
    authenticator.login(location="main", fields={
        "Form name": "🔒 Iniciar sesión — RuteoTiendas Planner",
        "Username": "Usuario", "Password": "Contraseña", "Login": "Entrar"})
    _estado = st.session_state.get("authentication_status")
    if _estado is False:
        st.error("❌ Usuario o contraseña incorrectos. Intenta de nuevo.")
        st.stop()
    if _estado is None:
        st.info("🔒 Esta herramienta es privada. Ingresa tus credenciales para continuar.")
        st.stop()
    auth_activo = True
    usuario_actual = (st.session_state.get("name")
                      or st.session_state.get("username") or "usuario")
    authenticator.logout("🚪 Cerrar sesión", "sidebar", key="logout_btn")
    st.sidebar.caption(f"👤 Sesión activa: **{usuario_actual}**")
    st.sidebar.markdown("---")
elif _auth_cfg and not AUTH_DISPONIBLE:
    st.warning("⚠️ Configuraste `[auth]` en los secrets pero falta la librería "
               "`streamlit-authenticator` en requirements.txt.")

NOMBRE_ALUMNO = "Jean Paul Apaza mendoza"
CODIGO_ISIL = "cuenta.appseet01@gmail.com"
URL_COLAB = "https://colab.research.google.com/drive/1HRFy03Da-KP6zSfyX6XSwvqeqqeaDUPP?usp=sharing"

MAX_K = 100                     # tope de clusters en modo clásico
R_TIERRA = 6_371_008.8          # radio medio de la Tierra (m)
VEL_PROMEDIO_KMH = 25           # velocidad urbana asumida para estimar duración (motor haversine)
OSRM_BASE = "https://router.project-osrm.org"
OSRM_MAX_PUNTOS = 100           # límite del servidor público de OSRM por request
ORS_MAX_JOBS = 50               # límite del plan gratuito de ORS (optimization)

# ===========================================================
# VISOR DE RESULTADOS — recuperar la visualización de un ruteo guardado
# Sube el CSV que exporta la app ("Descargar TODAS las rutas" o "Descargar
# resultados") y vuelve a ver los grupos y el orden de visita en el mapa,
# sin recalcular. Útil si la página se recargó y se perdió la vista.
# ===========================================================
def _visor_leer_csv(arch):
    """Lee un CSV subido detectando separador (, o ;) y codificación."""
    for _enc in ("utf-8-sig", "latin-1"):
        try:
            arch.seek(0)
            return pd.read_csv(arch, sep=None, engine="python",
                               encoding=_enc, on_bad_lines="skip")
        except Exception:
            continue
    return None


def _visor_buscar(cols, *alias):
    """Encuentra una columna por nombre tolerando mayúsculas/acentos/duplicados."""
    norm = {str(c).strip().lower(): c for c in cols}
    for a in alias:
        if a in norm:
            return norm[a]
    return None


def _visor_num(serie):
    return pd.to_numeric(serie.astype(str).str.replace(",", ".", regex=False),
                         errors="coerce")


def _visor_ckey(c):
    """Orden numérico de grupos: 0,1,2,...,10,11 (no 0,1,10,2...)."""
    try: return (0, int(float(c)))
    except Exception: return (1, str(c))


def _visor_norm_cluster(v):
    """Normaliza el id de grupo para que coincida siempre: '0.0'->'0', '12.0'->'12',
    ' 3 '->'3'; deja intactos los no numéricos ('nan', 'ZonaA')."""
    s = str(v).strip()
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else s
    except (ValueError, OverflowError):
        return s


def _visor_hav(lat, lon, lats, lons):
    """Distancia haversine (m). Vectorizada: acepta escalares o arrays alineados
    (punto→muchos, o pares elemento a elemento)."""
    R = 6_371_008.8
    p1 = np.radians(np.asarray(lat, dtype=float))
    p2 = np.radians(np.asarray(lats, dtype=float))
    dphi = p2 - p1
    dl = np.radians(np.asarray(lons, dtype=float)) - np.radians(np.asarray(lon, dtype=float))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _visor_plantilla_nuevos_df():
    """Estructura que debe tener el archivo de puntos nuevos."""
    return pd.DataFrame({
        "Tienda":    ["Tienda nueva 1", "Tienda nueva 2", "Tienda nueva 3"],
        "Latitud":   [-11.9360, -11.9372, -11.9505],
        "Longitud":  [-77.0745, -77.0790, -77.0801],
        "Distrito":  ["Los Olivos", "Los Olivos", "Los Olivos"],
        "Bultos":    [2, 3, 1],
        "Prioridad": [0, 1, 0],
        "Grupo":     ["", "", "2"],   # opcional (texto): vacío = asignación automática
    })


@st.cache_data
def _visor_plantilla_nuevos_csv():
    return _visor_plantilla_nuevos_df().to_csv(index=False).encode("utf-8")


@st.cache_data
def _visor_plantilla_nuevos_xlsx():
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        _visor_plantilla_nuevos_df().to_excel(w, index=False, sheet_name="puntos_nuevos")
    return buf.getvalue()


def _visor_mejor_insercion(plat, plon, d, clusters, cd_lat, cd_lon):
    """«Mejor ruta»: devuelve (grupo, orden_previo) donde insertar el punto añade
    el MENOR desvío a la ruta (inserción más barata, considerando el CD como
    inicio/fin de cada recorrido)."""
    mejor_g = clusters[0] if clusters else None
    mejor_prev, mejor_costo = 0.0, float("inf")
    for c in clusters:
        sub = d[d["cluster"] == c].sort_values("orden")
        lat = np.array([cd_lat] + list(sub["lat"]) + [cd_lat], dtype=float)
        lon = np.array([cd_lon] + list(sub["lon"]) + [cd_lon], dtype=float)
        ordn = [0.0] + list(sub["orden"].astype(float)) + \
               [(float(sub["orden"].max()) + 1) if len(sub) else 1.0]
        dp = _visor_hav(plat, plon, lat, lon)                    # punto → cada nodo
        seg = _visor_hav(lat[:-1], lon[:-1], lat[1:], lon[1:])   # nodo → nodo siguiente
        costos = dp[:-1] + dp[1:] - seg
        j = int(np.argmin(costos))
        if costos[j] < mejor_costo:
            mejor_costo, mejor_g, mejor_prev = costos[j], c, ordn[j]
    return mejor_g, mejor_prev


# Sentinela para puntos nuevos aún NO asignados a ninguna ruta.
_VISOR_SIN = "· sin asignar ·"


def _visor_clave(codigo, lat, lon):
    """Clave estable de un punto nuevo: su código (único) o, si no tiene, lat|lon.
    Sirve para recordar su asignación entre recargas y clics."""
    c = str(codigo).strip()
    return c if c and c.lower() not in ("nan", "none", "") \
        else f"{float(lat):.6f}|{float(lon):.6f}"


def render_visor_resultado():
    st.title("📤 Ver / editar un resultado de ruteo guardado")
    st.caption(
        "Sube el CSV que descargaste del ruteo y recupera el mapa. Además puedes "
        "fijar tu **Centro de Distribución**, **agregar puntos nuevos** desde otro "
        "archivo y **re-optimizar** las rutas afectadas — todo sin recalcular desde cero. "
        "Al final descarga el resultado actualizado para seguir sumando después.")

    # =================================================================
    # PASO ① — Subir el ruteo guardado
    # =================================================================
    st.subheader("① Sube tu ruteo guardado")
    archivo = st.file_uploader(
        "CSV del resultado (botón «Descargar TODAS las rutas» o «Descargar resultados»)",
        type=["csv"], key="visor_upload")
    if archivo is None:
        st.info("⬆️ Sube tu archivo para reconstruir la visualización.")
        return

    df_r = _visor_leer_csv(archivo)
    if df_r is None or df_r.empty:
        st.error("No pude leer el archivo. Asegúrate de que sea el CSV que exporta la app.")
        return

    cols = list(df_r.columns)
    c_cluster = _visor_buscar(cols, "cluster", "grupo")
    c_orden   = _visor_buscar(cols, "orden")
    c_codigo  = _visor_buscar(cols, "código", "codigo", "orden.1")
    c_tienda  = _visor_buscar(cols, "tienda", "name_sucursal", "nombre")
    c_distr   = _visor_buscar(cols, "distrito")
    c_bultos  = _visor_buscar(cols, "bultos", "cantidad_bultos")
    c_prior   = _visor_buscar(cols, "prioridad")
    c_eta     = _visor_buscar(cols, "llegada (eta)", "llegada", "eta")
    c_lat     = _visor_buscar(cols, "latitud", "lat")
    c_lon     = _visor_buscar(cols, "longitud", "lon", "lng", "long")
    faltan = [n for n, c in [("Cluster", c_cluster), ("Latitud", c_lat),
                             ("Longitud", c_lon)] if c is None]
    if faltan:
        st.error(f"Al archivo le faltan columnas obligatorias: {', '.join(faltan)}. "
                 f"Columnas encontradas: {', '.join(map(str, cols))}")
        return

    d = pd.DataFrame()
    d["cluster"]   = df_r[c_cluster].map(_visor_norm_cluster)
    d["lat"]       = _visor_num(df_r[c_lat])
    d["lon"]       = _visor_num(df_r[c_lon])
    d["orden"]     = _visor_num(df_r[c_orden]) if c_orden else pd.Series(range(1, len(df_r) + 1))
    d["tienda"]    = df_r[c_tienda].astype(str) if c_tienda else "Tienda"
    d["codigo"]    = df_r[c_codigo].astype(str) if c_codigo else ""
    d["distrito"]  = df_r[c_distr].astype(str) if c_distr else ""
    d["bultos"]    = _visor_num(df_r[c_bultos]).fillna(0).astype(int) if c_bultos else 0
    d["prioridad"] = _visor_num(df_r[c_prior]).fillna(0).astype(int) if c_prior else 0
    d["eta"]       = df_r[c_eta].astype(str) if c_eta else ""
    d["nuevo"]     = False
    d = d.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    if d.empty:
        st.error("No encontré coordenadas válidas (Latitud/Longitud) en el archivo.")
        return
    d["orden"] = d["orden"].fillna(0)

    # =================================================================
    # PASO ② — Centro de Distribución (lo colocas manualmente)
    # =================================================================
    st.subheader("② Centro de Distribución")
    cca, ccb, ccc = st.columns([1, 1, 1.4])
    cd_lat = cca.number_input("Latitud del CD", value=float(round(d["lat"].mean(), 6)),
                              format="%.6f", key="visor_cd_lat")
    cd_lon = ccb.number_input("Longitud del CD", value=float(round(d["lon"].mean(), 6)),
                              format="%.6f", key="visor_cd_lon")
    usar_cd = ccc.checkbox("Mostrar el CD y conectar las rutas desde él",
                           value=True, key="visor_usar_cd")
    ccc.caption("Empieza en el centro de tus puntos; edítalo con las coordenadas de tu CD real.")

    grupo_activo = None   # se define en el paso ③ si hay puntos nuevos (para el clic en mapa)

    # =================================================================
    # PASO ③ — Agregar puntos nuevos (opcional)
    # =================================================================
    st.subheader("③ Agregar puntos nuevos (opcional)")
    with st.expander("📥 ¿Qué estructura debe tener tu archivo? Descarga la plantilla"):
        st.caption("Tu archivo (CSV o Excel) debe tener estas columnas. Solo **Latitud** y "
                   "**Longitud** son obligatorias; el resto es opcional. Deja **Grupo** vacío "
                   "para asignarlo con la app, o pon el número de grupo para forzarlo.")
        st.dataframe(_visor_plantilla_nuevos_df(), use_container_width=True, hide_index=True)
        pc1, pc2 = st.columns(2)
        pc1.download_button("📄 Plantilla CSV", data=_visor_plantilla_nuevos_csv(),
                            file_name="plantilla_puntos_nuevos.csv", mime="text/csv",
                            use_container_width=True)
        pc2.download_button(
            "📊 Plantilla Excel", data=_visor_plantilla_nuevos_xlsx(),
            file_name="plantilla_puntos_nuevos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True)

    archivo_nuevos = st.file_uploader("Sube tu CSV de puntos nuevos", type=["csv"],
                                      key="visor_nuevos")

    if archivo_nuevos is not None:
        df_n = _visor_leer_csv(archivo_nuevos)
        if df_n is None or df_n.empty:
            st.warning("No pude leer el archivo de puntos nuevos.")
        else:
            nc = list(df_n.columns)
            nlat = _visor_buscar(nc, "latitud", "lat")
            nlon = _visor_buscar(nc, "longitud", "lon", "lng", "long")
            if not nlat or not nlon:
                st.error("El archivo de puntos nuevos necesita columnas Latitud y Longitud.")
            else:
                ngru = _visor_buscar(nc, "grupo", "cluster")
                nv = pd.DataFrame()
                nv["lat"]       = _visor_num(df_n[nlat])
                nv["lon"]       = _visor_num(df_n[nlon])
                _nt = _visor_buscar(nc, "tienda", "name_sucursal", "nombre")
                _ncod = _visor_buscar(nc, "código", "codigo", "codigo_sucursal")
                _ndis = _visor_buscar(nc, "distrito")
                _nbul = _visor_buscar(nc, "bultos", "cantidad_bultos")
                _npri = _visor_buscar(nc, "prioridad")
                nv["tienda"]    = df_n[_nt].astype(str) if _nt else "Nuevo punto"
                nv["codigo"]    = df_n[_ncod].astype(str) if _ncod else ""
                nv["distrito"]  = df_n[_ndis].astype(str) if _ndis else ""
                nv["bultos"]    = _visor_num(df_n[_nbul]).fillna(1).astype(int) if _nbul else 1
                nv["prioridad"] = _visor_num(df_n[_npri]).fillna(0).astype(int) if _npri else 0
                nv["grupo_arch"] = (df_n[ngru].map(_visor_norm_cluster) if ngru else "")
                nv["eta"]       = ""
                nv["orden"]     = 0.0
                nv["nuevo"]     = True
                nv = nv.dropna(subset=["lat", "lon"]).reset_index(drop=True)
                if nv.empty:
                    st.warning("El archivo de puntos nuevos no tiene coordenadas válidas.")
                else:
                    grupos_base = sorted(d["cluster"].unique(), key=_visor_ckey)
                    # Nombres vacíos -> "(sin nombre)" (así no sale "None")
                    _mal = nv["tienda"].astype(str).str.strip().str.lower()
                    nv.loc[_mal.isin(["", "nan", "none"]), "tienda"] = "(sin nombre)"
                    nv["clave"] = [_visor_clave(nv.at[i, "codigo"], nv.at[i, "lat"],
                                                nv.at[i, "lon"]) for i in nv.index]

                    # Estado de asignaciones (persiste entre recargas y clics del mapa).
                    # Se reinicia si cambia el archivo de puntos nuevos.
                    _sig = (archivo_nuevos.name, getattr(archivo_nuevos, "size", 0), len(nv))
                    if st.session_state.get("visor_nuevos_sig") != _sig:
                        st.session_state["visor_nuevos_sig"] = _sig
                        st.session_state["visor_asig"] = {}
                        st.session_state.pop("visor_edit_grupos", None)
                    asig = st.session_state.setdefault("visor_asig", {})
                    for i in nv.index:            # inicializa: grupo del archivo, o «sin asignar»
                        k = nv.at[i, "clave"]
                        if k not in asig:
                            gf = nv.at[i, "grupo_arch"]
                            asig[k] = gf if gf in grupos_base else _VISOR_SIN

                    # --- Controles de asignación ---
                    ca1, ca2, ca3 = st.columns([1.5, 1, 1])
                    grupo_activo = ca1.selectbox(
                        "Grupo activo (para el clic en el mapa)", grupos_base,
                        key="visor_grupo_activo",
                        help="Haz clic en un punto GRIS del mapa para asignarlo a este grupo.")
                    if ca2.button("🤖 Asignar pendientes (mejor ruta)", use_container_width=True):
                        for i in nv.index:
                            k = nv.at[i, "clave"]
                            if asig.get(k) == _VISOR_SIN:
                                g, _p = _visor_mejor_insercion(nv.at[i, "lat"], nv.at[i, "lon"],
                                                               d, grupos_base, cd_lat, cd_lon)
                                asig[k] = g
                        st.session_state.pop("visor_edit_grupos", None)
                    if ca3.button("↺ Todos sin asignar", use_container_width=True):
                        for i in nv.index:
                            asig[nv.at[i, "clave"]] = _VISOR_SIN
                        st.session_state.pop("visor_edit_grupos", None)

                    st.caption("Asigna en la tabla, con el botón automático, o con **clic en un "
                               "punto gris del mapa** (va al grupo activo). Los grises son los "
                               "que faltan asignar.")
                    edit_df = pd.DataFrame({
                        "Código": nv["codigo"].astype(str).values,
                        "Tienda": nv["tienda"].values, "Bultos": nv["bultos"].values,
                        "Grupo": [asig[nv.at[i, "clave"]] for i in nv.index]})
                    edited = st.data_editor(
                        edit_df, hide_index=True, use_container_width=True,
                        key="visor_edit_grupos",
                        column_config={
                            "Código": st.column_config.TextColumn(disabled=True),
                            "Tienda": st.column_config.TextColumn(disabled=True),
                            "Bultos": st.column_config.NumberColumn(disabled=True),
                            "Grupo": st.column_config.SelectboxColumn(
                                "Grupo", options=[_VISOR_SIN] + grupos_base, required=True,
                                help="Elige la ruta o «sin asignar»")})
                    for pos_local, i in enumerate(nv.index):
                        asig[nv.at[i, "clave"]] = str(edited["Grupo"].values[pos_local])

                    nv["cluster"] = [asig[nv.at[i, "clave"]] for i in nv.index]
                    n_pend = int((nv["cluster"] == _VISOR_SIN).sum())

                    # Anexar; asignados al final de su grupo, pendientes en orden 0
                    d = pd.concat([d, nv[d.columns]], ignore_index=True)
                    nuevos_idx = list(d.index[d["nuevo"]])
                    for pos_local, i in enumerate(nv.index):
                        g_idx = nuevos_idx[pos_local]
                        c_a = d.at[g_idx, "cluster"]
                        if c_a == _VISOR_SIN:
                            d.at[g_idx, "orden"] = 0.0
                        else:
                            mx = d[(d["cluster"] == c_a) & (~d["nuevo"])]["orden"].max()
                            d.at[g_idx, "orden"] = (0.0 if pd.isna(mx) else float(mx)) + 1.0
                    for c in nv.loc[nv["cluster"] != _VISOR_SIN, "cluster"].unique():
                        mask = d["cluster"] == c
                        d.loc[mask, "orden"] = d.loc[mask, "orden"].rank(method="first").astype(int)
                    st.success(f"➕ {len(nv)} punto(s) nuevo(s): {len(nv) - n_pend} asignado(s), "
                               f"**{n_pend} sin asignar** (grises en el mapa).")

    # Grupos "reales" (excluye los puntos aún sin asignar)
    clusters = sorted([c for c in d["cluster"].unique() if c != _VISOR_SIN], key=_visor_ckey)
    pend = d[d["cluster"] == _VISOR_SIN]

    # =================================================================
    # PASO ④ — Re-optimizar el orden (opcional, usa OR-Tools)
    # =================================================================
    st.subheader("④ Re-optimizar")
    reopt_on = st.checkbox("🔁 Re-optimizar el orden de visita con OR-Tools",
                           key="visor_reopt")
    if reopt_on:
        grupos_nuevos = sorted(d[d["nuevo"] & (d["cluster"] != _VISOR_SIN)]["cluster"].unique(),
                               key=_visor_ckey)
        r1, r2, r3 = st.columns(3)
        alcance = r1.radio("Qué re-optimizar",
                           ["Solo grupos con puntos nuevos", "Todas las rutas"],
                           key="visor_reopt_alcance")
        motor_lbl = r2.selectbox("Motor",
                                 ["Haversine (rápido, sin internet)",
                                  "OSRM (calles reales, necesita internet)"],
                                 key="visor_reopt_motor")
        tiempo = r3.slider("Segundos de cálculo por ruta", 1, 5, 2, key="visor_reopt_tiempo")
        s1, s2, s3 = st.columns(3)
        hora_salida = s1.time_input("Hora de salida del CD", value=_dt.time(8, 0),
                                    key="visor_reopt_salida")
        servicio_min = s2.number_input("Min. por parada (servicio)", 0, 60, 3,
                                       key="visor_reopt_serv")
        cerrar = s3.checkbox("Cerrar la ruta (volver al CD al final)", value=True,
                             key="visor_reopt_cerrar")
        salida_s = hora_salida.hour * 3600 + hora_salida.minute * 60
        motor = "osrm" if motor_lbl.startswith("OSRM") else "haversine"
        objetivo = grupos_nuevos if alcance.startswith("Solo") else clusters
        if not objetivo:
            st.info("No hay grupos con puntos nuevos. Agrega puntos en el paso ③ "
                    "o elige «Todas las rutas».")
        else:
            if alcance.startswith("Todas") and len(objetivo) > 6:
                st.caption(f"⏳ Re-optimizando {len(objetivo)} rutas × {tiempo}s — puede tardar "
                           f"~{len(objetivo) * tiempo}s la primera vez.")
            payload = tuple(
                (c, tuple((int(i), float(la), float(lo), int(pr))
                          for i, la, lo, pr in zip(
                              d.index[d["cluster"] == c], d.loc[d["cluster"] == c, "lat"],
                              d.loc[d["cluster"] == c, "lon"], d.loc[d["cluster"] == c, "prioridad"])))
                for c in objetivo)
            reopt = _visor_reoptimizar(payload, float(cd_lat), float(cd_lon), motor,
                                       bool(cerrar), int(tiempo), int(salida_s),
                                       int(servicio_min) * 60)
            if reopt:
                for c, info in reopt.items():
                    for idx, pos in info["orden"].items():
                        d.at[idx, "orden"] = pos
                        d.at[idx, "eta"] = info["eta"].get(idx, "")
                km = sum(info["dist_km"] for info in reopt.values())
                st.success(f"✅ Re-optimizada(s) {len(reopt)} ruta(s) desde el CD. "
                           f"Distancia total de esas rutas: {km:.1f} km.")
            else:
                st.warning("No se pudo re-optimizar (revisa el CD o el motor elegido).")

    # =================================================================
    # PASO ⑤ — Ver el mapa
    # =================================================================
    st.subheader("⑤ Mapa")
    c1, c2, c3 = st.columns([2, 1, 1])
    sel = c1.multiselect("Grupos a mostrar", clusters, default=clusters, key="visor_sel")
    estilo = c2.selectbox("Mapa base",
                          ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"],
                          key="visor_estilo")
    nombre_paleta = c3.selectbox("Paleta", ["Bold", "Vivid", "D3", "Light24", "Plotly"],
                                 key="visor_paleta")
    f1, f2, f3 = st.columns([1, 1, 1.6])
    mostrar_trazos = f1.checkbox(
        "🛣️ Mostrar trazos de las rutas", value=(len(clusters) <= 6), key="visor_trazos",
        help="Con muchas rutas los trazos tapan el mapa; apágalo para ver solo los "
             "puntos numerados con el color de su grupo.")
    agrupar_burbujas = f2.checkbox(
        "🫧 Agrupar tiendas en burbujas", value=True, key="visor_burbujas",
        help="Apágalo para ver CADA tienda con el color de su grupo (útil para saber "
             "qué grupos rodean a tus puntos nuevos). Con miles de puntos puede ir lento.")
    buscar = f3.text_input(
        "🔍 Localizar tienda (código o nombre) — solo la muestra, no modifica nada",
        key="visor_buscar", placeholder="Ej.: 6070826014445 o renelita")
    if not sel:
        st.warning("Selecciona al menos un grupo para ver el mapa.")
        return

    # Búsqueda: encuentra coincidencias en TODO el resultado (incluye sin asignar)
    matches = pd.DataFrame()
    if buscar and buscar.strip():
        q = buscar.strip().lower()
        matches = d[d["codigo"].astype(str).str.lower().str.contains(q, regex=False)
                    | d["tienda"].astype(str).str.lower().str.contains(q, regex=False)]
        if matches.empty:
            st.warning(f"🔍 No encontré ninguna tienda que coincida con «{buscar.strip()}».")
        else:
            _lineas = [f"**{r['codigo']}** · {r['tienda']} → Grupo **{r['cluster']}** · "
                       f"orden **#{int(r['orden']) if r['orden'] else '—'}** · "
                       f"ETA {r['eta'] or '—'}"
                       for _, r in matches.head(5).iterrows()]
            extra = f" (y {len(matches) - 5} más…)" if len(matches) > 5 else ""
            st.info(f"🔍 {len(matches)} coincidencia(s):\n\n" + "\n\n".join(_lineas) + extra)
    paleta = {"Bold": px.colors.qualitative.Bold, "Vivid": px.colors.qualitative.Vivid,
              "D3": px.colors.qualitative.D3, "Light24": px.colors.qualitative.Light24,
              "Plotly": px.colors.qualitative.Plotly}[nombre_paleta]
    color_de = {c: paleta[i % len(paleta)] for i, c in enumerate(clusters)}
    dv = d[d["cluster"].isin(sel)]

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("🏪 Asignadas", len(dv))
    k2.metric("🗂️ Grupos", dv["cluster"].nunique())
    k3.metric("📦 Bultos", int(dv["bultos"].sum()))
    k4.metric("🆕 Nuevas", int(dv["nuevo"].sum()))
    k5.metric("🕓 Sin asignar", len(pend))

    MAGENTA = "#E5007A"
    m = folium.Map(location=[d["lat"].mean(), d["lon"].mean()],
                   zoom_start=13, tiles=estilo, control_scale=True)
    Fullscreen(position="topleft", title="Pantalla completa",
               title_cancel="Salir").add_to(m)
    for c in clusters:
        if c not in sel:
            continue
        sub = d[d["cluster"] == c].sort_values("orden")
        color = color_de[c]
        fg = folium.FeatureGroup(name=f"Grupo {c} · {len(sub)} tiendas", show=True)
        pts = sub[["lat", "lon"]].values.tolist()
        linea = ([[cd_lat, cd_lon]] + pts + [[cd_lat, cd_lon]]) if usar_cd else pts
        if mostrar_trazos and len(linea) >= 2:
            folium.PolyLine(linea, color=color, weight=4, opacity=0.85).add_to(fg)
        # Tiendas EXISTENTES agrupadas en clúster (aligera el mapa); las NUEVAS,
        # en magenta y siempre visibles por encima. Con burbujas apagadas, cada
        # tienda se dibuja directa con el color de su grupo.
        if agrupar_burbujas:
            cluster_exist = MarkerCluster(
                options={"maxClusterRadius": 42, "disableClusteringAtZoom": 16},
                control=False, show=True).add_to(fg)
        else:
            cluster_exist = fg
        for _, r in sub.iterrows():
            num = int(r["orden"]) if r["orden"] else 0
            es_nuevo = bool(r["nuevo"]); prio = int(r["prioridad"]) > 0
            fill = MAGENTA if es_nuevo else color
            borde = "white" if es_nuevo else ("#FFD700" if prio else "white")
            destino = fg if es_nuevo else cluster_exist
            popup = folium.Popup(
                f"<div style='font-family:Arial;font-size:13px;min-width:190px'>"
                f"{'🆕 ' if es_nuevo else ''}<b>{r['tienda']}</b><br>Código: {r['codigo']}<br>"
                f"Distrito: {r['distrito']}<br>Bultos: {int(r['bultos'])}<br>"
                f"🕐 Llegada: <b>{r['eta'] or '—'}</b><br>Grupo: {c} · Orden: <b>#{num}</b><br>"
                f"Lat: {r['lat']:.5f} · Lon: {r['lon']:.5f}</div>", max_width=260)
            tip = ("🆕 " if es_nuevo else "") + ("⭐ " if prio else "") + f"{r['tienda']} · #{num}"
            if num:
                sz = 28 if es_nuevo else 24
                folium.Marker(
                    [r["lat"], r["lon"]],
                    icon=folium.DivIcon(
                        icon_size=(sz + 4, sz + 4), icon_anchor=((sz + 4) // 2, (sz + 4) // 2),
                        html=(f"<div style='background:{fill};border:3px solid {borde};"
                              f"border-radius:50%;width:{sz}px;height:{sz}px;display:flex;"
                              f"align-items:center;justify-content:center;color:white;"
                              f"font-weight:bold;font-size:11px;font-family:Arial;"
                              f"box-shadow:0 1px 4px rgba(0,0,0,.5)'>{num}</div>")),
                    tooltip=tip, popup=popup).add_to(destino)
            else:
                folium.CircleMarker(
                    [r["lat"], r["lon"]], radius=7 if es_nuevo else 6, color=borde,
                    weight=2 if es_nuevo else 1.5, fill=True, fill_color=fill,
                    fill_opacity=0.95, tooltip=tip, popup=popup).add_to(destino)
        fg.add_to(m)

    # Capa de PENDIENTES (sin asignar): gris, siempre visible y clicable
    if len(pend):
        fg_pend = folium.FeatureGroup(name=f"🕓 Sin asignar · {len(pend)}", show=True)
        for _, r in pend.iterrows():
            folium.CircleMarker(
                [r["lat"], r["lon"]], radius=9, color="#37474F", weight=2,
                fill=True, fill_color="#B0BEC5", fill_opacity=0.97,
                tooltip=f"🕓 SIN ASIGNAR · {r['tienda']} · cód {r['codigo']} "
                        f"— clic para asignar al grupo activo",
                popup=folium.Popup(
                    f"<div style='font-family:Arial;font-size:13px;min-width:200px'>"
                    f"🕓 <b>{r['tienda']}</b> — <b>SIN ASIGNAR</b><br>"
                    f"Código: {r['codigo']}<br>Bultos: {int(r['bultos'])}<br>"
                    f"<b>Clic aquí para asignarlo al grupo activo"
                    f"{'' if grupo_activo is None else ' (' + str(grupo_activo) + ')'}</b></div>",
                    max_width=260)).add_to(fg_pend)
        fg_pend.add_to(m)

    if usar_cd:
        folium.Marker(
            [cd_lat, cd_lon],
            icon=folium.Icon(color="black", icon="industry", prefix="fa"),
            tooltip="🏭 Centro de Distribución",
            popup=folium.Popup(f"<b>🏭 Centro de Distribución</b><br>"
                               f"Lat: {cd_lat:.5f}<br>Lon: {cd_lon:.5f}", max_width=220)
        ).add_to(m)

    # Resaltado de búsqueda: anillo rojo pulsante sobre cada coincidencia
    # (solo visual, no modifica la asignación).
    if not matches.empty:
        _pulso = (
            "<style>@keyframes vpulso{0%{transform:scale(.55);opacity:1}"
            "100%{transform:scale(1.9);opacity:0}}</style>"
            "<div style='position:relative;width:46px;height:46px'>"
            "<div style='position:absolute;inset:0;border:4px solid #FF1744;"
            "border-radius:50%;animation:vpulso 1.1s ease-out infinite'></div>"
            "<div style='position:absolute;inset:13px;border:3px solid #FF1744;"
            "border-radius:50%'></div></div>")
        for _, r in matches.head(30).iterrows():
            folium.Marker(
                [r["lat"], r["lon"]],
                icon=folium.DivIcon(icon_size=(46, 46), icon_anchor=(23, 23), html=_pulso),
                tooltip=f"🔍 {r['tienda']} · cód {r['codigo']} · Grupo {r['cluster']} · "
                        f"#{int(r['orden']) if r['orden'] else '—'}",
                z_index_offset=10000).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    try:
        if not matches.empty:
            # Centrar el mapa en lo buscado (con margen para ver el contexto)
            mlat, mlon = matches["lat"], matches["lon"]
            pad = 0.004 if len(matches) == 1 else 0.001
            m.fit_bounds([[mlat.min() - pad, mlon.min() - pad],
                          [mlat.max() + pad, mlon.max() + pad]])
        else:
            lats_b = list(dv["lat"]) + list(pend["lat"]) + ([cd_lat] if usar_cd else [])
            lons_b = list(dv["lon"]) + list(pend["lon"]) + ([cd_lon] if usar_cd else [])
            m.fit_bounds([[min(lats_b), min(lons_b)], [max(lats_b), max(lons_b)]])
    except Exception:
        pass
    # Si hay búsqueda activa, forzar centro/zoom hacia lo encontrado (st_folium
    # conserva la vista anterior entre reruns; center/zoom la sobreescriben).
    _kw = {}
    if not matches.empty:
        _kw = {"center": (float(matches["lat"].mean()), float(matches["lon"].mean())),
               "zoom": 16 if len(matches) == 1 else 14}
    salida = st_folium(m, height=620, use_container_width=True,
                       returned_objects=["last_object_clicked"], key="visor_map", **_kw)

    # Clic en un punto GRIS (sin asignar) -> asignarlo al grupo activo
    clic = (salida or {}).get("last_object_clicked")
    if clic and grupo_activo is not None and len(pend):
        kkey = (round(float(clic["lat"]), 6), round(float(clic["lng"]), 6))
        if st.session_state.get("visor_last_click") != kkey:
            st.session_state["visor_last_click"] = kkey
            match = pend[(pend["lat"].round(6) == kkey[0]) & (pend["lon"].round(6) == kkey[1])]
            if not match.empty:
                row = match.iloc[0]
                st.session_state["visor_asig"][
                    _visor_clave(row["codigo"], row["lat"], row["lon"])] = grupo_activo
                st.session_state.pop("visor_edit_grupos", None)
                st.rerun()

    # =================================================================
    # PASO ⑥ — Resumen, detalle y descarga del resultado actualizado
    # =================================================================
    dv_ord = dv.sort_values(["cluster", "orden"])
    resumen = (dv_ord.groupby("cluster")
               .agg(Tiendas=("tienda", "size"), Nuevos=("nuevo", "sum"),
                    Bultos=("bultos", "sum"), ETA_inicio=("eta", "first"),
                    ETA_fin=("eta", "last"))
               .reindex([c for c in clusters if c in sel]).reset_index()
               .rename(columns={"cluster": "Grupo", "ETA_inicio": "ETA inicio",
                                "ETA_fin": "ETA fin"}))
    st.markdown("#### Resumen por grupo")
    st.dataframe(resumen, use_container_width=True, hide_index=True)
    with st.expander("📋 Ver detalle completo (todas las tiendas)"):
        st.dataframe(
            dv_ord.rename(columns={
                "cluster": "Grupo", "orden": "Orden", "tienda": "Tienda",
                "codigo": "Código", "distrito": "Distrito", "bultos": "Bultos",
                "prioridad": "Prioridad", "eta": "Llegada (ETA)", "nuevo": "Nuevo",
                "lat": "Latitud", "lon": "Longitud"}),
            use_container_width=True, hide_index=True)

    d2 = d.sort_values(["cluster", "orden"])
    export = pd.DataFrame({
        "Cluster": d2["cluster"].replace(_VISOR_SIN, ""), "Orden": d2["orden"].astype(int),
        "Código": d2["codigo"], "Tienda": d2["tienda"], "Distrito": d2["distrito"],
        "Bultos": d2["bultos"].astype(int), "Prioridad": d2["prioridad"].astype(int),
        "Llegada (ETA)": d2["eta"], "Latitud": d2["lat"].round(6),
        "Longitud": d2["lon"].round(6)})
    st.download_button(
        "⬇️ Descargar resultado actualizado (CSV)",
        data=export.to_csv(index=False).encode("utf-8"),
        file_name="ruteo_actualizado.csv", mime="text/csv",
        help="Guárdalo y vuelve a subirlo aquí para seguir agregando puntos más adelante.")


# ===========================================================
# NAVEGACIÓN — Ruteo / Conversor / Visor de resultados
# Selector tipo pestañas arriba. Con st.stop() en los modos que no son Ruteo
# evitamos ejecutar todo el pipeline de ruteo cuando no se necesita.
# ===========================================================
_NAV_RUTEO = "🚛 Ruteo y clustering"
_NAV_CONV = "🌎 Conversor direcciones ↔ coordenadas"
_NAV_VISOR = "📤 Ver resultado guardado"
_opciones_nav = [_NAV_RUTEO]
if CONVERSOR_DISPONIBLE:
    _opciones_nav.append(_NAV_CONV)
_opciones_nav.append(_NAV_VISOR)
if len(_opciones_nav) > 1:
    try:
        _nav = st.segmented_control(
            "Navegación", _opciones_nav, default=_NAV_RUTEO,
            label_visibility="collapsed")
    except Exception:
        _nav = st.radio("Navegación", _opciones_nav, horizontal=True,
                        label_visibility="collapsed")
    if _nav == _NAV_CONV:
        render_conversor()
        st.stop()
    # El Visor (_NAV_VISOR) se ejecuta más abajo, después de definir las
    # funciones de ruteo que usa para re-optimizar (rutear_cluster_ortools).

# ===========================================================
# FUNCIONES — GEOGRAFÍA
# ===========================================================
def proyectar_metros(lats, lons):
    """Proyección equirectangular local: convierte lat/lon a coordenadas (x, y)
    en METROS. Así 1 unidad = 1 metro en cualquier dirección y el clustering
    agrupa por distancia geográfica real (StandardScaler distorsionaba esto)."""
    lat0 = np.radians(np.mean(lats))
    x = np.radians(np.asarray(lons, dtype=float)) * R_TIERRA * np.cos(lat0)
    y = np.radians(np.asarray(lats, dtype=float)) * R_TIERRA
    return np.column_stack([x, y])


def matriz_haversine(coords_latlon):
    """Matriz n x n de distancias haversine en metros (vectorizada).
    coords_latlon: array (n, 2) con columnas [latitud, longitud]."""
    lat = np.radians(coords_latlon[:, 0])[:, None]
    lon = np.radians(coords_latlon[:, 1])[:, None]
    dlat = lat - lat.T
    dlon = lon - lon.T
    a = np.sin(dlat / 2) ** 2 + np.cos(lat) * np.cos(lat.T) * np.sin(dlon / 2) ** 2
    return 2 * R_TIERRA * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def puntos_en_poligono(lats, lons, poligono_lonlat):
    """Ray casting vectorizado: True por cada punto (lat, lon) dentro del
    polígono. ``poligono_lonlat`` viene del GeoJSON de Leaflet.draw como
    [[lon, lat], ...] (anillo exterior)."""
    poly = np.asarray(poligono_lonlat, dtype=float)
    px, py = poly[:, 0], poly[:, 1]                     # lon, lat de vértices
    x = np.asarray(lons, dtype=float)
    y = np.asarray(lats, dtype=float)
    dentro = np.zeros(x.shape, dtype=bool)
    j = len(poly) - 1
    for i in range(len(poly)):
        cruza = ((py[i] > y) != (py[j] > y)) & (
            x < (px[j] - px[i]) * (y - py[i]) / (py[j] - py[i] + 1e-300) + px[i])
        dentro ^= cruza
        j = i
    return dentro


# ===========================================================
# FUNCIONES — TIEMPO (ventanas horarias, ETAs, hojas de ruta)
# ===========================================================
def hora_a_segundos(v):
    """Convierte una hora a segundos desde medianoche. Acepta 'HH:MM', '8:30',
    objetos time/datetime de Excel, horas decimales (8.5) o fracción de día
    de Excel (0.354). Devuelve None si está vacío o no se puede interpretar."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, _dt.time) or isinstance(v, _dt.datetime):
        return v.hour * 3600 + v.minute * 60
    if isinstance(v, str):
        try:
            partes = v.strip().replace(".", ":").split(":")
            h = int(partes[0])
            m = int(partes[1]) if len(partes) > 1 else 0
            if 0 <= h <= 24 and 0 <= m < 60:
                return h * 3600 + m * 60
        except (ValueError, IndexError):
            pass
        return None
    try:
        f = float(v)
        if 0 < f < 1:          # fracción de día (formato interno de Excel)
            return int(f * 86400)
        if 0 <= f <= 24:       # horas decimales
            return int(f * 3600)
    except (TypeError, ValueError):
        pass
    return None


def segundos_a_hora(s):
    """Segundos desde medianoche -> 'HH:MM' (o '—' si no hay dato)."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return "—"
    s = int(s)
    return f"{(s // 3600) % 24:02d}:{(s % 3600) // 60:02d}"


def simular_etas(secuencia, dur_s, servicio_s, salida_s):
    """Simula los horarios de una ruta siguiendo `secuencia` de nodos (0 = CD).
    Devuelve ({nodo: hora_llegada_s}, hora_fin_s). La hora de fin incluye el
    retorno al CD si la secuencia termina en 0."""
    t = float(salida_s)
    llegadas = {}
    prev = secuencia[0]
    for nodo in secuencia[1:]:
        t += float(dur_s[prev][nodo])
        if nodo != 0:
            llegadas[nodo] = t
            t += float(servicio_s[nodo])
        prev = nodo
    return llegadas, t


def resolver_tsp_tiempo(dur_s, servicio_s, ventanas, salida_s, jornada_s,
                        cerrado=True, tiempo_seg=3):
    """TSP con DIMENSIÓN DE TIEMPO en OR-Tools: respeta ventanas horarias por
    tienda, suma el tiempo de servicio y limita la jornada. Nodo 0 = CD.
    ventanas[i] = (ini_s, fin_s) o None. Devuelve (orden, llegadas, fin_s)
    o None si las ventanas son imposibles de cumplir."""
    n = len(dur_s)
    M = [[int(round(v)) for v in fila] for fila in np.asarray(dur_s)]
    serv = [int(round(s)) for s in servicio_s]
    if cerrado:
        manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    else:
        for fila in M:
            fila.append(0)
        M.append([0] * (n + 1))
        serv.append(0)
        manager = pywrapcp.RoutingIndexManager(n + 1, 1, [0], [n])
    routing = pywrapcp.RoutingModel(manager)

    def transito(i, j):
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        return (M[a][b] if a < n and b <= n else 0) + (serv[a] if a < n else 0)

    cb = routing.RegisterTransitCallback(transito)
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    horizonte = int(salida_s + (jornada_s if jornada_s > 0 else 24 * 3600))
    routing.AddDimension(cb, 24 * 3600, max(horizonte, int(salida_s) + 60), False, "Tiempo")
    dim = routing.GetDimensionOrDie("Tiempo")
    dim.CumulVar(routing.Start(0)).SetRange(int(salida_s), int(salida_s))
    for nodo in range(1, n):
        v = ventanas[nodo]
        if v is not None:
            ini, fin = int(v[0]), int(v[1])
            if fin <= ini:
                continue
            dim.CumulVar(manager.NodeToIndex(nodo)).SetRange(ini, fin)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(int(tiempo_seg))
    sol = routing.SolveWithParameters(params)
    if sol is None:
        return None
    orden, llegadas = [], {}
    idx = routing.Start(0)
    while not routing.IsEnd(idx):
        nodo = manager.IndexToNode(idx)
        if nodo < n:
            orden.append(nodo)
            if nodo != 0:
                llegadas[nodo] = sol.Value(dim.CumulVar(idx))
        idx = sol.Value(routing.NextVar(idx))
    fin_s = sol.Value(dim.CumulVar(idx))
    return orden, llegadas, fin_s


def links_google_maps(coords_orden):
    """Links de Google Maps con las paradas en orden de visita. Google acepta
    ~10 puntos por link, así que se generan tramos con un punto de empalme."""
    links = []
    paso = 10
    coords = list(coords_orden)
    i = 0
    while i < len(coords) - 1:
        tramo = coords[i:i + paso]
        if len(tramo) >= 2:
            path = "/".join(f"{lat:.6f},{lon:.6f}" for lat, lon in tramo)
            links.append(f"https://www.google.com/maps/dir/{path}")
        i += paso - 1
    return links


def link_waze(lat, lon):
    return f"https://waze.com/ul?ll={lat:.6f},{lon:.6f}&navigate=yes"


# ===========================================================
# FUNCIONES — GOOGLE SHEETS (app de choferes en AppSheet)
# ===========================================================
RUTAS_HEADERS = ["id_ruta", "id_despacho", "fecha", "cluster", "vehiculo", "vuelta",
                 "conductor", "salida_programada", "fin_estimado", "distancia_km",
                 "duracion_min", "costo", "tiendas", "bultos", "estado", "link_maps"]
PARADAS_HEADERS = ["id_parada", "id_ruta", "orden", "codigo_sucursal", "tienda",
                   "distrito", "bultos", "prioridad", "eta", "ventana", "ubicacion",
                   "latitud", "longitud", "link_waze", "estado_entrega",
                   "hora_entrega", "foto_entrega", "gps_entrega", "observaciones"]
HISTORIAL_HEADERS = ["id_despacho", "fecha", "hora", "creado_por", "modo", "criterio",
                     "rutas", "tiendas", "bultos", "km_total", "duracion_min_total",
                     "costo_total", "motor", "sin_asignar"]


def leer_secret(clave, defecto=""):
    """Lee un secret de Streamlit sin romper la app si no hay secrets.toml."""
    try:
        return st.secrets.get(clave, defecto)
    except Exception:
        return defecto


def extraer_id_hoja(url_o_id):
    """Acepta la URL completa de Google Sheets o solo el ID."""
    import re
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url_o_id)
    return m.group(1) if m else url_o_id.strip()


@st.cache_resource(show_spinner=False)
def conectar_gsheets():
    """Cliente de Google Sheets autenticado con la cuenta de servicio
    guardada en los secrets de Streamlit ([gcp_service_account])."""
    creds = GCredentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"],
    )
    return gspread.authorize(creds)


def asegurar_pestana(libro, nombre, encabezados):
    """Devuelve la pestaña `nombre`; la crea con encabezados si no existe."""
    try:
        ws = libro.worksheet(nombre)
    except gspread.WorksheetNotFound:
        ws = libro.add_worksheet(title=nombre, rows=2000, cols=len(encabezados) + 2)
        ws.append_row(encabezados, value_input_option="USER_ENTERED")
        return ws
    if not ws.row_values(1):
        ws.append_row(encabezados, value_input_option="USER_ENTERED")
    return ws


@st.cache_data(ttl=120, show_spinner="Leyendo historial de Google Sheets...")
def leer_pestana(url_o_id, nombre):
    """Lee una pestaña de la hoja y la devuelve como DataFrame (caché 2 min).
    Devuelve DataFrame vacío si la pestaña no existe todavía."""
    gc = conectar_gsheets()
    libro = gc.open_by_key(extraer_id_hoja(url_o_id))
    try:
        ws = libro.worksheet(nombre)
    except gspread.WorksheetNotFound:
        return pd.DataFrame()
    return pd.DataFrame(ws.get_all_records())


# ===========================================================
# FUNCIONES — CLUSTERING
# ===========================================================
def kmeans_balanceado(Xm, k, capacidad, pesos=None, seed=42, n_iter=15):
    """K-Means con restricción de capacidad. `capacidad` puede ser un máximo de
    TIENDAS (pesos = None -> cada tienda pesa 1) o un máximo de BULTOS
    (pesos = bultos de cada tienda). Heurística tipo 'balanced k-means':
    en cada iteración los puntos se asignan por orden de urgencia al cluster
    más cercano que aún tenga cupo. Escala bien a miles de puntos.
    Devuelve (labels, hubo_sobrecupo)."""
    n = len(Xm)
    if pesos is None:
        pesos = np.ones(n)
    pesos = np.asarray(pesos, dtype=float)
    base = MiniBatchKMeans(n_clusters=k, random_state=seed, n_init=10).fit(Xm)
    centros = base.cluster_centers_.copy()
    labels = np.full(n, -1)
    sobrecupo = False
    for _ in range(n_iter):
        D = pairwise_distances(Xm, centros)
        if k >= 2:
            mejores2 = np.partition(D, 1, axis=1)
            orden_puntos = np.argsort(mejores2[:, 0] - mejores2[:, 1])
        else:
            orden_puntos = np.arange(n)
        nuevo = np.full(n, -1)
        carga = np.zeros(k, dtype=float)
        sobrecupo = False
        for p in orden_puntos:
            colocado = False
            for c in np.argsort(D[p]):
                if carga[c] + pesos[p] <= capacidad:
                    nuevo[p] = c
                    carga[c] += pesos[p]
                    colocado = True
                    break
            if not colocado:
                # ningún cluster tiene cupo exacto: usar el de mayor cupo libre
                c = int(np.argmin(carga + pesos[p]))
                nuevo[p] = c
                carga[c] += pesos[p]
                sobrecupo = True
        if np.array_equal(nuevo, labels):
            break
        labels = nuevo
        for c in range(k):
            mask = labels == c
            if mask.any():
                centros[c] = Xm[mask].mean(axis=0)
    # Pulido: corrige asignaciones lejanas mediante movimientos e intercambios
    labels = _refinar_intercambios(Xm, labels, np.full(k, float(capacidad)),
                                   np.full(k, n + 1), pesos)
    return labels, sobrecupo


def _refinar_intercambios(Xm_sub, labels, caps, maxt, pesos_sub, n_pasadas=4):
    """Pulido local de la asignación: mueve o INTERCAMBIA tiendas entre grupos
    cuando eso reduce la distancia total sin violar capacidades. Corrige las
    asignaciones 'lejanas' que deja el empaque cuando los grupos van muy llenos."""
    labels = labels.copy()
    k = len(caps)
    for _ in range(n_pasadas):
        centros = np.vstack([
            Xm_sub[labels == c].mean(axis=0) if (labels == c).any()
            else np.full(Xm_sub.shape[1], 1e12) for c in range(k)
        ])
        D = pairwise_distances(Xm_sub, centros)
        carga = np.array([pesos_sub[labels == c].sum() for c in range(k)])
        cuenta = np.array([(labels == c).sum() for c in range(k)])
        asignados = np.where(labels >= 0)[0]
        if len(asignados) == 0:
            break
        regret = D[asignados, labels[asignados]] - D[asignados].min(axis=1)
        orden = asignados[np.argsort(-regret)]
        mejorado = False
        for p in orden:
            c_act = labels[p]
            for c_new in np.argsort(D[p])[:6]:
                if c_new == c_act:
                    break  # su grupo ya es el más cercano disponible
                ganancia_mov = D[p, c_act] - D[p, c_new]
                if ganancia_mov <= 1e-9:
                    break
                # 1) mover directo si el grupo cercano tiene cupo
                if carga[c_new] + pesos_sub[p] <= caps[c_new] and cuenta[c_new] < maxt[c_new]:
                    labels[p] = c_new
                    carga[c_act] -= pesos_sub[p]; carga[c_new] += pesos_sub[p]
                    cuenta[c_act] -= 1; cuenta[c_new] += 1
                    mejorado = True
                    break
                # 2) intercambiar con una tienda de ese grupo que prefiera el mío
                idx_new = np.where(labels == c_new)[0]
                if len(idx_new) == 0:
                    continue
                delta_q = D[idx_new, c_act] - D[idx_new, c_new]
                viable = ((carga[c_new] - pesos_sub[idx_new] + pesos_sub[p] <= caps[c_new])
                          & (carga[c_act] - pesos_sub[p] + pesos_sub[idx_new] <= caps[c_act])
                          & (delta_q < ganancia_mov - 1e-9))
                cand = np.where(viable)[0]
                if len(cand):
                    q = idx_new[cand[np.argmin(delta_q[cand])]]
                    labels[p], labels[q] = c_new, c_act
                    carga[c_act] += pesos_sub[q] - pesos_sub[p]
                    carga[c_new] += pesos_sub[p] - pesos_sub[q]
                    mejorado = True
                    break
        if not mejorado:
            break
    return labels


def _asignar_vehiculos(Xm_sub, pesos_sub, prio_sub, vehiculos, seed=42, n_iter=12):
    """Balanced k-means con capacidades HETEROGÉNEAS (una por vehículo).
    vehiculos: lista de (capacidad_bultos, max_tiendas); max_tiendas=0 -> sin límite.
    Los vehículos más grandes se asignan a las zonas con más demanda.
    Las tiendas PRIORITARIAS se colocan primero (si falta cupo, quedan fuera
    las normales). Devuelve labels locales; -1 = sin cupo en esta pasada."""
    n = len(Xm_sub)
    k = len(vehiculos)
    base = MiniBatchKMeans(n_clusters=k, random_state=seed, n_init=10).fit(Xm_sub)
    centros = base.cluster_centers_.copy()
    demanda_ini = np.array([pesos_sub[base.labels_ == c].sum() for c in range(k)])
    veh_orden = sorted(vehiculos, key=lambda t: -t[0])
    caps = np.zeros(k)
    maxt = np.zeros(k, dtype=int)
    veh_por_cluster = [None] * k  # qué vehículo real atiende cada cluster
    for rank, c in enumerate(np.argsort(-demanda_ini)):
        caps[c] = veh_orden[rank][0]
        maxt[c] = veh_orden[rank][1] if veh_orden[rank][1] > 0 else n
        veh_por_cluster[c] = veh_orden[rank]
    nivel = np.where(prio_sub > 0, prio_sub, 99)  # prioridad 1 va primero; 0 = normal al final
    labels = np.full(n, -1)
    for _ in range(n_iter):
        D = pairwise_distances(Xm_sub, centros)
        if k >= 2:
            mejores2 = np.partition(D, 1, axis=1)
            urgencia = mejores2[:, 0] - mejores2[:, 1]
        else:
            urgencia = D[:, 0]
        orden_puntos = np.lexsort((urgencia, nivel))
        nuevo = np.full(n, -1)
        carga = np.zeros(k)
        cuenta = np.zeros(k, dtype=int)
        for p in orden_puntos:
            for c in np.argsort(D[p]):
                if carga[c] + pesos_sub[p] <= caps[c] and cuenta[c] < maxt[c]:
                    nuevo[p] = c
                    carga[c] += pesos_sub[p]
                    cuenta[c] += 1
                    break
        if np.array_equal(nuevo, labels):
            break
        labels = nuevo
        for c in range(k):
            mask = labels == c
            if mask.any():
                centros[c] = Xm_sub[mask].mean(axis=0)

    # Pulido: corrige asignaciones lejanas mediante movimientos e intercambios
    labels = _refinar_intercambios(Xm_sub, labels, caps, maxt, pesos_sub)

    # Intentar colocar pendientes en el cupo que liberó el pulido (prioritarias primero)
    pendientes = np.where(labels < 0)[0]
    if len(pendientes):
        centros = np.vstack([
            Xm_sub[labels == c].mean(axis=0) if (labels == c).any()
            else np.full(Xm_sub.shape[1], 1e12) for c in range(k)
        ])
        D = pairwise_distances(Xm_sub, centros)
        carga = np.array([pesos_sub[labels == c].sum() for c in range(k)])
        cuenta = np.array([(labels == c).sum() for c in range(k)])
        for p in pendientes[np.argsort(nivel[pendientes])]:
            for c in np.argsort(D[p]):
                if carga[c] + pesos_sub[p] <= caps[c] and cuenta[c] < maxt[c]:
                    labels[p] = c
                    carga[c] += pesos_sub[p]
                    cuenta[c] += 1
                    break
    return labels, veh_por_cluster


def _fusionar_clusters(Xm_all, labels, info, pesos_all):
    """Consolidación de rutas: si dos grupos VECINOS caben completos en uno de
    sus dos vehículos (bultos y máx. tiendas), se fusionan en una sola ruta.
    Elimina rutas fragmentadas con vehículos medio vacíos en zonas dispersas
    y libera vehículos. Se repite hasta que ninguna fusión sea factible."""
    labels = labels.copy()
    info = {r: dict(v) for r, v in info.items()}
    while len(info) >= 2:
        ids = sorted(info.keys())
        centros = np.vstack([Xm_all[labels == r].mean(axis=0) for r in ids])
        carga = np.array([pesos_all[labels == r].sum() for r in ids])
        cuenta = np.array([(labels == r).sum() for r in ids])
        Dc = pairwise_distances(centros)
        np.fill_diagonal(Dc, np.inf)
        mejor = None  # (distancia, i, j, índice del vehículo destino)
        for i in range(len(ids)):
            for j in np.argsort(Dc[i])[:2]:  # solo sus 2 vecinos más cercanos
                j = int(j)
                if mejor is not None and Dc[i, j] >= mejor[0]:
                    continue
                # ¿caben juntos? probar primero el vehículo más pequeño de los dos
                for d_idx in sorted((i, j), key=lambda t: info[ids[t]]["capacidad"]):
                    cap_d = info[ids[d_idx]]["capacidad"]
                    mt_d = info[ids[d_idx]]["max_tiendas"] or 10 ** 9
                    if carga[i] + carga[j] <= cap_d and cuenta[i] + cuenta[j] <= mt_d:
                        mejor = (Dc[i, j], i, j, d_idx)
                        break
        if mejor is None:
            break
        _, i, j, d_idx = mejor
        destino = ids[d_idx]
        origen = ids[j] if d_idx == i else ids[i]
        labels[labels == origen] = destino
        del info[origen]
    # reindexar rutas como 0..k-1
    ids = sorted(info.keys())
    mapa = {viejo: nuevo for nuevo, viejo in enumerate(ids)}
    labels_out = labels.copy()
    for viejo, nuevo in mapa.items():
        labels_out[labels == viejo] = nuevo
    return labels_out, {mapa[v]: info[v] for v in ids}


def asignar_flota(Xm_all, pesos_all, prio_all, flota, max_vueltas, usar_holgura=True, seed=42):
    """Asigna tiendas a una flota heterogénea por vueltas.
    flota: tupla de (capacidad_bultos, max_tiendas) por vehículo disponible.
    En cada vuelta se usan los vehículos mínimos necesarios (se agregan más si
    la geografía no permite empacar); lo que no entra pasa a la siguiente vuelta.
    Devuelve (labels, info): labels[i] = id de ruta o -1 (no asignada);
    info[ruta] = {'capacidad', 'max_tiendas', 'vuelta'}."""
    n = len(Xm_all)
    labels_global = np.full(n, -1)
    info = {}
    siguiente = 0
    pendientes = np.arange(n)
    flota_orden = sorted(flota, key=lambda t: -t[0])
    max_cap = flota_orden[0][0]
    for vuelta in range(1, max_vueltas + 1):
        # tiendas imposibles: su pedido excede al vehículo más grande
        posibles = pendientes[pesos_all[pendientes] <= max_cap]
        if len(posibles) == 0:
            break
        demanda = float(pesos_all[posibles].sum())
        usados = []
        cap_acum, cupo_tiendas = 0.0, 0
        for cap, mt in flota_orden:
            if cap_acum >= demanda and cupo_tiendas >= len(posibles):
                break
            usados.append((cap, mt))
            cap_acum += cap
            cupo_tiendas += mt if mt > 0 else len(posibles)
        if usar_holgura:
            # ~30% más de vehículos que el mínimo: grupos al ~75-85% de llenado
            # producen zonas geográficas mucho más compactas y sin cruces
            extra = math.ceil(len(usados) * 0.3)
            for cap, mt in flota_orden[len(usados):len(usados) + extra]:
                usados.append((cap, mt))
        sub_labels = np.full(len(posibles), -1)
        veh_cluster = []
        for _ in range(9):  # si el empaque no cierra, sumar vehículos de la flota
            usados = usados[:max(1, min(len(usados), len(posibles)))]
            sub_labels, veh_cluster = _asignar_vehiculos(
                Xm_all[posibles], pesos_all[posibles],
                prio_all[posibles], usados, seed)
            if (sub_labels < 0).sum() == 0 or len(usados) >= len(flota_orden) \
                    or len(usados) >= len(posibles):
                break
            usados.append(flota_orden[len(usados)])
        for c in range(len(veh_cluster)):
            mask_c = sub_labels == c
            if not mask_c.any():
                continue
            labels_global[posibles[mask_c]] = siguiente
            info[siguiente] = {"capacidad": int(veh_cluster[c][0]),
                               "max_tiendas": int(veh_cluster[c][1]), "vuelta": vuelta}
            siguiente += 1
        pendientes = np.where(labels_global < 0)[0]
        if len(pendientes) == 0:
            break
    # Consolidación final: fusionar grupos vecinos que caben en un solo vehículo
    if len(info) >= 2:
        labels_global, info = _fusionar_clusters(Xm_all, labels_global, info, pesos_all)
    return labels_global, info


# ===========================================================
# FUNCIONES — MATRICES DE DISTANCIA (OSRM público, gratis)
# ===========================================================
@st.cache_data(show_spinner=False)
def osrm_tabla(coords_lonlat):
    """Matriz de distancias (m) y duraciones (s) por calles reales usando el
    servicio /table del servidor público de OSRM. Sin API key. Gratis.
    coords_lonlat: tupla de tuplas (lon, lat) — máx ~100 puntos por request."""
    locs = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in coords_lonlat)
    r = requests.get(
        f"{OSRM_BASE}/table/v1/driving/{locs}",
        params={"annotations": "distance,duration"},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM table: {data.get('message', data.get('code'))}")
    dist = np.array(data["distances"], dtype=float)
    dur = np.array(data["durations"], dtype=float)
    # Si algún par no tiene ruta, OSRM devuelve null -> rellenar con haversine
    if np.isnan(dist).any() or np.isnan(dur).any():
        coords_latlon = np.array([(lat, lon) for lon, lat in coords_lonlat])
        H = matriz_haversine(coords_latlon) * 1.4  # factor de rodeo urbano
        dist = np.where(np.isnan(dist), H, dist)
        dur = np.where(np.isnan(dur), H / (VEL_PROMEDIO_KMH / 3.6), dur)
    return dist, dur


@st.cache_data(show_spinner=False)
def osrm_geometria(coords_lonlat_orden):
    """Geometría de la ruta por calles reales (servicio /route de OSRM público).
    Acepta cualquier cantidad de paradas: trocea en tramos de 80 y concatena.
    Devuelve lista de (lat, lon) para dibujar en el mapa."""
    coords = list(coords_lonlat_orden)
    puntos = []
    paso = 80
    tramos = [coords[i:i + paso + 1] for i in range(0, max(len(coords) - 1, 1), paso)]
    for t_idx, tramo in enumerate(tramos):
        if len(tramo) < 2:
            continue
        locs = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in tramo)
        r = requests.get(
            f"{OSRM_BASE}/route/v1/driving/{locs}",
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok":
            raise RuntimeError(f"OSRM route: {data.get('message', data.get('code'))}")
        puntos.extend((lat, lon) for lon, lat in data["routes"][0]["geometry"]["coordinates"])
        if t_idx < len(tramos) - 1:
            time.sleep(0.15)  # cortesía con el servidor público
    return puntos


@st.cache_data(show_spinner=False)
def osrm_ruta_orden(coords_lonlat_orden):
    """Como osrm_geometria, pero además devuelve la distancia (m) y duración (s)
    reales del recorrido siguiendo ese orden exacto de paradas."""
    coords = list(coords_lonlat_orden)
    puntos, dist_total, dur_total = [], 0.0, 0.0
    paso = 80
    tramos = [coords[i:i + paso + 1] for i in range(0, max(len(coords) - 1, 1), paso)]
    for t_idx, tramo in enumerate(tramos):
        if len(tramo) < 2:
            continue
        locs = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in tramo)
        r = requests.get(
            f"{OSRM_BASE}/route/v1/driving/{locs}",
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok":
            raise RuntimeError(f"OSRM route: {data.get('message', data.get('code'))}")
        ruta = data["routes"][0]
        puntos.extend((lat, lon) for lon, lat in ruta["geometry"]["coordinates"])
        dist_total += float(ruta.get("distance", 0))
        dur_total += float(ruta.get("duration", 0))
        if t_idx < len(tramos) - 1:
            time.sleep(0.15)
    return puntos, dist_total, dur_total


def evaluar_orden_personalizado(cluster_data, cd_lat, cd_lon, orden_df, cerrado,
                                servicio_map=None, salida_cd_s=8 * 3600):
    """Recalcula distancia, duración, geometría y ETAs de una ruta siguiendo un
    orden de visita definido por el usuario (lista de índices del DataFrame).
    Intenta calles reales con OSRM; si falla, usa haversine."""
    servicio_map = servicio_map or {}
    paradas = [(float(cluster_data.loc[idx, "latitud"]), float(cluster_data.loc[idx, "longitud"]))
               for idx in orden_df]
    coords = [(cd_lat, cd_lon)] + paradas + ([(cd_lat, cd_lon)] if cerrado else [])
    # duraciones por tramo con haversine (para repartir las ETAs)
    H = matriz_haversine(np.array(coords))
    legs_hav = [float(H[j][j + 1]) / (VEL_PROMEDIO_KMH / 3.6) for j in range(len(coords) - 1)]
    try:
        puntos, dist_m, dur_viaje_s = osrm_ruta_orden(tuple((lon, lat) for lat, lon in coords))
        motor = "✏️ Orden personalizado · OSRM (calles reales)"
        # escalar los tramos haversine para que sumen la duración real de OSRM
        factor = dur_viaje_s / sum(legs_hav) if sum(legs_hav) > 0 else 1.0
        legs = [l * factor for l in legs_hav]
    except Exception:
        dist_m = float(sum(H[j][j + 1] for j in range(len(coords) - 1))) * 1.4
        legs = [l * 1.4 for l in legs_hav]
        puntos = coords
        motor = "✏️ Orden personalizado · Haversine (línea recta)"
    # simular ETAs con tiempo de servicio
    t = float(salida_cd_s)
    etas = {}
    for pos, idx in enumerate(orden_df):
        t += legs[pos]
        etas[idx] = t
        t += float(servicio_map.get(idx, 0))
    if cerrado:
        t += legs[-1]
    fin_s = t
    return {
        "orden": list(orden_df),
        "coords_route": puntos,
        "distance_km": dist_m / 1000.0,
        "duration_min": (fin_s - salida_cd_s) / 60.0,
        "motor": motor,
        "aviso": None,
        "personalizada": True,
        "etas": etas,
        "salida_s": salida_cd_s,
        "fin_s": fin_s,
    }


# ===========================================================
# FUNCIONES — TSP CON OR-TOOLS (local, sin API, sin límites)
# ===========================================================
def resolver_tsp(matriz_m, cerrado=True, tiempo_seg=2):
    """Resuelve el orden óptimo de visita con Google OR-Tools (ejecuta en el
    propio servidor, NO consume ninguna API). El nodo 0 es el CD.
    Para ruta abierta se agrega un nodo fantasma con costo 0 como destino.
    Devuelve la lista de nodos en orden de visita (empieza en 0 = CD)."""
    M = [[int(round(v)) for v in fila] for fila in np.asarray(matriz_m)]
    n = len(M)
    if cerrado:
        manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    else:
        for fila in M:
            fila.append(0)
        M.append([0] * (n + 1))
        manager = pywrapcp.RoutingIndexManager(n + 1, 1, [0], [n])
    routing = pywrapcp.RoutingModel(manager)

    def costo(i, j):
        return M[manager.IndexToNode(i)][manager.IndexToNode(j)]

    transit = routing.RegisterTransitCallback(costo)
    routing.SetArcCostEvaluatorOfAllVehicles(transit)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(int(tiempo_seg))
    solucion = routing.SolveWithParameters(params)
    if solucion is None:
        return None

    orden = []
    idx = routing.Start(0)
    while not routing.IsEnd(idx):
        nodo = manager.IndexToNode(idx)
        if nodo < n:  # excluir nodo fantasma
            orden.append(nodo)
        idx = solucion.Value(routing.NextVar(idx))
    return orden


def rutear_cluster_ortools(cluster_data, cd_lat, cd_lon, motor, cerrado, tiempo_tsp,
                           servicio_s=None, ventanas=None, salida_cd_s=8 * 3600,
                           jornada_max_s=0):
    """Calcula la ruta óptima de un cluster con OR-Tools.
    motor: 'osrm' (calles reales, gratis) o 'haversine' (línea recta, sin internet).
    servicio_s: segundos de servicio por tienda (alineado a cluster_data).
    ventanas: lista de (ini_s, fin_s) o None por tienda. Si hay ventanas, se usa
    el solver con dimensión de tiempo; si no, TSP por distancia + simulación de ETAs."""
    idx_tiendas = list(cluster_data.index)
    coords_latlon = np.vstack([
        [cd_lat, cd_lon],
        cluster_data[["latitud", "longitud"]].values.astype(float),
    ])
    n = len(coords_latlon)
    avisos = []

    usa_osrm = (motor == "osrm") and n <= OSRM_MAX_PUNTOS
    if motor == "osrm" and n > OSRM_MAX_PUNTOS:
        avisos.append(f"{n - 1} tiendas superan el límite del servidor OSRM público "
                      f"({OSRM_MAX_PUNTOS - 1}); se usó distancia haversine en este cluster.")

    if usa_osrm:
        coords_lonlat = tuple((float(lon), float(lat)) for lat, lon in coords_latlon)
        dist_m, dur_s = osrm_tabla(coords_lonlat)
    else:
        dist_m = matriz_haversine(coords_latlon)
        dur_s = dist_m / (VEL_PROMEDIO_KMH / 3.6)

    # Nodo 0 = CD; nodos 1..m = tiendas
    servicio_nodos = [0.0] + ([float(s) for s in servicio_s] if servicio_s is not None
                              else [0.0] * len(idx_tiendas))
    ventanas_nodos = [None] + (list(ventanas) if ventanas is not None
                               else [None] * len(idx_tiendas))
    tiene_ventanas = any(v is not None for v in ventanas_nodos)

    # Prioridades: las tiendas con prioridad 1 se visitan primero, luego 2, ...
    # y al final las normales (prioridad 0).
    if "prioridad" in cluster_data.columns:
        prioridades = cluster_data["prioridad"].astype(int).values
    else:
        prioridades = np.zeros(len(idx_tiendas), dtype=int)
    niveles = sorted({int(p) for p in prioridades if p > 0})

    orden_nodos = None
    llegadas, fin_s = None, None

    if tiene_ventanas:
        # Solver con dimensión de tiempo (ventanas mandan sobre prioridades)
        if niveles:
            avisos.append("Hay ventanas horarias y prioridades en el mismo grupo: "
                          "las ventanas tienen precedencia sobre el orden por prioridad.")
        rt = resolver_tsp_tiempo(dur_s, servicio_nodos, ventanas_nodos,
                                 salida_cd_s, jornada_max_s, cerrado, tiempo_tsp)
        if rt is not None:
            orden_nodos, llegadas, fin_s = rt
        else:
            avisos.append("No fue posible cumplir todas las ventanas horarias de este "
                          "grupo (revisa horas vs. hora de salida del CD); la ruta se "
                          "calculó sin ventanas.")

    if orden_nodos is None:
        # TSP por distancia (con etapas de prioridad si las hay) + simulación de ETAs
        if niveles:
            grupos = [[j + 1 for j, p in enumerate(prioridades) if int(p) == nv] for nv in niveles]
            grupos.append([j + 1 for j, p in enumerate(prioridades) if int(p) == 0])
            dist_arr = np.asarray(dist_m)
            orden_nodos = [0]
            actual = 0
            for grupo in grupos:
                if not grupo:
                    continue
                sub = [actual] + grupo
                orden_sub = resolver_tsp(dist_arr[np.ix_(sub, sub)], cerrado=False,
                                         tiempo_seg=tiempo_tsp)
                if orden_sub is None:
                    return None
                orden_nodos.extend(sub[j] for j in orden_sub[1:])
                actual = orden_nodos[-1]
        else:
            orden_nodos = resolver_tsp(dist_m, cerrado=cerrado, tiempo_seg=tiempo_tsp)
            if orden_nodos is None:
                return None
        secuencia_sim = orden_nodos + ([0] if cerrado else [])
        llegadas, fin_s = simular_etas(secuencia_sim, dur_s, servicio_nodos, salida_cd_s)
        # avisar si la simulación viola alguna ventana
        if tiene_ventanas:
            fuera = sum(1 for nodo, t in llegadas.items()
                        if ventanas_nodos[nodo] is not None
                        and not (ventanas_nodos[nodo][0] <= t <= ventanas_nodos[nodo][1]))
            if fuera:
                avisos.append(f"{fuera} tiendas quedarían fuera de su ventana horaria.")

    secuencia = orden_nodos + ([0] if cerrado else [])
    dist_total = float(sum(dist_m[a][b] for a, b in zip(secuencia[:-1], secuencia[1:])))
    dur_total = float(fin_s - salida_cd_s)
    orden_df = [idx_tiendas[nodo - 1] for nodo in orden_nodos if nodo != 0]
    etas_df = {idx_tiendas[nodo - 1]: t for nodo, t in llegadas.items() if nodo != 0}

    if jornada_max_s > 0 and dur_total > jornada_max_s:
        avisos.append(f"La ruta dura {dur_total / 3600:.1f} h y excede la jornada "
                      f"máxima de {jornada_max_s / 3600:.1f} h: divide el grupo o "
                      f"reduce la capacidad por ruta.")

    coords_orden = [tuple(coords_latlon[nodo]) for nodo in secuencia]
    if usa_osrm:
        try:
            coords_route = osrm_geometria(tuple((lon, lat) for lat, lon in coords_orden))
        except Exception:
            coords_route = coords_orden  # si falla la geometría, línea recta
    else:
        coords_route = coords_orden

    return {
        "orden": orden_df,
        "coords_route": coords_route,
        "distance_km": dist_total / 1000.0,
        "duration_min": dur_total / 60.0,
        "motor": "OR-Tools + OSRM (calles reales)" if usa_osrm else "OR-Tools + Haversine (línea recta)",
        "aviso": " | ".join(avisos) if avisos else None,
        "personalizada": False,
        "etas": etas_df,
        "salida_s": salida_cd_s,
        "fin_s": fin_s,
    }


def calcular_ruta_ors(cd_coord, tiendas_coords, api_key, cerrada=True,
                      servicio_map=None, salida_cd_s=8 * 3600):
    """Motor original: API de optimización de OpenRouteService (HeiGIT).
    Límite del plan gratuito: ~50 tiendas por cluster y 500 requests/día.
    servicio_map: {idx: segundos de servicio} opcional."""
    client = ors.Client(key=api_key)
    servicio_map = servicio_map or {}
    jobs = [optimization.Job(id=int(idx), location=[float(lon), float(lat)],
                             service=int(servicio_map.get(idx, 0)))
            for (lon, lat, idx) in tiendas_coords]
    if cerrada:
        vehicle = optimization.Vehicle(id=1, profile='driving-car', start=cd_coord, end=cd_coord)
    else:
        vehicle = optimization.Vehicle(id=1, profile='driving-car', start=cd_coord)
    result = client.optimization(jobs=jobs, vehicles=[vehicle], geometry=True)
    if not result.get('routes'):
        return None
    route = result['routes'][0]
    decoded = convert.decode_polyline(route['geometry'])
    coords_route = [(lat, lon) for lon, lat in decoded['coordinates']]
    steps = route.get('steps', [])
    orden_visita = [step['id'] for step in steps if step.get('type') == 'job']
    # ETAs: VROOM entrega 'arrival' en segundos relativos al inicio del vehículo
    etas = {step['id']: salida_cd_s + step.get('arrival', 0)
            for step in steps if step.get('type') == 'job'}
    dur_total_s = route.get('duration', 0) + route.get('service', 0)
    return {
        'orden': orden_visita,
        'coords_route': coords_route,
        'distance_km': route.get('distance', 0) / 1000.0,
        'duration_min': dur_total_s / 60.0,
        'motor': 'OpenRouteService (calles reales)',
        'aviso': None,
        'personalizada': False,
        'etas': etas,
        'salida_s': salida_cd_s,
        'fin_s': salida_cd_s + dur_total_s,
    }


# ===========================================================
# FUNCIONES — DATOS Y PLANTILLAS
# ===========================================================
@st.cache_data
def cargar_datos():
    return pd.read_excel("Dataset.xlsx", sheet_name="df")


def _plantilla_df():
    return pd.DataFrame({
        "codigo_sucursal": [101, 102, 103],
        "name_sucursal": ["Tienda Centro Lima", "Tienda Miraflores", "Tienda San Isidro"],
        "distrito": ["Lima", "Miraflores", "San Isidro"],
        "latitud": [-12.046374, -12.119860, -12.097980],
        "longitud": [-77.042793, -77.029350, -77.036430],
        "cantidad_bultos": [12, 8, 15],
        "prioridad": [0, 1, 0],
        "hora_inicio": ["", "09:00", ""],
        "hora_fin": ["", "13:00", ""]
    })


@st.cache_data
def generar_plantilla_excel():
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        _plantilla_df().to_excel(writer, index=False, sheet_name='df')
    return buffer.getvalue()


@st.cache_data
def generar_plantilla_csv():
    return _plantilla_df().to_csv(index=False).encode("utf-8")


# ===========================================================
# VISOR DE RESULTADOS — ejecución
# Se corre aquí (no arriba) porque re-optimiza con rutear_cluster_ortools,
# ya definida. El resultado del re-optimizado se cachea por sus argumentos,
# así cambiar la paleta/vista no lo recalcula.
# ===========================================================
@st.cache_data(show_spinner="Re-optimizando rutas con OR-Tools…")
def _visor_reoptimizar(payload, cd_lat, cd_lon, motor, cerrar, tiempo, salida_s, servicio_uni):
    """payload: tupla ( (grupo, ((idx, lat, lon, prioridad), ...)), ... ).
    servicio_uni: segundos de servicio por parada (para ETAs realistas).
    Devuelve {grupo: {orden:{idx:pos}, eta:{idx:'HH:MM'}, dist_km, dur_min}}."""
    out = {}
    for cluster, filas in payload:
        cdata = pd.DataFrame(
            {"latitud":  [la for (_i, la, _lo, _pr) in filas],
             "longitud": [lo for (_i, _la, lo, _pr) in filas],
             "prioridad":[pr for (_i, _la, _lo, pr) in filas]},
            index=[i for (i, _la, _lo, _pr) in filas])
        serv = [servicio_uni] * len(filas) if servicio_uni else None
        try:
            res = rutear_cluster_ortools(cdata, cd_lat, cd_lon, motor, cerrar,
                                         tiempo, servicio_s=serv, salida_cd_s=salida_s)
        except Exception:
            res = None
        if not res:
            continue
        out[cluster] = {
            "orden": {int(idx): pos + 1 for pos, idx in enumerate(res["orden"])},
            "eta":   {int(idx): segundos_a_hora(res["etas"].get(idx)) for idx in res["orden"]},
            "dist_km": res["distance_km"], "dur_min": res["duration_min"]}
    return out


if _nav == _NAV_VISOR:
    render_visor_resultado()
    st.stop()

# ===========================================================
# SIDEBAR — UPLOAD
# ===========================================================
st.sidebar.markdown(
    "<div class='rt-side-brand'>🏪 <b>Ruteo</b>Tiendas <em>planner</em></div>",
    unsafe_allow_html=True)
st.sidebar.header("📂 Cargar tu propio dataset")

with st.sidebar.expander("📥 Descarga la plantilla", expanded=False):
    st.caption("Edítala con tus tiendas y súbela abajo.")
    st.markdown("""
    | Columna | Ejemplo |
    |---|---|
    | codigo_sucursal | 101 |
    | name_sucursal | Tienda Centro |
    | distrito | Lima |
    | **latitud** ⭐ | -12.046374 |
    | **longitud** ⭐ | -77.042793 |
    | cantidad_bultos | 12 |
    | prioridad | 0, 1, 2... |
    | hora_inicio | 09:00 |
    | hora_fin | 13:00 |

    ⭐ = obligatoria. `cantidad_bultos` (opcional, por defecto 1) permite limitar
    cada ruta por bultos. `prioridad` (opcional): 1 = se visita primero,
    2 = después, ... 0 o vacío = normal. `hora_inicio`/`hora_fin` (opcionales):
    ventana horaria en que la tienda puede recibir — vacío = todo el día.
    """)
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.download_button("📊 Excel", data=generar_plantilla_excel(),
            file_name="plantilla_tiendas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True)
    with col_p2:
        st.download_button("📄 CSV", data=generar_plantilla_csv(),
            file_name="plantilla_tiendas.csv", mime="text/csv", use_container_width=True)

archivo_subido = st.sidebar.file_uploader("Sube un archivo Excel o CSV", type=["xlsx", "xls", "csv"])

if archivo_subido is not None:
    try:
        if archivo_subido.name.endswith(".csv"):
            df = pd.read_csv(archivo_subido)
        else:
            df = pd.read_excel(archivo_subido)
        if not {"latitud", "longitud"}.issubset(df.columns):
            st.sidebar.error("⚠️ Faltan columnas 'latitud' y 'longitud'.")
            st.stop()
        if "codigo_sucursal" not in df.columns:
            df["codigo_sucursal"] = range(1, len(df) + 1)
        if "name_sucursal" not in df.columns:
            df["name_sucursal"] = [f"Tienda {i}" for i in range(1, len(df) + 1)]
        if "distrito" not in df.columns:
            df["distrito"] = "Sin especificar"
        df["latitud"] = pd.to_numeric(df["latitud"], errors="coerce")
        df["longitud"] = pd.to_numeric(df["longitud"], errors="coerce")
        df = df.dropna(subset=["latitud", "longitud"]).reset_index(drop=True)
        # descartar coordenadas inválidas
        df = df[df["latitud"].between(-90, 90) & df["longitud"].between(-180, 180)].reset_index(drop=True)
        if len(df) < 2:
            st.sidebar.error("⚠️ Al menos 2 tiendas válidas.")
            st.stop()
        st.sidebar.success(f"✅ {len(df)} tiendas cargadas")
    except Exception as e:
        st.sidebar.error(f"Error: {e}")
        st.stop()
else:
    df = cargar_datos()
    st.sidebar.info(f"ℹ️ Dataset por defecto ({len(df)} tiendas)")

# Normalizar columnas operativas (aplica al archivo subido y al dataset por defecto)
if "cantidad_bultos" not in df.columns:
    df["cantidad_bultos"] = 1
df["cantidad_bultos"] = (pd.to_numeric(df["cantidad_bultos"], errors="coerce")
                         .fillna(1).clip(lower=1).round().astype(int))
if "prioridad" not in df.columns:
    df["prioridad"] = 0
df["prioridad"] = (pd.to_numeric(df["prioridad"], errors="coerce")
                   .fillna(0).clip(lower=0, upper=9).round().astype(int))
# Ventanas horarias opcionales (hora_inicio / hora_fin -> segundos desde medianoche)
for col in ("hora_inicio", "hora_fin"):
    if col not in df.columns:
        df[col] = None
df["ventana_ini_s"] = df["hora_inicio"].map(hora_a_segundos)
df["ventana_fin_s"] = df["hora_fin"].map(hora_a_segundos)
# si solo dieron una de las dos: completar con inicio/fin del día
solo_ini = df["ventana_ini_s"].notna() & df["ventana_fin_s"].isna()
solo_fin = df["ventana_fin_s"].notna() & df["ventana_ini_s"].isna()
df.loc[solo_ini, "ventana_fin_s"] = 24 * 3600 - 60
df.loc[solo_fin, "ventana_ini_s"] = 0

n_tiendas = len(df)
# Identificador estable del dataset (para caché y validación de rutas)
dataset_id = int(pd.util.hash_pandas_object(
    df[["latitud", "longitud", "cantidad_bultos", "prioridad"]].assign(
        v_ini=df["ventana_ini_s"].fillna(-1), v_fin=df["ventana_fin_s"].fillna(-1))).sum())

st.sidebar.markdown("---")

# ===========================================================
# HEADER — barra de marca
# ===========================================================
st.markdown(f"""
<div class="rt-topbar">
  <div class="rt-brand">
    <div class="rt-logo">🏪</div>
    <div>
      <div class="rt-title">Ruteo<span>Tiendas</span><em>planner</em></div>
      <div class="rt-sub">Agrupación de tiendas por zonas y ruteo óptimo de despacho</div>
    </div>
  </div>
  <div class="rt-meta">
    <span class="rt-pill">👤 {NOMBRE_ALUMNO}</span>
    <span class="rt-pill">✉️ {CODIGO_ISIL}</span>
    <a class="rt-pill" href="{URL_COLAB}" target="_blank">📓 Cuaderno Colab</a>
  </div>
</div>
""", unsafe_allow_html=True)

with st.expander("📋 Descripción del problema y modelo", expanded=False):
    st.markdown("""
    ### Problema de negocio
    Optimizar las **rutas de despacho** desde un Centro de Distribución (CD) hacia múltiples tiendas.

    1. **Agrupamos** las tiendas por cercanía geográfica. El modo *balanceado por capacidad*
       garantiza que ningún grupo supere las tiendas que un vehículo puede atender,
       y escala a **miles de coordenadas**.
    2. Para cada grupo calculamos la **ruta óptima** con **Google OR-Tools**
       (se resuelve localmente, sin límites de API). Las distancias pueden ser por
       **calles reales (OSRM, gratis)** o en **línea recta (haversine)**.
    """)

# ===========================================================
# HISTORIAL DE DESPACHOS (lee la pestaña Historial de Google Sheets)
# ===========================================================
with st.expander("📅 Historial de despachos", expanded=False):
    _url_hist = leer_secret("gsheets_url", "")
    _tiene_cred = bool(GSHEETS_DISPONIBLE
                       and leer_secret("gcp_service_account", {}) not in (None, {}))
    if not _tiene_cred or not _url_hist:
        st.caption("Conecta tu Google Sheet (sección 📤 *Asignar rutas* y guía "
                   "SETUP_APPSHEET.md) para guardar y consultar aquí cada despacho "
                   "enviado, con su fecha, autor, km, bultos y costo.")
    else:
        c_h1, c_h2 = st.columns([1, 3])
        if c_h1.button("🔄 Cargar / actualizar historial", use_container_width=True):
            st.session_state.ver_historial = True
            leer_pestana.clear()
        if st.session_state.get("ver_historial"):
            try:
                df_hist = leer_pestana(_url_hist, "Historial")
            except Exception as e:
                df_hist = pd.DataFrame()
                st.error(f"No se pudo leer el historial: {type(e).__name__}: {e}")
            if df_hist.empty:
                st.info("Aún no hay despachos registrados. Envía uno desde la sección "
                        "📤 *Asignar rutas → Google Sheets* y aparecerá aquí.")
            else:
                df_hist = df_hist.iloc[::-1].reset_index(drop=True)  # más reciente primero
                fechas = ["(todas)"] + sorted(
                    [f for f in df_hist.get("fecha", pd.Series()).astype(str).unique() if f],
                    reverse=True)
                f_sel = c_h2.selectbox("Filtrar por fecha:", fechas, key="hist_fecha")
                vista = df_hist if f_sel == "(todas)" else df_hist[df_hist["fecha"].astype(str) == f_sel]
                tot_desp = len(vista)
                tot_km = pd.to_numeric(vista.get("km_total"), errors="coerce").sum()
                tot_bultos = pd.to_numeric(vista.get("bultos"), errors="coerce").sum()
                st.caption(f"📦 {tot_desp} despachos · {int(tot_bultos):,} bultos · "
                           f"{tot_km:,.1f} km acumulados")
                st.dataframe(vista, use_container_width=True, hide_index=True, height=300)
                st.download_button(
                    "⬇️ Descargar historial (CSV)",
                    data=vista.to_csv(index=False).encode("utf-8"),
                    file_name="historial_despachos.csv", mime="text/csv")

# ===========================================================
# SIDEBAR — AGRUPAMIENTO
# ===========================================================
st.sidebar.header("⚙️ Configuración del agrupamiento")

modo_cluster = st.sidebar.radio(
    "Modo de agrupamiento:",
    options=["capacidad", "manual", "clasico"],
    format_func=lambda x: {
        "capacidad": "🚚 Balanceado por capacidad (recomendado)",
        "manual": "✋ Selección manual en el mapa",
        "clasico": "📐 K-Means clásico (elegir K)"
    }[x],
    help="Balanceado: defines cuántas tiendas atiende cada ruta/vehículo y "
         "ningún grupo supera ese máximo. Manual: tú eliges los puntos de cada "
         "grupo haciendo clic en el mapa (con bultos en tiempo real). Clásico: "
         "K-Means estándar (los grupos pueden salir muy desiguales)."
)

Xm = proyectar_metros(df["latitud"].values, df["longitud"].values)

flota = None
vueltas_max = 1
uso_flota = "compacto"
modo_manual = (modo_cluster == "manual")

if modo_cluster == "capacidad":
    criterio_cap = st.sidebar.radio(
        "Limitar cada ruta por:",
        options=["tiendas", "bultos", "flota"],
        format_func=lambda x: {
            "tiendas": "🏪 Nº de tiendas",
            "bultos": "📦 Nº de bultos (un solo tipo de vehículo)",
            "flota": "🚛 Flota personalizada (tipos de vehículo)"
        }[x],
        help="Bultos: todos los vehículos cargan lo mismo. Flota: define cuántos "
             "vehículos tienes de cada tipo (capacidad en bultos y máx. de tiendas); "
             "el número de rutas queda limitado por tu flota."
    )
    if criterio_cap == "tiendas":
        capacidad = st.sidebar.slider(
            "Máx. tiendas por grupo (capacidad del vehículo):",
            min_value=5, max_value=80, value=min(25, max(5, n_tiendas - 1)), step=1
        )
        pesos = np.ones(n_tiendas)
    elif criterio_cap == "bultos":
        total_bultos = int(df["cantidad_bultos"].sum())
        max_bulto_tienda = int(df["cantidad_bultos"].max())
        capacidad = int(st.sidebar.number_input(
            "Máx. bultos por ruta (capacidad del vehículo):",
            min_value=max_bulto_tienda,
            value=max(max_bulto_tienda, math.ceil(total_bultos / 10)),
            step=10,
            help=f"Tu dataset suma {total_bultos:,} bultos. "
                 f"La tienda más grande pide {max_bulto_tienda} (mínimo permitido)."
        ))
        pesos = df["cantidad_bultos"].values.astype(float)
    else:  # flota personalizada
        st.sidebar.caption("Define tu flota: cuántos vehículos tienes de cada tipo, "
                           "su capacidad en bultos y (opcional) el máximo de tiendas "
                           "que puede visitar cada uno (0 = sin límite).")
        flota_editada = st.sidebar.data_editor(
            pd.DataFrame({
                "Vehículos": [10, 10],
                "Capacidad (bultos)": [300, 250],
                "Máx. tiendas": [0, 0],
            }),
            num_rows="dynamic", hide_index=True, use_container_width=True,
            key="editor_flota",
            column_config={
                "Vehículos": st.column_config.NumberColumn(min_value=1, max_value=500, step=1),
                "Capacidad (bultos)": st.column_config.NumberColumn(min_value=1, step=10),
                "Máx. tiendas": st.column_config.NumberColumn(
                    min_value=0, step=1, help="0 = sin límite de tiendas para ese tipo"),
            }
        )
        vueltas_max = st.sidebar.slider(
            "🔁 Vueltas máximas de la flota:", 1, 3, 1,
            help="Si en una vuelta no se cubren todas las tiendas, la flota puede "
                 "salir de nuevo (2ª/3ª vuelta) para atender las pendientes."
        )
        uso_flota = st.sidebar.radio(
            "Uso de la flota:",
            options=["compacto", "minimo"],
            format_func=lambda x: (
                "🗺️ Zonas compactas (~30% más vehículos, recomendado)"
                if x == "compacto" else
                "🚛 Mínimo de vehículos (rutas más llenas)"
            ),
            help="Con el mínimo de vehículos los grupos van llenos al ~100% y el "
                 "empaque obliga a juntar tiendas lejanas. Con holgura (~75-85% de "
                 "llenado) las zonas salen geográficamente limpias."
        )
        flota_lista = []
        for _, fila in flota_editada.iterrows():
            if pd.isna(fila["Vehículos"]) or pd.isna(fila["Capacidad (bultos)"]):
                continue
            cant, cap_v = int(fila["Vehículos"]), int(fila["Capacidad (bultos)"])
            mt = int(fila["Máx. tiendas"]) if pd.notna(fila["Máx. tiendas"]) else 0
            if cant > 0 and cap_v > 0:
                flota_lista.extend([(cap_v, mt)] * cant)
        if not flota_lista:
            st.sidebar.error("⚠️ Define al menos un vehículo válido en la flota.")
            st.stop()
        flota = tuple(flota_lista)
        pesos = df["cantidad_bultos"].values.astype(float)
        capacidad = None  # cada vehículo tiene su propia capacidad
        total_bultos = int(pesos.sum())
        cap_vuelta = sum(c for c, _ in flota)
        cap_total = cap_vuelta * vueltas_max
        st.sidebar.info(
            f"🚛 Flota: **{len(flota)} vehículos** · {cap_vuelta:,} bultos por vuelta"
            + (f" × {vueltas_max} vueltas = {cap_total:,}" if vueltas_max > 1 else "")
            + f" | Demanda: {total_bultos:,} bultos"
        )
        if cap_total < total_bultos:
            st.sidebar.warning(
                f"⚠️ La flota no cubre toda la demanda: ~{total_bultos - cap_total:,} "
                f"bultos quedarían sin asignar (las tiendas prioritarias entran primero).")

    if criterio_cap == "flota":
        # rutas estimadas = vehículos mínimos necesarios en la 1ª vuelta
        K_estimado, acum = 0, 0.0
        for cap_v, _ in sorted(flota, key=lambda t: -t[0]):
            if acum >= float(pesos.sum()):
                break
            acum += cap_v
            K_estimado += 1
        K = max(1, K_estimado)
    else:
        K_estimado = max(1, math.ceil(float(pesos.sum()) / capacidad))
        unidad = "tiendas" if criterio_cap == "tiendas" else "bultos"
        st.sidebar.info(f"💡 {int(pesos.sum()):,} {unidad} ÷ {capacidad} por ruta → **~{K_estimado} grupos/rutas**")
        K = K_estimado
elif modo_cluster == "manual":
    criterio_cap = "manual"
    capacidad = None
    pesos = df["cantidad_bultos"].values.astype(float)

    # Estado persistente: una lista de grupos (cada uno = set de índices 0..n-1)
    if (st.session_state.get("manual_dsid") != dataset_id
            or "grupos_manual" not in st.session_state):
        st.session_state.manual_dsid = dataset_id
        st.session_state.grupos_manual = [set()]
        st.session_state.grupo_activo = 0
        st.session_state.ultimo_clic_manual = None
        st.session_state.ultimo_dibujo_manual = None

    grupos_m = st.session_state.grupos_manual
    # saneamiento por si quedó vacío
    if not grupos_m:
        grupos_m.append(set())
        st.session_state.grupo_activo = 0
    st.session_state.grupo_activo = min(st.session_state.grupo_activo, len(grupos_m) - 1)

    st.sidebar.caption("Haz **clic en una tienda** del mapa para asignarla al grupo "
                       "activo (clic de nuevo para quitarla), o **dibuja un área** "
                       "(⬛ rectángulo / ⬠ polígono, botones a la izquierda del mapa) "
                       "para seleccionar **todo un sector de golpe**. Los puntos "
                       "**grises** están libres.")

    accion_dibujo = st.sidebar.radio(
        "Al dibujar un área:",
        ["➕ Asignar el sector al grupo activo", "➖ Liberar el sector (quitar de todos)"],
        key="accion_dibujo",
        help="Dibuja un rectángulo o polígono sobre el mapa: todas las tiendas "
             "dentro del área se asignan al grupo activo, o se liberan si eliges quitar.")

    opciones_g = list(range(len(grupos_m)))
    st.session_state.grupo_activo = st.sidebar.selectbox(
        "Grupo activo (recibe los clics):", options=opciones_g,
        index=st.session_state.grupo_activo,
        format_func=lambda g: f"Grupo {g + 1}  ·  {len(grupos_m[g])} tiendas / "
                              f"{int(pesos[list(grupos_m[g])].sum()) if grupos_m[g] else 0} bultos"
    )
    g_act = st.session_state.grupo_activo

    # Tope opcional para alerta visual de capacidad
    cap_alerta = st.sidebar.number_input(
        "Tope de bultos por grupo (alerta, 0 = sin tope):",
        min_value=0, value=0, step=10,
        help="Solo para avisarte cuando un grupo supera ese límite mientras seleccionas. "
             "No impide asignar.")

    c_b1, c_b2 = st.sidebar.columns(2)
    if c_b1.button("➕ Nuevo grupo", use_container_width=True):
        grupos_m.append(set())
        st.session_state.grupo_activo = len(grupos_m) - 1
        st.rerun()
    if c_b2.button("🧹 Vaciar grupo", use_container_width=True):
        grupos_m[g_act] = set()
        st.rerun()
    c_b3, c_b4 = st.sidebar.columns(2)
    if c_b3.button("🗑️ Eliminar grupo", use_container_width=True, disabled=len(grupos_m) <= 1):
        grupos_m.pop(g_act)
        st.session_state.grupo_activo = 0
        st.rerun()
    if c_b4.button("♻️ Reiniciar todo", use_container_width=True):
        st.session_state.grupos_manual = [set()]
        st.session_state.grupo_activo = 0
        st.rerun()

    # KPI en tiempo real del grupo activo
    n_act = len(grupos_m[g_act])
    bultos_act = int(pesos[list(grupos_m[g_act])].sum()) if grupos_m[g_act] else 0
    asignadas_tot = set().union(*grupos_m) if grupos_m else set()
    libres_tot = n_tiendas - len(asignadas_tot)
    alerta_cap = (cap_alerta > 0 and bultos_act > cap_alerta)
    st.sidebar.markdown(
        f"<div style='background:{'#FDE7E7' if alerta_cap else '#E8F1FD'};"
        f"border-radius:10px;padding:10px 12px;margin-top:6px'>"
        f"<b>Grupo {g_act + 1} (activo)</b><br>"
        f"🏪 {n_act} tiendas<br>📦 <b>{bultos_act}</b> bultos"
        + (f" / {cap_alerta} ⚠️" if alerta_cap else
           (f" / {cap_alerta}" if cap_alerta else "")) +
        f"<br>🟢 {libres_tot} libres · {len(asignadas_tot)} asignadas</div>",
        unsafe_allow_html=True)

    # Auto-asignar los puntos que queden libres (híbrido manual + automático)
    st.sidebar.markdown("**🤖 Completar automáticamente**")
    cap_auto = st.sidebar.number_input(
        "Máx. bultos por grupo automático:", min_value=1,
        value=max(1, int(pesos.sum() / max(1, n_tiendas)) * 25), step=10)
    if st.sidebar.button("🤖 Auto-asignar puntos libres", use_container_width=True):
        libres_idx = [i for i in range(n_tiendas) if i not in asignadas_tot]
        if libres_idx:
            Xm_libres = Xm[libres_idx]
            pesos_libres = pesos[libres_idx]
            k_auto = max(1, math.ceil(float(pesos_libres.sum()) / cap_auto))
            if k_auto == 1 or len(libres_idx) <= 1:
                lab_auto = np.zeros(len(libres_idx), dtype=int)
            else:
                lab_auto, _ = kmeans_balanceado(Xm_libres, k_auto, cap_auto, pesos=pesos_libres)
            for c in range(int(lab_auto.max()) + 1):
                nuevo = {libres_idx[j] for j in range(len(libres_idx)) if lab_auto[j] == c}
                if nuevo:
                    grupos_m.append(nuevo)
            st.rerun()
        else:
            st.sidebar.info("No quedan puntos libres.")

    K = sum(1 for g in grupos_m if g)
else:
    criterio_cap = "tiendas"
    pesos = np.ones(n_tiendas)
    capacidad = None
    max_k_slider = min(MAX_K, n_tiendas - 1)
    k_usuario = st.sidebar.slider("Selecciona el número de clusters (K):",
        min_value=2, max_value=max(2, max_k_slider),
        value=min(8, max(2, max_k_slider)), step=1)
    K = k_usuario
    calcular_k_opt = st.sidebar.checkbox(
        "Sugerir K óptimo (silhouette)", value=False,
        help="Evalúa varios K y sugiere el mejor. Con miles de puntos puede tardar unos segundos."
    )
    if calcular_k_opt:
        @st.cache_data(show_spinner="Evaluando K óptimo...")
        def calcular_k_optimo(ds_id, n):
            ks = range(2, min(MAX_K, n - 1) + 1, max(1, min(MAX_K, n - 1) // 25))
            sils = {}
            muestra = min(1500, n)
            for k in ks:
                km = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=10)
                labels = km.fit_predict(Xm)
                if len(np.unique(labels)) > 1:
                    sils[k] = silhouette_score(Xm, labels, sample_size=muestra, random_state=42)
            mejor = max(sils, key=sils.get)
            return mejor, sils[mejor]

        k_opt, sil_opt = calcular_k_optimo(dataset_id, n_tiendas)
        st.sidebar.info(f"💡 **K óptimo sugerido:** {k_opt} (Silhouette = {sil_opt:.3f})")

st.sidebar.markdown("---")

# ===========================================================
# SIDEBAR — CD Y RUTEO
# ===========================================================
st.sidebar.header("🚛 Centro de Distribución y Ruteo")
cd_lat = st.sidebar.number_input("Latitud del CD:", value=-12.046374, format="%.6f")
cd_lon = st.sidebar.number_input("Longitud del CD:", value=-77.042793, format="%.6f")
tipo_recorrido = st.sidebar.selectbox(
    "Tipo de recorrido:",
    options=["cerrado", "abierto"],
    format_func=lambda x: "🔁 Cerrado (CD → tiendas → CD)" if x == "cerrado" else "➡️ Abierto (CD → tiendas)"
)

n_con_ventana = int((df["ventana_ini_s"].notna() & df["ventana_fin_s"].notna()).sum())
with st.sidebar.expander("⏱️ Tiempos, ventanas horarias y costos", expanded=False):
    hora_salida = st.time_input("Hora de salida del CD:", value=_dt.time(8, 0))
    servicio_base = st.number_input(
        "Minutos de servicio por parada:", min_value=0.0, max_value=120.0,
        value=10.0, step=1.0,
        help="Tiempo de descarga/atención en cada tienda. Se suma a la duración "
             "y se usa para calcular la hora estimada de llegada (ETA).")
    servicio_bulto = st.number_input(
        "Minutos adicionales por bulto:", min_value=0.0, max_value=10.0,
        value=0.0, step=0.5,
        help="Opcional: si descargar cada bulto toma tiempo medible.")
    jornada_horas = st.number_input(
        "Jornada máxima por ruta (horas, 0 = sin límite):",
        min_value=0.0, max_value=24.0, value=8.0, step=0.5)
    if n_con_ventana:
        st.caption(f"⏰ **{n_con_ventana} tiendas con ventana horaria** detectadas "
                   "(columnas hora_inicio / hora_fin). El ruteo las respetará.")
    else:
        st.caption("Sin ventanas horarias en el dataset. Puedes agregarlas con las "
                   "columnas opcionales `hora_inicio` y `hora_fin` (ej. 09:00).")
    st.markdown("**💰 Costos (opcional)**")
    moneda = st.text_input("Moneda:", value="S/", max_chars=5)
    costo_fijo = st.number_input(f"Costo fijo por vehículo/ruta ({moneda}):",
                                 min_value=0.0, value=0.0, step=10.0)
    costo_km = st.number_input(f"Costo por km ({moneda}):",
                               min_value=0.0, value=0.0, step=0.1, format="%.2f")

salida_s = hora_salida.hour * 3600 + hora_salida.minute * 60
jornada_s = int(jornada_horas * 3600)
hay_costos = costo_fijo > 0 or costo_km > 0

opciones_motor = ["osrm", "haversine"] + (["ors"] if ORS_DISPONIBLE else [])
motor_ruteo = st.sidebar.selectbox(
    "Motor de ruteo:",
    options=opciones_motor,
    format_func=lambda x: {
        "osrm": "🆓 OR-Tools + OSRM (calles reales, gratis, sin API key)",
        "haversine": "⚡ OR-Tools + Haversine (línea recta, sin internet)",
        "ors": "🔑 OpenRouteService (requiere API key, máx. 50 tiendas/grupo)"
    }[x],
    help="OR-Tools resuelve el orden óptimo LOCALMENTE (sin límites de requests). "
         "OSRM aporta distancias y geometría por calles reales gratis. "
         "Haversine no usa internet (distancia en línea recta)."
)

api_key_ors = ""
if motor_ruteo == "ors":
    api_key_ors = st.sidebar.text_input(
        "API Key de OpenRouteService:", type="password",
        help="Obtén tu key gratis en https://openrouteservice.org/dev/#/signup"
    )

tiempo_tsp = st.sidebar.slider(
    "⏱️ Segundos de optimización por grupo (OR-Tools):",
    min_value=1, max_value=15, value=2,
    help="Más tiempo = rutas ligeramente mejores. Con grupos de ≤30 tiendas, 1-3 s ya da resultados casi óptimos."
) if motor_ruteo != "ors" else 2

calcular_rutas = st.sidebar.button("🚛 Calcular rutas óptimas", use_container_width=True, type="primary")
st.sidebar.markdown("---")

# ===========================================================
# ENTRENAR MODELO DE CLUSTERING
# ===========================================================
@st.cache_data(show_spinner="Agrupando tiendas...")
def agrupar(ds_id, modo, criterio, cap, k_clasico, flota_cfg, vueltas, holgura):
    """Devuelve (labels, k_final, hubo_sobrecupo, info_flota).
    - flota: asignación a vehículos heterogéneos; labels=-1 = tienda no asignada.
    - tiendas/bultos: si el empaque no cierra, reintenta agregando grupos."""
    if modo == "capacidad" and criterio == "flota":
        labels, info = asignar_flota(Xm, PESOS_GLOBAL, PRIO_GLOBAL, flota_cfg, vueltas,
                                     usar_holgura=(holgura == "compacto"))
        k_final = int(labels.max()) + 1 if (labels >= 0).any() else 0
        return labels, k_final, False, info
    if modo == "capacidad":
        total = float(PESOS_GLOBAL.sum())
        k = max(1, math.ceil(total / cap))
        if k == 1:
            return np.zeros(len(Xm), dtype=int), 1, False, None
        sobrecupo = False
        labels = None
        for _ in range(6):
            labels, sobrecupo = kmeans_balanceado(Xm, k, cap, pesos=PESOS_GLOBAL)
            if not sobrecupo:
                return labels, k, False, None
            k = min(k + 1, len(Xm))
        return labels, int(labels.max()) + 1, True, None
    if k_clasico == 1:
        return np.zeros(len(Xm), dtype=int), 1, False, None
    # modo clásico: MiniBatch para datasets grandes, KMeans exacto para pequeños
    if len(Xm) > 3000:
        modelo = MiniBatchKMeans(n_clusters=k_clasico, random_state=42, n_init=10)
    else:
        modelo = KMeans(n_clusters=k_clasico, random_state=42, n_init=10)
    return modelo.fit_predict(Xm), k_clasico, False, None

PESOS_GLOBAL = pesos
PRIO_GLOBAL = df["prioridad"].values.astype(int)
if modo_manual:
    # labels desde la selección manual (grupos no vacíos -> 0..K-1; resto = -1 libre)
    labels = np.full(n_tiendas, -1, dtype=int)
    k_m = 0
    for conjunto in st.session_state.grupos_manual:
        if conjunto:
            for idx_pos in conjunto:
                labels[idx_pos] = k_m
            k_m += 1
    K = k_m
    hubo_sobrecupo, info_flota = False, None
else:
    labels, K, hubo_sobrecupo, info_flota = agrupar(
        dataset_id, modo_cluster, criterio_cap,
        capacidad if capacidad else 0, K, flota, vueltas_max, uso_flota)
if hubo_sobrecupo:
    st.warning("⚠️ No fue posible repartir los bultos sin exceder la capacidad en "
               "algún grupo (los tamaños de pedido no encajan perfecto). Algún "
               "grupo quedó ligeramente por encima del límite; revisa el resumen.")
df["cluster"] = labels.astype(str)

no_asignadas = df[df["cluster"] == "-1"]
n_no_asignadas = len(no_asignadas)
if K == 0 and not modo_manual:
    st.error("🚫 Ninguna tienda pudo asignarse con la flota definida. "
             "Aumenta la capacidad, la cantidad de vehículos o las vueltas.")
    st.stop()

# Centroides geográficos = promedio de lat/lon de cada grupo (sin las no asignadas)
df_centroides = df[df["cluster"] != "-1"].groupby("cluster").agg(
    latitud=("latitud", "mean"), longitud=("longitud", "mean")
).reset_index()
df_centroides["cluster_num"] = df_centroides["cluster"].astype(int)
df_centroides = df_centroides.sort_values("cluster_num").reset_index(drop=True)

# ===========================================================
# SIDEBAR — FILTROS
# ===========================================================
st.sidebar.header("🔍 Filtros de visualización")

modo_enfoque = st.sidebar.radio(
    "Modo de visualización:",
    options=["todos", "aislar", "solo_rutas"],
    format_func=lambda x: {
        "todos": "👁️ Mostrar todo",
        "aislar": "🎯 Aislar un cluster",
        "solo_rutas": "🛣️ Solo rutas (sin zonas)"
    }[x], index=0
)

if modo_enfoque == "aislar":
    cluster_aislado = st.sidebar.selectbox("Cluster a aislar:",
        options=list(range(K)), format_func=lambda x: f"Cluster {x}")
    clusters_visibles = [cluster_aislado]
else:
    if K > 20:
        # con muchos grupos, multiselect se vuelve incómodo: rango
        rango = st.sidebar.slider("Rango de clusters visibles:", 0, K - 1, (0, K - 1))
        clusters_visibles = list(range(rango[0], rango[1] + 1))
    else:
        clusters_visibles = st.sidebar.multiselect(
            "Clusters visibles:",
            options=list(range(K)), default=list(range(K)),
            format_func=lambda x: f"Cluster {x}"
        )

mostrar_zonas_check = st.sidebar.checkbox("Mostrar zonas de cobertura", value=True)
mostrar_rutas_check = st.sidebar.checkbox("Mostrar rutas calculadas", value=True)
mostrar_tiendas_check = st.sidebar.checkbox("Mostrar tiendas", value=True)
mostrar_numeros_orden = st.sidebar.checkbox("Mostrar números de orden", value=(n_tiendas <= 400))
mostrar_centroides = st.sidebar.checkbox("Mostrar centroides", value=True)
agrupar_marcadores = st.sidebar.checkbox(
    "Agrupar marcadores al hacer zoom", value=(n_tiendas > 400),
    help="Recomendado con cientos/miles de tiendas: los puntos se agrupan en "
         "burbujas con contador y se expanden al acercarte."
)
animar_rutas = st.sidebar.checkbox(
    "✨ Rutas animadas", value=False,
    help="Dibuja las rutas con animación de flujo (indica el sentido del recorrido)."
)
mostrar_zonas = mostrar_zonas_check and modo_enfoque != "solo_rutas"

if modo_manual:
    # En selección manual cada tienda debe ser un marcador individual y clicable
    agrupar_marcadores = False
    mostrar_tiendas_check = True

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎨 Estilo del mapa")
estilo_mapa = st.sidebar.selectbox(
    "Estilo:",
    options=["CartoDB positron", "OpenStreetMap", "CartoDB dark_matter", "CartoDB voyager"],
    format_func=lambda x: {
        "CartoDB positron": "🌅 Claro (recomendado)",
        "OpenStreetMap": "🗺️ OpenStreetMap",
        "CartoDB dark_matter": "🌃 Oscuro",
        "CartoDB voyager": "🧭 Voyager (tonos suaves)"
    }[x], index=0
)
paleta_colores = st.sidebar.selectbox("Paleta de colores:",
    options=["Vivid", "Bold", "Pastel", "Plotly", "D3", "Light24"], index=0)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 Ver detalles")
mostrar_codo = st.sidebar.checkbox(
    "Mostrar método del codo / silhouette",
    value=(n_tiendas <= 500),
    help="Con miles de puntos este gráfico tarda; actívalo solo cuando lo necesites."
)
mostrar_metricas = st.sidebar.checkbox("Mostrar métricas del modelo", value=True)

# ===========================================================
# CÁLCULO DE RUTAS
# ===========================================================
if "rutas_calculadas" not in st.session_state:
    st.session_state.rutas_calculadas = None
    st.session_state.rutas_k_config = None

config_actual = (f"{K}_{cd_lat}_{cd_lon}_{tipo_recorrido}_{dataset_id}_"
                 f"{motor_ruteo}_{modo_cluster}_{criterio_cap}_{capacidad}_"
                 f"{hash(flota) if flota else 0}_{vueltas_max}_{uso_flota}_"
                 f"{salida_s}_{servicio_base}_{servicio_bulto}_{jornada_s}")

if calcular_rutas:
    if motor_ruteo == "ors" and not api_key_ors:
        st.sidebar.error("⚠️ Ingresa tu API Key de OpenRouteService.")
    else:
        if motor_ruteo == "ors" and (df["prioridad"] > 0).any():
            st.sidebar.warning("⚠️ Las prioridades de envío solo se aplican con los "
                               "motores OR-Tools (OSRM o Haversine). Con ORS se "
                               "calculará el orden óptimo sin prioridades.")
        if motor_ruteo == "ors" and n_con_ventana:
            st.sidebar.warning("⚠️ Las ventanas horarias solo se aplican con los "
                               "motores OR-Tools. Con ORS se rutea sin ventanas.")
        rutas = {}
        errores = []
        barra = st.progress(0.0, text="🚛 Calculando rutas óptimas...")
        for pos, i in enumerate(range(K)):
            barra.progress((pos + 1) / K, text=f"🚛 Optimizando ruta del cluster {i} ({pos + 1}/{K})...")
            cluster_data = df[df["cluster"] == str(i)].copy()
            if len(cluster_data) == 0:
                continue
            # segundos de servicio por tienda y ventanas horarias del cluster
            serv_arr = (servicio_base * 60.0
                        + cluster_data["cantidad_bultos"].values.astype(float) * servicio_bulto * 60.0)
            vent_arr = [
                (int(a), int(b)) if pd.notna(a) and pd.notna(b) and b > a else None
                for a, b in zip(cluster_data["ventana_ini_s"], cluster_data["ventana_fin_s"])
            ]
            try:
                if motor_ruteo == "ors":
                    if len(cluster_data) > ORS_MAX_JOBS:
                        errores.append(
                            f"Cluster {i}: {len(cluster_data)} tiendas superan el límite gratuito "
                            f"de ORS ({ORS_MAX_JOBS}). Usa el motor OR-Tools + OSRM, o reduce la "
                            f"capacidad por grupo.")
                        continue
                    tiendas_coords = [(float(row["longitud"]), float(row["latitud"]), idx)
                                      for idx, row in cluster_data.iterrows()]
                    servicio_map = {idx: int(s) for idx, s in zip(cluster_data.index, serv_arr)}
                    resultado = calcular_ruta_ors(
                        cd_coord=[cd_lon, cd_lat],
                        tiendas_coords=tiendas_coords,
                        api_key=api_key_ors,
                        cerrada=(tipo_recorrido == "cerrado"),
                        servicio_map=servicio_map,
                        salida_cd_s=salida_s
                    )
                else:
                    resultado = rutear_cluster_ortools(
                        cluster_data, cd_lat, cd_lon,
                        motor=motor_ruteo,
                        cerrado=(tipo_recorrido == "cerrado"),
                        tiempo_tsp=tiempo_tsp,
                        servicio_s=serv_arr,
                        ventanas=vent_arr,
                        salida_cd_s=salida_s,
                        jornada_max_s=jornada_s
                    )
                if resultado:
                    rutas[i] = resultado
                    if resultado.get("aviso"):
                        errores.append(f"Cluster {i}: {resultado['aviso']}")
            except Exception as e:
                errores.append(f"Cluster {i}: {type(e).__name__}: {e}")
        barra.empty()
        if errores:
            for err in errores:
                st.sidebar.warning(err)
        if rutas:
            st.session_state.rutas_calculadas = rutas
            st.session_state.rutas_k_config = config_actual
            st.sidebar.success(f"✅ {len(rutas)} rutas calculadas")
        elif not errores:
            st.sidebar.error("No se pudo calcular ninguna ruta.")

rutas_validas = (
    st.session_state.rutas_calculadas is not None
    and st.session_state.rutas_k_config == config_actual
)

# ===========================================================
# MÉTRICAS — franja de KPIs
# ===========================================================
mask_asig = (df["cluster"] != "-1").values
sil_val, db_val = "—", "—"
if K >= 2 and mask_asig.sum() > K:
    muestra_sil = min(2000, int(mask_asig.sum()))
    sil_val = f"{silhouette_score(Xm[mask_asig], df.loc[mask_asig, 'cluster'], sample_size=muestra_sil, random_state=42):.3f}"
    db_val = f"{davies_bouldin_score(Xm[mask_asig], df.loc[mask_asig, 'cluster']):.3f}"
if rutas_validas:
    total_km_visibles = sum(r['distance_km'] for i, r in st.session_state.rutas_calculadas.items()
                            if i in clusters_visibles)
    km_val = f"{total_km_visibles:.1f} km"
else:
    km_val = "—"
badge_noasig = (f"<span class='rt-kpi-bad'>{n_no_asignadas} sin asignar</span>"
                if n_no_asignadas else "")
kpis = [
    ("🏪", "#FDF3E3", "Tiendas", f"{n_tiendas:,}", badge_noasig),
    ("🚛", "#E8F1FD", "Grupos", f"{K}", ""),
    ("📦", "#FDEDE6", "Bultos", f"{int(df['cantidad_bultos'].sum()):,}", ""),
    ("📈", "#E6F7F2", "Silhouette", sil_val, ""),
    ("📐", "#F3E9FD", "Davies-Bouldin", db_val, ""),
    ("🛣️", "#FFF6DE", "Km visibles", km_val, ""),
]
st.markdown("<div class='rt-kpis'>" + "".join(
    f"<div class='rt-kpi'><div class='rt-kpi-ico' style='background:{tinte}'>{icono}</div>"
    f"<div><div class='rt-kpi-lbl'>{etiqueta}</div>"
    f"<div class='rt-kpi-val'>{valor}{extra}</div></div></div>"
    for icono, tinte, etiqueta, valor, extra in kpis) + "</div>",
    unsafe_allow_html=True)

# Balance de los grupos (solo asignadas)
df_asig = df[df["cluster"] != "-1"]
tam = df_asig["cluster"].value_counts()
if tam.empty:
    # Modo manual sin nada asignado todavía: el mapa de abajo permite seleccionar
    st.caption("✋ Aún no hay grupos armados. Selecciona puntos en el mapa de abajo.")
else:
    texto_balance = (f"🏪 Tiendas por grupo — mín: {tam.min()} · máx: {tam.max()} · "
                     f"promedio: {tam.mean():.1f}")
    hay_bultos_reales = int(df["cantidad_bultos"].sum()) != n_tiendas
    if hay_bultos_reales or criterio_cap in ("bultos", "flota", "manual"):
        bultos_grupo = df_asig.groupby("cluster")["cantidad_bultos"].sum()
        texto_balance += (f" | 📦 Bultos por grupo — mín: {int(bultos_grupo.min())} · "
                          f"máx: {int(bultos_grupo.max())} · total: {int(df['cantidad_bultos'].sum()):,}")
    if capacidad:
        texto_balance += f" | capacidad máx.: {capacidad} {'bultos' if criterio_cap == 'bultos' else 'tiendas'}/ruta"
    if criterio_cap == "flota" and info_flota:
        texto_balance += (f" | 🚛 {K} vehículos en ruta de {len(flota)} disponibles"
                          + (f" ({max(v['vuelta'] for v in info_flota.values())} vueltas)"
                             if vueltas_max > 1 else ""))
    n_prioritarias = int((df["prioridad"] > 0).sum())
    if n_prioritarias:
        texto_balance += f" | ⭐ {n_prioritarias} tiendas prioritarias"
    if n_no_asignadas:
        texto_balance += f" | 🚫 {n_no_asignadas} sin asignar (ver sección al final)"
    st.caption(texto_balance)

st.markdown("---")

if not clusters_visibles and not modo_manual:
    st.warning("⚠️ No hay clusters seleccionados. Activa al menos uno en el sidebar.")
elif modo_manual and K == 0:
    st.info("✋ **Modo manual activo.** Todos los puntos están libres (grises). "
            "Haz clic en el mapa para empezar a armar el Grupo 1.")

# ===========================================================
# MAPA INTERACTIVO
# ===========================================================
st.subheader(f"🗺️ Mapa interactivo — {K} zonas de despacho")

if modo_enfoque == "aislar" and clusters_visibles:
    cluster_data_focus = df[df["cluster"] == str(clusters_visibles[0])]
    center_lat = cluster_data_focus["latitud"].mean()
    center_lon = cluster_data_focus["longitud"].mean()
    lat_range = cluster_data_focus["latitud"].max() - cluster_data_focus["latitud"].min()
    lon_range = cluster_data_focus["longitud"].max() - cluster_data_focus["longitud"].min()
else:
    center_lat = df["latitud"].mean()
    center_lon = df["longitud"].mean()
    lat_range = df["latitud"].max() - df["latitud"].min()
    lon_range = df["longitud"].max() - df["longitud"].min()

max_range = max(lat_range, lon_range, 0.001)
if max_range < 0.02: zoom_calc = 14
elif max_range < 0.05: zoom_calc = 13
elif max_range < 0.1: zoom_calc = 12
elif max_range < 0.3: zoom_calc = 11
elif max_range < 1: zoom_calc = 9
elif max_range < 5: zoom_calc = 6
elif max_range < 20: zoom_calc = 4
else: zoom_calc = 2

paletas = {
    "Vivid": px.colors.qualitative.Vivid, "Bold": px.colors.qualitative.Bold,
    "Pastel": px.colors.qualitative.Pastel, "Plotly": px.colors.qualitative.Plotly,
    "D3": px.colors.qualitative.D3, "Light24": px.colors.qualitative.Light24
}
colores = paletas[paleta_colores]  # hex o 'rgb(r,g,b)': ambos son CSS válidos para Folium

@st.fragment
def _render_mapa(_no_asig=no_asignadas, _n_no_asig=n_no_asignadas,
                 _df_cent=df_centroides, _clus_vis=clusters_visibles):
    # OPTIMIZACION: el mapa vive en un st.fragment. En modo manual, dibujar/clicar
    # re-ejecuta SOLO este fragment (no las ~3000 lineas del script), recalculando
    # la seleccion fresca desde session_state -> interaccion mucho mas fluida.
    if modo_manual:
        _lbl = np.full(n_tiendas, -1, dtype=int)
        _k = 0
        for _conj in st.session_state.grupos_manual:
            if _conj:
                for _ip in _conj:
                    _lbl[_ip] = _k
                _k += 1
        df["cluster"] = _lbl.astype(str)
        no_asignadas = df[df["cluster"] == "-1"]
        n_no_asignadas = len(no_asignadas)
        df_centroides = (df[df["cluster"] != "-1"].groupby("cluster")
                         .agg(latitud=("latitud", "mean"), longitud=("longitud", "mean"))
                         .reset_index())
        df_centroides["cluster_num"] = df_centroides["cluster"].astype(int)
        df_centroides = df_centroides.sort_values("cluster_num").reset_index(drop=True)
        clusters_visibles = list(range(_k))
    else:
        no_asignadas, n_no_asignadas = _no_asig, _n_no_asig
        df_centroides, clusters_visibles = _df_cent, _clus_vis
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom_calc,
        tiles=estilo_mapa,
        control_scale=True
    )

    # Herramientas profesionales dentro del mapa
    Fullscreen(position="topleft", title="Pantalla completa", title_cancel="Salir").add_to(m)
    MeasureControl(position="topleft", primary_length_unit="kilometers",
                   secondary_length_unit="meters").add_to(m)
    MiniMap(toggle_display=True, position="bottomright", zoom_level_offset=-5).add_to(m)

    # Capas activables desde el control del propio mapa (esquina superior derecha)
    fg_zonas = folium.FeatureGroup(name="🔲 Zonas de cobertura", show=mostrar_zonas)
    fg_rutas = folium.FeatureGroup(name="🛣️ Rutas óptimas", show=mostrar_rutas_check)
    fg_tiendas = folium.FeatureGroup(name="🏪 Tiendas", show=mostrar_tiendas_check)
    fg_centroides = folium.FeatureGroup(name="📍 Centroides", show=mostrar_centroides)
    fg_noasig = folium.FeatureGroup(name="🚫 No asignadas", show=True)

    # 0) Tiendas NO asignadas
    if modo_manual:
        # Modo manual: puntos LIBRES en gris, clicables para asignarlos al grupo activo
        fg_libres = folium.FeatureGroup(name="🟢 Puntos libres", show=True)
        for idx, row in no_asignadas.iterrows():
            folium.CircleMarker(
                [row["latitud"], row["longitud"]],
                radius=7, color="#5a5a5a", weight=1.5,
                fill=True, fill_color="#c9c9c9", fill_opacity=0.9,
                tooltip=f"🟢 {row['name_sucursal']} · LIBRE · {int(row['cantidad_bultos'])} bultos",
                popup=folium.Popup(
                    f"<div style='font-family:Arial;font-size:13px;min-width:190px'>"
                    f"<b>{row['name_sucursal']}</b><br>"
                    f"Código: {row['codigo_sucursal']}<br>"
                    f"Distrito: {row['distrito']}<br>"
                    f"Bultos: {int(row['cantidad_bultos'])}<br>"
                    f"<b>🟢 Punto libre — clic para asignar al grupo "
                    f"{st.session_state.grupo_activo + 1}</b></div>", max_width=260),
            ).add_to(fg_libres)
        fg_libres.add_to(m)
    else:
        # Modo automático: tiendas sin cupo en la flota -> marcador rojo
        for idx, row in no_asignadas.iterrows():
            folium.CircleMarker(
                [row["latitud"], row["longitud"]],
                radius=8, color="#d62728", weight=3, dash_array="4",
                fill=True, fill_color="#ffffff", fill_opacity=0.9,
                tooltip=f"🚫 {row['name_sucursal']} · SIN RUTA",
                popup=folium.Popup(
                    f"<div style='font-family:Arial;font-size:13px;min-width:190px'>"
                    f"<b>🚫 {row['name_sucursal']}</b><br>"
                    f"Código: {row['codigo_sucursal']}<br>"
                    f"Distrito: {row['distrito']}<br>"
                    f"Bultos: {int(row['cantidad_bultos'])}<br>"
                    f"<b>No asignada: sin cupo en la flota</b></div>", max_width=260),
            ).add_to(fg_noasig)

    # 1) Zonas de cobertura (polígonos convex hull)
    if mostrar_zonas:
        for i in clusters_visibles:
            cluster_data = df[df["cluster"] == str(i)]
            if len(cluster_data) >= 3:
                puntos = cluster_data[["latitud", "longitud"]].values
                try:
                    hull = ConvexHull(puntos)
                    hull_pts = puntos[hull.vertices].tolist()
                    color_cluster = colores[i % len(colores)]
                    folium.Polygon(
                        locations=hull_pts,
                        color=color_cluster, weight=2,
                        fill=True, fill_color=color_cluster, fill_opacity=0.12,
                        tooltip=f"Zona del cluster {i}"
                    ).add_to(fg_zonas)
                except Exception:
                    pass

    # 2) Rutas óptimas (con animación opcional que muestra el sentido del recorrido)
    if rutas_validas:
        for i, ruta in st.session_state.rutas_calculadas.items():
            if i not in clusters_visibles:
                continue
            color_cluster = colores[i % len(colores)]
            coords = [(lat, lon) for lat, lon in ruta["coords_route"]]
            tooltip_ruta = (f"Ruta {i} — {ruta['distance_km']:.1f} km · "
                            f"{ruta['duration_min']:.0f} min")
            if animar_rutas:
                AntPath(coords, color=color_cluster, weight=5, opacity=0.9,
                        delay=800, dash_array=[12, 24],
                        tooltip=tooltip_ruta).add_to(fg_rutas)
            else:
                folium.PolyLine(coords, color=color_cluster, weight=4, opacity=0.9,
                                tooltip=tooltip_ruta).add_to(fg_rutas)

    # 3) Tiendas (con cluster de marcadores opcional para datasets grandes)
    if agrupar_marcadores:
        contenedor_tiendas = MarkerCluster(
            options={"maxClusterRadius": 45, "disableClusteringAtZoom": 15}
        ).add_to(fg_tiendas)
    else:
        contenedor_tiendas = fg_tiendas

    if mostrar_tiendas_check:
        for i in clusters_visibles:
            cluster_data = df[df["cluster"] == str(i)]
            if len(cluster_data) == 0:
                continue
            color_cluster = colores[i % len(colores)]

            tiene_orden = (rutas_validas and mostrar_numeros_orden
                           and i in st.session_state.rutas_calculadas)
            mapa_orden = {}
            if tiene_orden:
                orden = st.session_state.rutas_calculadas[i]["orden"]
                mapa_orden = {idx_global: pos + 1 for pos, idx_global in enumerate(orden)}

            for idx, row in cluster_data.iterrows():
                num = mapa_orden.get(idx, 0)
                es_prioritaria = int(row["prioridad"]) > 0
                orden_txt = f"<br>Orden de visita: <b>#{num}</b>" if num else ""
                prior_txt = (f"<br>⭐ <b>Prioridad: nivel {int(row['prioridad'])}</b>"
                             if es_prioritaria else "")
                eta_txt = ""
                if rutas_validas and i in st.session_state.rutas_calculadas:
                    eta_v = st.session_state.rutas_calculadas[i].get("etas", {}).get(idx)
                    if eta_v is not None:
                        eta_txt = f"<br>🕐 Llegada estimada: <b>{segundos_a_hora(eta_v)}</b>"
                vent_txt = ""
                if pd.notna(row["ventana_ini_s"]) and pd.notna(row["ventana_fin_s"]):
                    vent_txt = (f"<br>⏰ Ventana: {segundos_a_hora(row['ventana_ini_s'])}"
                                f"-{segundos_a_hora(row['ventana_fin_s'])}")
                popup_html = (
                    f"<div style='font-family:Arial;font-size:13px;min-width:190px'>"
                    f"<b>{row['name_sucursal']}</b><br>"
                    f"Código: {row['codigo_sucursal']}<br>"
                    f"Distrito: {row['distrito']}<br>"
                    f"Bultos: {int(row['cantidad_bultos'])}{prior_txt}{vent_txt}{eta_txt}<br>"
                    f"Cluster: {i}{orden_txt}<br>"
                    f"Lat: {row['latitud']:.5f} · Lon: {row['longitud']:.5f}</div>"
                )
                tooltip_txt = (("⭐ " if es_prioritaria else "") + f"{row['name_sucursal']}"
                               + (f" · #{num}" if num else ""))
                borde = "#FFD700" if es_prioritaria else "white"
                if num:
                    # Badge numerado con el color del cluster (borde dorado = prioritaria)
                    folium.Marker(
                        [row["latitud"], row["longitud"]],
                        icon=folium.DivIcon(
                            icon_size=(26, 26), icon_anchor=(13, 13),
                            html=(
                                f"<div style='background:{color_cluster};"
                                f"border:3px solid {borde};border-radius:50%;"
                                f"width:24px;height:24px;display:flex;align-items:center;"
                                f"justify-content:center;color:white;font-weight:bold;"
                                f"font-size:11px;font-family:Arial;"
                                f"box-shadow:0 1px 4px rgba(0,0,0,.5)'>{num}</div>"
                            )
                        ),
                        tooltip=tooltip_txt,
                        popup=folium.Popup(popup_html, max_width=260),
                    ).add_to(contenedor_tiendas)
                else:
                    folium.CircleMarker(
                        [row["latitud"], row["longitud"]],
                        radius=7 if es_prioritaria else 6,
                        color=borde, weight=3 if es_prioritaria else 1.5,
                        fill=True, fill_color=color_cluster, fill_opacity=0.95,
                        tooltip=tooltip_txt,
                        popup=folium.Popup(popup_html, max_width=260),
                    ).add_to(contenedor_tiendas)

    # 4) Centroides
    if mostrar_centroides:
        cv = df_centroides[df_centroides["cluster_num"].isin(clusters_visibles)]
        for _, row in cv.iterrows():
            folium.Marker(
                [row["latitud"], row["longitud"]],
                icon=folium.DivIcon(
                    icon_size=(30, 30), icon_anchor=(15, 15),
                    html=(
                        f"<div style='background:#1a1a1a;border:3px solid white;"
                        f"border-radius:50%;width:28px;height:28px;display:flex;"
                        f"align-items:center;justify-content:center;color:white;"
                        f"font-weight:bold;font-size:10px;font-family:Arial;"
                        f"box-shadow:0 1px 5px rgba(0,0,0,.6)'>C{int(row['cluster_num'])}</div>"
                    )
                ),
                tooltip=f"Centroide del cluster {int(row['cluster_num'])}",
            ).add_to(fg_centroides)

    # 5) Centro de Distribución (siempre visible)
    folium.Marker(
        [cd_lat, cd_lon],
        icon=folium.Icon(color="black", icon="industry", prefix="fa"),
        tooltip="🏭 Centro de Distribución (punto de partida)",
        popup=folium.Popup(
            f"<b>🏭 Centro de Distribución</b><br>Lat: {cd_lat:.5f}<br>Lon: {cd_lon:.5f}",
            max_width=220
        ),
    ).add_to(m)

    for fg in (fg_zonas, fg_rutas, fg_tiendas, fg_centroides):
        fg.add_to(m)
    if n_no_asignadas:
        fg_noasig.add_to(m)
    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    if modo_manual:
        # Herramientas de dibujo (rectángulo/polígono) para seleccionar por sectores
        Draw(
            draw_options={"polyline": False, "circle": False, "marker": False,
                          "circlemarker": False,
                          "rectangle": {"shapeOptions": {"color": "#F2A33C",
                                                         "fillOpacity": 0.12}},
                          "polygon": {"shapeOptions": {"color": "#F2A33C",
                                                       "fillOpacity": 0.12},
                                      "allowIntersection": False}},
            edit_options={"edit": False, "remove": True},
            position="topleft",
        ).add_to(m)

        # Mapa interactivo: capturamos el clic en una tienda para asignar/quitar
        # y el área dibujada para asignar/liberar sectores completos
        salida_mapa = st_folium(m, height=680, use_container_width=True,
                                returned_objects=["last_object_clicked",
                                                  "last_active_drawing"],
                                key="mapa_manual")

        # --- Selección por ÁREA dibujada (rectángulo o polígono) ---
        dibujo = (salida_mapa or {}).get("last_active_drawing")
        if dibujo and (dibujo.get("geometry") or {}).get("type") == "Polygon":
            anillo = dibujo["geometry"]["coordinates"][0]   # [[lon, lat], ...]
            g_act = st.session_state.grupo_activo
            liberar = str(st.session_state.get("accion_dibujo", "")).startswith("➖")
            # Firma incluye grupo y acción: el mismo trazo vale de nuevo si cambias de grupo
            firma_d = (g_act, liberar,
                       tuple((round(float(px), 6), round(float(py), 6)) for px, py in anillo))
            if st.session_state.get("ultimo_dibujo_manual") != firma_d:
                st.session_state.ultimo_dibujo_manual = firma_d
                dentro = puntos_en_poligono(df["latitud"].to_numpy(),
                                            df["longitud"].to_numpy(), anillo)
                idx_dentro = set(np.nonzero(dentro)[0].tolist())
                if idx_dentro:
                    grupos_m = st.session_state.grupos_manual
                    for g in grupos_m:
                        g.difference_update(idx_dentro)       # fuera de todos los grupos
                    if not liberar:
                        grupos_m[g_act].update(idx_dentro)    # y dentro del activo
                    st.toast(f"{'➖ Liberadas' if liberar else '➕ Asignadas'} "
                             f"{len(idx_dentro)} tiendas del sector dibujado.")
                    st.rerun(scope="fragment")

        # --- Selección por CLIC individual ---
        clic = (salida_mapa or {}).get("last_object_clicked")
        if clic and clic.get("lat") is not None:
            firma = (round(float(clic["lat"]), 6), round(float(clic["lng"]), 6))
            if st.session_state.get("ultimo_clic_manual") != firma:
                st.session_state.ultimo_clic_manual = firma
                _lats = df["latitud"].to_numpy()
                _lons = df["longitud"].to_numpy()
                d2 = (_lats - firma[0]) ** 2 + (_lons - firma[1]) ** 2
                i_sel = int(np.argmin(d2))
                if d2[i_sel] < (5e-4) ** 2:  # ~50 m: ignora clics que no son una tienda (p.ej. el CD)
                    grupos_m = st.session_state.grupos_manual
                    g_act = st.session_state.grupo_activo
                    if i_sel in grupos_m[g_act]:
                        grupos_m[g_act].discard(i_sel)        # ya estaba en el activo -> quitar
                    else:
                        for g in grupos_m:
                            g.discard(i_sel)                  # sacarla de cualquier otro grupo
                        grupos_m[g_act].add(i_sel)            # y ponerla en el activo
                    st.rerun(scope="fragment")

        # Contador en vivo del grupo activo (se actualiza al instante, sin
        # re-ejecutar el resto del script)
        _gm = st.session_state.grupos_manual
        _ga = st.session_state.grupo_activo
        _asig = set().union(*_gm) if _gm else set()
        _c1, _c2, _c3 = st.columns(3)
        _c1.metric(f"✋ Grupo {_ga + 1} (activo)", f"{len(_gm[_ga])} tiendas")
        _c2.metric("📦 Bultos del grupo",
                   int(pesos[list(_gm[_ga])].sum()) if _gm[_ga] else 0)
        _c3.metric("🟢 Libres / asignadas", f"{n_tiendas - len(_asig)} / {len(_asig)}")
    else:
        # returned_objects=[] -> el mapa no fuerza re-ejecuciones al interactuar (más fluido)
        st_folium(m, height=680, use_container_width=True, returned_objects=[])

    if modo_manual:
        g_act = st.session_state.grupo_activo
        st.caption(f"✋ **Selección manual** — clic en un punto **gris** para asignarlo al "
                   f"**Grupo {g_act + 1}**; clic en uno del grupo activo para quitarlo. "
                   f"⬛ **Dibuja un rectángulo o polígono** (botones a la izquierda del mapa) "
                   f"para seleccionar un sector completo de una vez. "
                   f"Cambia el grupo activo o crea otro en el panel de la izquierda. "
                   f"Usa **🤖 Auto-asignar** para que la herramienta complete los puntos libres.")
    elif modo_enfoque == "aislar":
        st.caption(f"🎯 **Modo aislado:** Cluster {clusters_visibles[0]}. Cambia el modo en el sidebar.")
    elif modo_enfoque == "solo_rutas":
        st.caption("🛣️ **Modo solo rutas:** zonas de cobertura ocultas.")
    elif rutas_validas:
        st.caption("💡 🏭 CD (negro) = punto de partida. **Líneas gruesas** = ruta. **Círculos numerados** = orden de visita.")
    else:
        st.caption("💡 Calcula las rutas óptimas desde el sidebar para ver el ruteo.")
    st.caption("🧭 Controles del mapa: **capas** (esquina superior derecha), **pantalla completa** y "
               "**regla de medición** (esquina superior izquierda), minimapa (abajo a la derecha). "
               "Haz **clic en una tienda** para ver su ficha completa.")

_render_mapa()

# ===========================================================
# DETALLE DE RUTAS
# ===========================================================
if rutas_validas:
    st.markdown("---")
    st.subheader("🚛 Detalle de rutas óptimas")
    motores_usados = {r.get("motor", "—") for r in st.session_state.rutas_calculadas.values()}
    st.caption("Motor de cálculo: " + " · ".join(sorted(motores_usados)))
    resumen_rutas = []
    for i, ruta in st.session_state.rutas_calculadas.items():
        cluster_data = df[df["cluster"] == str(i)]
        fila = {
            "Cluster": i,
            "Visible": "✅" if i in clusters_visibles else "—",
            "Tiendas": len(cluster_data),
            "Bultos": int(cluster_data["cantidad_bultos"].sum()),
            "⭐ Prioritarias": int((cluster_data["prioridad"] > 0).sum()),
            "Distancia (km)": round(ruta['distance_km'], 2),
            "Duración (min)": round(ruta['duration_min'], 1),
            "Inicio": segundos_a_hora(ruta.get("salida_s")),
            "Fin": segundos_a_hora(ruta.get("fin_s")),
            "Modo": "✏️ Personalizada" if ruta.get("personalizada") else "Óptima"
        }
        if hay_costos:
            fila[f"Costo ({moneda})"] = round(costo_fijo + ruta['distance_km'] * costo_km, 2)
        if info_flota and i in info_flota:
            cap_v = info_flota[i]["capacidad"]
            carga_v = int(cluster_data["cantidad_bultos"].sum())
            fila["Vehículo"] = f"{cap_v} bultos"
            fila["Uso"] = f"{carga_v}/{cap_v} ({100 * carga_v / cap_v:.0f}%)"
            fila["Vuelta"] = info_flota[i]["vuelta"]
        resumen_rutas.append(fila)
    df_resumen_rutas = pd.DataFrame(resumen_rutas)
    fila_total = {
        "Cluster": "TOTAL", "Visible": "",
        "Tiendas": df_resumen_rutas["Tiendas"].sum(),
        "Bultos": df_resumen_rutas["Bultos"].sum(),
        "⭐ Prioritarias": df_resumen_rutas["⭐ Prioritarias"].sum(),
        "Distancia (km)": round(df_resumen_rutas["Distancia (km)"].sum(), 2),
        "Duración (min)": round(df_resumen_rutas["Duración (min)"].sum(), 1),
        "Inicio": "", "Fin": "",
        "Modo": ""
    }
    if hay_costos:
        fila_total[f"Costo ({moneda})"] = round(df_resumen_rutas[f"Costo ({moneda})"].sum(), 2)
    df_resumen_rutas = pd.concat([df_resumen_rutas, pd.DataFrame([fila_total])],
                                 ignore_index=True)
    st.dataframe(df_resumen_rutas, use_container_width=True, hide_index=True)

    if hay_costos:
        costo_total = float(df_resumen_rutas[f"Costo ({moneda})"].iloc[-1])
        entregas = int(df_resumen_rutas["Tiendas"].iloc[-1])
        st.caption(f"💰 **Costo total estimado: {moneda} {costo_total:,.2f}** · "
                   f"costo por entrega: {moneda} {costo_total / max(entregas, 1):,.2f} · "
                   f"(fijo {moneda} {costo_fijo:,.2f}/vehículo + {moneda} {costo_km:,.2f}/km)")

    # ---- Guardar escenario para comparar ----
    if "escenarios" not in st.session_state:
        st.session_state.escenarios = []
    col_esc1, col_esc2 = st.columns([2, 1])
    with col_esc1:
        nombre_esc = st.text_input(
            "Nombre del escenario:",
            value=f"Escenario {len(st.session_state.escenarios) + 1}",
            key="nombre_escenario",
            help="Guarda esta corrida (rutas, km, costo) para compararla con otras "
                 "configuraciones de flota o capacidad.")
    with col_esc2:
        st.write("")
        st.write("")
        if st.button("💾 Guardar escenario", use_container_width=True):
            km_tot = float(sum(r['distance_km'] for r in st.session_state.rutas_calculadas.values()))
            dur_tot = float(sum(r['duration_min'] for r in st.session_state.rutas_calculadas.values()))
            fines = [r.get('fin_s') for r in st.session_state.rutas_calculadas.values()
                     if r.get('fin_s') is not None]
            n_rutas_esc = len(st.session_state.rutas_calculadas)
            esc = {
                "Escenario": nombre_esc,
                "Criterio": {"tiendas": "Máx. tiendas", "bultos": "Máx. bultos",
                             "flota": "Flota"}.get(criterio_cap, "K clásico"),
                "Rutas": n_rutas_esc,
                "Tiendas": int(sum(len(df[df["cluster"] == str(i)])
                                   for i in st.session_state.rutas_calculadas)),
                "Sin asignar": n_no_asignadas,
                "Km": round(km_tot, 1),
                "Horas": round(dur_tot / 60.0, 1),
                "Fin más tardío": segundos_a_hora(max(fines)) if fines else "—",
                "Motor": {"osrm": "OSRM", "haversine": "Haversine", "ors": "ORS"}[motor_ruteo],
            }
            if hay_costos:
                esc[f"Costo ({moneda})"] = round(n_rutas_esc * costo_fijo + km_tot * costo_km, 2)
            st.session_state.escenarios.append(esc)
            st.success(f"✅ '{nombre_esc}' guardado. Cambia la configuración, recalcula "
                       f"y guarda otro para comparar.")

    # Descarga consolidada de TODAS las rutas (útil con muchos grupos)
    todas_filas = []
    for i, ruta in st.session_state.rutas_calculadas.items():
        cluster_data = df[df["cluster"] == str(i)]
        for pos, idx_global in enumerate(ruta['orden'], start=1):
            if idx_global in cluster_data.index:
                row = cluster_data.loc[idx_global]
                todas_filas.append({
                    "Cluster": i, "Orden": pos,
                    "Código": row["codigo_sucursal"], "Tienda": row["name_sucursal"],
                    "Distrito": row["distrito"],
                    "Bultos": int(row["cantidad_bultos"]),
                    "Prioridad": int(row["prioridad"]),
                    "Llegada (ETA)": segundos_a_hora(ruta.get("etas", {}).get(idx_global)),
                    "Latitud": round(row["latitud"], 6), "Longitud": round(row["longitud"], 6)
                })
    if todas_filas:
        csv_todas = pd.DataFrame(todas_filas).to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Descargar TODAS las rutas (CSV)", data=csv_todas,
            file_name="rutas_todas.csv", mime="text/csv")

    rutas_visibles_dict = {i: r for i, r in st.session_state.rutas_calculadas.items()
                           if i in clusters_visibles}
    if rutas_visibles_dict and len(rutas_visibles_dict) <= 30:
        tabs = st.tabs([f"Cluster {i}" for i in rutas_visibles_dict.keys()])
        for tab_idx, (i, ruta) in enumerate(rutas_visibles_dict.items()):
            with tabs[tab_idx]:
                cluster_data = df[df["cluster"] == str(i)].copy()
                orden = ruta['orden']
                secuencia = []
                for pos, idx_global in enumerate(orden, start=1):
                    if idx_global in cluster_data.index:
                        row = cluster_data.loc[idx_global]
                        eta = ruta.get("etas", {}).get(idx_global)
                        if pd.notna(row["ventana_ini_s"]) and pd.notna(row["ventana_fin_s"]):
                            ventana_txt = (f"{segundos_a_hora(row['ventana_ini_s'])}-"
                                           f"{segundos_a_hora(row['ventana_fin_s'])}")
                        else:
                            ventana_txt = "—"
                        secuencia.append({
                            "Orden": pos,
                            "Código": row["codigo_sucursal"],
                            "Tienda": row["name_sucursal"],
                            "Distrito": row["distrito"],
                            "Bultos": int(row["cantidad_bultos"]),
                            "Prioridad": "⭐ " + str(int(row["prioridad"])) if row["prioridad"] > 0 else "—",
                            "Llegada (ETA)": segundos_a_hora(eta),
                            "Ventana": ventana_txt,
                            "Latitud": round(row["latitud"], 5),
                            "Longitud": round(row["longitud"], 5)
                        })
                df_seq = pd.DataFrame(secuencia)
                bultos_ruta = int(cluster_data["cantidad_bultos"].sum())
                st.markdown(f"**Distancia:** {ruta['distance_km']:.2f} km — "
                            f"**Duración:** {ruta['duration_min']:.1f} min — "
                            f"**Bultos:** {bultos_ruta} — "
                            f"*{ruta.get('motor', '')}*")
                st.dataframe(df_seq, use_container_width=True, hide_index=True)
                csv_ruta = df_seq.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label=f"⬇️ Descargar ruta Cluster {i} (CSV)",
                    data=csv_ruta, file_name=f"ruta_cluster_{i}.csv",
                    mime="text/csv", key=f"download_ruta_{i}"
                )
    elif len(rutas_visibles_dict) > 30:
        st.info("ℹ️ Hay más de 30 rutas visibles: usa la descarga consolidada de arriba "
                "o aísla un cluster para ver su detalle.")

    # -------------------------------------------------------
    # HOJA DE RUTA PARA CONDUCTORES
    # -------------------------------------------------------
    st.markdown("---")
    st.subheader("🖨️ Hoja de ruta para conductores")
    st.caption("Descarga la hoja de ruta con horarios estimados y links de navegación: "
               "**Google Maps** abre los tramos con las paradas en orden, **Waze** navega "
               "a cada tienda, y el **QR** deja que el chofer abra su ruta desde el celular.")

    def _filas_hoja(i, ruta):
        cdat = df[df["cluster"] == str(i)]
        filas = []
        for pos, idx_g in enumerate(ruta["orden"], start=1):
            if idx_g not in cdat.index:
                continue
            row = cdat.loc[idx_g]
            if pd.notna(row["ventana_ini_s"]) and pd.notna(row["ventana_fin_s"]):
                vent = f"{segundos_a_hora(row['ventana_ini_s'])}-{segundos_a_hora(row['ventana_fin_s'])}"
            else:
                vent = ""
            filas.append({
                "Orden": pos, "Código": row["codigo_sucursal"],
                "Tienda": str(row["name_sucursal"]), "Distrito": str(row["distrito"]),
                "Bultos": int(row["cantidad_bultos"]),
                "ETA": segundos_a_hora(ruta.get("etas", {}).get(idx_g)),
                "Ventana": vent,
                "Prioridad": int(row["prioridad"]),
                "Latitud": float(row["latitud"]), "Longitud": float(row["longitud"]),
            })
        return filas

    def _coords_hoja(i, ruta):
        filas = _filas_hoja(i, ruta)
        coords = [(cd_lat, cd_lon)] + [(f["Latitud"], f["Longitud"]) for f in filas]
        if tipo_recorrido == "cerrado":
            coords.append((cd_lat, cd_lon))
        return coords

    # ---- Excel multi-hoja (una hoja por ruta) ----
    buf_xl = BytesIO()
    with pd.ExcelWriter(buf_xl, engine="openpyxl") as writer:
        df_resumen_rutas.to_excel(writer, index=False, sheet_name="Resumen")
        for i, ruta in st.session_state.rutas_calculadas.items():
            filas = _filas_hoja(i, ruta)
            if filas:
                pd.DataFrame(filas).to_excel(writer, index=False, sheet_name=f"Ruta_{i}")

    # ---- HTML imprimible con links ----
    bloques = []
    for i, ruta in st.session_state.rutas_calculadas.items():
        filas = _filas_hoja(i, ruta)
        if not filas:
            continue
        veh_txt = ""
        if info_flota and i in info_flota:
            veh_txt = (f" · Vehículo: {info_flota[i]['capacidad']} bultos"
                       f" · Vuelta {info_flota[i]['vuelta']}")
        costo_txt = (f" · Costo: {moneda} {costo_fijo + ruta['distance_km'] * costo_km:,.2f}"
                     if hay_costos else "")
        enlaces_gm = links_google_maps(_coords_hoja(i, ruta))
        links_html = " · ".join(
            f"<a href='{u}'>🗺️ Google Maps tramo {t + 1}</a>" for t, u in enumerate(enlaces_gm))
        filas_html = "".join(
            f"<tr><td>{f['Orden']}</td><td>{f['Código']}</td><td>{f['Tienda']}</td>"
            f"<td>{f['Distrito']}</td><td>{f['Bultos']}</td><td>{f['ETA']}</td>"
            f"<td>{f['Ventana']}</td>"
            f"<td><a href='{link_waze(f['Latitud'], f['Longitud'])}'>Waze</a></td></tr>"
            for f in filas)
        bloques.append(f"""
        <div class="ruta">
          <h2>Ruta {i}{veh_txt}</h2>
          <p><b>Salida CD:</b> {segundos_a_hora(ruta.get('salida_s'))} ·
             <b>Fin estimado:</b> {segundos_a_hora(ruta.get('fin_s'))} ·
             <b>Distancia:</b> {ruta['distance_km']:.1f} km ·
             <b>Duración:</b> {ruta['duration_min']:.0f} min{costo_txt}</p>
          <p>{links_html}</p>
          <table><tr><th>#</th><th>Código</th><th>Tienda</th><th>Distrito</th>
          <th>Bultos</th><th>ETA</th><th>Ventana</th><th>Navegar</th></tr>{filas_html}</table>
        </div>""")
    html_doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <title>Hojas de ruta — {_dt.date.today().isoformat()}</title><style>
    body{{font-family:Arial,sans-serif;margin:24px;color:#111}}
    h1{{font-size:20px}} h2{{font-size:16px;margin-bottom:4px}}
    table{{border-collapse:collapse;width:100%;font-size:12px;margin-top:6px}}
    th,td{{border:1px solid #999;padding:4px 6px;text-align:left}}
    th{{background:#eee}} .ruta{{page-break-after:always;margin-bottom:28px}}
    @media print{{a{{color:#111;text-decoration:none}}}}
    </style></head><body>
    <h1>🚛 Hojas de ruta — {_dt.date.today().strftime('%d/%m/%Y')} —
    Salida {segundos_a_hora(salida_s)}</h1>
    {''.join(bloques)}</body></html>"""

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.download_button("📊 Hoja de ruta Excel (una hoja por vehículo)",
            data=buf_xl.getvalue(), file_name="hojas_de_ruta.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True)
    with col_d2:
        st.download_button("📄 Hoja de ruta imprimible (HTML con links)",
            data=html_doc.encode("utf-8"), file_name="hojas_de_ruta.html",
            mime="text/html", use_container_width=True,
            help="Ábrela en el navegador e imprímela (Ctrl+P) o guárdala como PDF. "
                 "Cada ruta sale en su propia página con sus links de navegación.")

    # ---- Links y QR por ruta ----
    ruta_hoja = st.selectbox("Ver links y QR de la ruta:",
        options=list(st.session_state.rutas_calculadas.keys()),
        format_func=lambda x: f"Ruta {x}", key="ruta_hoja_sel")
    enlaces_sel = links_google_maps(_coords_hoja(ruta_hoja, st.session_state.rutas_calculadas[ruta_hoja]))
    cols_qr = st.columns(max(len(enlaces_sel), 1))
    for t, (col_qr, url) in enumerate(zip(cols_qr, enlaces_sel)):
        with col_qr:
            st.markdown(f"**[🗺️ Abrir tramo {t + 1} en Google Maps]({url})**")
            if QR_DISPONIBLE:
                buf_qr = BytesIO()
                qrcode.make(url).get_image().save(buf_qr, format="PNG")
                st.image(buf_qr.getvalue(), width=180,
                         caption=f"Ruta {ruta_hoja} · tramo {t + 1}")
    if not QR_DISPONIBLE:
        st.caption("ℹ️ Para ver códigos QR agrega `qrcode` a requirements.txt.")

    # -------------------------------------------------------
    # ENVÍO A GOOGLE SHEETS (app de choferes en AppSheet)
    # -------------------------------------------------------
    st.markdown("---")
    st.subheader("📤 Asignar rutas → Google Sheets (app de choferes)")
    st.caption("Envía el despacho a tu hoja de Google Sheets en las pestañas **Rutas** y "
               "**Paradas** (se crean solas con sus encabezados). Tu app de AppSheet lee "
               "esa hoja: los choferes marcan cada entrega con **foto, GPS y hora**. "
               "El envío es *solo-agregar* con IDs únicos por despacho: nunca pisa lo que "
               "los choferes ya registraron.")

    if not GSHEETS_DISPONIBLE:
        st.info("Para activar esta función agrega `gspread` y `google-auth` a "
                "requirements.txt (ya incluidos en la versión actual del repo).")
    else:
        url_defecto = leer_secret("gsheets_url", "")
        url_hoja = st.text_input(
            "URL de tu hoja de Google Sheets:", value=url_defecto,
            placeholder="https://docs.google.com/spreadsheets/d/…",
            help="La hoja debe estar compartida (como Editor) con el correo de la "
                 "cuenta de servicio configurada en los secrets. Ver guía SETUP_APPSHEET.md.")
        tiene_credenciales = bool(leer_secret("gcp_service_account", None) is not None
                                  and leer_secret("gcp_service_account", {}) != {})
        if not tiene_credenciales:
            st.warning("🔐 Falta configurar la cuenta de servicio en los **secrets** de "
                       "Streamlit (sección `[gcp_service_account]`). Sigue la guía "
                       "**SETUP_APPSHEET.md** del repositorio — es una configuración de "
                       "una sola vez (~10 min).")

        if st.button("🚀 Asignar y enviar rutas a Google Sheets",
                     type="primary", disabled=not (url_hoja and tiene_credenciales)):
            try:
                with st.spinner("Enviando despacho a Google Sheets..."):
                    gc = conectar_gsheets()
                    libro = gc.open_by_key(extraer_id_hoja(url_hoja))
                    ws_rutas = asegurar_pestana(libro, "Rutas", RUTAS_HEADERS)
                    ws_paradas = asegurar_pestana(libro, "Paradas", PARADAS_HEADERS)

                    id_despacho = _dt.datetime.now().strftime("%Y%m%d-%H%M")
                    fecha_hoy = _dt.date.today().isoformat()
                    filas_rutas, filas_paradas = [], []
                    for i, ruta in st.session_state.rutas_calculadas.items():
                        filas = _filas_hoja(i, ruta)
                        if not filas:
                            continue
                        id_ruta = f"{id_despacho}-R{i}"
                        veh_txt = (f"{info_flota[i]['capacidad']} bultos"
                                   if info_flota and i in info_flota else "")
                        vuelta_v = (info_flota[i]["vuelta"]
                                    if info_flota and i in info_flota else 1)
                        enlaces = links_google_maps(_coords_hoja(i, ruta))
                        costo_v = (round(costo_fijo + ruta["distance_km"] * costo_km, 2)
                                   if hay_costos else "")
                        filas_rutas.append([
                            id_ruta, id_despacho, fecha_hoy, i, veh_txt, vuelta_v, "",
                            segundos_a_hora(ruta.get("salida_s")),
                            segundos_a_hora(ruta.get("fin_s")),
                            round(ruta["distance_km"], 2),
                            round(ruta["duration_min"], 1), costo_v,
                            len(filas), int(sum(f["Bultos"] for f in filas)),
                            "Planificada", enlaces[0] if enlaces else "",
                        ])
                        for f in filas:
                            filas_paradas.append([
                                f"{id_ruta}-P{f['Orden']:02d}", id_ruta, f["Orden"],
                                str(f["Código"]), f["Tienda"], f["Distrito"],
                                f["Bultos"], f["Prioridad"], f["ETA"], f["Ventana"],
                                f"{f['Latitud']:.6f},{f['Longitud']:.6f}",
                                f["Latitud"], f["Longitud"],
                                link_waze(f["Latitud"], f["Longitud"]),
                                "Pendiente", "", "", "", "",
                            ])
                    ws_rutas.append_rows(filas_rutas, value_input_option="USER_ENTERED")
                    ws_paradas.append_rows(filas_paradas, value_input_option="USER_ENTERED")

                    # Registro en el HISTORIAL (una fila por despacho)
                    ws_hist = asegurar_pestana(libro, "Historial", HISTORIAL_HEADERS)
                    km_tot_h = round(sum(r["distance_km"]
                                         for r in st.session_state.rutas_calculadas.values()), 2)
                    dur_tot_h = round(sum(r["duration_min"]
                                          for r in st.session_state.rutas_calculadas.values()), 1)
                    costo_tot_h = (round(len(filas_rutas) * costo_fijo + km_tot_h * costo_km, 2)
                                   if hay_costos else "")
                    ws_hist.append_row([
                        id_despacho, fecha_hoy, _dt.datetime.now().strftime("%H:%M"),
                        usuario_actual, modo_cluster, criterio_cap, len(filas_rutas),
                        int(sum(r[12] for r in filas_rutas)),
                        int(sum(r[13] for r in filas_rutas)),
                        km_tot_h, dur_tot_h, costo_tot_h, motor_ruteo, int(n_no_asignadas),
                    ], value_input_option="USER_ENTERED")
                st.success(f"✅ Despacho **{id_despacho}** enviado: {len(filas_rutas)} rutas "
                           f"y {len(filas_paradas)} paradas. Registrado en el historial "
                           f"por **{usuario_actual}**. Ya está disponible en tu app de AppSheet.")
                st.markdown(f"[📗 Abrir la hoja de Google Sheets]({url_hoja})")
            except KeyError:
                st.error("🔐 No encontré `[gcp_service_account]` en los secrets de "
                         "Streamlit. Sigue la guía SETUP_APPSHEET.md (paso B).")
            except gspread.exceptions.APIError as e:
                st.error(f"Error de la API de Google Sheets: {e}. Verifica que la hoja "
                         f"esté compartida como **Editor** con el correo de la cuenta "
                         f"de servicio y que la API de Sheets esté habilitada.")
            except Exception as e:
                st.error(f"No se pudo enviar: {type(e).__name__}: {e}")

    # -------------------------------------------------------
    # EDITOR DE RUTAS — personalizar el orden de visita
    # -------------------------------------------------------
    st.markdown("---")
    st.subheader("✏️ Personalizar una ruta (orden manual)")
    st.caption("Cambia los números de la columna **Orden** y aplica: la ruta se recalcula "
               "(distancia, duración y trazado en el mapa) con tu secuencia. "
               "El mapa no permite arrastrar tiendas directamente, así que este editor es el "
               "equivalente: identifica la tienda haciendo clic en el mapa y muévela aquí.")

    if st.session_state.get("flash_ruta"):
        st.success(st.session_state.pop("flash_ruta"))

    cluster_editar = st.selectbox(
        "Ruta a personalizar:",
        options=list(st.session_state.rutas_calculadas.keys()),
        format_func=lambda x: f"Cluster {x}"
        + (" · ✏️ ya personalizada" if st.session_state.rutas_calculadas[x].get("personalizada") else ""),
        key="cluster_editar"
    )
    ruta_e = st.session_state.rutas_calculadas[cluster_editar]
    cdata_e = df[df["cluster"] == str(cluster_editar)]
    filas_edit = []
    for pos, idx_global in enumerate(ruta_e["orden"], start=1):
        if idx_global in cdata_e.index:
            row = cdata_e.loc[idx_global]
            filas_edit.append({
                "Orden": pos, "_idx": idx_global,
                "Código": row["codigo_sucursal"], "Tienda": row["name_sucursal"],
                "Distrito": row["distrito"],
                "Bultos": int(row["cantidad_bultos"]),
                "Prioridad": int(row["prioridad"]),
            })
    df_edit = pd.DataFrame(filas_edit)
    n_paradas = len(df_edit)

    editado = st.data_editor(
        df_edit,
        column_config={
            "Orden": st.column_config.NumberColumn(
                "Orden", min_value=1, max_value=n_paradas, step=1,
                help="Cambia el número para mover la tienda a otra posición de la ruta"),
            "_idx": None,
        },
        disabled=["Código", "Tienda", "Distrito", "Bultos", "Prioridad"],
        hide_index=True, use_container_width=True,
        key=f"editor_ruta_{cluster_editar}_{config_actual}"
    )

    col_e1, col_e2 = st.columns([1, 2])
    with col_e1:
        aplicar_orden = st.button("✅ Aplicar orden personalizado",
                                  type="primary", use_container_width=True)
    with col_e2:
        st.caption(f"Actual: {ruta_e['distance_km']:.2f} km · {ruta_e['duration_min']:.1f} min · "
                   f"{ruta_e.get('motor', '')}")

    if aplicar_orden:
        ordenes = [int(o) if pd.notna(o) else -1 for o in editado["Orden"]]
        if sorted(ordenes) != list(range(1, n_paradas + 1)):
            st.error(f"⚠️ La columna Orden debe contener los números 1 a {n_paradas} "
                     f"sin repetir ni dejar vacíos. Revisa los valores e intenta de nuevo.")
        else:
            nuevo_orden = (editado.assign(_orden=ordenes)
                           .sort_values("_orden")["_idx"].tolist())
            serv_map_e = {idx: servicio_base * 60.0 + float(cdata_e.loc[idx, "cantidad_bultos"]) * servicio_bulto * 60.0
                          for idx in nuevo_orden}
            with st.spinner("Recalculando la ruta con tu orden..."):
                nueva = evaluar_orden_personalizado(
                    cdata_e, cd_lat, cd_lon, nuevo_orden,
                    cerrado=(tipo_recorrido == "cerrado"),
                    servicio_map=serv_map_e, salida_cd_s=salida_s)
            st.session_state.rutas_calculadas[cluster_editar] = nueva
            st.session_state.flash_ruta = (
                f"✅ Ruta del cluster {cluster_editar} actualizada con tu orden: "
                f"{nueva['distance_km']:.2f} km · {nueva['duration_min']:.1f} min")
            st.rerun()

# ===========================================================
# RESTO
# ===========================================================
# ===========================================================
# TIENDAS NO ASIGNADAS (modo flota)
# ===========================================================
if n_no_asignadas and modo_manual:
    st.markdown("---")
    st.subheader(f"🟢 Puntos libres ({n_no_asignadas})")
    st.info(f"Aún quedan {n_no_asignadas} tiendas sin asignar "
            f"({int(no_asignadas['cantidad_bultos'].sum()):,} bultos). Selecciónalas en "
            f"el mapa para sumarlas a un grupo, o usa **🤖 Auto-asignar puntos libres** "
            f"en el panel izquierdo para que la herramienta las agrupe sola.")
    df_libres_ver = no_asignadas[["codigo_sucursal", "name_sucursal", "distrito",
                                  "cantidad_bultos", "prioridad", "latitud", "longitud"]]
    st.dataframe(df_libres_ver, use_container_width=True, hide_index=True, height=240)
elif n_no_asignadas:
    st.markdown("---")
    st.subheader(f"🚫 Tiendas no asignadas ({n_no_asignadas})")
    st.warning(f"Estas {n_no_asignadas} tiendas (con "
               f"{int(no_asignadas['cantidad_bultos'].sum()):,} bultos en total) no "
               f"entraron en ninguna ruta porque la flota no tiene capacidad "
               f"suficiente. Las tiendas prioritarias se asignan primero, así que "
               f"las excluidas son siempre las de menor prioridad.")
    df_noasig_ver = no_asignadas[["codigo_sucursal", "name_sucursal", "distrito",
                                  "cantidad_bultos", "prioridad", "latitud", "longitud"]]
    st.dataframe(df_noasig_ver, use_container_width=True, hide_index=True, height=240)
    st.download_button(
        "⬇️ Descargar tiendas no asignadas (CSV)",
        data=df_noasig_ver.to_csv(index=False).encode("utf-8"),
        file_name="tiendas_no_asignadas.csv", mime="text/csv",
        help="Este CSV tiene el formato de la plantilla: puedes volver a subirlo "
             "mañana como dataset para planificar su despacho."
    )
    with st.expander("💡 ¿Qué hacer con las tiendas no asignadas?", expanded=True):
        st.markdown("""
        | Opción | Cómo hacerlo en la app |
        |---|---|
        | 🔁 **Segunda vuelta de la flota** | Sube el slider "Vueltas máximas de la flota" a 2 o 3: los mismos vehículos salen de nuevo para las pendientes. |
        | 🚛 **Ampliar la flota** | Agrega una fila en la tabla de flota (ej. un camión alquilado de 400 bultos) o sube la capacidad de un tipo. |
        | 📅 **Despachar al día siguiente** | Descarga el CSV de no asignadas y súbelo mañana como dataset: la app planifica solo esas tiendas. |
        | ⭐ **Proteger las críticas** | Marca con `prioridad = 1` las tiendas que NUNCA deben quedar fuera: el algoritmo las asigna primero. |
        | 🤝 **Tercerizar el excedente** | El CSV de no asignadas (con bultos y coordenadas) es justo lo que necesitas enviarle a un transportista externo. |
        """)

# ===========================================================
# COMPARADOR DE ESCENARIOS
# ===========================================================
if st.session_state.get("escenarios"):
    st.markdown("---")
    st.subheader("⚖️ Comparador de escenarios")
    st.caption("Corridas guardadas en esta sesión. Cambia la flota/capacidad/motor, "
               "recalcula las rutas y guarda otro escenario para comparar lado a lado. "
               "(Se borran al recargar la página.)")
    df_esc = pd.DataFrame(st.session_state.escenarios)
    st.dataframe(df_esc, use_container_width=True, hide_index=True)
    col_e1, col_e2 = st.columns([1, 3])
    with col_e1:
        if st.button("🗑️ Limpiar escenarios", use_container_width=True):
            st.session_state.escenarios = []
            st.rerun()
    with col_e2:
        st.download_button("⬇️ Descargar comparativa (CSV)",
            data=df_esc.to_csv(index=False).encode("utf-8"),
            file_name="comparativa_escenarios.csv", mime="text/csv")

st.markdown("---")
st.subheader("📊 Resumen general por cluster")
resumen = df[df["cluster"] != "-1"].groupby("cluster").agg(
    cantidad_tiendas=("codigo_sucursal", "count"),
    total_bultos=("cantidad_bultos", "sum"),
    tiendas_prioritarias=("prioridad", lambda s: int((s > 0).sum())),
    lat_centro=("latitud", "mean"),
    lon_centro=("longitud", "mean")
).reset_index()
st.dataframe(resumen, use_container_width=True)

if mostrar_codo and K >= 2 and n_tiendas > 3:
    st.subheader("📈 Selección del K óptimo")

    @st.cache_data(show_spinner="Calculando curvas de codo y silhouette...")
    def curvas_codo(ds_id, n):
        max_k = min(MAX_K, n - 1)
        paso = max(1, max_k // 25)
        ks = list(range(2, max_k + 1, paso))
        inercias, silhouettes = [], []
        muestra = min(1500, n)
        for k in ks:
            km_tmp = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=10)
            labels_tmp = km_tmp.fit_predict(Xm)
            inercias.append(km_tmp.inertia_)
            if len(np.unique(labels_tmp)) > 1:
                silhouettes.append(silhouette_score(Xm, labels_tmp, sample_size=muestra, random_state=42))
            else:
                silhouettes.append(np.nan)
        return ks, inercias, silhouettes

    K_range, inercias, silhouettes = curvas_codo(dataset_id, n_tiendas)
    col_a, col_b = st.columns(2)
    with col_a:
        fig_codo = px.line(x=K_range, y=inercias, markers=True,
                           labels={"x": "K", "y": "Inercia (WCSS)"}, title="Método del Codo")
        fig_codo.add_vline(x=K, line_dash="dash", line_color="red", annotation_text=f"K = {K}")
        st.plotly_chart(fig_codo, use_container_width=True)
    with col_b:
        fig_sil = px.line(x=K_range, y=silhouettes, markers=True,
                          labels={"x": "K", "y": "Silhouette Score"}, title="Silhouette por K")
        fig_sil.add_vline(x=K, line_dash="dash", line_color="red", annotation_text=f"K = {K}")
        st.plotly_chart(fig_sil, use_container_width=True)

if mostrar_metricas and K >= 2 and mask_asig.sum() > K:
    st.subheader("📐 Interpretación de las métricas")
    muestra_sil = min(2000, int(mask_asig.sum()))
    st.markdown("""
    | Métrica | Valor | Interpretación |
    |---|---|---|
    | **Silhouette Score** | {:.3f} | Va de -1 a 1. Más cercano a 1 = clusters mejor separados. |
    | **Davies-Bouldin** | {:.3f} | Más bajo = mejor (clusters compactos y separados). |
    """.format(
        silhouette_score(Xm[mask_asig], df.loc[mask_asig, "cluster"], sample_size=muestra_sil, random_state=42),
        davies_bouldin_score(Xm[mask_asig], df.loc[mask_asig, "cluster"])
    ))
    if modo_cluster == "capacidad":
        st.caption("ℹ️ En modo balanceado el Silhouette puede ser algo menor que en K-Means libre: "
                   "se sacrifica un poco de 'pureza geométrica' a cambio de grupos del mismo tamaño, "
                   "que es lo que necesita la operación de despacho.")

st.markdown("---")
st.subheader("📋 Detalle de tiendas asignadas a cada cluster")
df_descarga = df[["codigo_sucursal", "name_sucursal", "distrito", "cantidad_bultos",
                  "prioridad", "latitud", "longitud", "cluster"]].copy().sort_values(["cluster", "name_sucursal"])
st.dataframe(df_descarga, use_container_width=True, height=400)
csv = df_descarga.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Descargar resultados (CSV)", data=csv,
    file_name=f"tiendas_agrupadas_K{K}.csv", mime="text/csv")

st.markdown("---")
st.subheader("🆕 Predecir el cluster de una tienda NUEVA (modelo KNN)")
st.caption("Ingresa las coordenadas y el clasificador KNN te dirá a qué grupo pertenece.")
col_n1, col_n2, col_n3 = st.columns([1, 1, 1])
with col_n1:
    nueva_lat = st.number_input("Latitud", value=-12.18, format="%.6f", key="pred_lat")
with col_n2:
    nueva_lon = st.number_input("Longitud", value=-76.96, format="%.6f", key="pred_lon")
with col_n3:
    if st.button("🔍 Predecir cluster", use_container_width=True):
        from sklearn.neighbors import KNeighborsClassifier
        mask_knn = (df["cluster"] != "-1").values
        knn_actual = KNeighborsClassifier(n_neighbors=min(3, int(mask_knn.sum())))
        knn_actual.fit(Xm[mask_knn], df.loc[mask_knn, "cluster"].astype(int))
        # proyectar la nueva coordenada con la MISMA referencia que el dataset
        lat0 = np.radians(df["latitud"].mean())
        nueva_xy = [[np.radians(nueva_lon) * R_TIERRA * np.cos(lat0),
                     np.radians(nueva_lat) * R_TIERRA]]
        pred = knn_actual.predict(nueva_xy)[0]
        st.success(f"La nueva tienda pertenece al **Cluster {pred}**")

st.markdown("---")
st.markdown(f"""
<div class="rt-foot">
  <b>🏪 RuteoTiendas planner</b> · Proyecto académico — Proceso de Aprendizaje 2 — ISIL<br>
  Modelos: <b>K-Means balanceado + KNN</b> · Ruteo: <b>Google OR-Tools</b> (local) + OSRM / OpenRouteService
  · <a href="{URL_COLAB}" target="_blank">Ver cuaderno de código (Google Colab)</a>
</div>
""", unsafe_allow_html=True)
