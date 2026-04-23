from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="ForceHub")

@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html>
      <body style="font-family:Arial;background:#111;color:#eee;padding:30px">
        <h1>ForceHub</h1>
        <p>ForceHub is running.</p>
      </body>
    </html>
    """
