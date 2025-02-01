from flask import Flask
from .routes import app_routes
from .scheduler import start_scheduler

def create_app():
    app = Flask(__name__)
    app.register_blueprint(app_routes)
    start_scheduler()
    return app
