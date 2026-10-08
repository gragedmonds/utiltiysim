"""Main phase truth inspection stays in the administrator presentation."""
import pytest
from test_world_field_execution import command as field_command
from test_world_water_mains import world

from utilsim.world import field_execution, field_reporting, field_water_mains


def test_reporting_crews_do_not_receive_current_physical_eligibility(tmp_path, monkeypatch):
    w = world(tmp_path)
    f = field_execution.FieldExecution(w, tmp_path / "field.sqlite")
    field_execution.command(f, field_command(f, "crew", "configure-crew", skills=["water-main"]))
    phase = field_command(f, operation="isolate-water-main", assetId="main")
    phase.update(schemaVersion=field_water_mains.VERSION, predecessorAssignmentId=None)
    field_water_mains.command(f, phase)

    def admin_truth(*args):
        raise ValueError("Current physical eligibility inspection")

    monkeypatch.setattr(field_water_mains, "blocked", admin_truth)
    view = field_reporting.inspect(f, actor_id="crew-plumbing")
    assert len(view["items"]) == 1
    assert view["items"][0]["phase"] == {"predecessorAssignmentId": None}
    assert view["items"][0]["blockedReason"] is None
    assert field_reporting.inspect(f, actor_id="another-crew")["items"] == []
    with pytest.raises(ValueError, match="Current physical eligibility"):
        field_reporting.inspect(f)
