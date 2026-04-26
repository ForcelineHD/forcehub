from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

APP_NAME = "forcehub"
APP_VERSION = "0.1.0"

app = FastAPI(
    title="ForceHub",
    description="Local dashboard for ForceHub projects and tools.",
    version=APP_VERSION,
)


class StatusResponse(BaseModel):
    status: str
    app: str
    version: str


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!doctype html>
    <html>
      <head>
        <title>ForceHub</title>
      </head>
      <body style="font-family:Arial;background:#111;color:#eee;padding:30px">
        <h1>ForceHub</h1>
        <p>ForceHub is running.</p>
        <ul>
          <li><a style="color:#8ab4ff" href="/status">Status API</a></li>
          <li><a style="color:#8ab4ff" href="/docs">API Docs</a></li>
        </ul>
      </body>
    </html>
    """


@app.get("/status", response_model=StatusResponse)
def status():
    return StatusResponse(
        status="ok",
        app=APP_NAME,
        version=APP_VERSION,
    )
