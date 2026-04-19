from __future__ import annotations

import os
import platform
import socket
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

try:
    import resource
except ImportError:  # pragma: no cover - resource is unavailable on Windows
    resource = None  # type: ignore[assignment]


_CPU_SAMPLE_CACHE: dict[str, tuple[float, float]] = {}


class RuntimeProcessStats(BaseModel):
    pid: int
    ppid: int | None = None
    name: str | None = None
    command: str | None = None
    rss_bytes: int | None = None
    vms_bytes: int | None = None
    rss_anon_bytes: int | None = None
    rss_file_bytes: int | None = None
    rss_shmem_bytes: int | None = None
    swap_bytes: int | None = None
    cpu_percent: float | None = None
    cpu_user_seconds: float | None = None
    cpu_system_seconds: float | None = None
    thread_count: int | None = None
    open_fds: int | None = None
    started_at: int | None = None
    uptime_seconds: float | None = None


class RuntimeAggregateStats(BaseModel):
    process_count: int
    rss_bytes: int | None = None
    vms_bytes: int | None = None
    rss_anon_bytes: int | None = None
    rss_file_bytes: int | None = None
    rss_shmem_bytes: int | None = None
    swap_bytes: int | None = None
    cpu_percent: float | None = None
    cpu_user_seconds: float | None = None
    cpu_system_seconds: float | None = None
    thread_count: int | None = None
    open_fds: int | None = None


class BackendRuntimeStatsResponse(BaseModel):
    service: str = "backend"
    sampled_at: int
    hostname: str
    platform: str
    python_version: str
    cpu_count: int | None = None
    collection_scope: str
    current_pid: int
    aggregate: RuntimeAggregateStats
    current_process: RuntimeProcessStats
    processes: list[RuntimeProcessStats]


def _kb_to_bytes(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value) * 1024
    except (TypeError, ValueError):
        return None


def _compute_cpu_percent(cache_key: str, cpu_total_seconds: float | None) -> float | None:
    if cpu_total_seconds is None:
        return None

    now = time.time()
    previous = _CPU_SAMPLE_CACHE.get(cache_key)
    _CPU_SAMPLE_CACHE[cache_key] = (now, cpu_total_seconds)
    if previous is None:
        return None

    elapsed = now - previous[0]
    cpu_delta = cpu_total_seconds - previous[1]
    if elapsed <= 0 or cpu_delta < 0:
        return None

    return round((cpu_delta / elapsed) * 100, 1)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _read_proc_status(pid: int) -> dict[str, str] | None:
    raw = _read_text(Path("/proc") / str(pid) / "status")
    if not raw:
        return None

    data: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def _read_proc_cmdline(pid: int) -> str | None:
    try:
        raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None

    parts = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\x00") if part]
    return " ".join(parts).strip() or None


def _read_proc_stat(pid: int) -> dict[str, Any] | None:
    raw = _read_text(Path("/proc") / str(pid) / "stat")
    if not raw or ") " not in raw:
        return None

    head, tail = raw.split(") ", 1)
    name = head.split("(", 1)[-1]
    parts = tail.split()
    if len(parts) < 22:
        return None

    try:
        return {
            "name": name,
            "ppid": int(parts[1]),
            "utime_ticks": int(parts[11]),
            "stime_ticks": int(parts[12]),
            "thread_count": int(parts[17]),
            "start_ticks": int(parts[19]),
            "vms_bytes": int(parts[20]),
            "rss_pages": int(parts[21]),
        }
    except (TypeError, ValueError):
        return None


def _read_proc_boot_time() -> float | None:
    raw = _read_text(Path("/proc/stat"))
    if not raw:
        return None

    for line in raw.splitlines():
        if line.startswith("btime "):
            try:
                return float(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def _count_open_fds(pid: int) -> int | None:
    try:
        return len(list((Path("/proc") / str(pid) / "fd").iterdir()))
    except OSError:
        return None


def _linux_process_snapshot(pid: int) -> RuntimeProcessStats | None:
    stat = _read_proc_stat(pid)
    status = _read_proc_status(pid)
    if stat is None or status is None:
        return None

    clock_ticks = os.sysconf("SC_CLK_TCK")
    page_size = os.sysconf("SC_PAGE_SIZE")
    boot_time = _read_proc_boot_time()

    cpu_user = stat["utime_ticks"] / clock_ticks
    cpu_system = stat["stime_ticks"] / clock_ticks
    cpu_total = cpu_user + cpu_system
    started_at = None
    uptime_seconds = None
    if boot_time is not None:
        started_at = int(boot_time + (stat["start_ticks"] / clock_ticks))
        uptime_seconds = max(0.0, time.time() - started_at)

    rss_from_stat = stat["rss_pages"] * page_size
    rss_bytes = _kb_to_bytes(status.get("VmRSS", "").split()[0] if status.get("VmRSS") else None)
    if rss_bytes is None:
        rss_bytes = rss_from_stat

    vms_bytes = _kb_to_bytes(status.get("VmSize", "").split()[0] if status.get("VmSize") else None)
    if vms_bytes is None:
        vms_bytes = stat["vms_bytes"]

    return RuntimeProcessStats(
        pid=pid,
        ppid=stat["ppid"],
        name=status.get("Name") or stat["name"],
        command=_read_proc_cmdline(pid),
        rss_bytes=rss_bytes,
        vms_bytes=vms_bytes,
        rss_anon_bytes=_kb_to_bytes(status.get("RssAnon", "").split()[0] if status.get("RssAnon") else None),
        rss_file_bytes=_kb_to_bytes(status.get("RssFile", "").split()[0] if status.get("RssFile") else None),
        rss_shmem_bytes=_kb_to_bytes(status.get("RssShmem", "").split()[0] if status.get("RssShmem") else None),
        swap_bytes=_kb_to_bytes(status.get("VmSwap", "").split()[0] if status.get("VmSwap") else None),
        cpu_percent=_compute_cpu_percent(f"pid:{pid}", cpu_total),
        cpu_user_seconds=round(cpu_user, 3),
        cpu_system_seconds=round(cpu_system, 3),
        thread_count=stat["thread_count"],
        open_fds=_count_open_fds(pid),
        started_at=started_at,
        uptime_seconds=round(uptime_seconds, 1) if uptime_seconds is not None else None,
    )


def _looks_like_backend_master(command: str | None) -> bool:
    normalized = (command or "").replace("\\", "/").lower()
    return any(
        token in normalized
        for token in ("fastapi", "uvicorn", "app/main.py", "app.main")
    )


def _list_linux_related_processes() -> tuple[str, list[RuntimeProcessStats]]:
    current_pid = os.getpid()
    current_process = _linux_process_snapshot(current_pid)
    if current_process is None:
        return "current_process", []

    parent_pid = current_process.ppid
    parent_process = _linux_process_snapshot(parent_pid) if parent_pid else None

    if not parent_process or not _looks_like_backend_master(parent_process.command):
        return "current_process", [current_process]

    related_pids = {parent_process.pid}
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        pid = int(proc_dir.name)
        snapshot = _linux_process_snapshot(pid)
        if snapshot is None:
            continue
        if snapshot.ppid == parent_process.pid or snapshot.pid == current_pid:
            related_pids.add(snapshot.pid)

    processes: list[RuntimeProcessStats] = []
    for pid in sorted(related_pids):
        snapshot = _linux_process_snapshot(pid)
        if snapshot is not None:
            processes.append(snapshot)
    return "parent_process_group", processes


def _windows_memory_bytes() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        success = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
        if not success:
            return None
        return int(counters.WorkingSetSize)
    except Exception:
        return None


def _fallback_process_snapshot() -> RuntimeProcessStats:
    process_times = os.times()
    cpu_user = float(process_times.user)
    cpu_system = float(process_times.system)
    cpu_total = cpu_user + cpu_system
    rss_bytes = _windows_memory_bytes()

    if rss_bytes is None and resource is not None:
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            rss_candidate = int(usage.ru_maxrss)
            if sys.platform == "darwin":
                rss_bytes = rss_candidate
            else:
                rss_bytes = rss_candidate * 1024
        except Exception:
            rss_bytes = None

    return RuntimeProcessStats(
        pid=os.getpid(),
        ppid=os.getppid(),
        name=Path(sys.executable).name,
        command=" ".join(sys.argv) or None,
        rss_bytes=rss_bytes,
        cpu_percent=_compute_cpu_percent("pid:self", cpu_total),
        cpu_user_seconds=round(cpu_user, 3),
        cpu_system_seconds=round(cpu_system, 3),
        thread_count=None,
        open_fds=None,
        started_at=None,
        uptime_seconds=None,
    )


def _sum_optional(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)


def _build_aggregate(processes: list[RuntimeProcessStats]) -> RuntimeAggregateStats:
    cpu_user_seconds = sum(process.cpu_user_seconds or 0 for process in processes)
    cpu_system_seconds = sum(process.cpu_system_seconds or 0 for process in processes)
    cpu_total = cpu_user_seconds + cpu_system_seconds

    return RuntimeAggregateStats(
        process_count=len(processes),
        rss_bytes=_sum_optional([process.rss_bytes for process in processes]),
        vms_bytes=_sum_optional([process.vms_bytes for process in processes]),
        rss_anon_bytes=_sum_optional([process.rss_anon_bytes for process in processes]),
        rss_file_bytes=_sum_optional([process.rss_file_bytes for process in processes]),
        rss_shmem_bytes=_sum_optional([process.rss_shmem_bytes for process in processes]),
        swap_bytes=_sum_optional([process.swap_bytes for process in processes]),
        cpu_percent=_compute_cpu_percent("aggregate", cpu_total),
        cpu_user_seconds=round(cpu_user_seconds, 3),
        cpu_system_seconds=round(cpu_system_seconds, 3),
        thread_count=_sum_optional([process.thread_count for process in processes]),
        open_fds=_sum_optional([process.open_fds for process in processes]),
    )


def collect_backend_runtime_stats() -> BackendRuntimeStatsResponse:
    if Path("/proc").exists():
        collection_scope, processes = _list_linux_related_processes()
    else:
        collection_scope = "current_process"
        processes = [_fallback_process_snapshot()]

    if not processes:
        processes = [_fallback_process_snapshot()]
        collection_scope = "current_process"

    current_pid = os.getpid()
    current_process = next((process for process in processes if process.pid == current_pid), processes[0])
    processes = sorted(
        processes,
        key=lambda process: (
            0 if process.pid == current_pid else 1,
            -(process.rss_bytes or 0),
            process.pid,
        ),
    )

    return BackendRuntimeStatsResponse(
        sampled_at=int(time.time()),
        hostname=socket.gethostname(),
        platform=platform.platform(),
        python_version=sys.version.split()[0],
        cpu_count=os.cpu_count(),
        collection_scope=collection_scope,
        current_pid=current_pid,
        aggregate=_build_aggregate(processes),
        current_process=current_process,
        processes=processes,
    )
