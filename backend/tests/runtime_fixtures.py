import socket
import sys
from pathlib import Path

from generationstation.runtimes import parse_catalog

FAKE = str(Path(__file__).with_name("fake_basalt.py"))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def catalog(port, *, env=None, ready_timeout=20):
    return parse_catalog(catalog_data(port, env=env, ready_timeout=ready_timeout))


def catalog_data(port, *, env=None, ready_timeout=20):
    return {"runtimes": {"basalt": {
        "kind": "basalt", "name": "Basalt", "workload": "text",
        "executable": sys.executable, "leading_args": [FAKE], "port": port,
        "env": env or {}, "ready_timeout_seconds": ready_timeout, "stop_timeout_seconds": 10,
        "default_preset": "ds41",
        "presets": {
            "ds41": {
                "name": "DeepSeek V4.1 Flash", "alias": "DeepSeek", "model_path": "C:/models/ds.basalt",
                "gpus": [0, 1], "env": {"BASALT_ENGRAM_OFFSET": "416"},
                "settings": {"max_context": 262144, "vram_reserve_mib": 700, "peer_reserve_mib": 600,
                             "resident_budget_gib": 48, "ram_reserve_mib": 0,
                             "conversation_cache_mib": 4096},
                "estimate": {"ram_gib": 8, "gpu_min_free_gib": {"0": 24, "1": 10}},
            },
            "fn": {
                "name": "Qwen3.8 Flash-Next", "alias": "Flash-Next", "model_path": "C:/models/fn.basalt",
                "gpus": [0, 1], "fixed": {"ple-io": "direct"}, "kv_options": ["int8", "q4_0"],
                "settings": {"max_context": 262144, "kv": "int8", "resident_experts": True,
                             "vram_reserve_mib": 700, "peer_reserve_mib": 3072, "resident_budget_gib": None},
                "estimate": {"ram_gib": 40, "gpu_min_free_gib": {"0": 24, "1": 10}},
            },
        },
    }}}


GIB = 1024**3


def host(gpu_free_gib=(30, 14), ram_free_gib=100):
    gpus = []
    for index, free in enumerate(gpu_free_gib):
        total = (32 if index == 0 else 16) * GIB
        gpus.append({"id": f"GPU-{index}", "index": index, "name": ["RTX 5090", "RTX 4080"][index],
                     "memory": {"total_bytes": total, "available_bytes": int(free * GIB),
                                "used_bytes": total - int(free * GIB)}, "error": None})
    ram_total = 128 * GIB
    return {
        "host": {"hostname": "test", "os": "Windows", "label": "test", "role": "desktop", "scope": "host"},
        "ram": {"total_bytes": ram_total, "available_bytes": int(ram_free_gib * GIB),
                "used_bytes": ram_total - int(ram_free_gib * GIB)},
        "ram_error": None, "gpus": gpus, "gpu_error": None,
        "stale": False, "age_seconds": 0.1, "stale_after_seconds": 5,
    }
