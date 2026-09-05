"""
SahyogSutra Application Package.
Exposes the ASGI app instance so `uvicorn app:app` works seamlessly.
"""

from app.main import asgi_app as app, app as fastapi_app

__all__ = ["app", "fastapi_app"]
