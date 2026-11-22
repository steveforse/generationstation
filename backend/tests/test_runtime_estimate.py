import pytest

from generationstation.lifecycle import LifecycleError, LifecycleManager
from tests.runtime_fixtures import catalog, host
from tests.test_telemetry import settings

GIB = 1024 ** 3


class ReservationStore:
    def __init__(self, reservations):
        self.reservations = reservations
        self.writes = 0

    def active_reservations(self):
        return self.reservations

    def __getattr__(self, name):  # any write would be a bug: an estimate changes nothing
        def write(*args, **kwargs):
            self.writes += 1
        return write


def manager(reservations=()):
    store = ReservationStore(list(reservations))
    lifecycle = LifecycleManager(store, settings(), catalog=catalog(8160), runtime_adapter=object())
    return lifecycle, store


def test_estimate_matches_what_a_start_would_ask_for_and_reports_headroom_and_reservations():
    lifecycle, store = manager([{"ram_bytes": 3 * GIB, "gpu_vram_bytes_by_id": {"GPU-0": 5 * GIB}}])
    estimate = lifecycle.estimate_runtime("basalt", "ds41", {"resident_budget_gib": 20}, [0], host())
    assert estimate == {
        "ram_bytes": (8 + 20) * GIB, "gpu_vram_bytes_by_id": {"GPU-0": 24 * GIB},
        "ram_headroom_bytes": 4 * GIB, "gpu_headroom_bytes": 2 * GIB,
        "reserved_ram_bytes": 3 * GIB, "reserved_gpu_vram_bytes_by_id": {"GPU-0": 5 * GIB},
    }
    assert store.writes == 0


def test_estimate_rejects_invalid_choices_like_a_start():
    lifecycle, _ = manager()
    with pytest.raises(LifecycleError) as invalid:
        lifecycle.estimate_runtime("basalt", "ds41", {"vram_reserve_mib": 1}, None, host())
    assert invalid.value.code == "SETTINGS_INVALID"
    with pytest.raises(LifecycleError) as missing:
        lifecycle.estimate_runtime("nope", None, {}, None, host())
    assert missing.value.code == "MODEL_NOT_FOUND"
