FROM python:3.11-slim

WORKDIR /app

COPY services/event-bridge/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["uvicorn", "services.event-bridge.main:app", "--host", "0.0.0.0", "--port", "8090", "--reload", "--reload-dir", "/app"]
