FROM python:3.11-slim

WORKDIR /app
COPY phase2/phase7/alert_consumer/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/app
CMD ["python", "-m", "phase2.phase7.alert_consumer.consumer"]