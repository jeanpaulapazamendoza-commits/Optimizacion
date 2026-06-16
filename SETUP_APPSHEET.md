# 📲 Fase 2 — Conectar la app a Google Sheets + AppSheet (app de choferes)

Flujo completo: planificas en Streamlit → pulsas **"🚀 Asignar y enviar rutas"** →
las rutas aparecen en tu Google Sheet → tus choferes las ven en **AppSheet** y marcan
cada entrega con **foto, GPS y hora** → tú ves el avance en la misma hoja.

**No necesitas crear tablas a mano**: la app crea las pestañas `Rutas` y `Paradas`
con sus encabezados en el primer envío. El diseño es *solo-agregar* (append-only) con
IDs únicos por despacho, así Streamlit nunca pisa lo que los choferes ya registraron.

---

## Parte A — Crear la hoja de Google Sheets (1 minuto)

1. Entra a <https://sheets.new> con tu cuenta de Google.
2. Nómbrala, por ejemplo: **`Despachos Rutas Mass`**.
3. Copia la URL (la necesitarás en las partes B y C). Nada más — las pestañas las crea la app.

## Parte B — Cuenta de servicio de Google (una sola vez, ~8 minutos)

La cuenta de servicio es un "usuario robot" que le da permiso a tu app de Streamlit
para escribir en la hoja. Es gratis.

1. Entra a <https://console.cloud.google.com/> (misma cuenta de Google).
2. Arriba a la izquierda → selector de proyecto → **"Proyecto nuevo"** → nombre:
   `ruteo-tiendas` → **Crear** (y selecciónalo).
3. Menú ☰ → **APIs y servicios → Biblioteca**:
   - Busca **"Google Sheets API"** → **Habilitar**.
   - Busca **"Google Drive API"** → **Habilitar**.
4. Menú ☰ → **APIs y servicios → Credenciales** → **+ Crear credenciales** →
   **Cuenta de servicio**:
   - Nombre: `streamlit-rutas` → **Crear y continuar** → (rol: puedes omitirlo) → **Listo**.
5. Click en la cuenta recién creada → pestaña **Claves** → **Agregar clave** →
   **Crear clave nueva** → tipo **JSON** → **Crear**. Se descarga un archivo `.json`:
   **guárdalo bien y no lo subas nunca a GitHub**.
6. Abre el JSON y copia el valor de `client_email`
   (algo como `streamlit-rutas@ruteo-tiendas.iam.gserviceaccount.com`).
7. Vuelve a tu Google Sheet → **Compartir** → pega ese correo → permiso **Editor** →
   Enviar (ignora el aviso de que no se pudo notificar).

## Parte C — Secrets en Streamlit Cloud (3 minutos)

1. Entra a <https://share.streamlit.io/> → tu app → **⋮ → Settings → Secrets**.
2. Pega esto, reemplazando con los valores de TU archivo JSON:

```toml
gsheets_url = "https://docs.google.com/spreadsheets/d/TU_ID_DE_HOJA/edit"

[gcp_service_account]
type = "service_account"
project_id = "ruteo-tiendas"
private_key_id = "xxxxxxxxxxxxxxxxxxxx"
private_key = "-----BEGIN PRIVATE KEY-----\nMIIE...resto de la clave...\n-----END PRIVATE KEY-----\n"
client_email = "streamlit-rutas@ruteo-tiendas.iam.gserviceaccount.com"
client_id = "123456789"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/streamlit-rutas%40ruteo-tiendas.iam.gserviceaccount.com"
```

> 💡 Lo más fácil: abre el `.json` descargado, copia cada campo a su línea.
> El `private_key` debe ir en UNA sola línea con los `\n` tal como vienen en el JSON.
> Para probar en tu PC, crea el archivo `.streamlit/secrets.toml` con el mismo contenido
> (la carpeta `.streamlit/` ya está en el `.gitignore`).

3. **Save** → la app se reinicia. Listo: el botón "🚀 Asignar y enviar rutas" quedará habilitado.

## Parte D — Primer envío de prueba

1. En la app: calcula rutas → baja a **"📤 Asignar rutas → Google Sheets"** →
   verifica la URL → **🚀 Asignar y enviar**.
2. Abre tu Google Sheet: verás las pestañas **Rutas** y **Paradas** con el despacho
   (id tipo `20260611-0930-R0`). Cada nuevo envío AGREGA filas con un nuevo
   `id_despacho` — el historial completo queda en la hoja.

### Columnas que crea la app

**Pestaña `Rutas`** (una fila por ruta): `id_ruta` (clave), `id_despacho`, `fecha`,
`cluster`, `vehiculo`, `vuelta`, `conductor` (vacía: asígnala tú), `salida_programada`,
`fin_estimado`, `distancia_km`, `duracion_min`, `costo`, `tiendas`, `bultos`,
`estado` (Planificada), `link_maps`.

**Pestaña `Paradas`** (una fila por tienda): `id_parada` (clave), `id_ruta`, `orden`,
`codigo_sucursal`, `tienda`, `distrito`, `bultos`, `prioridad`, `eta`, `ventana`,
`ubicacion` (lat,long para el mapa de AppSheet), `latitud`, `longitud`, `link_waze`,
y las columnas **del chofer**: `estado_entrega` (Pendiente), `hora_entrega`,
`foto_entrega`, `gps_entrega`, `observaciones`.

## Parte E — Crear la app en AppSheet (15-20 minutos)

1. Entra a <https://www.appsheet.com/> → **Create → App → Start with existing data** →
   **Google Sheets** → elige `Despachos Rutas Mass`. AppSheet detecta las dos pestañas.
2. **Data → Tables**: verifica que existan `Rutas` y `Paradas` (agrega la que falte
   con *Add Table*). Permiso de `Paradas`: **Updates only** (los choferes editan,
   no agregan ni borran). `Rutas`: **Read-Only** (o Updates si quieres editar
   `conductor`/`estado` desde la app).
3. **Data → Columns → Paradas** — ajusta tipos (lo demás déjalo como AppSheet lo detecte):
   | Columna | Tipo | Ajustes |
   |---|---|---|
   | `id_parada` | Text | marcar como **KEY** y **LABEL** no |
   | `id_ruta` | **Ref** | tabla referenciada: `Rutas` (crea la vista agrupada automática) |
   | `tienda` | Text | marcar **LABEL** |
   | `ubicacion` | **LatLong** | habilita el pin en el mapa |
   | `link_waze` | **Url** | |
   | `estado_entrega` | **Enum** | valores: `Pendiente`, `Entregado`, `No entregado`, `Reprogramado` · Input mode: **Buttons** |
   | `hora_entrega` | ChangeTimestamp | *Columns:* `estado_entrega` (se llena sola al marcar) |
   | `foto_entrega` | **Image** | el chofer toma la foto con la cámara |
   | `gps_entrega` | **LatLong** | Initial value: `HERE()` (captura el GPS del celular) |
   | `observaciones` | LongText | |
   - En `Paradas`, deja **editables** SOLO: `estado_entrega`, `foto_entrega`,
     `gps_entrega`, `observaciones` (en cada otra columna desmarca *Editable*).
     Así el chofer no puede alterar la planificación.
4. **Data → Columns → Rutas**: `id_ruta` = KEY; `id_ruta` o `cluster` como LABEL;
   `link_maps` tipo **Url**; `estado` tipo Enum (`Planificada`, `En curso`, `Completada`).
5. **Slices** (Data → Slices) — opcional pero recomendado:
   - `Despacho de hoy`: tabla `Paradas`, condición `[fecha de su ruta] = TODAY()` o más
     simple: `CONTAINS([id_ruta], TEXT(TODAY(), "YYYYMMDD"))`.
   - `Pendientes`: `[estado_entrega] = "Pendiente"`.
6. **Views** (UX → Views):
   - **"Mis Rutas"**: tabla `Rutas`, tipo **Deck**, orden por `id_ruta` DESC.
     Al tocar una ruta se ven sus paradas (gracias al Ref).
   - **"Paradas"**: tipo **Map** (columna `ubicacion`) y/o **Table** ordenada por `orden`.
   - El chofer toca una parada → botones grandes de `estado_entrega` → foto → guardar.
7. **Filtrar por chofer** (opcional): en la tabla `Rutas` usa *Security filter*:
   `OR([conductor] = "", [conductor] = USEREMAIL())` — cada chofer solo ve sus rutas
   (escribe su correo en la columna `conductor` de la hoja o desde la app).
8. **Users**: Share → agrega los correos de tus choferes. El plan gratuito de AppSheet
   permite hasta 10 usuarios de prueba; para producción el plan Starter es por usuario/mes.
9. Los choferes instalan **AppSheet** (Android/iOS) → abren tu app → ¡a repartir!

## Parte F — Reglas que evitan conflictos

- **Streamlit solo AGREGA filas** (nunca edita ni borra): cada despacho tiene un
  `id_despacho` único con fecha y hora.
- **AppSheet solo EDITA las 4 columnas del chofer** (`estado_entrega`, `hora_entrega`,
  `foto_entrega`, `gps_entrega`, `observaciones`) — las demás van bloqueadas como
  no-editables.
- Como cada quien escribe en celdas distintas, no hay colisiones aunque trabajen
  al mismo tiempo.
- ¿Reenviaste un despacho por error? Borra en la hoja las filas de ese `id_despacho`
  (filtra por la columna B) — nada más depende de ellas.
- Limpieza: cuando la hoja crezca demasiado (≈30-50 mil filas), corta el historial
  antiguo a otra hoja "Archivo".
