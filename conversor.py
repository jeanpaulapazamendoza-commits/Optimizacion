"""
conversor.py — Sección "Conversor de direcciones ↔ coordenadas" para la app de ruteo.

Se integra con `app.py` mediante `render_conversor()`. Usa la librería local
`geocodificador.py` (Nominatim gratis / Google opcional) y reutiliza folium +
st_folium que ya trae la app.

Flujo:
  * Configuración de proveedor (Nominatim / Google + API key) y país.
  * Conversión puntual (una dirección o una coordenada) con mini-mapa.
  * Conversión por archivo (CSV/Excel) con plantilla de muestra descargable,
    tabla de resultados EDITABLE (ajuste dinámico de lat/lon) y mapa de revisión.
"""
from io import BytesIO

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Fullscreen
from streamlit_folium import st_folium

from geocodificador import (
    geocode, reverse_geocode, es_coordenada, GeoError,
)

# Claves de session_state propias (prefijo conv_ para no chocar con la app de ruteo).
_K_RES = "conv_resultado"        # DataFrame de resultados del lote


# ---------------------------------------------------------------------------
# Plantillas de muestra
# ---------------------------------------------------------------------------

def _plantilla_direcciones() -> pd.DataFrame:
    """Plantilla para DIRECCIÓN → coordenadas (columna de texto)."""
    return pd.DataFrame({
        "codigo_cliente": [1, 2, 3],
        "nombre": ["Cliente A", "Cliente B", "Cliente C"],
        "direccion": [
            "Av. Javier Prado Este 4200, Surco, Lima, Perú",
            "Jr. de la Unión 800, Cercado de Lima, Perú",
            "Av. Arequipa 1000, Lima, Perú",
        ],
    })


def _plantilla_coordenadas() -> pd.DataFrame:
    """Plantilla para COORDENADAS → dirección (columnas lat/lon)."""
    return pd.DataFrame({
        "codigo_cliente": [1, 2, 3],
        "nombre": ["Cliente A", "Cliente B", "Cliente C"],
        "latitud": [-12.046374, -12.119860, -12.097980],
        "longitud": [-77.042793, -77.029350, -77.036430],
    })


@st.cache_data
def _excel_bytes(df: pd.DataFrame, hoja: str = "datos") -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=hoja)
    return buffer.getvalue()


def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


# ---------------------------------------------------------------------------
# Mapa de revisión
# ---------------------------------------------------------------------------

def _mapa_resultados(df: pd.DataFrame, key: str):
    """Dibuja los puntos válidos del DataFrame (columnas lat/lon) en un folium."""
    validos = df.dropna(subset=["lat", "lon"])
    validos = validos[(validos["lat"].between(-90, 90)) &
                      (validos["lon"].between(-180, 180))]
    if validos.empty:
        st.info("No hay coordenadas válidas para mostrar en el mapa.")
        return

    centro = [validos["lat"].mean(), validos["lon"].mean()]
    m = folium.Map(location=centro, zoom_start=12, tiles="cartodbpositron")
    Fullscreen().add_to(m)
    for _, fila in validos.iterrows():
        etiqueta = str(fila.get("direccion") or fila.get("entrada") or "")
        folium.Marker(
            [fila["lat"], fila["lon"]],
            tooltip=f"{fila['lat']:.6f}, {fila['lon']:.6f}",
            popup=folium.Popup(etiqueta[:200], max_width=280),
            icon=folium.Icon(color="blue", icon="map-pin", prefix="fa"),
        ).add_to(m)
    if len(validos) > 1:
        m.fit_bounds(validos[["lat", "lon"]].values.tolist())
    st_folium(m, height=420, use_container_width=True, key=key,
              returned_objects=[])


# ---------------------------------------------------------------------------
# Conversión puntual
# ---------------------------------------------------------------------------

def _bloque_puntual(prov_kw: dict, pais):
    sub1, sub2 = st.tabs(["📍 Dirección → Coordenadas", "🏠 Coordenadas → Dirección"])

    with sub1:
        direccion = st.text_input(
            "Dirección a buscar",
            placeholder="Av. Javier Prado Este 4200, Lima, Perú", key="conv_dir_txt")
        if st.button("Buscar coordenadas", type="primary",
                     disabled=not direccion, key="conv_btn_geo"):
            try:
                with st.spinner("Geocodificando…"):
                    r = geocode(direccion, pais=pais, **prov_kw)
                c1, c2, c3 = st.columns(3)
                c1.metric("Latitud", f"{r.lat:.6f}")
                c2.metric("Longitud", f"{r.lon:.6f}")
                c3.metric("Proveedor", r.proveedor)
                st.code(r.coords_str(), language=None)
                st.success(r.direccion)
                _mapa_resultados(
                    pd.DataFrame([{"lat": r.lat, "lon": r.lon,
                                   "direccion": r.direccion}]), key="conv_map_geo")
            except GeoError as e:
                st.error(str(e))

    with sub2:
        c1, c2 = st.columns(2)
        lat = c1.number_input("Latitud", value=-12.046374, format="%.6f", key="conv_lat")
        lon = c2.number_input("Longitud", value=-77.042793, format="%.6f", key="conv_lon")
        if st.button("Buscar dirección", type="primary", key="conv_btn_rev"):
            try:
                with st.spinner("Geocodificando…"):
                    r = reverse_geocode(lat, lon, **prov_kw)
                st.success(r.direccion)
                with st.expander("Componentes"):
                    st.json(r.componentes)
                _mapa_resultados(
                    pd.DataFrame([{"lat": r.lat, "lon": r.lon,
                                   "direccion": r.direccion}]), key="conv_map_rev")
            except GeoError as e:
                st.error(str(e))


# ---------------------------------------------------------------------------
# Conversión por archivo (lote)
# ---------------------------------------------------------------------------

def _leer_archivo(archivo) -> pd.DataFrame:
    if archivo.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(archivo)
    return pd.read_csv(archivo)


def _procesar_lote(valores, modo, prov_kw, pais):
    filas = []
    barra = st.progress(0.0, "Procesando…")
    total = len(valores)
    for i, v in enumerate(valores):
        v = str(v).strip()
        try:
            if modo == "dir2coord":
                r = geocode(v, pais=pais, **prov_kw)
            else:
                r = reverse_geocode(v, **prov_kw)
            filas.append({"entrada": v, "lat": round(r.lat, 6), "lon": round(r.lon, 6),
                          "direccion": r.direccion, "estado": "ok"})
        except GeoError as e:
            filas.append({"entrada": v, "lat": None, "lon": None,
                          "direccion": "", "estado": f"error: {e}"})
        barra.progress((i + 1) / total, f"{i + 1}/{total}")
    barra.empty()
    return pd.DataFrame(filas)


def _bloque_archivo(prov_kw: dict, pais, proveedor):
    # --- Plantillas de muestra ---
    with st.expander("📥 Descarga una plantilla de muestra", expanded=False):
        st.caption("Usa **una** de las dos según lo que tengas. Las columnas extra "
                   "(código, nombre…) se conservan en el resultado.")
        cA, cB = st.columns(2)
        with cA:
            st.markdown("**Direcciones → coordenadas**  \nColumna de texto `direccion`.")
            st.download_button("📊 Excel", _excel_bytes(_plantilla_direcciones()),
                "plantilla_direcciones.xlsx", key="conv_tpl_dir_xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True)
            st.download_button("📄 CSV", _csv_bytes(_plantilla_direcciones()),
                "plantilla_direcciones.csv", "text/csv", key="conv_tpl_dir_csv",
                use_container_width=True)
        with cB:
            st.markdown("**Coordenadas → direcciones**  \nColumnas `latitud` y `longitud`.")
            st.download_button("📊 Excel", _excel_bytes(_plantilla_coordenadas()),
                "plantilla_coordenadas.xlsx", key="conv_tpl_coord_xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True)
            st.download_button("📄 CSV", _csv_bytes(_plantilla_coordenadas()),
                "plantilla_coordenadas.csv", "text/csv", key="conv_tpl_coord_csv",
                use_container_width=True)

    archivo = st.file_uploader("Sube tu CSV o Excel de clientes",
                               type=["csv", "xlsx", "xls"], key="conv_uploader")
    if archivo is None:
        return

    try:
        df = _leer_archivo(archivo)
    except Exception as e:
        st.error(f"No se pudo leer el archivo: {e}")
        return

    if df.empty:
        st.warning("El archivo está vacío.")
        return

    st.dataframe(df.head(), use_container_width=True)
    cols = list(df.columns)
    cols_lower = {c.lower(): c for c in cols}

    # Autodetección de la dirección de conversión.
    tiene_dir = any("direcc" in c.lower() or "address" in c.lower() for c in cols)
    tiene_coords = "latitud" in cols_lower and "longitud" in cols_lower
    modo_def = 0 if (tiene_dir and not tiene_coords) else (1 if tiene_coords else 0)

    modo_txt = st.radio("¿Qué quieres hacer?",
                        ["Dirección → Coordenadas", "Coordenadas → Dirección"],
                        index=modo_def, horizontal=True, key="conv_modo")

    if modo_txt.startswith("Dirección"):
        col_def = next((c for c in cols if "direcc" in c.lower() or "address" in c.lower()), cols[0])
        col_dir = st.selectbox("Columna con la dirección", cols,
                               index=cols.index(col_def), key="conv_col_dir")
        valores = df[col_dir].astype(str).tolist()
        modo = "dir2coord"
        entradas = valores
    else:
        c1, c2 = st.columns(2)
        lat_def = cols_lower.get("latitud", cols[0])
        lon_def = cols_lower.get("longitud", cols[-1])
        col_lat = c1.selectbox("Columna latitud", cols, index=cols.index(lat_def),
                               key="conv_col_lat")
        col_lon = c2.selectbox("Columna longitud", cols, index=cols.index(lon_def),
                               key="conv_col_lon")
        entradas = [f"{la}, {lo}" for la, lo in zip(df[col_lat], df[col_lon])]
        modo = "coord2dir"

    if proveedor == "nominatim" and len(entradas) > 30:
        st.caption(f"⏱️ Nominatim procesa ~1 fila/seg → ~{len(entradas)} s para "
                   f"{len(entradas)} filas. Para volúmenes grandes usa Google.")

    if st.button(f"🚀 Convertir {len(entradas)} filas", type="primary", key="conv_run"):
        res = _procesar_lote(entradas, modo, prov_kw, pais)
        # Conserva columnas originales del archivo junto al resultado.
        base = df.reset_index(drop=True)
        res = pd.concat([base, res[["lat", "lon", "direccion", "estado"]]], axis=1)
        st.session_state[_K_RES] = res

    # --- Resultados (editable) + mapa ---
    if _K_RES in st.session_state:
        res = st.session_state[_K_RES]
        ok = int((res["estado"] == "ok").sum())
        err = len(res) - ok
        c1, c2 = st.columns(2)
        c1.metric("✅ Convertidas", ok)
        c2.metric("⚠️ Con error", err)

        st.markdown("#### ✏️ Resultados — edita `lat`/`lon` para ajustar puntos")
        st.caption("Corrige manualmente cualquier coordenada; el mapa de abajo se "
                   "actualiza al instante.")
        editado = st.data_editor(
            res, use_container_width=True, num_rows="fixed", key="conv_editor",
            column_config={
                "lat": st.column_config.NumberColumn("lat", format="%.6f"),
                "lon": st.column_config.NumberColumn("lon", format="%.6f"),
            },
        )
        st.session_state[_K_RES] = editado

        _mapa_resultados(editado, key="conv_map_lote")

        cdl, cde = st.columns(2)
        cdl.download_button("⬇️ Descargar CSV", _csv_bytes(editado),
                            "clientes_geocodificados.csv", "text/csv",
                            use_container_width=True, key="conv_dl_csv")
        cde.download_button("⬇️ Descargar Excel", _excel_bytes(editado),
                            "clientes_geocodificados.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True, key="conv_dl_xlsx")
        if err:
            st.warning(f"{err} fila(s) sin resultado (revisa la columna `estado`). "
                       "Puedes corregir la dirección original y reconvertir, o "
                       "completar lat/lon a mano en la tabla.")


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def render_conversor():
    st.markdown("## 🌎 Conversor de direcciones ↔ coordenadas")
    st.caption("Convierte direcciones escritas en coordenadas para rutear, o "
               "coordenadas en direcciones legibles. Revisa los puntos en el mapa "
               "y ajústalos antes de exportar.")

    # --- Configuración de proveedor (sidebar) ---
    with st.sidebar:
        st.header("⚙️ Conversor — proveedor")
        proveedor = st.radio(
            "Servicio de geocodificación", ["nominatim", "google"],
            format_func=lambda p: {"nominatim": "Nominatim (gratis)",
                                   "google": "Google Maps (API key)"}[p],
            key="conv_prov")
        api_key = None
        if proveedor == "google":
            api_key = st.text_input(
                "Google API key", type="password", key="conv_apikey",
                help="Requiere facturación activada en Google Cloud.") or None
            if not api_key:
                st.info("Pega tu API key para usar Google. Mientras tanto se usa "
                        "Nominatim.")
                proveedor = "nominatim"
        pais = st.text_input("Sesgo por país (ISO-2)", value="pe", key="conv_pais",
                             help="Mejora la precisión. Ej.: pe, cl, mx. Vacío = global.") or None
        idioma = st.text_input("Idioma", value="es", key="conv_idioma")

    prov_kw = dict(proveedor=proveedor, api_key=api_key, idioma=idioma)

    tab_archivo, tab_puntual = st.tabs(
        ["📑 Por archivo (CSV/Excel)", "🔎 Conversión puntual"])
    with tab_archivo:
        _bloque_archivo(prov_kw, pais, proveedor)
    with tab_puntual:
        _bloque_puntual(prov_kw, pais)
