FROM apache/airflow:2.9.1

COPY requirements-airflow.txt .
RUN pip install -r requirements-airflow.txt