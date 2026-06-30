# 🔒 Login y 📅 Historial de despachos — Guía de configuración

Esta versión agrega **inicio de sesión** (la app deja de ser pública) y un
**historial de despachos** que queda guardado para consultarlo cualquier día.

> La app **no se bloquea** hasta que tú configures el login. Si no haces nada,
> sigue abierta como antes. El login se activa solo cuando agregas la sección
> `[auth]` en los *secrets* (Parte A).

---

## Parte A — Activar el login (5 minutos)

1. Entra a <https://share.streamlit.io/> → tu app → **⋮ → Settings → Secrets**.
2. Agrega al final lo siguiente (puedes tener varios usuarios). **La contraseña va
   en texto normal aquí**: los *secrets* son privados y cifrados, no se publican
   en GitHub.

```toml
[auth]
cookie_name = "ruteo_auth"
cookie_key = "pon-aqui-una-frase-larga-y-aleatoria-2026"   # inventa una, mín. 20 caracteres
cookie_expiry_days = 30

[auth.credentials.usernames.jean]
name = "Jean Paul Apaza"
password = "TuClaveSegura123"
email = "cuenta.appsheet.01@gmail.com"

[auth.credentials.usernames.despachador]
name = "Despachador Turno Mañana"
password = "OtraClave456"
email = "despacho@empresa.com"
```

3. **Save**. La app se reinicia y pedirá usuario y contraseña.
   - El **usuario** es la palabra después de `usernames.` (arriba: `jean`, `despachador`).
   - `cookie_expiry_days = 30` mantiene la sesión iniciada 30 días en ese navegador
     (no tienes que re-loguearte en cada recarga).
   - Para **agregar/quitar personas**, edita esta sección y guarda. Para cambiar una
     contraseña, cambia el valor de `password`.

> 💡 Cambia `cookie_key` por una frase única tuya. Si la dejas igual a la de otra
> app, las sesiones podrían cruzarse.

### Probar en tu PC (opcional)
Crea `.streamlit/secrets.toml` con el mismo contenido (esa carpeta ya está en
`.gitignore`, así que nunca se sube).

---

## Parte B — Historial de despachos (usa tu Google Sheet)

No requiere configuración extra **si ya conectaste Google Sheets** (guía
`SETUP_APPSHEET.md`). El historial se guarda en una pestaña nueva llamada
**`Historial`** que la app crea sola.

- Cada vez que pulsas **🚀 Asignar y enviar rutas a Google Sheets**, además de las
  pestañas `Rutas` y `Paradas`, se registra **una fila en `Historial`** con:
  `id_despacho`, fecha, hora, **quién lo creó** (el usuario que inició sesión),
  modo de agrupamiento, nº de rutas, tiendas, bultos, km totales, costo y motor.
- Para consultarlo: arriba en la app, abre **📅 Historial de despachos** →
  **🔄 Cargar / actualizar historial**. Puedes filtrar por fecha, ver totales
  acumulados y **descargar el historial en CSV**.

> ¿Por qué en Google Sheets y no en la app? Streamlit Cloud borra el disco en cada
> reinicio, así que un archivo local no sobreviviría. Tu Google Sheet es el
> almacenamiento que sí persiste (y ya lo tienes conectado).

---

## Resumen de lo que cambió

| Función | Dónde se ve | Requiere |
|---|---|---|
| 🔒 Login usuario/contraseña | Pantalla inicial + botón "Cerrar sesión" en el panel izquierdo | Sección `[auth]` en Secrets |
| 📅 Registro automático de cada despacho | Pestaña `Historial` de tu Google Sheet | Google Sheets conectado |
| 📅 Consulta de historial (filtro por fecha, totales, CSV) | Panel "📅 Historial de despachos" arriba | Google Sheets conectado |
| 👤 Autor del despacho | Columna `creado_por` del historial | Login activo |
