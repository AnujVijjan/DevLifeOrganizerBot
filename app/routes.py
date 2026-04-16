from flask import Blueprint, request, jsonify
from .models import add_task_to_db, get_tasks_from_db, update_task_to_db
from .slack_bot import handle_slack_mention, async_generate_standup
from typing import Dict, Any, List, Set, Tuple
from datetime import datetime, timedelta
import sqlite3
import threading
from .constants import SLACK_USER_ID, DB_FILE
from .helper import resolve_createpr_inputs, resolve_createprodpr_inputs

app_routes = Blueprint('app_routes', __name__)

CREATEPR_USAGE = "Usage: `/createpr TICKET-123 --repo repo-name [--branch feature-branch] [--no-transition]`"
CREATEPRODPR_USAGE = "Usage: `/createprodpr TICKET-123 [--branch feature-branch] [--repo repo-name]`"

def _parse_slack_command_parts(
    parts: List[str],
    value_flags: Set[str],
    switch_flags: Set[str],
) -> Tuple[List[str], Dict[str, str], Set[str]]:
    positional: List[str] = []
    options: Dict[str, str] = {}
    switches: Set[str] = set()
    i = 0

    while i < len(parts):
        part = parts[i]

        if "=" in part:
            flag, value = part.split("=", 1)
            if flag in value_flags:
                if flag in options or not value:
                    raise ValueError("Duplicate or empty option value.")
                options[flag] = value
                i += 1
                continue

        if part in value_flags:
            if part in options or i + 1 >= len(parts):
                raise ValueError("Missing option value.")
            options[part] = parts[i + 1]
            i += 2
            continue

        if part in switch_flags:
            switches.add(part)
            i += 1
            continue

        if part.startswith("--"):
            raise ValueError("Unknown option.")

        positional.append(part)
        i += 1

    return positional, options, switches

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
    /createprodpr TICKET-123 [--branch feature-branch] [--repo repo-name]

    Reads DEV PR links from the Jira ticket, creates a '{feature-branch-or-ticket}-Prod'
    branch from each repo's prod branch, opens a PROD PR, and links it back to the ticket.
    """

    data = request.form
    text = data.get("text", "").strip()

    if not text:
        return jsonify({
            "response_type": "ephemeral",
            "text": CREATEPRODPR_USAGE
        })

    try:
        positional, options, _ = _parse_slack_command_parts(
            text.split(),
            value_flags={"--branch", "--repo"},
            switch_flags=set(),
        )
        if not positional:
            raise ValueError("Jira ticket is required.")

        jira_ticket = positional[0]
        feature_branch, repo_name = resolve_createprodpr_inputs(
            jira_ticket=jira_ticket,
            legacy_args=positional[1:],
            feature_branch=options.get("--branch"),
            repo_name=options.get("--repo"),
        )
    except ValueError as e:
        return jsonify({
            "response_type": "ephemeral",
            "text": f"{str(e)}\n{CREATEPRODPR_USAGE}"
        })

    from .slack_bot import handle_create_prod_pr

    threading.Thread(
        target=handle_create_prod_pr,
        args=(jira_ticket, feature_branch, repo_name)
    ).start()

    return jsonify({
        "response_type": "ephemeral",
        "text": "Creating PROD PRs... please wait ⏳"
    })


@app_routes.route("/slack/createpr", methods=["POST"])
def create_pr() -> Dict[str, Any]:
    """
    Slack command:
    /createpr TICKET-123 --repo repo-name [--branch feature-branch] [--no-transition]
    """

    data = request.form
    text = data.get("text", "").strip()

    if not text:
        return jsonify({
            "response_type": "ephemeral",
            "text": CREATEPR_USAGE
        })

    try:
        positional, options, switches = _parse_slack_command_parts(
            text.split(),
            value_flags={"--branch", "--repo"},
            switch_flags={"--no-transition"},
        )
        if not positional:
            raise ValueError("Jira ticket is required.")

        jira_ticket = positional[0]
        feature_branch, repo_name = resolve_createpr_inputs(
            jira_ticket=jira_ticket,
            legacy_args=positional[1:],
            feature_branch=options.get("--branch"),
            repo_name=options.get("--repo"),
        )
        move_to_review = "--no-transition" not in switches
    except ValueError as e:
        return jsonify({
            "response_type": "ephemeral",
            "text": f"{str(e)}\n{CREATEPR_USAGE}"
        })

    from .slack_bot import handle_create_pr

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
