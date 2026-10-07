"""Versioned observation-only export with explicit derived sewer service.

Sewer is calculated from observed water use. No sewer meter is fabricated and
hidden actual consumption is never used to fill missing observations.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from .store import stable


def export_v2(world, start, end, sewer_factor="0.9", delay_seconds=0):
    with world.db() as db:
        return export_in_transaction(world, db, start, end, sewer_factor, delay_seconds)


def delivery_settings(sewer_factor, delay_seconds):
    try:
        factor = Decimal(str(sewer_factor))
    except InvalidOperation as exc:
        raise ValueError("Invalid sewer return factor.") from exc
    if not factor.is_finite() or not 0 <= factor <= 1:
        raise ValueError("Sewer return factor must be between zero and one.")
    if type(delay_seconds) is not int or not 0 <= delay_seconds <= 366 * 86400:
        raise ValueError("Observation delay must be nonnegative integer seconds, at most 366 days.")
    return str(factor), delay_seconds


def export_in_transaction(world, db, start, end, sewer_factor="0.9", delay_seconds=0):
    factor_text, delay_seconds = delivery_settings(sewer_factor, delay_seconds)
    factor = Decimal(factor_text)
    batch = world._export(db, start, end)
    env = batch["environmentId"]
    assets, observations = [], []
    points = {}
    for asset in batch["assets"]:
        point = "SP-" + stable(env, asset["installationId"])
        points[asset["meterId"]] = point
        assets.append({**asset, "servicePointId": point, "measurementType": "metered",
                       "sourceServicePointId": None, "derivation": None})
        if asset["commodity"] == "water":
            assets.append({**asset, "servicePointId": "SEWER-" + point,
                           "installationId": "SEWER-" + asset["installationId"],
                           "meterId": None, "commodity": "sewer", "measurementType": "derived",
                           "sourceServicePointId": point,
                           "derivation": {"method": "water-return-factor", "factor": str(factor)}})
    # Cached observed-interval reconstruction preserves gaps without scanning prior years.
    register_values = {r["id"]: r["value"] for r in db.execute(
        "SELECT o.id,r.value FROM observations o JOIN observed_register_values r ON r.observation=o.id "
        "WHERE o.day>=? AND o.day<?", (start, end))}
    for observation in batch["observations"]:
        point = points[observation["meterId"]]
        available = (datetime.fromisoformat(observation["observedAt"].replace("Z", "+00:00")) +
                     timedelta(seconds=delay_seconds)).astimezone(UTC).isoformat().replace("+00:00", "Z")
        reading = {**observation, "servicePointId": point,
                   "registerId": "REG-" + stable(env, observation["deviceId"]),
                   "registerValue": register_values.get(observation["sourceId"]),
                   "availableAt": available, "measurementType": "metered",
                   "sourceObservationIds": [], "derivation": None}
        observations.append(reading)
        if observation["commodity"] == "water":
            observations.append({**reading, "sourceId": "SEWER-" + observation["sourceId"],
                                 "servicePointId": "SEWER-" + point,
                                 "installationId": "SEWER-" + observation["installationId"],
                                 "commodity": "sewer", "meterId": None, "deviceId": None,
                                 "registerId": None, "registerValue": None,
                                 "quantity": None if observation["quantity"] is None else
                                 str(Decimal(observation["quantity"]) * factor),
                                 "measurementType": "derived", "sourceObservationIds": [observation["sourceId"]],
                                 "derivation": {"method": "water-return-factor", "factor": str(factor)}})
    result = {**batch, "schemaVersion": "utility-observations/2.0", "assets": assets,
              "observations": observations}
    result.pop("batchId")
    result["batchId"] = stable(result)
    return result
