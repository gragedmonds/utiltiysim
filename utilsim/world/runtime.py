"""Daily world jobs for a shared scheduler; no enterprise package dependency.

Register DailyWorld only behind an authenticated scheduler which supplies actor
and processingAt. Its submission callback must use a dedicated producer actor.
"""
import json
from datetime import UTC, date, datetime, timedelta

from . import delivery
from .store import canonical, stable


def daily_commands(world, through):
    """Stable, dependency-linked jobs from delivery activation through exclusive end.

    Re-submit this sequence using the same scheduler actor to extend a run safely.
    Already accepted commands are deduplicated by the recipient.
    """
    end = date.fromisoformat(through)
    if end.isoformat() != through:
        raise ValueError("Use canonical YYYY-MM-DD dates.")
    config = delivery.status(world, limit=1)["configuration"]
    if config is None:
        raise ValueError("Configure observation delivery before scheduling physical days.")
    day = date.fromisoformat(config["from"])
    if end < day:
        raise ValueError("Cannot schedule before delivery activation.")
    previous = None
    while day < end:
        finish = (day + timedelta(days=1)).isoformat()
        command_id = "world-day-" + stable(config["environmentId"], finish)
        yield {"id": command_id, "runId": config["environmentId"], "target": "world",
               "operation": "advance_day", "requestedAt": day.isoformat() + "T00:00:00Z",
               "availableAt": finish + "T00:00:00Z", "payload": {"through": finish},
               "cause": previous, "correlation": "world-day:" + config["environmentId"] + ":" + day.isoformat(),
               "dependsOn": [previous] if previous else []}
        previous = command_id
        day += timedelta(days=1)


class DailyWorld:
    def __init__(self, world, submit_observation):
        self.world = world
        self.submit_observation = submit_observation

    def __call__(self, envelope):
        if envelope.get("target") != "world" or envelope.get("operation") != "advance_day":
            raise ValueError("Unsupported world operation.")
        payload = envelope.get("payload")
        if not isinstance(payload, dict) or set(payload) != {"through"}:
            raise ValueError("Provide one physical day's exclusive end date.")
        finish = date.fromisoformat(payload["through"])
        through = finish.isoformat()
        if through != payload["through"]:
            raise ValueError("Use canonical YYYY-MM-DD dates.")
        day = (finish - timedelta(days=1)).isoformat()
        processed = datetime.fromisoformat(envelope["processingAt"].replace("Z", "+00:00"))
        if processed.tzinfo is None or processed.astimezone(UTC) < datetime.fromisoformat(through).replace(tzinfo=UTC):
            raise ValueError("The shared clock has not reached this day's completion.")
        if any(not isinstance(envelope.get(k), str) or not envelope[k].strip() for k in ("id", "runId", "actor")):
            raise ValueError("An authenticated run, actor and command identity are required.")
        identity = canonical({k: envelope[k] for k in ("id", "runId", "actor", "target", "operation", "payload")})
        with self.world.db() as db:
            meta = self.world.metadata(db)
            if meta.get("environment") != envelope["runId"]:
                raise ValueError("World and scheduler run identities must match.")
            prior = db.execute("SELECT payload,result FROM commands WHERE id=?", (envelope["id"],)).fetchone()
            if prior:
                if prior["payload"] != identity:
                    raise ValueError("Conflicting world command retry.")
                return json.loads(prior["result"])
            if meta["through"] not in (day, through):
                raise ValueError("Physical days must execute in order, one day at a time.")
            config = db.execute("SELECT value FROM observation_delivery_configuration WHERE singleton=1").fetchone()
            if config is None or day < json.loads(config[0])["from"]:
                raise ValueError("This day is outside the configured delivery stream.")
            if db.execute("SELECT 1 FROM observation_outbox WHERE day<? AND state='pending' LIMIT 1",
                          (day,)).fetchone():
                raise ValueError("An earlier physical day still has an unaccepted delivery.")
        # A crash after this commit is recovered by the same date + immutable outbox.
        self.world.advance(through)
        result = delivery.relay(self.world, self.submit_observation)
        if result["blocked"]:
            raise RuntimeError("World delivery is pending (" + result["error"] + "); retry this daily job.")
        with self.world.db() as db:
            message = db.execute("SELECT id,state FROM observation_outbox WHERE day=?", (day,)).fetchone()
            if not message or message["state"] != "accepted":
                raise RuntimeError("The daily observation message has not been accepted.")
            result = {"day": day, "through": through, "observationCommandId": message["id"],
                      "created": db.execute("SELECT COUNT(*) FROM observations WHERE day=?", (day,)).fetchone()[0]}
            prior = db.execute("SELECT payload,result FROM commands WHERE id=?", (envelope["id"],)).fetchone()
            if prior:
                if prior["payload"] != identity:
                    raise ValueError("Conflicting world command retry.")
                return json.loads(prior["result"])
            db.execute("INSERT INTO commands VALUES(?,?,?)", (envelope["id"], identity, canonical(result)))
            return result
