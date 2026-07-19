# 🗺️ Roadmap: de RuteoTiendas a SaaS last-mile (tipo Beetrack/SimpliRoute)

> Plan aprobado el 2026-07-19. Objetivo: sistema profesional de gestión last-mile
> con app para transportistas, vendible como SaaS a terceros. Ritmo: pocas
> horas/semana, ~11-12 semanas. Presupuesto: free tiers → máx ~$45/mes en Etapa 4.

## Arquitectura objetivo (resumen)

| Componente | Tecnología | Estado |
|---|---|---|
| Planificador | Streamlit actual (Render/Docker) | ✅ Ya existe, se conserva |
| Motor de ruteo | Paquete `motor_ruteo/` extraído de app.py | Etapa 1 |
| Base de datos | Supabase (Postgres + Auth + Storage + Realtime + RLS) | Etapa 1 |
| App conductor | AppSheet (piloto) → PWA → Capacitor (si hace falta GPS background) | Etapas 0 → 2 → 4+ |
| Torre de control | Streamlit autorefresh → Leaflet + Supabase Realtime | Etapa 3 |
| API | FastAPI en Render (solo cuando haga falta `/optimizar`) | Etapa 2+ |

Multi-tenant desde el día 1: **toda tabla lleva `org_id` + RLS**, aunque al inicio
haya una sola organización.

## Etapas y entregables

### Etapa 0 — Piloto AppSheet (semanas 1-2 · $0) ← EN CURSO
La app del chofer en AppSheet sobre las hojas `Rutas`/`Paradas` que Streamlit ya
genera. **Guía completa: [SETUP_APPSHEET.md](SETUP_APPSHEET.md)** (partes A-F).

Checklist:
- [ ] Verificar que el botón "🚀 Asignar y enviar rutas" está habilitado en la app
      (si no: completar partes A-C de SETUP_APPSHEET.md — hoja + cuenta de servicio + secrets).
- [ ] Hacer un envío de prueba y confirmar pestañas `Rutas`/`Paradas` en la hoja (parte D).
- [ ] Crear la app AppSheet (parte E): tipos de columna, slice "Pendientes",
      vista Deck ordenada por `orden`, botones `estado_entrega`, foto, `HERE()`.
- [ ] Asignar conductor (correo) a cada ruta y activar el security filter (parte E.7).
- [ ] **Piloto real**: 1 despacho completo donde el chofer cierra cada parada con
      foto + GPS desde su celular, sin intervención manual.
- [ ] Anotar feedback de los choferes (qué sobra, qué falta) → alimenta la PWA de Etapa 2.

⚠️ AppSheet es un **piloto desechable**: caduca al final de la Etapa 2. No pulirlo.

### Etapa 1 — Cimientos: Supabase + motor extraído (semanas 2-4 · $0)
- Proyecto Supabase con el modelo: `orgs`, `usuarios`, `vehiculos`, `conductores`,
  `despachos`, `rutas`, `paradas` (con campos POD), `posiciones_gps`, `eventos_pod`.
  Base: los `RUTAS_HEADERS`/`PARADAS_HEADERS`/`HISTORIAL_HEADERS` de app.py (~L1140).
- **Escritura dual** en el bloque de envío (~L3267-3452): Sheets (AppSheet sigue vivo)
  + Supabase (`supabase-py`) con `org_id` fijo.
- Extraer `motor_ruteo/` (funciones puras ~L965-1836: geometría, ETAs, OSRM, TSP,
  flota) y que app.py lo importe. `geocodificador.py` se reutiliza tal cual.
- ✔️ Verificación: un despacho aparece en Sheets Y Postgres; app.py funciona igual.

### Etapa 2 — PWA del conductor (semanas 4-7 · $0-7/mes) — corazón del MVP
- PWA HTML/JS simple (sin React) hablando directo con Supabase (Auth + RLS = backend):
  login → paradas del día → Entregado/Fallido + cámara → foto a Storage.
- GPS por eventos + `watchPosition` con Wake Lock en primer plano → `posiciones_gps`.
- Piloto A/B contra AppSheet con 1-2 conductores.
- ✔️ Verificación: despacho completo gestionado solo con la PWA desde un celular real.

### Etapa 3 — Torre de control (semanas 7-9 · $7-15/mes)
- Mapa monitor (Streamlit autorefresh 20 s o Leaflet + Realtime): última posición
  por vehículo, semáforo de paradas, % avance por ruta. Purga de `posiciones_gps` a 30 días.
- ✔️ Verificación: marcar una parada (conductor) se refleja en el monitor en <30 s.

### Etapa 4 — SaaS mínimo + primer cliente (semanas 9-12 · $33-45/mes)
- Segunda org (alta manual en Supabase), **test ritual RLS** (org B no ve datos de org A),
  roles en PWA/monitor, landing 1 página + demo con `tiendas_prueba_1500.csv`.
- Capacitor (GPS background) SOLO si el piloto lo exige.
- ✔️ Verificación: 1 cliente externo operando un despacho real en su org, pagando.

## Posicionamiento comercial

- Competencia: SimpliRoute ~$40-60 USD/veh/mes (Perú: S/153-188 vía Movistar);
  Beetrack/DispatchTrack cotiza similar.
- Nicho: distribuidoras pequeñas/medianas en Perú (5-20 vehículos).
  Precio objetivo: **S/80-120/veh/mes** + onboarding en persona + puente Excel/Sheets.
- Activo diferencial ya construido: optimizador real (flota heterogénea + ventanas
  horarias + multi-vuelta), que los SaaS baratos no tienen.

## Puertas de decisión (no avanzar sin cumplirlas)

1. **Fin E0:** ≥2 semanas de despachos reales con ≥80% de paradas cerradas con POD.
2. **Fin E2-3:** la PWA reemplaza AppSheet sin caída de adopción; el monitor se usa a diario.
3. **Antes de E4:** 3-5 conversaciones con distribuidoras validando precio +
   **1 cliente pagando que renueva** tras 1 mes.
4. **Siempre:** soporte <3-4 h/semana; si desborda, ajustar antes de sumar clientes.

## Riesgos vigilados

1. GPS background en PWA (iOS bloquea) → vender "tracking por hitos"; Capacitor como plan B.
2. Fuga entre tenants por RLS mal hecho → test ritual con 2 orgs; alternativa: instancia por cliente.
3. Soporte unipersonal → Sheets/AppSheet como contingencia permanente; runbooks; SLA humilde.
4. OSRM público sin SLA → cache propio + ORS como proveedor B + OSRM self-hosted como plan C.
5. Quedarse atrapado en AppSheet → caducidad explícita al fin de la Etapa 2.
