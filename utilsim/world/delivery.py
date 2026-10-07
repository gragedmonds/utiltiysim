"""World-owned observation outbox. Acceptance is distinct from business processing.

The scheduler owns actor authentication and recipient deduplication. Only committed,
observation-only messages leave this store; no recipient database is opened here.
"""
import json
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .exchange import delivery_settings, export_in_transaction
from .store import canonical, stable

SCHEMA = """
CREATE TABLE IF NOT EXISTS observation_delivery_configuration(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observation_outbox(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
 day TEXT UNIQUE NOT NULL, available_at TEXT NOT NULL, fingerprint TEXT NOT NULL,
 envelope TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','accepted')),
 attempts INTEGER NOT NULL DEFAULT 0, receipt TEXT, last_error TEXT);
CREATE INDEX IF NOT EXISTS observation_outbox_pending ON observation_outbox(state,sequence);
"""


def configure(world, environment, sewer_factor="0.9", delay_seconds=0):
    """Pin a delivery stream from the next unprocessed day; never rewrite history."""
    factor, delay = delivery_settings(sewer_factor, delay_seconds)
    with world.db() as db:
        meta = world.metadata(db)
        if not meta or meta["environment"] != environment:
            raise ValueError("Initialize the matching world before configuring delivery.")
        settings = {"schemaVersion": "world-observation-delivery/1.0", "environmentId": environment,
                    "sewerReturnFactor": factor, "delaySeconds": delay}
        prior = db.execute("SELECT value FROM observation_delivery_configuration WHERE singleton=1").fetchone()
        if prior:
            value = json.loads(prior[0])
            if any(value[k] != v for k, v in settings.items()):
                raise ValueError("Delivery configuration is pinned; use a separate run for different settings.")
            return value
        value = {**settings, "from": meta["through"]}
        db.execute("INSERT INTO observation_delivery_configuration VALUES(1,?)", (canonical(value),))
        world.event(db, environment, meta["through"], "ObservationDeliveryConfigured", environment, value)
        return value


def append_day(world, db, start, end, cause):
    """Called inside the day transaction, including its cursor and observations."""
    row = db.execute("SELECT value FROM observation_delivery_configuration WHERE singleton=1").fetchone()
    if row is None:
        return
    config = json.loads(row[0])
    batch = export_in_transaction(world, db, start, end, config["sewerReturnFactor"], config["delaySeconds"])
    from datetime import UTC, datetime, timedelta

    requested = end + "T00:00:00Z"
    available = (datetime.fromisoformat(requested.replace("Z", "+00:00")) +
                 timedelta(seconds=config["delaySeconds"])).astimezone(UTC).isoformat().replace("+00:00", "Z")
    command = {"id": "world-observations-" + stable(config, start), "runId": config["environmentId"],
               "target": "isu", "operation": "ingest_v2", "requestedAt": requested,
               "availableAt": available, "payload": {"batch": batch}, "cause": cause,
               "correlation": "world-day:" + config["environmentId"] + ":" + start}
    envelope = canonical(command)
    if len(envelope.encode("utf-8")) > 8 * 1024 * 1024:
        raise ValueError("Daily observation delivery exceeds the 8 MiB gateway limit; day was rolled back.")
    db.execute("INSERT INTO observation_outbox(id,day,available_at,fingerprint,envelope,state) "
               "VALUES(?,?,?,?,?,'pending')", (command["id"], start, available, stable(command), envelope))


def status(world, offset=0, limit=50):
    """Bounded admin metadata; payloads, credentials and world truth are excluded."""
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Use a nonnegative offset and a limit between 1 and 200.")
    with world.db() as db:
        config = db.execute("SELECT value FROM observation_delivery_configuration WHERE singleton=1").fetchone()
        counts = {r["state"]: r["n"] for r in db.execute(
            "SELECT state,COUNT(*) n FROM observation_outbox GROUP BY state")}
        rows = [dict(r) for r in db.execute(
            "SELECT id,day,available_at,state,attempts,last_error FROM observation_outbox "
            "ORDER BY sequence LIMIT ? OFFSET ?", (limit, offset))]
        return {"configuration": json.loads(config[0]) if config else None,
                "pending": counts.get("pending", 0), "accepted": counts.get("accepted", 0),
                "offset": offset, "limit": limit, "items": rows}


def relay(world, send, limit=100):
    """Retry the exact committed envelope. An unknown reply keeps the oldest pending.

    Concurrent relays may send duplicates; the recipient must deduplicate by actor
    and command ID. No SQLite lock is held across the network call.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Relay between 1 and 1000 messages per call.")
    accepted = 0
    for _ in range(limit):
        with world.db() as db:
            row = db.execute("SELECT * FROM observation_outbox WHERE state='pending' "
                             "ORDER BY sequence LIMIT 1").fetchone()
            if row is None:
                break
            db.execute("UPDATE observation_outbox SET attempts=attempts+1 WHERE id=?", (row["id"],))
            command = json.loads(row["envelope"])
            if stable(command) != row["fingerprint"]:
                raise ValueError("Stored observation message checksum mismatch; restore a verified checkpoint.")
        try:
            receipt = send(command)
            if (not isinstance(receipt, dict) or receipt.get("id") != command["id"] or
                    receipt.get("status") not in ("pending", "delivering", "completed", "failed")):
                raise ValueError("Recipient did not acknowledge this command.")
            receipt_json = canonical(receipt)
        except Exception as exc:  # Unknown receipt: retain the original identity and payload.
            # Store the exception class, not URLs, credentials or arbitrary provider text.
            error = type(exc).__name__
            with world.db() as db:
                db.execute("UPDATE observation_outbox SET last_error=? WHERE id=? AND state='pending'",
                           (error, row["id"]))
            return {"accepted": accepted, "blocked": row["id"], "error": error}
        with world.db() as db:
            updated = db.execute("UPDATE observation_outbox SET state='accepted',receipt=?,last_error=NULL "
                                 "WHERE id=? AND state='pending'", (receipt_json, row["id"])).rowcount
        accepted += updated
    return {"accepted": accepted, "blocked": None, "error": None}


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_sender(base_url, token):
    """Authenticated loopback gateway; never send credentials to proxies/redirects."""
    url = urlsplit(base_url)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost") or
            url.username is not None or url.password is not None or url.path not in ("", "/") or
            url.query or url.fragment or url.port is None):
        raise ValueError("Use an explicit local runtime URL, for example http://127.0.0.1:8027.")
    if not isinstance(token, str) or not token or "\r" in token or "\n" in token:
        raise ValueError("A local runtime actor credential is required.")
    endpoint = base_url.rstrip("/") + "/api/commands"
    opener = build_opener(ProxyHandler({}), _NoRedirects())

    def send(command):
        request = Request(endpoint, data=canonical(command).encode("utf-8"),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
        try:
            with opener.open(request, timeout=30) as response:
                data = response.read(65537)
                if len(data) > 65536:
                    raise ValueError("Runtime acknowledgment is too large.")
                return json.loads(data)
        except HTTPError as exc:
            # Preserve useful error category without storing a remote body or credential.
            if exc.code in (401, 403):
                raise PermissionError("Runtime rejected the actor credential or permission.") from None
            raise ConnectionError("Runtime rejected the command; inspect its job monitor.") from None

    return send
