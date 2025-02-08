from flask import Flask
from .routes import app_routes
from .scheduler import start_scheduler
from .models import init_db

def create_app() -> Flask:
    """
    Initializes the Flask app, registers the routes, and starts the scheduler.

    This function sets up the main app by registering the blueprint that contains
    the routes for handling Slack interactions, and it also starts the scheduler
    for automated tasks like daily summaries and reminders.

    :return: Flask app instance.
    """
    app = Flask(__name__)

    # Initialize the database tables
    init_db()
    
    # Register blueprint for app routes
    app.register_blueprint(app_routes)

    # Start the scheduler for background tasks
    start_scheduler()

    return app
