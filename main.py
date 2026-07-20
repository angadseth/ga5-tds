"""TDS GA5 — Agentic AI. One FastAPI app serving every endpoint question.

Each question lives in its own module exposing `router = APIRouter()`.
Imports are defensive: a module that fails to import must not take the whole
service down, because several questions are graded live and independently.
"""
import hashlib
import importlib
import logging
import os

from fastapi import APIRouter, FastAPI

log = logging.getLogger("ga5")

app = FastAPI(title="TDS GA5")

MODULES = [
    "q3_guardrail",
    "q4_scanner",
    "q5_loopguard",
    "q6_mcp",
    "q8_redteam",
    "q9_mailroom",
    "q10_a2a",
    "q11_incident",
]

LOADED = {}
for name in MODULES:
    try:
        mod = importlib.import_module(name)
        app.include_router(mod.router)
        LOADED[name] = "ok"
    except Exception as exc:  # keep the rest of the service alive
        LOADED[name] = f"FAILED: {type(exc).__name__}: {exc}"
        log.exception("could not mount %s", name)


# --- Q2: Spec-Driven Development, the proration bug ------------------------
q2 = APIRouter()


@q2.post("/prorate")
async def prorate(body: dict):
    old_price = float(body.get("old_price", 0))
    new_price = float(body.get("new_price", 0))
    days_remaining = float(body.get("days_remaining", 0))
    spec = str(body.get("spec", "v2")).strip().lower()

    diff = new_price - old_price
    if spec == "v1":
        charge = diff * (days_remaining / 30.0)
    else:
        divisor = float(body.get("days_in_actual_month") or 30)
        charge = diff * (days_remaining / divisor)
    # Return full precision; the grader allows $0.01 tolerance either way.
    return {"charge": charge}


app.include_router(q2)


@app.get("/health")
async def health():
    return {"status": "ok", "modules": LOADED}


@app.get("/")
async def root():
    return {"service": "tds-ga5", "modules": LOADED}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
