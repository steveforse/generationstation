"""Measures the RAM and per-GPU VRAM held by the model processes this service started.

Display only: admission uses host totals and reservations, never these per-model figures.

NVML cannot report per-process VRAM for GPUs in WDDM mode (every consumer card on Windows),
so on Windows VRAM comes from the "GPU Process Memory" performance counters that Task Manager
uses. Those counters name adapters by LUID; the LUID is matched to an NVML GPU by PCI bus number.
"""
import ctypes
import sys
import time

import psutil
import pynvml

VRAM_UNAVAILABLE = "Per-model VRAM is not available on this host."


def process_tree(pid, create_time):
    """The owned root process and its descendants, or [] if the PID now belongs to another process."""
    try:
        root = psutil.Process(pid)
        if create_time and abs(root.create_time() - create_time) > 0.01:
            return []
        return [root, *root.children(recursive=True)]
    except psutil.Error:
        return []


def darwin_footprint(pid):
    """A process's physical footprint on macOS (what Activity Monitor and `footprint` show), or None.

    The resident size psutil reports leaves out memory-mapped model weights and Metal buffers, so an MLX server holding
    16 GiB reads as 0.6 GiB there. proc_pid_rusage's first flavor carries the footprint after eight 8-byte fields.
    """
    if sys.platform != "darwin":
        return None
    try:
        import ctypes.util
        lib = ctypes.CDLL(ctypes.util.find_library("proc"), use_errno=True)
        buf = (ctypes.c_uint64 * 32)()
        if lib.proc_pid_rusage(int(pid), 0, ctypes.byref(buf)) != 0:  # RUSAGE_INFO_V0
            return None
        return int(buf[9])  # rusage_info_v0: ri_uuid (2 words), 7 counters, then ri_phys_footprint
    except (OSError, AttributeError, TypeError, ValueError):
        return None


def tree_ram_bytes(procs):
    total = 0
    for proc in procs:
        try:
            footprint = darwin_footprint(proc.pid)
            total += footprint if footprint is not None else proc.memory_info().rss  # working set on Windows
        except psutil.Error:
            continue
    return total


# ----- Windows: PDH counters and D3DKMT adapter addresses ------------------------------------

if sys.platform == "win32":
    from ctypes import wintypes

    class _LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _AdapterInfo(ctypes.Structure):
        _fields_ = [("hAdapter", ctypes.c_uint), ("AdapterLuid", _LUID), ("NumOfSources", wintypes.ULONG),
                    ("bPrecisePresentRegionsPreferred", wintypes.BOOL)]

    class _EnumAdapters2(ctypes.Structure):
        _fields_ = [("NumAdapters", wintypes.ULONG), ("pAdapters", ctypes.POINTER(_AdapterInfo))]

    class _QueryAdapterInfo(ctypes.Structure):
        _fields_ = [("hAdapter", ctypes.c_uint), ("Type", ctypes.c_int),
                    ("pPrivateDriverData", ctypes.c_void_p), ("PrivateDriverDataSize", ctypes.c_uint)]

    class _AdapterAddress(ctypes.Structure):
        _fields_ = [("BusNumber", ctypes.c_uint), ("DeviceNumber", ctypes.c_uint), ("FunctionNumber", ctypes.c_uint)]

    class _CloseAdapter(ctypes.Structure):
        _fields_ = [("hAdapter", ctypes.c_uint)]

    class _FmtValue(ctypes.Structure):
        _fields_ = [("CStatus", wintypes.DWORD), ("largeValue", ctypes.c_longlong)]

    class _FmtItem(ctypes.Structure):
        _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _FmtValue)]

    _KMTQAITYPE_ADAPTERADDRESS = 6
    _PDH_FMT_LARGE = 0x00000400
    _PDH_MORE_DATA = 0x800007D2
    _COUNTER = r"\GPU Process Memory(*)\Dedicated Usage"


def luid_key(high, low):
    return f"luid_0x{high & 0xFFFFFFFF:08x}_0x{low & 0xFFFFFFFF:08x}"


def windows_luid_buses():
    """{"luid_0x…_0x…": PCI bus number} for each display adapter with a PCI address."""
    gdi = ctypes.WinDLL("gdi32")
    request = _EnumAdapters2(0, None)
    if gdi.D3DKMTEnumAdapters2(ctypes.byref(request)) != 0 or request.NumAdapters == 0:
        return {}
    adapters = (_AdapterInfo * request.NumAdapters)()
    request.pAdapters = adapters
    if gdi.D3DKMTEnumAdapters2(ctypes.byref(request)) != 0:
        return {}
    buses = {}
    for adapter in adapters[:request.NumAdapters]:
        address = _AdapterAddress()
        query = _QueryAdapterInfo(adapter.hAdapter, _KMTQAITYPE_ADAPTERADDRESS,
                                  ctypes.cast(ctypes.byref(address), ctypes.c_void_p), ctypes.sizeof(address))
        if gdi.D3DKMTQueryAdapterInfo(ctypes.byref(query)) == 0 and address.BusNumber != 0xFFFFFFFF:
            buses[luid_key(adapter.AdapterLuid.HighPart, adapter.AdapterLuid.LowPart)] = address.BusNumber
        gdi.D3DKMTCloseAdapter(ctypes.byref(_CloseAdapter(adapter.hAdapter)))
    return buses


def windows_process_vram():
    """{(pid, luid key): dedicated VRAM bytes} from the GPU Process Memory counters."""
    pdh = ctypes.WinDLL("pdh")
    query, counter = ctypes.c_void_p(), ctypes.c_void_p()
    if pdh.PdhOpenQueryW(None, None, ctypes.byref(query)) != 0:
        raise OSError("PdhOpenQuery failed")
    try:
        if pdh.PdhAddEnglishCounterW(query, _COUNTER, None, ctypes.byref(counter)) != 0:
            raise OSError("The GPU Process Memory counter is unavailable")
        if pdh.PdhCollectQueryData(query) != 0:
            raise OSError("PdhCollectQueryData failed")
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        status = pdh.PdhGetFormattedCounterArrayW(counter, _PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), None)
        if status & 0xFFFFFFFF != _PDH_MORE_DATA:
            return {}
        buffer = ctypes.create_string_buffer(size.value)
        if pdh.PdhGetFormattedCounterArrayW(counter, _PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), buffer) != 0:
            raise OSError("PdhGetFormattedCounterArray failed")
        items = ctypes.cast(buffer, ctypes.POINTER(_FmtItem))
        usage = {}
        for item in items[:count.value]:
            # Instance names look like pid_1234_luid_0x00000000_0x0001369e_phys_0.
            # PDH may report the LUID's hex digits in either case.
            parts = (item.szName or "").lower().split("_")
            if len(parts) < 5 or parts[0] != "pid" or parts[2] != "luid" or item.FmtValue.CStatus not in (0, 1):
                continue
            key = (int(parts[1]), f"luid_{parts[3]}_{parts[4]}")
            usage[key] = usage.get(key, 0) + item.FmtValue.largeValue
        return usage
    finally:
        pdh.PdhCloseQuery(query)


# ----- collector -----------------------------------------------------------------------------

class ProcessMemoryCollector:
    """Per-model usage for {model_id: (pid, create_time)}; gpus are the telemetry sample's GPUs."""

    def __init__(self, platform=sys.platform, luid_buses=None, process_vram=None, nvml_bus=None, nvml_processes=None,
                 pids_named=None):
        self.platform = platform
        self.pids_named = pids_named or _pids_named
        self.luid_buses = luid_buses or windows_luid_buses
        self.process_vram = process_vram or windows_process_vram
        self.nvml_bus = nvml_bus or _nvml_bus
        self.nvml_processes = nvml_processes or _nvml_processes

    def sample(self, owned, gpus, helpers=None):
        """`helpers`: {model_id: process names} whose GPU memory also counts for that model (not their RAM)."""
        if not owned:
            return {}
        trees = {model_id: process_tree(pid, created) for model_id, (pid, created) in owned.items()}
        borrowed = {model_id: self.pids_named(names) for model_id, names in (helpers or {}).items() if model_id in owned}
        result = {model_id: {"ram_bytes": tree_ram_bytes(procs) if procs else None, "gpus": {}, "error": None}
                  for model_id, procs in trees.items()}
        try:
            vram = self._vram_by_pid(gpus)
        except Exception:  # noqa: BLE001 - per-model VRAM is display-only; report it as unknown.
            vram = None
        for model_id, procs in trees.items():
            if vram is None:
                result[model_id]["error"] = VRAM_UNAVAILABLE
                continue
            pids = {proc.pid for proc in procs} | borrowed.get(model_id, set())
            for (pid, gpu_id), used in vram.items():
                if pid in pids:
                    result[model_id]["gpus"][gpu_id] = result[model_id]["gpus"].get(gpu_id, 0) + used
        return result

    def _vram_by_pid(self, gpus):
        """{(pid, gpu id): bytes} for the telemetry GPUs."""
        by_bus = {}
        for gpu in gpus:
            if gpu.get("error") is None and isinstance(gpu.get("index"), int):
                bus = self.nvml_bus(gpu["index"])
                if bus is not None:
                    by_bus[bus] = gpu["id"]
        if not by_bus:
            return None
        if self.platform != "win32":
            return {(pid, by_bus[bus]): used for (pid, bus), used in self.nvml_processes(list(by_bus)).items()}
        gpu_by_luid = {luid: by_bus[bus] for luid, bus in self.luid_buses().items() if bus in by_bus}
        if not gpu_by_luid:
            return None
        usage = {}
        for (pid, luid), used in self.process_vram().items():
            luid = luid.lower()
            if luid in gpu_by_luid:
                key = (pid, gpu_by_luid[luid])
                usage[key] = usage.get(key, 0) + used
        return usage


def _pids_named(names):
    """PIDs of running processes with one of these names (case-insensitive, with or without .exe)."""
    wanted = {name.lower().removesuffix(".exe") for name in names}
    pids = set()
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower().removesuffix(".exe")
        if name in wanted:
            pids.add(proc.pid)
    return pids


def _nvml_bus(index):
    try:
        return pynvml.nvmlDeviceGetPciInfo(pynvml.nvmlDeviceGetHandleByIndex(index)).bus
    except pynvml.NVMLError:
        return None


def _nvml_processes(buses):
    """Linux/TCC: NVML reports per-process VRAM directly. {(pid, bus): bytes}."""
    usage = {}
    for index in range(pynvml.nvmlDeviceGetCount()):
        handle = pynvml.nvmlDeviceGetHandleByIndex(index)
        bus = pynvml.nvmlDeviceGetPciInfo(handle).bus
        if bus not in buses:
            continue
        for proc in pynvml.nvmlDeviceGetComputeRunningProcesses(handle):
            if isinstance(proc.usedGpuMemory, int):
                usage[(proc.pid, bus)] = usage.get((proc.pid, bus), 0) + proc.usedGpuMemory
    return usage


if __name__ == "__main__":
    # Manual check on a host: python -m generationstation.process_memory <pid> [<pid>...]
    pynvml.nvmlInit()
    host_gpus = []
    for i in range(pynvml.nvmlDeviceGetCount()):
        h = pynvml.nvmlDeviceGetHandleByIndex(i)
        host_gpus.append({"index": i, "id": pynvml.nvmlDeviceGetUUID(h), "error": None})
    started = time.perf_counter()
    owned = {f"pid-{p}": (int(p), 0) for p in sys.argv[1:]}
    print(ProcessMemoryCollector().sample(owned, host_gpus))
    print(f"{(time.perf_counter() - started) * 1000:.0f} ms")
