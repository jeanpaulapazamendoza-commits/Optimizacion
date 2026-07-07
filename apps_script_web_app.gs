/**
 * apps_script_web_app.gs
 * =====================================================================
 * Web App que expone el geocoder GRATIS de Google Apps Script
 * (Maps.newGeocoder()) para que la librería `geocodificador.py` lo use
 * como proveedor "apps_script". NO requiere API key ni facturación.
 *
 * ── Cómo desplegar (una sola vez) ────────────────────────────────────
 * 1. Ve a https://script.google.com  →  Nuevo proyecto.
 * 2. Pega TODO este archivo y guarda.
 * 3. (Opcional) pon un valor en TOKEN para que solo tu app pueda llamarla.
 * 4. Implementar → Nueva implementación → tipo «Aplicación web».
 *      - Ejecutar como:  Yo (tu cuenta)
 *      - Quién tiene acceso:  Cualquiera
 * 5. Autoriza los permisos y copia la URL que termina en /exec.
 *    Pégala en la app (campo «URL de la Web App»).
 *
 * ── Prueba rápida en el navegador ───────────────────────────────────
 *   https://.../exec?q=Plaza+Mayor+de+Lima
 *   https://.../exec?q=-12.046374,-77.042793&mode=reverse
 *
 * Parámetros que acepta:
 *   q       (obligatorio) dirección  o  "lat,lng"
 *   mode    "geocode" (por defecto)  |  "reverse"
 *   lang    idioma de la respuesta   (ej. es)
 *   region  sesgo por país ISO-2     (ej. pe)
 *   token   debe coincidir con TOKEN si lo configuraste
 */

// Déjalo vacío para acceso libre, o pon una frase secreta y envíala como &token=...
var TOKEN = "";

function doGet(e) {
  var p = (e && e.parameter) || {};
  try {
    if (TOKEN && p.token !== TOKEN) {
      return _json({ status: "ERROR", error_message: "Token inválido" });
    }
    var q = (p.q || "").trim();
    if (!q) return _json({ status: "ERROR", error_message: "Falta el parámetro q" });

    var geocoder = Maps.newGeocoder();
    if (p.lang)   geocoder.setLanguage(p.lang);
    if (p.region) geocoder.setRegion(p.region);

    var res;
    if (p.mode === "reverse") {
      var c = q.split(",");
      res = geocoder.reverseGeocode(parseFloat(c[0]), parseFloat(c[1]));
    } else {
      res = geocoder.geocode(q);
    }
    return _json(res); // mismo formato que la Google Geocoding API (status + results[])
  } catch (err) {
    return _json({ status: "ERROR", error_message: String(err) });
  }
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
