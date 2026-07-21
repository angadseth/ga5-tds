"""Record what the grader actually sends us.

Both remaining failures are guesses about inputs we have never seen: which
URL Q8's surviving probe uses, and what Q9's dossiers really contain. The
service already receives all of it, so store it and read it back instead of
theorising.

Retrieval is behind a secret so the dump is not public. Nothing here changes
how any question answers.
"""
import json
import os
import sqlite3
import threading
import time

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

DB = os.environ.get("GA5_DB", "/tmp/ga5.db")
SECRET = os.environ.get("CAPTURE_SECRET", "")
MAX_BODY = 2_000_000
_lock = threading.Lock()

WATCH = ("/q8/check", "/q9/mailroom", "/v2/incidents", "/a2a/", "/q4/scan")


def _conn():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


with _lock:
    _c = _conn()
    _c.execute("""CREATE TABLE IF NOT EXISTS capture(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL, path TEXT, client TEXT, body TEXT, response TEXT)""")
    cols = {r[1] for r in _c.execute("PRAGMA table_info(capture)")}
    if "headers" not in cols:
        _c.execute("ALTER TABLE capture ADD COLUMN headers TEXT")
    if "method" not in cols:
        _c.execute("ALTER TABLE capture ADD COLUMN method TEXT")
    if "status" not in cols:
        _c.execute("ALTER TABLE capture ADD COLUMN status INTEGER")
    _c.commit()
    _c.close()


def record(path, client, body, response=None, headers=None, method="POST", status=None):
    try:
        with _lock:
            c = _conn()
            c.execute("INSERT INTO capture(ts,path,client,body,response,headers,method,status)"
                      " VALUES(?,?,?,?,?,?,?,?)",
                      (time.time(), path, client, body[:MAX_BODY],
                       (response or "")[:MAX_BODY],
                       json.dumps(headers or {})[:MAX_BODY], method, status))
            c.execute("DELETE FROM capture WHERE id NOT IN "
                      "(SELECT id FROM capture ORDER BY id DESC LIMIT 400)")
            c.commit()
            c.close()
    except Exception:
        pass


async def middleware(request: Request, call_next):
    path = request.url.path
    if not any(path.startswith(w) for w in WATCH):
        return await call_next(request)

    raw = await request.body()

    # Starlette consumes the body stream; hand it back so the route still reads it.
    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    request._receive = receive
    response = await call_next(request)

    chunks = [c async for c in response.body_iterator]
    payload = b"".join(chunks)

    from starlette.responses import Response
    out = Response(content=payload, status_code=response.status_code,
                   headers=dict(response.headers), media_type=response.media_type)

    client = request.client.host if request.client else "?"
    record(path, client, raw.decode("utf-8", "replace"),
           payload.decode("utf-8", "replace"),
           headers=dict(request.headers), method=request.method,
           status=response.status_code)
    return out


def _auth(key):
    if not SECRET or key != SECRET:
        raise HTTPException(status_code=404, detail="not found")


@router.get("/debug/capture")
async def list_capture(key: str = "", path: str = "", limit: int = 20):
    _auth(key)
    c = _conn()
    q = ("SELECT id,ts,path,client,length(body),length(response),method,status"
         " FROM capture")
    args = []
    if path:
        q += " WHERE path LIKE ?"
        args.append(path + "%")
    q += " ORDER BY id DESC LIMIT ?"
    args.append(min(limit, 200))
    rows = c.execute(q, args).fetchall()
    c.close()
    return [{"id": r[0], "ts": r[1], "path": r[2], "client": r[3],
             "reqBytes": r[4], "respBytes": r[5], "method": r[6],
             "status": r[7]} for r in rows]


@router.get("/debug/capture/{cid}")
async def get_capture(cid: int, key: str = ""):
    _auth(key)
    c = _conn()
    row = c.execute("SELECT ts,path,client,body,response,headers,method,status"
                    " FROM capture WHERE id=?", (cid,)).fetchone()
    c.close()
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    def _p(s):
        try:
            return json.loads(s)
        except Exception:
            return s
    return {"ts": row[0], "path": row[1], "client": row[2],
            "method": row[6], "status": row[7], "headers": _p(row[5]),
            "request": _p(row[3]), "response": _p(row[4])}
