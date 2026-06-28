"""ASGI entrypoint. The platform's supervisor serves `server:app` with uvicorn;
`server.py` re-exports this `application`."""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
