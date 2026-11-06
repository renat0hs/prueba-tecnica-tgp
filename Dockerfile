FROM python:3.12-slim

# No generar .pyc y mostrar los logs al instante (sin buffer)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code

# Primero solo las dependencias: si no cambia requirements.txt, Docker reutiliza esta capa
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Después el código
COPY app ./app

# Puerto: el de $PORT si existe (Render lo define), si no 8000 (local).
# "exec" reemplaza al sh por uvicorn: así uvicorn queda como PID 1 y recibe el SIGTERM directo.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
