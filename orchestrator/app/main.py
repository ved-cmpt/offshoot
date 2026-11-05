from fastapi import FastAPI

app = FastAPI(title="LegacyLens orchestrator")


@app.get("/api/v1/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
