import sqlite3
from typing import List, Tuple
from .constants import DB_FILE

def init_db() -> None:
    """
    Initializes the database by creating the necessary tables if they do not exist.
    :return: None
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Create tasks table (if not exists)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            completed INTEGER DEFAULT 0
        )
    """)

    # Create deep work mode table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deep_work (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            active INTEGER DEFAULT 0,
            end_time TEXT
        )
    """)

    conn.commit()
    conn.close()

def add_task_to_db(task_text: str) -> None:
    """
    Adds a new task to the database.

    :param task_text: str -> The description of the task to be added.
    :return: None
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tasks (task) VALUES (?)", (task_text,))
    conn.commit()
    conn.close()

def get_tasks_from_db() -> List[Tuple[int, str, int]]:
    """
    Retrieves all pending tasks from the database.

    :return: List[Tuple[int, str, int]] -> A list of tasks, where each task is represented as (id, task, completed).
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE completed = 0")
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def update_task_to_db(task_id: int) -> None:
    """
    Marks a task as completed in the database.

    :param task_id: int -> The ID of the task to be marked as completed.
    :return: None
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE tasks SET completed = 1 WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
