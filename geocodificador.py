"""
geocodificador.py
=================

Geocodificador multi-proveedor: convierte **direcciones <-> coordenadas** en ambos
sentidos. Es el port en Python de las funciones de Google Apps Script
``GMAPS_LATLONG`` (dirección -> coordenadas) y ``GMAPS_ADDRESS`` (coordenadas ->
dirección), con caché y limitación de frecuencia incorporadas.

Proveedores
-----------
* ``nominatim`` : OpenStreetMap. Gratis, sin clave. Límite de 1 petición/seg.
* ``google``    : Google Maps Geocoding API. Máxima precisión. Requiere API key
                  con facturación activada.
* ``auto``      : usa Google si se entrega ``api_key``, en caso contrario Nominatim.

Uso rápido
----------
>>> from geocodificador import geocode, reverse_geocode
>>> r = geocode("Av. Javier Prado Este 4200, Lima, Perú")
>>> r.coords_str()
'-12.0876, -76.9748'
>>> reverse_geocode(-12.046374, -77.042793).direccion
'Plaza Mayor, Lima, Perú'

Solo depende de ``requests``.
"""
from __future__ import annotations

import re
import time
import json
import hashlib
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional, Iterable

import requests

__all__ = [
    "GeoResultado",
    "GeoError",
    "geocode",
    "reverse_geocode",
    "geocode_lote",
    "gmaps_latlong",
    "gmaps_address",
    "es_coordenada",
    "limpiar_cache",
]

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

#: User-Agent descriptivo (Nominatim lo exige en su política de uso).
#: Personalízalo con el nombre/contacto de tu app. Evita dominios de ejemplo
#: (p.ej. example.com): Nominatim rechaza algunos de ellos con HTTP 403.
USER_AGENT = "geocodificador-py/1.0"

#: TTL del caché en segundos (6 horas, igual que el Cache.gs original).
CACHE_TTL = 6 * 60 * 60

#: Segundos mínimos entre peticiones a Nominatim (su política exige >= 1s).
NOMINATIM_MIN_INTERVALO = 1.0

#: Tiempo máximo de espera por petición HTTP.
TIMEOUT = 15

# Detecta una entrada del tipo "lat, lon" (admite espacios y signo).
_RE_COORD = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


# ---------------------------------------------------------------------------
# Modelo de resultado y errores
# ---------------------------------------------------------------------------

class GeoError(Exception):
    """Error de geocodificación (sin resultados, fallo de red, etc.)."""


@dataclass
class GeoResultado:
    """Resultado normalizado, independiente del proveedor."""

    lat: float
    lon: float
    direccion: str                      # dirección formateada completa
    componentes: dict = field(default_factory=dict)  # país, ciudad, calle, ...
    proveedor: str = ""
    raw: dict = field(default_factory=dict)           # respuesta cruda del API

    def coords_str(self, decimales: int = 6) -> str:
        """Devuelve ``"lat, lon"`` como el original ``GMAPS_LATLONG``."""
        return f"{round(self.lat, decimales)}, {round(self.lon, decimales)}"

    def componente(self, parte: str) -> Optional[str]:
        """Obtiene un componente (``"country"``, ``"locality"``, ...) o ``None``."""
        return self.componentes.get(parte)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Caché TTL en memoria (equivalente al Cache.gs de Apps Script)
# ---------------------------------------------------------------------------

class _CacheTTL:
    def __init__(self, ttl: int = CACHE_TTL):
        self.ttl = ttl
        self._datos: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def clave(*partes) -> str:
        crudo = "|".join(json.dumps(p, sort_keys=True, ensure_ascii=False)
                         if not isinstance(p, str) else p for p in partes)
        crudo = crudo.lower().replace(" ", "")
        return hashlib.md5(crudo.encode("utf-8")).hexdigest()

    def get(self, clave: str) -> Optional[dict]:
        with self._lock:
            item = self._datos.get(clave)
            if item is None:
                return None
            ts, valor = item
            if time.time() - ts > self.ttl:
                self._datos.pop(clave, None)
                return None
            return valor

    def set(self, clave: str, valor: dict) -> None:
        with self._lock:
            self._datos[clave] = (time.time(), valor)

    def clear(self) -> None:
        with self._lock:
            self._datos.clear()


_cache = _CacheTTL()


def limpiar_cache() -> None:
    """Vacía el caché en memoria."""
    _cache.clear()


# ---------------------------------------------------------------------------
# Limitador de frecuencia para Nominatim (1 req/seg)
# ---------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self, intervalo: float):
        self.intervalo = intervalo
        self._ultima = 0.0
        self._lock = threading.Lock()

    def esperar(self) -> None:
        with self._lock:
            ahora = time.time()
            espera = self.intervalo - (ahora - self._ultima)
            if espera > 0:
                time.sleep(espera)
            self._ultima = time.time()


_nominatim_limiter = _RateLimiter(NOMINATIM_MIN_INTERVALO)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def es_coordenada(texto: str) -> Optional[tuple[float, float]]:
    """Si ``texto`` es un par ``"lat, lon"`` válido devuelve ``(lat, lon)``; si no, ``None``."""
    if not isinstance(texto, str):
        return None
    m = _RE_COORD.match(texto)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return (lat, lon)
    return None


def _resolver_proveedor(proveedor: str, api_key: Optional[str]) -> str:
    if proveedor == "auto":
        return "google" if api_key else "nominatim"
    return proveedor


# ---------------------------------------------------------------------------
# Proveedor: Nominatim (OpenStreetMap)
# ---------------------------------------------------------------------------

_NOMINATIM_BASE = "https://nominatim.openstreetmap.org"


def _nominatim_get(endpoint: str, params: dict) -> dict | list:
    _nominatim_limiter.esperar()
    try:
        r = requests.get(
            f"{_NOMINATIM_BASE}/{endpoint}",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise GeoError(f"Nominatim: fallo de red ({e})") from e


def _nominatim_componentes(direccion: dict) -> dict:
    """Normaliza el bloque ``address`` de Nominatim a llaves estilo Google."""
    if not direccion:
        return {}
    comp = {
        "country": direccion.get("country"),
        "country_code": (direccion.get("country_code") or "").upper() or None,
        "locality": direccion.get("city") or direccion.get("town")
        or direccion.get("village") or direccion.get("municipality"),
        "administrative_area_level_1": direccion.get("state"),
        "administrative_area_level_2": direccion.get("county"),
        "postal_code": direccion.get("postcode"),
        "route": direccion.get("road"),
        "street_number": direccion.get("house_number"),
        "neighborhood": direccion.get("suburb") or direccion.get("neighbourhood"),
    }
    return {k: v for k, v in comp.items() if v}


def _geocode_nominatim(consulta: str, idioma: str, pais: Optional[str]) -> GeoResultado:
    params = {
        "q": consulta,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 1,
        "accept-language": idioma,
    }
    if pais:
        params["countrycodes"] = pais.lower()
    datos = _nominatim_get("search", params)
    if not datos:
        raise GeoError(f"Nominatim: sin resultados para «{consulta}»")
    d = datos[0]
    return GeoResultado(
        lat=float(d["lat"]),
        lon=float(d["lon"]),
        direccion=d.get("display_name", ""),
        componentes=_nominatim_componentes(d.get("address", {})),
        proveedor="nominatim",
        raw=d,
    )


def _reverse_nominatim(lat: float, lon: float, idioma: str) -> GeoResultado:
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "addressdetails": 1,
        "accept-language": idioma,
    }
    d = _nominatim_get("reverse", params)
    if not d or "error" in d:
        raise GeoError(f"Nominatim: sin dirección para ({lat}, {lon})")
    return GeoResultado(
        lat=float(d["lat"]),
        lon=float(d["lon"]),
        direccion=d.get("display_name", ""),
        componentes=_nominatim_componentes(d.get("address", {})),
        proveedor="nominatim",
        raw=d,
    )


# ---------------------------------------------------------------------------
# Proveedor: Google Maps Geocoding API
# ---------------------------------------------------------------------------

_GOOGLE_BASE = "https://maps.googleapis.com/maps/api/geocode/json"


def _google_get(params: dict) -> dict:
    try:
        r = requests.get(_GOOGLE_BASE, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise GeoError(f"Google: fallo de red ({e})") from e
    estado = data.get("status")
    if estado == "OK":
        return data
    if estado == "ZERO_RESULTS":
        raise GeoError("Google: sin resultados")
    msg = data.get("error_message", estado or "error desconocido")
    raise GeoError(f"Google: {msg}")


def _google_componentes(componentes: list) -> dict:
    """Aplana ``address_components`` a ``{tipo: long_name}`` (1er tipo de cada bloque)."""
    out: dict = {}
    for c in componentes or []:
        long_name = c.get("long_name")
        for tipo in c.get("types", []):
            out.setdefault(tipo, long_name)
        # también guardamos el código corto del país y región
        if "country" in c.get("types", []):
            out["country_code"] = c.get("short_name")
    return out


def _resultado_google(item: dict) -> GeoResultado:
    loc = item["geometry"]["location"]
    return GeoResultado(
        lat=float(loc["lat"]),
        lon=float(loc["lng"]),
        direccion=item.get("formatted_address", ""),
        componentes=_google_componentes(item.get("address_components", [])),
        proveedor="google",
        raw=item,
    )


def _geocode_google(consulta: str, api_key: str, idioma: str,
                    pais: Optional[str]) -> GeoResultado:
    params = {"address": consulta, "key": api_key, "language": idioma}
    if pais:
        params["components"] = f"country:{pais}"
    data = _google_get(params)
    return _resultado_google(data["results"][0])


def _reverse_google(lat: float, lon: float, api_key: str, idioma: str) -> GeoResultado:
    params = {"latlng": f"{lat},{lon}", "key": api_key, "language": idioma}
    data = _google_get(params)
    return _resultado_google(data["results"][0])


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def geocode(consulta: str, proveedor: str = "auto", api_key: Optional[str] = None,
            idioma: str = "es", pais: Optional[str] = None,
            usar_cache: bool = True) -> GeoResultado:
    """Dirección -> coordenadas.

    Si ``consulta`` ya es un par ``"lat, lon"`` se devuelve tal cual (sin llamar al API),
    replicando el comportamiento de ``GMAPS_LATLONG`` con coordenadas de entrada.

    Parameters
    ----------
    consulta : dirección, código postal o ``"lat, lon"``.
    proveedor : ``"auto"`` | ``"nominatim"`` | ``"google"``.
    api_key : clave de Google (necesaria para el proveedor ``google``).
    idioma : idioma de la respuesta (ISO, p.ej. ``"es"``).
    pais : sesgo/filtro por país (ISO-2, p.ej. ``"pe"``) para mayor precisión.
    """
    coords = es_coordenada(consulta)
    if coords is not None:
        lat, lon = coords
        return GeoResultado(lat=lat, lon=lon, direccion=consulta.strip(),
                            proveedor="passthrough")

    prov = _resolver_proveedor(proveedor, api_key)
    clave = _CacheTTL.clave("geocode", prov, consulta, idioma, pais or "")
    if usar_cache and (cacheado := _cache.get(clave)) is not None:
        return GeoResultado(**cacheado)

    if prov == "google":
        if not api_key:
            raise GeoError("El proveedor 'google' requiere api_key.")
        res = _geocode_google(consulta, api_key, idioma, pais)
    elif prov == "nominatim":
        res = _geocode_nominatim(consulta, idioma, pais)
    else:
        raise GeoError(f"Proveedor desconocido: {prov!r}")

    if usar_cache:
        _cache.set(clave, res.to_dict())
    return res


def reverse_geocode(lat, lon: Optional[float] = None, proveedor: str = "auto",
                    api_key: Optional[str] = None, idioma: str = "es",
                    usar_cache: bool = True) -> GeoResultado:
    """Coordenadas -> dirección.

    Acepta ``reverse_geocode(lat, lon)`` o ``reverse_geocode("lat, lon")``.
    """
    if lon is None:
        coords = es_coordenada(lat) if isinstance(lat, str) else None
        if coords is None:
            raise GeoError(f"Coordenada inválida: {lat!r}")
        lat, lon = coords
    lat, lon = float(lat), float(lon)

    prov = _resolver_proveedor(proveedor, api_key)
    clave = _CacheTTL.clave("reverse", prov, round(lat, 6), round(lon, 6), idioma)
    if usar_cache and (cacheado := _cache.get(clave)) is not None:
        return GeoResultado(**cacheado)

    if prov == "google":
        if not api_key:
            raise GeoError("El proveedor 'google' requiere api_key.")
        res = _reverse_google(lat, lon, api_key, idioma)
    elif prov == "nominatim":
        res = _reverse_nominatim(lat, lon, idioma)
    else:
        raise GeoError(f"Proveedor desconocido: {prov!r}")

    if usar_cache:
        _cache.set(clave, res.to_dict())
    return res


def geocode_lote(consultas: Iterable[str], proveedor: str = "auto",
                 api_key: Optional[str] = None, idioma: str = "es",
                 pais: Optional[str] = None,
                 on_error: str = "none") -> list[Optional[GeoResultado]]:
    """Geocodifica una lista de direcciones (ideal para un CSV de clientes).

    ``on_error``: ``"none"`` agrega ``None`` y continúa; ``"raise"`` lanza al primer fallo.
    El limitador de Nominatim se aplica automáticamente entre llamadas.
    """
    salida: list[Optional[GeoResultado]] = []
    for c in consultas:
        try:
            salida.append(geocode(c, proveedor, api_key, idioma, pais))
        except GeoError:
            if on_error == "raise":
                raise
            salida.append(None)
    return salida


# ---------------------------------------------------------------------------
# Compatibilidad con los nombres de Apps Script
# ---------------------------------------------------------------------------

def gmaps_latlong(consulta: str, **kw) -> str:
    """Equivalente a ``GMAPS_LATLONG``: devuelve ``"lat, lon"``."""
    return geocode(consulta, **kw).coords_str()


def gmaps_address(consulta: str, part: Optional[str] = None, **kw) -> str:
    """Equivalente a ``GMAPS_ADDRESS``.

    Sin ``part`` devuelve la dirección formateada. Con ``part`` (``"country"``,
    ``"locality"``, ...) devuelve ese componente.
    """
    coords = es_coordenada(consulta)
    res = reverse_geocode(consulta, **kw) if coords else geocode(consulta, **kw)
    if not part:
        return res.direccion
    return res.componente(part) or ""


# ---------------------------------------------------------------------------
# CLI mínima
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser(description="Geocodificador dirección <-> coordenadas")
    p.add_argument("consulta", help='Dirección o "lat, lon"')
    p.add_argument("--reverse", action="store_true", help="Forzar coordenadas -> dirección")
    p.add_argument("--proveedor", default="auto", choices=["auto", "nominatim", "google"])
    p.add_argument("--api-key", default=None)
    p.add_argument("--pais", default=None, help="ISO-2, p.ej. pe")
    p.add_argument("--idioma", default="es")
    args = p.parse_args()

    try:
        if args.reverse or es_coordenada(args.consulta):
            r = reverse_geocode(args.consulta, proveedor=args.proveedor,
                                api_key=args.api_key, idioma=args.idioma)
        else:
            r = geocode(args.consulta, proveedor=args.proveedor, api_key=args.api_key,
                        idioma=args.idioma, pais=args.pais)
        print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
    except GeoError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
