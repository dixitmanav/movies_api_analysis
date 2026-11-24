"""
movies_backfill: adds the most-voted movies of each year (1980-2025) to movies.db.

    check_keys -> backfill_movies -> clean_snapshots -> quality_checks -> log_run

Manual trigger only. The backfill takes about half an hour for TMDb, and OMDb ratings
need a few days of calls, so trigger it again on later days; it picks up where it left off.
"""

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

from pipeline_tasks import check_keys, finish_run, run_script

with DAG(
    dag_id="movies_backfill",
    description="One-time historical pull of ~5,750 movies (1980-2025) + OMDb ratings",
    schedule=None,   # manual only
    start_date=pendulum.datetime(2026, 11, 1, tz="America/Chicago"),
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "movies-team", "retries": 0},
    tags=["movies"],
    doc_md=__doc__,
) as dag:

    keys = PythonOperator(
        task_id="check_keys",
        python_callable=check_keys,
        op_kwargs={"need_omdb_list": True},   # accepts OMDB_API_KEYS (several keys)
    )

    backfill = BashOperator(
        task_id="backfill_movies",
        bash_command=run_script("backfill_movies.py"),
        execution_timeout=timedelta(hours=8),
    )

    clean = BashOperator(
        task_id="clean_snapshots",
        bash_command=run_script("clean_snapshots.py"),
    )

    quality = BashOperator(
        task_id="quality_checks",
        bash_command=run_script("quality_checks.py", "--no-today"),   # no daily snapshot needed
    )

    log = PythonOperator(
        task_id="log_run",
        python_callable=finish_run,
        trigger_rule=TriggerRule.ALL_DONE,
    )

    keys >> backfill >> clean >> quality >> log
