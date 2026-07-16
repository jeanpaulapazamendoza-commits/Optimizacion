#!/usr/bin/env sh
# ============================================================
#  entrypoint.sh — se ejecuta al arrancar el contenedor
#  1) Coloca los secretos (login + credenciales de Google)
#     donde Streamlit los espera: /app/.streamlit/secrets.toml
#  2) Lanza Streamlit en el puerto que asigne la plataforma
# ============================================================
set -e

# Streamlit busca los secretos aquí:
mkdir -p /app/.streamlit

if [ -f /etc/secrets/secrets.toml ]; then
  # CASO A) Render montó un "Secret File" llamado secrets.toml
  cp /etc/secrets/secrets.toml /app/.streamlit/secrets.toml
  echo "[entrypoint] Secretos cargados desde /etc/secrets/secrets.toml"

elif [ -n "$APP_SECRETS_TOML" ]; then
  # CASO B) Los secretos vienen en una variable de entorno
  #         (útil en Cloud Run, Railway, Fly.io, etc.)
  printf '%s' "$APP_SECRETS_TOML" > /app/.streamlit/secrets.toml
  echo "[entrypoint] Secretos cargados desde la variable APP_SECRETS_TOML"

else
  echo "[entrypoint] AVISO: no encontre secretos. El login y la escritura"
  echo "[entrypoint] a Google Sheets estaran deshabilitados (la app abre igual)."
fi

# $PORT lo inyecta la plataforma (Render, Cloud Run...); 8501 es el valor local.
exec streamlit run app.py \
  --server.port="${PORT:-8501}" \
  --server.address=0.0.0.0 \
  --server.headless=true
