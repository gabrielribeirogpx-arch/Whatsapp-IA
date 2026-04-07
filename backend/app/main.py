from fastapi import FastAPI
from backend.app.routers import webhook

app = FastAPI()

app.include_router(webhook.router)


@app.get("/")
def root():
    return {"status": "ok"}
