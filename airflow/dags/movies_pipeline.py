"""
movies_pipeline: pulls today's trending and now-playing movies into movies.db.

    check_keys -> build_database -> clean_snapshots -> quality_checks -> log_run

Runs only when triggered (ad hoc). To run it every day instead, change SCHEDULE below,
e.g. SCHEDULE = "0 9 * * *" runs at 9 AM Chicago time.
"""

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

from pipeline_tasks import check_keys, finish_run, run_script

SCHEDULE = None   # None = only when triggered in the Airflow UI

with DAG(
    dag_id="movies_pipeline",
    description="Daily TMDb trending/now-playing pull + OMDb ratings into movies.db",
    schedule=SCHEDULE,
    start_date=pendulum.datetime(2026, 11, 1, tz="America/Chicago"),
    catchup=False,
    max_active_runs=1,   # never two runs writing to movies.db at once
    default_args={"owner": "movies-team", "retries": 0},
    tags=["movies"],
    doc_md=__doc__,
) as dag:

    keys = PythonOperator(
        task_id="check_keys",
        python_callable=check_keys,
    )

    build = BashOperator(
        task_id="build_database",
        bash_command=run_script("build_database.py"),
        retries=1,                          # safe to rerun: no duplicates
        retry_delay=timedelta(minutes=5),
    )

    clean = BashOperator(
        task_id="clean_snapshots",
        bash_command=run_script("clean_snapshots.py"),
    )

    quality = BashOperator(
        task_id="quality_checks",
        bash_command=run_script("quality_checks.py"),
    )

    log = PythonOperator(
        task_id="log_run",
        python_callable=finish_run,
        trigger_rule=TriggerRule.ALL_DONE,  # log failed runs too
    )

    keys >> build >> clean >> quality >> log
