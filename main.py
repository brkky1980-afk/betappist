from fastapi import FastAPI
from app.db import Base, engine

app = FastAPI(title="BetAppist API", version="0.1.0")

@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/")
def root() -> dict[str, str]:
    return {"service": "betappist", "status": "running"}
