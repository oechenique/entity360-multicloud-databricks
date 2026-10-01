# Fase 8 (regla 10): Airflow local con Cosmos. Contexto de build: la raíz del repo (docker-compose.yml);
# Dockerfile.dockerignore deja pasar solo los requirements.
FROM apache/airflow:3.3.2-python3.12

# Airflow y sus providers, con los constraints oficiales de la versión (Cosmos no está en ellos).
ARG AIRFLOW_VERSION=3.3.2
ARG CONSTRAINTS=https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" \
      "apache-airflow-providers-databricks==7.20.0" \
      "astronomer-cosmos==1.15.1" \
      "pymssql==2.4.1" "requests==2.34.2" \
      --constraint "${CONSTRAINTS}"

# dbt y Soda en entornos propios: sus dependencias no se mezclan con las de Airflow.
COPY --chown=airflow:root dbt/requirements.txt dbt/requirements-snowflake.txt /tmp/
COPY --chown=airflow:root contracts/requirements.txt /tmp/req-soda.txt
RUN python -m venv /opt/airflow/venvs/dbt && /opt/airflow/venvs/dbt/bin/pip install --no-cache-dir -r /tmp/requirements-snowflake.txt \
 && python -m venv /opt/airflow/venvs/soda && /opt/airflow/venvs/soda/bin/pip install --no-cache-dir -r /tmp/req-soda.txt
