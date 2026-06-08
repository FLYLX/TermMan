from __future__ import annotations

import os
import platform
import socket
import sys
import time
from pathlib import Path
from typing import Any

_CPU_SAMPLE_CACHE: dict[str, tuple[float, float]] = {}


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


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
    parts = tail.split()
    if len(parts) < 22:
        return None

    try:
        return {
            "name": head.split("(", 1)[-1],
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
        if not line.startswith("btime "):
            continue
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


def _process_snapshot(pid: int) -> dict[str, Any] | None:
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

    rss_bytes = _kb_to_bytes(status.get("VmRSS", "").split()[0] if status.get("VmRSS") else None)
    return {
        "pid": pid,
        "ppid": stat["ppid"],
        "name": status.get("Name") or stat["name"],
        "command": _read_proc_cmdline(pid),
        "rss_bytes": rss_bytes if rss_bytes is not None else stat["rss_pages"] * page_size,
        "vms_bytes": _kb_to_bytes(
            status.get("VmSize", "").split()[0] if status.get("VmSize") else None
        )
        or stat["vms_bytes"],
        "rss_anon_bytes": _kb_to_bytes(
            status.get("RssAnon", "").split()[0] if status.get("RssAnon") else None
        ),
        "rss_file_bytes": _kb_to_bytes(
            status.get("RssFile", "").split()[0] if status.get("RssFile") else None
        ),
        "rss_shmem_bytes": _kb_to_bytes(
            status.get("RssShmem", "").split()[0] if status.get("RssShmem") else None
        ),
        "swap_bytes": _kb_to_bytes(
            status.get("VmSwap", "").split()[0] if status.get("VmSwap") else None
        ),
        "cpu_percent": _compute_cpu_percent(f"daemon:pid:{pid}", cpu_total),
        "cpu_user_seconds": round(cpu_user, 3),
        "cpu_system_seconds": round(cpu_system, 3),
        "thread_count": stat["thread_count"],
        "open_fds": _count_open_fds(pid),
        "started_at": started_at,
        "uptime_seconds": round(uptime_seconds, 1) if uptime_seconds is not None else None,
    }


def _descendant_pids(root_pid: int) -> set[int]:
    if not Path("/proc").exists():
        return {root_pid}

    parent_map: dict[int, list[int]] = {}
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        pid = int(proc_dir.name)
        stat = _read_proc_stat(pid)
        if stat is None:
            continue
        parent_map.setdefault(stat["ppid"], []).append(pid)

    descendants = {root_pid}
    pending = [root_pid]
    while pending:
        parent = pending.pop()
        for child in parent_map.get(parent, []):
            if child in descendants:
                continue
            descendants.add(child)
            pending.append(child)
    return descendants


def _sum_optional(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _aggregate(processes: list[dict[str, Any]]) -> dict[str, Any]:
    cpu_user_seconds = sum(process.get("cpu_user_seconds") or 0 for process in processes)
    cpu_system_seconds = sum(
        process.get("cpu_system_seconds") or 0 for process in processes
    )
    cpu_total = cpu_user_seconds + cpu_system_seconds
    cpu_values = [
        process.get("cpu_percent")
        for process in processes
        if process.get("cpu_percent") is not None
    ]
    return {
        "process_count": len(processes),
        "rss_bytes": _sum_optional([process.get("rss_bytes") for process in processes]),
        "vms_bytes": _sum_optional([process.get("vms_bytes") for process in processes]),
        "rss_anon_bytes": _sum_optional(
            [process.get("rss_anon_bytes") for process in processes]
        ),
        "rss_file_bytes": _sum_optional(
            [process.get("rss_file_bytes") for process in processes]
        ),
        "rss_shmem_bytes": _sum_optional(
            [process.get("rss_shmem_bytes") for process in processes]
        ),
        "swap_bytes": _sum_optional([process.get("swap_bytes") for process in processes]),
        "cpu_percent": round(sum(cpu_values), 1) if cpu_values else None,
        "cpu_user_seconds": round(cpu_user_seconds, 3),
        "cpu_system_seconds": round(cpu_system_seconds, 3),
        "thread_count": _sum_optional([process.get("thread_count") for process in processes]),
        "open_fds": _sum_optional([process.get("open_fds") for process in processes]),
    }


def _linux_memory_info() -> dict[str, int | float | None]:
    raw = _read_text(Path("/proc/meminfo"))
    if not raw:
        return {}
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    total = _kb_to_bytes(data.get("MemTotal", "").split()[0] if data.get("MemTotal") else None)
    available = _kb_to_bytes(
        data.get("MemAvailable", "").split()[0] if data.get("MemAvailable") else None
    )
    used = total - available if total is not None and available is not None else None
    return {
        "memory_total_bytes": total,
        "memory_available_bytes": available,
        "memory_used_bytes": used,
        "memory_percent": round((used / total) * 100, 1) if used is not None and total else None,
    }


def _local_ip_addresses(hostname: str) -> list[str]:
    addresses: list[str] = []

    def add(address: str | None) -> None:
        if not address or address.startswith("127.") or address in addresses:
            return
        addresses.append(address)

    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass

    try:
        for address in socket.gethostbyname_ex(hostname)[2]:
            add(address)
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            add(sock.getsockname()[0])
    except OSError:
        pass

    return addresses


def collect_runtime_stats(service: str) -> dict[str, Any]:
    current_pid = os.getpid()
    processes = [
        snapshot
        for pid in sorted(_descendant_pids(current_pid))
        if (snapshot := _process_snapshot(pid)) is not None
    ]
    if not processes:
        processes = [
            {
                "pid": current_pid,
                "ppid": os.getppid(),
                "name": Path(sys.executable).name,
                "command": " ".join(sys.argv) or None,
                "rss_bytes": None,
                "vms_bytes": None,
                "rss_anon_bytes": None,
                "rss_file_bytes": None,
                "rss_shmem_bytes": None,
                "swap_bytes": None,
                "cpu_percent": None,
                "cpu_user_seconds": None,
                "cpu_system_seconds": None,
                "thread_count": None,
                "open_fds": None,
                "started_at": None,
                "uptime_seconds": None,
            }
        ]
    current_process = next(
        (process for process in processes if process["pid"] == current_pid),
        processes[0],
    )
    memory_info = _linux_memory_info()
    hostname = socket.gethostname()
    return {
        "service": service,
        "sampled_at": int(time.time()),
        "hostname": hostname,
        "ip_addresses": _local_ip_addresses(hostname),
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "cpu_model": platform.processor() or None,
        "cpu_frequency_mhz": None,
        "memory_total_bytes": memory_info.get("memory_total_bytes"),
        "memory_available_bytes": memory_info.get("memory_available_bytes"),
        "memory_used_bytes": memory_info.get("memory_used_bytes"),
        "memory_percent": memory_info.get("memory_percent"),
        "collection_scope": "current_process_tree",
        "current_pid": current_pid,
        "aggregate": _aggregate(processes),
        "current_process": current_process,
        "processes": processes,
    }
