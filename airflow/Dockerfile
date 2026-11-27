FROM apache/airflow:2.9.3-python3.10

# Packages our scripts need (requests, pandas, python-dotenv).
# The constraints file keeps them compatible with Airflow 2.9.3.
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt \
    --constraint https://raw.githubusercontent.com/apache/airflow/constraints-2.9.3/constraints-3.10.txt
