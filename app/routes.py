from flask import Blueprint, request, jsonify
from .models import add_task_to_db, get_tasks_from_db, update_task_to_db
from .slack_bot import handle_slack_mention, async_generate_standup
from typing import Dict, Any
from datetime import datetime, timedelta
import sqlite3
import threading
from .constants import SLACK_USER_ID, DB_FILE

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

@app_routes.route("/slack/standup", methods=["POST"])
def send_standup_update() -> Dict[str, Any]:
    """
    Handles the Slack command `/standup` and responds asynchronously to prevent timeout.

    :return: A JSON response confirming that the standup report is being generated.
    """
    
    # Respond immediately to prevent Slack timeout
    threading.Thread(target=async_generate_standup).start()

    return jsonify({
        "response_type": "ephemeral",
        "text": "⏳ Generating your standup report... Please wait a moment."
    })

@app_routes.route("/slack/createprodpr", methods=["POST"])
def create_prod_pr() -> Dict[str, Any]:
    """
    Slack command:
    /createprodpr TICKET-123 [feature-branch]

    Reads DEV PR links from the Jira ticket, creates a '{feature-branch-or-ticket}-Prod'
    branch from each repo's prod branch, opens a PROD PR, and links it back to the ticket.
    """

    data = request.form
    text = data.get("text", "").strip()

    if not text:
        return jsonify({
            "response_type": "ephemeral",
            "text": "Usage: `/createprodpr TICKET-123 [feature-branch]`"
        })

    parts = text.split()

    if len(parts) not in (1, 2):
        return jsonify({
            "response_type": "ephemeral",
            "text": "Usage: `/createprodpr TICKET-123 [feature-branch]`"
        })

    jira_ticket = parts[0]
    feature_branch = parts[1] if len(parts) == 2 else None

    from .slack_bot import handle_create_prod_pr

    threading.Thread(
        target=handle_create_prod_pr,
        args=(jira_ticket, feature_branch)
    ).start()

    return jsonify({
        "response_type": "ephemeral",
        "text": "Creating PROD PRs... please wait ⏳"
    })


@app_routes.route("/slack/createpr", methods=["POST"])
def create_pr() -> Dict[str, Any]:
    """
    Slack command:
    /createpr TICKET-123 [feature-branch] repo-name [--no-transition]
    """

    data = request.form
    text = data.get("text", "").strip()

    if not text:
        return jsonify({
            "response_type": "ephemeral",
            "text": "Usage: `/createpr TICKET-123 [feature-branch] repo-name [--no-transition]`"
        })

    parts = text.split()
    move_to_review = "--no-transition" not in parts
    positional = [p for p in parts if not p.startswith("--")]

    if len(positional) not in (2, 3):
        return jsonify({
            "response_type": "ephemeral",
            "text": "Usage: `/createpr TICKET-123 [feature-branch] repo-name [--no-transition]`"
        })

    jira_ticket = positional[0]
    if len(positional) == 2:
        feature_branch = None
        repo_name = positional[1]
    else:
        feature_branch = positional[1]
        repo_name = positional[2]

    from .slack_bot import handle_create_pr
    import threading

    # Run PR creation in background thread
    threading.Thread(
        target=handle_create_pr,
        args=(jira_ticket, repo_name, feature_branch, move_to_review)
    ).start()

    # Immediate response to Slack
    return jsonify({
        "response_type": "ephemeral",
        "text": "Creating PR... please wait ⏳"
    })
