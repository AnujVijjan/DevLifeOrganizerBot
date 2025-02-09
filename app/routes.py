from flask import Blueprint, request, jsonify
from .models import add_task_to_db, get_tasks_from_db, update_task_to_db
from .slack_bot import handle_slack_mention, SLACK_USER_ID
from typing import Dict, Any
from datetime import datetime, timedelta
import sqlite3
import os

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'bot_data.db')

app_routes = Blueprint('app_routes', __name__)

@app_routes.route("/slack/events", methods=["POST"])
def slack_events() -> Dict[str, Any]:
    """
    Handles Slack event subscription verification and incoming Slack events.

    :return: A JSON response containing the challenge token if requested, or a confirmation message.
    """
    data = request.json
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})
    
    if "event" in data:
        event = data["event"]
        event_type = event.get("type")
        user_id = event.get("user")

        if event_type == "message" and user_id != SLACK_USER_ID and "subtype" not in event and "bot_id" not in event:
            handle_slack_mention(event)
                
    return jsonify({"message": "Event received"}), 200

@app_routes.route("/slack/list_tasks", methods=["POST"])
def list_tasks() -> Dict[str, Any]:
    """
    Retrieves and formats a list of all pending tasks.

    :return: A JSON response containing the list of pending tasks formatted for Slack.
    """
    tasks = get_tasks_from_db()

    if not tasks:
        return jsonify({
            "response_type": "ephemeral",
            "text": "*Here are your tasks:* \nNo tasks available at the moment."
        })

    formatted_tasks = [
        {
            "task_id": task[0],
            "task": task[1],
            "status": "Pending" if task[2] == 0 else "Completed"
        }
        for task in tasks
    ]

    return jsonify({
        "response_type": "ephemeral",
        "text": "*Here are your tasks:* \n" + "\n".join(
            f"{task['task_id']}. {task['task']} - {task['status']}" for task in formatted_tasks
        )
    })

@app_routes.route("/slack/add_task", methods=["POST"])
def add_task() -> Dict[str, Any]:
    """
    Adds a new task to the database from a Slack command.

    :return: A JSON response confirming the task has been added or an error message.
    """
    data = request.form
    task_text = data.get("text")

    if not task_text:
        return jsonify({
            "response_type": "ephemeral",
            "text": "Please provide a task description, e.g. `/addtask Fix bug in login API`"
        }), 400

    add_task_to_db(task_text)

    return jsonify({
        "response_type": "ephemeral",
        "text": f"Task '{task_text}' has been added to your to-do list!"
    })

@app_routes.route("/slack/mark_task_done", methods=["POST"])
def mark_task_done() -> Dict[str, Any]:
    """
    Marks a task as completed based on the task ID received from Slack.

    :return: A JSON response confirming the task completion or an error message.
    """
    data = request.form
    task_id = data.get("text")

    if not task_id:
        return jsonify({
            "response_type": "ephemeral",
            "text": "Please provide a task ID to mark as done, e.g. `/marktaskdone 1`"
        }), 400

    update_task_to_db(task_id)

    return jsonify({
        "response_type": "ephemeral",
        "text": f"Task ID {task_id} has been marked as done!"
    })

@app_routes.route("/slack/deepworkon", methods=["POST"])
def enable_deep_work_mode() -> Dict[str, Any]:
    """
    Enables Deep Work Mode by muting notifications and setting an auto-reply.

    :return: A JSON response confirming activation.
    """
    data = request.form
    duration = int(data.get("text", 60))  # Default to 60 minutes if no duration is provided
    end_time = datetime.utcnow() + timedelta(minutes=duration)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM deep_work")  # Ensure only one active session
    cursor.execute("INSERT INTO deep_work (active, end_time) VALUES (1, ?)", (end_time,))
    conn.commit()
    conn.close()

    return jsonify({
        "response_type": "ephemeral",
        "text": f"🔕 Deep Work Mode is ON for {duration} minutes! I'll auto-reply if someone messages you."
    })

@app_routes.route("/slack/deepworkoff", methods=["POST"])
def disable_deep_work_mode() -> Dict[str, Any]:
    """
    Disables Deep Work Mode and unmutes notifications.

    :return: A JSON response confirming deactivation.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM deep_work")  # Clear deep work mode
    conn.commit()
    conn.close()

    return jsonify({
        "response_type": "ephemeral",
        "text": "✅ Deep Work Mode is OFF! You're back online."
    })
