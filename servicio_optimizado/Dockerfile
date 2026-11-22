# Dockerfile - Imagen OPTIMIZADA de la API de WODPredict-AI (Etapa 6)
# Se construye desde la RAÍZ del repositorio para copiar modelo/:
#   docker build -f servicio_optimizado/Dockerfile -t wodpredict-api:2.0-onnx .
#   docker run -d --name wodpredict-onnx -p 8001:8000 wodpredict-api:2.0-onnx
#
# Cambios frente a la imagen de la Etapa 4 (mismas buenas prácticas: slim, usuario sin privilegios,
# HEALTHCHECK, puerto por variable PORT):
#   - Solo instala numpy, onnxruntime, fastapi, pydantic y uvicorn (sin pandas/scipy/scikit-learn).
#   - Copia el modelo ONNX (≈ 3 KB) en lugar del pickle de scikit-learn.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY servicio_optimizado/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY servicio_optimizado/app.py .
COPY servicio_optimizado/frontend/ frontend/
COPY modelo/model.onnx modelo/metadata.json modelo/

RUN useradd --create-home appuser
USER appuser

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, os; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/')" || exit 1

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
