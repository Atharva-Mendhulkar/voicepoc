FROM python:3.11-slim

WORKDIR /app

COPY services/session-router/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The shared library and the service code will be mounted as volumes in docker-compose for hot-reloading
CMD ["uvicorn", "services.session-router.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/app"]
