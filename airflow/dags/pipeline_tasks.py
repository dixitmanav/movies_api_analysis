"""
Shared pieces for the movie DAGs (this file has no DAG of its own).

The repo folder is mounted into the Airflow container at PROJECT_DIR, so the tasks
run our existing scripts there and movies.db stays in the repo folder.
"""

import os
import sys

from airflow.exceptions import AirflowException

PROJECT_DIR = os.getenv("MOVIES_PROJECT_DIR", "/opt/airflow/project")
DB_PATH = os.path.join(PROJECT_DIR, "movies.db")


def run_script(script, *args):
    """Shell command for a BashOperator: run one of our scripts from the repo folder."""
    return f"cd {PROJECT_DIR} && python {script} {' '.join(args)}".strip()


def check_keys(need_omdb_list=False):
    """Fail right away, with a clear message, if the API keys are missing from .env."""
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_DIR, ".env"))
    missing = []
    if not os.getenv("TMDB_API_KEY"):
        missing.append("TMDB_API_KEY")
    if not (os.getenv("OMDB_API_KEY") or (need_omdb_list and os.getenv("OMDB_API_KEYS"))):
        missing.append("OMDB_API_KEY" + (" or OMDB_API_KEYS" if need_omdb_list else ""))
    if missing:
        raise AirflowException(f"Missing in .env: {', '.join(missing)}. Copy .env.example to .env and add your keys.")
    print("API keys found.")


def finish_run(**context):
    """
    Last task of every DAG run (runs even if an earlier task failed).
    Logs the run to pipeline_runs, then fails if anything upstream failed,
    so the DAG run still shows red in Airflow.
    """
    dag_run = context["dag_run"]
    failed = [
        ti.task_id
        for ti in dag_run.get_task_instances()
        if ti.task_id != context["task"].task_id and ti.state in ("failed", "upstream_failed")
    ]

    sys.path.insert(0, PROJECT_DIR)
    from log_run import log_run   # our script in the repo folder

    row = log_run(
        run_id=dag_run.run_id,
        dag_id=dag_run.dag_id,
        started_at=dag_run.start_date,
        status="failed" if failed else "success",
        failed_tasks=", ".join(failed),
        db_path=DB_PATH,
    )
    print(f"Logged run: {row}")

    if failed:
        raise AirflowException(f"These tasks failed: {', '.join(failed)}")
