# ============================================================
#  Dockerfile — RuteoTiendas Planner (Streamlit)
#  Construye una imagen lista para desplegar en Render,
#  Google Cloud Run, Railway, Fly.io, etc.
# ============================================================

# Imagen base ligera con Python 3.11 (suficiente para todas las
# dependencias: pandas, scikit-learn, ortools, folium, gspread...)
FROM python:3.11-slim

# Buenas prácticas: logs en vivo, sin archivos .pyc, sin caché de pip
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Carpeta de trabajo dentro del contenedor
WORKDIR /app

# 1) Copiamos SOLO requirements.txt primero.
#    Así, si no cambian las dependencias, Docker reutiliza esta capa
#    y las siguientes construcciones son mucho más rápidas.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 2) Copiamos el resto del proyecto (código, datos de ejemplo, config).
#    Lo que NO queremos copiar está listado en .dockerignore.
COPY . .

# El script de arranque coloca los secretos y lanza Streamlit.
RUN chmod +x entrypoint.sh

# Puerto informativo (en la nube la plataforma inyecta $PORT en runtime).
EXPOSE 8501

# Arranque de la app.
ENTRYPOINT ["./entrypoint.sh"]
