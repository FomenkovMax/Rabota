"""Точка входа: uvicorn backend.main:app"""
from .app import create_app
from .legacy import import_legacy
from .settings import load_settings

settings = load_settings()
app = create_app(settings)
import_legacy(app.state.factory, settings.data_dir)
