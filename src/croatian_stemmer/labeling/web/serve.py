"""Uvicorn entry point; importing the optional package alone creates no server."""
from .api import create_app
from .config import Settings

app = create_app(Settings.from_environment())
