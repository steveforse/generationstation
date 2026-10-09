"""Fail-closed admission rules shared by the API and persistence transaction."""
import math


def _positive_integer(value):
    return type(value) is int and 0 < value < 2**63


def _memory_reading(value):
    if not isinstance(value, dict):
        return False
    total = value.get("total_bytes")
    available = value.get("available_bytes")
    used = value.get("used_bytes")
    return (
        all(type(item) is int for item in (total, available, used))
        and total > 0 and 0 <= available <= total and 0 <= used <= total
    )


def _refusal(code, message, resources=None):
    return {"code": code, "message": message, "resources": resources or []}


def evaluate_capacity(host, profile, reservations, ram_headroom_bytes, gpu_headroom_bytes):
    """Return a stable refusal payload, or None when every requested resource fits."""
    identity = host.get("host") if isinstance(host, dict) else None
    if not isinstance(identity, dict) or identity.get("role") != "desktop" or identity.get("scope") != "host":
        return _refusal("HOST_ROLE_UNSUPPORTED", "Loading is allowed only on a native desktop host.")

    age = host.get("age_seconds")
    stale_after = host.get("stale_after_seconds")
    if (host.get("stale") is not False or type(age) not in (int, float)
            or not math.isfinite(age) or type(stale_after) not in (int, float)
            or not math.isfinite(stale_after) or age < 0 or stale_after <= 0 or age >= stale_after):
        return _refusal("TELEMETRY_STALE", "A fresh host measurement is required before loading.")
    if host.get("ram_error") is not None or not _memory_reading(host.get("ram")):
        return _refusal("TELEMETRY_UNKNOWN", "System memory capacity is unavailable.")
    gpus = host.get("gpus")
    if (host.get("gpu_error") is not None or not isinstance(gpus, list) or not gpus
            or any(not isinstance(gpu, dict) or gpu.get("error") is not None
                   or not isinstance(gpu.get("id"), str) or not gpu.get("id")
                   or not _memory_reading(gpu.get("memory")) for gpu in gpus)):
        return _refusal("GPU_ACCOUNTING_UNSUPPORTED", "Complete per-device GPU memory accounting is required.")
    gpu_by_id = {gpu["id"]: gpu["memory"] for gpu in gpus}
    if len(gpu_by_id) != len(gpus):
        return _refusal("GPU_ACCOUNTING_UNSUPPORTED", "GPU device identifiers are not unique.")

    requested_ram = profile.get("ram_peak_bytes")
    requested_gpu = profile.get("gpu_vram_bytes_by_id")
    if (profile.get("mode") != "simulation" or not _positive_integer(requested_ram)
            or not isinstance(requested_gpu, dict)
            or any(not isinstance(device_id, str) or not device_id or not _positive_integer(amount)
                   for device_id, amount in requested_gpu.items())):
        return _refusal("PROFILE_INVALID", "The simulation profile has invalid resource requirements.")

    reserved_ram = 0
    reserved_gpu = {device_id: 0 for device_id in gpu_by_id}
    for reservation in reservations:
        amount = reservation.get("ram_bytes")
        demand = reservation.get("gpu_vram_bytes_by_id")
        if not _positive_integer(amount) or not isinstance(demand, dict):
            return _refusal("TELEMETRY_UNKNOWN", "An active reservation cannot be accounted for safely.")
        reserved_ram += amount
        for device_id, bytes_required in demand.items():
            if device_id not in reserved_gpu or not _positive_integer(bytes_required):
                return _refusal("GPU_ACCOUNTING_UNSUPPORTED", "An active GPU reservation cannot be matched to this host.")
            reserved_gpu[device_id] += bytes_required

    resources = []
    ram_available = max(0, host["ram"]["available_bytes"] - ram_headroom_bytes - reserved_ram)
    if requested_ram > ram_available:
        resources.append({"resource": "ram", "required_bytes": requested_ram,
                          "available_bytes": ram_available, "headroom_bytes": ram_headroom_bytes})

    for device_id, requested in requested_gpu.items():
        memory = gpu_by_id.get(device_id)
        if memory is None:
            return _refusal("GPU_ACCOUNTING_UNSUPPORTED",
                            f"The profile's GPU {device_id} is not available with reliable accounting.")
        available = max(0, memory["available_bytes"] - gpu_headroom_bytes - reserved_gpu[device_id])
        if requested > available:
            resources.append({"resource": f"gpu:{device_id}", "required_bytes": requested,
                              "available_bytes": available, "headroom_bytes": gpu_headroom_bytes})
    if resources:
        codes = {resource["resource"].split(":", 1)[0] for resource in resources}
        if "ram" in codes:
            code, message = "INSUFFICIENT_RAM", "The requested model exceeds available system memory after headroom and reservations."
        else:
            code, message = "INSUFFICIENT_VRAM", "The requested model exceeds available VRAM on one or more assigned GPUs."
        return _refusal(code, message, resources)
    return None
