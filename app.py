"""
SahyogSutra Main Entrypoint.
Exposes the ASGI app instance for Uvicorn and production WSGI/ASGI servers.
"""

import os
from app.main import asgi_app as app
from app.config import HOST, PORT

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=HOST, port=PORT, reload=False)
