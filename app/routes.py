from flask import Blueprint, request, jsonify
from .models import add_task_to_db, get_tasks_from_db, update_task_to_db
from .slack_bot import send_message_to_slack

app_routes = Blueprint('app_routes', __name__)

@app_routes.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.json
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})
    return jsonify({"message": "Event received"}), 200

@app_routes.route("/slack/list_tasks", methods=["POST"])
def list_tasks():
    tasks = get_tasks_from_db()

    formatted_tasks = []
    for task in tasks:
        task_id, task_description, completed = task
        status = "Pending" if completed == 0 else "Completed"
        formatted_tasks.append({
            "task_id": task_id,
            "task": task_description,
            "status": status
        })

    return jsonify({
        "response_type": "ephemeral",
        "text": f"*Here are your tasks:* \n{formatted_tasks}"
    })

@app_routes.route("/slack/add_task", methods=["POST"])
def add_task():
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
def mark_task_done():
    data = request.form
    
    task_id = data.get("text")  # The task ID should be passed as text
    
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