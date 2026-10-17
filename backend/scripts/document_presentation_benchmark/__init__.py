"""Internal implementation for the document-presentation benchmark."""

from app.main import create_app

# Importing the app factory first matches the production service's module order.
_APP_FACTORY = create_app
