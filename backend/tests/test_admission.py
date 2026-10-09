import pytest

from generationstation.admission import evaluate_capacity
from tests.m2_fakes import make_host


def profile(ram=100, gpu=None):
    return {"mode": "simulation", "ram_peak_bytes": ram,
            "gpu_vram_bytes_by_id": gpu or {}}


@pytest.mark.parametrize("role,scope", [("development", "host"), ("desktop", "container"),
                                        ("desktop", "wsl"), ("", "host")])
def test_only_desktop_native_host_is_eligible(role, scope):
    refusal = evaluate_capacity(make_host(role=role, scope=scope), profile(), [], 0, 0)
    assert refusal["code"] == "HOST_ROLE_UNSUPPORTED"


@pytest.mark.parametrize("kwargs", [
    {"stale": True}, {"age": 5.0}, {"age": -1}, {"age": float("nan")},
    {"ram_unknown": True}, {"gpu_error": "unknown"}, {"gpu_failures": ("GPU-A",)},
])
def test_stale_unknown_or_unsupported_telemetry_fails_closed(kwargs):
    refusal = evaluate_capacity(make_host(**kwargs), profile(), [], 0, 0)
    assert refusal
    assert refusal["code"] in {"TELEMETRY_STALE", "TELEMETRY_UNKNOWN", "GPU_ACCOUNTING_UNSUPPORTED"}


def test_exact_headroom_boundary_is_admitted():
    host = make_host(ram_available=200, gpu_available={"GPU-A": 100, "GPU-B": 1})
    requested = profile(ram=180, gpu={"GPU-A": 80})
    assert evaluate_capacity(host, requested, [], ram_headroom_bytes=20, gpu_headroom_bytes=20) is None


def test_ram_over_boundary_returns_machine_readable_shortage():
    refusal = evaluate_capacity(make_host(ram_available=199), profile(ram=180), [], 20, 0)
    assert refusal["code"] == "INSUFFICIENT_RAM"
    assert refusal["resources"] == [{"resource": "ram", "required_bytes": 180,
                                      "available_bytes": 179, "headroom_bytes": 20}]


def test_gpu_capacities_are_never_summed_across_devices():
    host = make_host(gpu_available={"GPU-A": 50, "GPU-B": 50})
    refusal = evaluate_capacity(host, profile(gpu={"GPU-A": 90}), [], 0, 0)
    assert refusal["code"] == "INSUFFICIENT_VRAM"
    assert refusal["resources"] == [{"resource": "gpu:GPU-A", "required_bytes": 90,
                                      "available_bytes": 50, "headroom_bytes": 0}]


def test_unknown_gpu_uuid_is_not_substituted_with_another_gpu():
    refusal = evaluate_capacity(make_host(), profile(gpu={"GPU-missing": 1}), [], 0, 0)
    assert refusal["code"] == "GPU_ACCOUNTING_UNSUPPORTED"


def test_active_reservations_are_subtracted_by_ram_and_exact_gpu_uuid():
    host = make_host(ram_available=200, gpu_available={"GPU-A": 200, "GPU-B": 200})
    reservation = {"ram_bytes": 100, "gpu_vram_bytes_by_id": {"GPU-A": 100}}
    refusal = evaluate_capacity(host, profile(ram=101, gpu={"GPU-A": 101}), [reservation], 0, 0)
    assert refusal["code"] == "INSUFFICIENT_RAM"
    assert {entry["resource"]: entry["available_bytes"] for entry in refusal["resources"]} == {
        "ram": 100, "gpu:GPU-A": 100,
    }
    # A reservation on GPU-A does not reduce GPU-B's budget.
    assert evaluate_capacity(host, profile(ram=100, gpu={"GPU-B": 200}), [reservation], 0, 0) is None


@pytest.mark.parametrize("bad_profile", [
    {"mode": "measured", "ram_peak_bytes": 1, "gpu_vram_bytes_by_id": {}},
    {"mode": "simulation", "ram_peak_bytes": True, "gpu_vram_bytes_by_id": {}},
    {"mode": "simulation", "ram_peak_bytes": 1, "gpu_vram_bytes_by_id": {"GPU-A": False}},
])
def test_invalid_or_non_simulation_profiles_are_refused(bad_profile):
    refusal = evaluate_capacity(make_host(), bad_profile, [], 0, 0)
    assert refusal["code"] == "PROFILE_INVALID"
