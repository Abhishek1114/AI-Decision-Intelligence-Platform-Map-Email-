FROM python:3.11-slim

WORKDIR /app
COPY phase2/phase7/dashboard/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/app
CMD ["streamlit", "run", "phase2/phase7/dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8501"]