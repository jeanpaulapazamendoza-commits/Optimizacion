# 🏪 Agrupación de Tiendas y Ruteo Óptimo — v2 (escalable a 1000+ coordenadas)

Aplicación web en **Streamlit** que:

1. **Agrupa** tiendas por cercanía geográfica con **K-Means balanceado por capacidad**
   (cada grupo respeta un máximo de tiendas por vehículo/ruta — escala a miles de puntos).
2. **Rutea** cada grupo con **Google OR-Tools** (se resuelve localmente, **sin límites de API**),
   usando distancias por **calles reales (OSRM, gratis, sin API key)** o en línea recta (haversine).
3. Mantiene **OpenRouteService (HeiGIT)** como motor opcional (requiere API key gratuita).
4. **Mapa profesional con Folium (Leaflet)**: control de capas dentro del mapa,
   agrupación automática de marcadores al hacer zoom (ideal con miles de tiendas),
   pantalla completa, regla de medición de distancias, minimapa, fichas emergentes
   por tienda (popup al hacer clic) y rutas animadas que muestran el sentido del recorrido.
5. **Bultos**: columna opcional `cantidad_bultos` en tu archivo; cada ruta puede
   limitarse por **número de tiendas o por bultos totales** (capacidad real del vehículo).
6. **Prioridades de envío**: columna opcional `prioridad` (1 = más urgente).
   Las tiendas prioritarias **se visitan primero** dentro de su ruta
   (nivel 1, luego 2, ... y al final las normales). En el mapa se resaltan con borde dorado ⭐.
7. **Editor de rutas**: sección "✏️ Personalizar una ruta" para cambiar manualmente
   el orden de visita de cualquier ruta; la distancia, duración y el trazado del mapa
   se recalculan con tu secuencia.
8. **Flota personalizada**: define tu flota real (ej. 10 vehículos de 300 bultos +
   10 de 250) con máximo opcional de tiendas por vehículo. El número de rutas queda
   limitado por la flota, puedes habilitar **2ª/3ª vueltas**, y las tiendas que no
   entran se reportan en una sección propia (mapa, tabla y CSV descargable) —
   las **prioritarias se asignan primero** y nunca quedan fuera si hay cupo.
9. **Ventanas horarias** (columnas opcionales `hora_inicio`/`hora_fin`): el ruteo
   respeta el horario en que cada tienda puede recibir (OR-Tools con dimensión de tiempo).
10. **Tiempo de servicio y ETAs**: define minutos de descarga por parada (y por bulto),
    la hora de salida del CD, y la app calcula la **hora estimada de llegada a cada
    tienda** (visible en tablas, popups del mapa y descargas) más una **jornada máxima**
    por ruta con alertas si se excede.
11. **Modelo de costos**: costo fijo por vehículo + costo por km → costo por ruta,
    costo total y **costo por entrega**.
12. **Hoja de ruta para conductores**: Excel con una hoja por vehículo y HTML
    imprimible (una página por ruta) con **links de Google Maps** (paradas en orden),
    **Waze** por tienda y **código QR** para abrir la ruta desde el celular.
13. **Comparador de escenarios**: guarda corridas (rutas, km, horas, costo) y
    compáralas lado a lado para decidir la mejor configuración de flota.
14. **Selección manual en el mapa**: modo "✋ Selección manual" — haces **clic en los
    puntos del mapa** para armar cada grupo a tu criterio, viendo en **tiempo real** las
    tiendas y bultos acumulados del grupo activo. Puntos libres en gris; clic para
    asignar al grupo activo, clic de nuevo para quitar. Botones para crear/​vaciar/​eliminar
    grupos y un **🤖 Auto-asignar puntos libres** que agrupa automáticamente lo que dejes
    sin seleccionar (flujo híbrido manual + automático). El resultado alimenta el mismo
    ruteo, hojas de ruta y envío a Google Sheets.
15. **Inicio de sesión** (opcional): protege la app con usuario/contraseña
    (multi-usuario, sesión recordada por cookie). Se activa al agregar la sección
    `[auth]` en los *secrets*; si no la configuras, la app sigue abierta. Ver **SETUP_LOGIN.md**.
16. **Historial de despachos**: cada envío a Google Sheets queda registrado en una
    pestaña `Historial` (fecha, **autor**, rutas, tiendas, bultos, km, costo). El panel
    **📅 Historial de despachos** permite consultarlo, filtrar por fecha y exportar a CSV —
    persiste entre sesiones porque vive en tu Google Sheet.

## 📑 Formato del archivo (Excel o CSV)

| Columna | ¿Obligatoria? | Descripción |
|---|---|---|
| `latitud` | ⭐ Sí | Latitud decimal (ej. -12.046374) |
| `longitud` | ⭐ Sí | Longitud decimal (ej. -77.042793) |
| `codigo_sucursal` | No | Código interno (se autogenera si falta) |
| `name_sucursal` | No | Nombre de la tienda |
| `distrito` | No | Distrito o zona |
| `cantidad_bultos` | No | Bultos que pide la tienda (por defecto 1). Permite limitar cada ruta por bultos |
| `prioridad` | No | 0 o vacío = normal · 1 = se visita primero · 2 = después de las de nivel 1, etc. |
| `hora_inicio` | No | Inicio de la ventana horaria de recepción (ej. `09:00`). Vacío = todo el día |
| `hora_fin` | No | Fin de la ventana horaria (ej. `13:00`). Acepta HH:MM, horas de Excel o decimales |

---

## 📁 Archivos del repositorio

| Archivo | Descripción |
|---|---|
| `app.py` | Aplicación completa (clustering + ruteo + mapa interactivo) |
| `requirements.txt` | Dependencias (Streamlit Cloud las instala automáticamente) |
| `Dataset.xlsx` | Dataset por defecto (54 tiendas Mass de Lima, hoja `df`) |
| `tiendas_prueba_1500.csv` | **Dataset de prueba con 1,500 tiendas** para validar el caso de datasets grandes |
| `generar_dataset_prueba.py` | Script para generar datasets de prueba de cualquier tamaño |
| `README.md` | Esta guía |
| `.gitignore` | Archivos a excluir del repositorio |

---

## 🚀 Paso 1 — Crear el repositorio en GitHub

1. Entra a <https://github.com/new>.
2. Nombre sugerido: `ruteo-tiendas-v2` (o el que prefieras). Visibilidad: **Public**
   (Streamlit Community Cloud gratuito requiere repos públicos o autorizar el privado).
3. Crea el repositorio **vacío** (sin README inicial).
4. Sube los archivos: botón **"uploading an existing file"** → arrastra los 7 archivos
   de esta carpeta → **Commit changes**.

## ☁️ Paso 2 — Desplegar en Streamlit Community Cloud (gratis)

1. Entra a <https://share.streamlit.io/> e inicia sesión con tu cuenta de GitHub.
2. **Create app** → **Deploy a public app from GitHub**.
3. Repository: `tu-usuario/ruteo-tiendas-v2` · Branch: `main` · Main file path: `app.py`.
4. **Deploy**. La primera vez tarda 2-4 minutos instalando dependencias
   (`ortools` pesa ~25 MB, es normal).

> La app queda en `https://<nombre-que-elijas>.streamlit.app/`

## 💻 Alternativa — Probarlo en tu PC ahora mismo

```bash
pip install -r requirements.txt
streamlit run app.py
```

Se abre en el navegador en `http://localhost:8501`.

---

## 🔑 Paso 3 — APIs y herramientas: qué necesita cada motor de ruteo

| Motor (selector en el sidebar) | ¿Necesita registro/API key? | Límites | ¿Cuándo usarlo? |
|---|---|---|---|
| 🆓 **OR-Tools + OSRM** (calles reales) | **NO** — usa el servidor público `router.project-osrm.org` | ~100 puntos por grupo (el modo balanceado lo respeta solo); servidor demo sin SLA | **Recomendado.** Distancias y rutas dibujadas por calles reales, gratis |
| ⚡ **OR-Tools + Haversine** (línea recta) | **NO** — no usa internet | Ninguno | Vista previa instantánea con miles de puntos, o si OSRM no responde |
| 🔑 **OpenRouteService** (HeiGIT) | **SÍ** — key gratuita | 50 tiendas por grupo y 500 requests/día (plan free) | Solo si quieres comparar con el motor original |

**El orden de visita óptimo SIEMPRE lo calcula Google OR-Tools localmente**
(librería de optimización, no es una API): cero requests, cero límites, sin costo.

### Si quieres usar el motor OpenRouteService (opcional)

1. Regístrate gratis en <https://openrouteservice.org/dev/#/signup>.
2. Confirma tu correo y entra al dashboard.
3. **Request a token** → plan **Free** → copia el token.
4. En la app: selecciona el motor "OpenRouteService" y pega el token en el campo de API Key.

---

## ✅ Paso 4 — Probar el caso de 1,000+ coordenadas (el flujo completo)

1. Abre la app y en el sidebar usa **"Sube un archivo Excel o CSV"** →
   sube `tiendas_prueba_1500.csv` (incluido en este repo).
2. En **Modo de agrupamiento** deja **"🚚 Balanceado por capacidad"** y elige,
   por ejemplo, **25 tiendas por grupo** → la app creará **60 grupos balanceados**
   (verás bajo las métricas: tamaño mín/máx/promedio de los grupos).
3. Configura tu **Centro de Distribución** (latitud/longitud del punto de partida)
   y el tipo de recorrido (cerrado o abierto).
4. Motor de ruteo: **"🆓 OR-Tools + OSRM"**.
5. Click en **"🚛 Calcular rutas óptimas"** → verás una barra de progreso grupo por grupo
   (60 grupos tardan ~2-4 min porque se consulta OSRM por cada grupo; con el motor
   Haversine tarda segundos).
6. Revisa el mapa, la tabla de resumen (km y minutos por ruta) y descarga
   **todas las rutas en un solo CSV**.

¿Quieres probar con más volumen? Genera otro dataset:

```bash
python generar_dataset_prueba.py 3000
```

## 🧪 Probar las funciones nuevas (bultos, prioridades, editor)

El dataset `tiendas_prueba_1500.csv` ya trae `cantidad_bultos` (1-8 por tienda)
y ~3% de tiendas con `prioridad = 1`.

1. **Capacidad por bultos**: en "Limitar cada ruta por" elige **📦 Nº de bultos**
   y define la capacidad del vehículo (ej. 120 bultos). Los grupos se arman para
   no superar ese límite (verás la carga por grupo bajo las métricas).
2. **Prioridades**: calcula las rutas con un motor OR-Tools y revisa el detalle:
   las tiendas con ⭐ aparecen al inicio de la secuencia y en el mapa tienen
   **borde dorado**. (Con el motor OpenRouteService las prioridades no aplican.)
3. **Editor de rutas**: tras calcular rutas, baja a **"✏️ Personalizar una ruta"**,
   elige el cluster, cambia los números de la columna **Orden** y pulsa
   **Aplicar orden personalizado**: el mapa y las métricas se actualizan con tu
   secuencia (marcada como "✏️ Personalizada" en el resumen). Si recalculas las
   rutas con el botón principal, vuelven todas al orden óptimo.
4. **Flota personalizada**: en "Limitar cada ruta por" elige **🚛 Flota personalizada**
   y edita la tabla (por defecto: 10 vehículos de 300 bultos + 10 de 250). Puedes
   agregar filas (otro tipo de camión), fijar un máximo de tiendas por vehículo
   (0 = sin límite) y habilitar hasta 3 vueltas. El resumen de rutas muestra el
   vehículo asignado, su % de uso y la vuelta. Si la flota no alcanza, la sección
   **"🚫 Tiendas no asignadas"** muestra cuáles quedaron fuera (siempre las de menor
   prioridad), con CSV descargable para tercerizar o reprogramar al día siguiente.

---

## 🧠 ¿Por qué esta versión agrupa bien 1000+ coordenadas?

- **K-Means clásico no controla el tamaño de los grupos**: con muchos puntos genera
  clusters de 300 tiendas junto a clusters de 10 — inservible para asignar vehículos.
  El modo balanceado garantiza `tamaño de grupo ≤ capacidad`.
- Las coordenadas se proyectan a **metros reales** (antes se usaba StandardScaler,
  que distorsiona la geografía).
- Los cálculos pesados (silhouette, método del codo) usan **muestreo** y
  `MiniBatchKMeans`, así la app responde fluida con miles de puntos.

## ⚠️ Notas y límites conocidos

- El servidor OSRM público es un servicio de cortesía (sin garantía de disponibilidad).
  Si falla, la app usa haversine automáticamente para ese grupo y te lo avisa.
- Si un grupo supera 99 tiendas con el motor OSRM, ese grupo se calcula con haversine
  (reduce la capacidad por grupo para evitarlo).
- La duración con motor haversine es una estimación a 25 km/h urbanos.

---

**Autor:** Jean Paul Apaza Mendoza · Proyecto académico ISIL — Fundamentos de Machine Learning
Modelos: K-Means balanceado + KNN · Ruteo: Google OR-Tools + OSRM / OpenRouteService
