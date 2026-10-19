import re
import pyodbc
from typing import Any, Dict, List, Tuple

from .constants import DEPLOY_ENVIRONMENTS
from .helper import get_pr_file_content, get_pr_files

_BATCH_SEPARATOR_RE = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)

def get_deploy_environment(env: str) -> Dict[str, Any]:
    """
    Returns the DEPLOY_ENVIRONMENTS entry for env, raising if the env is unknown
    or any of its source database, target database or connection string is unset.
    """

    config = DEPLOY_ENVIRONMENTS.get(env)

    if not config:
        raise ValueError(f"Unknown deploy environment `{env}`. Choose one of: {', '.join(DEPLOY_ENVIRONMENTS)}.")

    prefix = env.upper()
    required = {
        "source_database": "SP_SOURCE_DATABASE",
        "target_database": f"{prefix}_DATABASE_NAME",
        "connection_string": f"{prefix}_DATABASE_CONNECTION_STRING",
    }
    missing = [var for key, var in required.items() if not config.get(key)]

    if missing:
        raise RuntimeError(f"Missing configuration for {config['label']} deploy: {', '.join(missing)}.")

    return config

def get_changed_stored_procedures(repo: str, pr_number: int) -> List[Dict[str, Any]]:
    """
    Returns the .sql files changed in a PR (added/modified, not removed), each as
    {"path", "status", "content"}. Skips files whose blob isn't decodable as UTF-8
    text.
    """

    procs = []

    for f in get_pr_files(repo, pr_number):
        path = f["filename"]
        if not path.lower().endswith(".sql") or f["status"] == "removed":
            continue

        content = get_pr_file_content(repo, f)
        if content is None:
            continue

        procs.append({"path": path, "status": f["status"], "content": content})

    return procs

def rewrite_use_statement(sql_text: str, env: str) -> Tuple[str, int]:
    """
    Replaces every `USE [<source database>]` with `USE [<env target database>]`.
    Returns the rewritten text and the number of replacements made.
    """

    config = get_deploy_environment(env)
    pattern = re.compile(rf"USE\s*\[{re.escape(config['source_database'])}\]", re.IGNORECASE)

    return pattern.subn(lambda _: f"USE [{config['target_database']}]", sql_text)

def run_sql_script(cursor, sql_text: str) -> None:
    """
    Executes a SQL script that may contain `GO` batch separators, which pyodbc
    can't run in a single execute() call.
    """

    for batch in _BATCH_SEPARATOR_RE.split(sql_text):
        batch = batch.strip()
        if batch:
            cursor.execute(batch)

def deploy_stored_procs(procs: List[Dict[str, Any]], env: str) -> List[Dict[str, Any]]:
    """
    Rewrites each proc's USE statement to target the env's database and runs it
    there, one transaction per script. Returns one result dict per proc.
    """

    config = get_deploy_environment(env)
    results = []
    conn = pyodbc.connect(config["connection_string"], autocommit=False)

    try:
        cursor = conn.cursor()
        for proc in procs:
            rewritten, replacements = rewrite_use_statement(proc["content"], env)
            try:
                run_sql_script(cursor, rewritten)
                conn.commit()
                results.append({
                    "path": proc["path"],
                    "success": True,
                    "use_statements_rewritten": replacements,
                })
            except pyodbc.Error as e:
                conn.rollback()
                results.append({"path": proc["path"], "success": False, "error": str(e)})
    finally:
        conn.close()

    return results
