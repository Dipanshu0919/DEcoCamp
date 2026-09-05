"""
SahyogSutra Root Entrypoint Alias for `uvicorn main:app`.
"""

from app.main import asgi_app as app, app as fastapi_app

if __name__ == "__main__":
    import uvicorn
    from app.config import HOST, PORT
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)

