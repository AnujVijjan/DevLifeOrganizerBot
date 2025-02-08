from flask import Blueprint, request, jsonify
from .models import add_task_to_db, get_tasks_from_db, update_task_to_db
from typing import Dict, Any

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
