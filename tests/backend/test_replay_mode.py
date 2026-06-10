import pytest
from pydantic import ValidationError
from backend.schemas.backtest_schemas import ScanSource


def test_replay_mode_requires_account_id():
    with pytest.raises(ValidationError):
        ScanSource(mode="replay")            # no replay_account_id


def test_replay_mode_valid():
    s = ScanSource(mode="replay", replay_account_id="75aecaa7-0f10-400b-a562-1ddd7ae6cf94")
    assert s.mode == "replay"
    assert s.replay_account_id == "75aecaa7-0f10-400b-a562-1ddd7ae6cf94"


def test_existing_modes_unaffected():
    assert ScanSource(mode="schedule", schedule_id="x").mode == "schedule"
    assert ScanSource(mode="explicit", scan_ids=["a"]).mode == "explicit"
