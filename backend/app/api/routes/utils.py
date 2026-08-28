import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pydantic.networks import EmailStr
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_superuser
from app.models import Item, Message
from app.plugins.robot.bridge_client import robot_bridge_client
from app.services.runtime_monitor import (
    BackendRuntimeStatsResponse,
    TermPawsRuntimeStatsResponse,
    build_TermPaws_runtime_response,
    collect_backend_runtime_stats,
    runtime_service_stats,
)
from app.utils import generate_test_email, send_email

router = APIRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/test-email/",
    dependencies=[Depends(get_current_active_superuser)],
    status_code=201,
)
def test_email(email_to: EmailStr) -> Message:
    """
    Test emails.
    """
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


class SetupBody(BaseModel):
    email: EmailStr | None = None
    password: str


@router.get("/setup-required")
def setup_required(session: SessionDep) -> dict:
    from app.models import User

    existing = session.exec(select(User).where(User.is_superuser == True)).first()  # noqa: E712
    return {"required": existing is None}


@router.post("/setup")
def setup_admin(body: SetupBody, session: SessionDep) -> Message:
    from app import crud
    from app.core.config import settings
    from app.models import User, UserCreate

    existing = session.exec(select(User).where(User.is_superuser == True)).first()  # noqa: E712
    if existing is not None:
        raise HTTPException(status_code=403, detail="Setup already completed")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    email = body.email or settings.FIRST_SUPERUSER
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    crud.create_user(
        session=session,
        user_create=UserCreate(email=email, password=body.password, is_superuser=True),
    )
    return Message(message="Admin account created")


@router.get("/health-check/")
async def health_check() -> bool:
    return True


@router.get("/version/")
async def version() -> dict:
    try:
        from importlib.metadata import version as pkg_version

        app_version = pkg_version("termpaws-backend")
    except Exception:
        app_version = "dev"
    return {"version": app_version}


@router.get("/mem-snapshot/")
async def mem_snapshot():
    import gc, resource, types, collections
    gc.collect()
    objs = gc.get_objects()
    type_counts = {}
    for obj in objs:
        t = type(obj).__name__
        type_counts[t] = type_counts.get(t, 0) + 1
    top = sorted(type_counts.items(), key=lambda x: -x[1])[:20]
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    funcs = [o for o in objs if isinstance(o, types.FunctionType)]
    func_mods = collections.Counter()
    for f in funcs:
        func_mods[getattr(f, "__module__", "?") or "?"] += 1
    return {
        "rss_mb": round(rss),
        "gc_objects": len(objs),
        "top_types": [{"type": k, "count": v} for k, v in top],
        "function_count": len(funcs),
        "func_modules": [{"module": k, "count": v} for k, v in func_mods.most_common(20)],
    }


_GC_BASELINE = {}

@router.get("/leak-probe/")
async def leak_probe():
    import gc, resource
    gc.collect()
    out = {}
    out["rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    out["gc_objects"] = len(gc.get_objects())
    def safe(fn):
        try:
            return fn()
        except Exception as exc:
            return f"err:{exc}"
    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.session import agent_session_manager
    from app.services.agent.stream_manager import stream_manager
    from app.services.agent.agent import Agent, AgentManager
    out["tickets"] = safe(lambda: len(reply_ticket_manager._tickets))
    out["sessions"] = safe(lambda: len(agent_session_manager._sessions))
    out["agent_instances"] = safe(lambda: len(Agent._instances))
    out["stream_chat_items"] = safe(lambda: len(stream_manager._chat_callbacks))
    out["stream_chat_cbs"] = safe(lambda: sum(len(s) for s in stream_manager._chat_callbacks.values()))
    out["stream_agent_windows"] = safe(lambda: len(stream_manager._agent_windows))
    out["stream_term_batches"] = safe(lambda: len(stream_manager._terminal_batches))
    out["robot_controllers"] = safe(lambda: __import__("app.plugins.robot.service", fromlist=["robot_service"]).robot_service._conversation_controllers.__len__())
    def _sd():
        d=[]
        for item_id, sess in agent_session_manager._sessions.items():
            d.append({"item": item_id[:8], "callbacks": len(getattr(sess, "output_callbacks", [])), "queue": getattr(sess, "input_queue", None).qsize() if getattr(sess, "input_queue", None) else -1})
        return d
    out["session_detail"] = safe(_sd)
    return out

@router.get("/malloc-test/")
async def malloc_test():
    import gc, ctypes, glob
    def vmrss_kb():
        try:
            for line in open("/proc/self/status"):
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
        except Exception:
            return -1
        return -1
    before = vmrss_kb()
    th = len(glob.glob("/proc/self/task/*"))
    gc.collect()
    try:
        libc = ctypes.CDLL("libc.so.6")
        trimmed = int(libc.malloc_trim(0))
    except Exception as exc:
        trimmed = f"err:{exc}"
    after = vmrss_kb()
    mi = {}
    try:
        class _mallinfo2(ctypes.Structure):
            _fields_ = [(n, ctypes.c_size_t) for n in ("arena","ordblks","smblks","hblks","hblkhd","usmblks","fsmblks","uordblks","fordblks","keepcost")]
        libc2 = ctypes.CDLL("libc.so.6")
        libc2.mallinfo2.restype = _mallinfo2
        m = libc2.mallinfo2()
        mb = 1024*1024
        mi = {"arena_mb": round(m.arena/mb,1), "used_mb": round(m.uordblks/mb,1), "free_in_arena_mb": round(m.fordblks/mb,1), "mmap_mb": round(m.hblkhd/mb,1), "frag_pct": round((m.arena-m.uordblks)/max(m.arena,1)*100,1)}
    except Exception as exc:
        mi = {"err": str(exc)}
    return {"rss_before_mb": round(before/1024,1), "rss_after_mb": round(after/1024,1), "rss_freed_mb": round((before-after)/1024,1), "malloc_trim_return": trimmed, "threads": th, "mallinfo": mi}

@router.get("/mem-debug/")
async def mem_debug() -> dict:
    """综合内存诊断：分配器状态、jemalloc 统计、smaps 构成、最大匿名映射、
    embedding 模型状态、数据文件大小。"""
    import ctypes
    import gc
    import glob
    import os
    import tracemalloc

    out: dict = {}

    def _read(path: str) -> str:
        try:
            with open(path, errors="replace") as f:
                return f.read()
        except Exception:
            return ""

    env_raw = open("/proc/self/environ", "rb").read().replace(b"\0", b"\n").decode(errors="replace")
    out["allocator_env"] = [
        line
        for line in env_raw.splitlines()
        if line.startswith(("MALLOC_CONF", "PYTHONMALLOC", "LD_PRELOAD", "EMBEDDING_MODEL_NAME"))
    ]
    maps = _read("/proc/self/maps")
    out["jemalloc_loaded"] = "libjemalloc" in maps

    try:
        lib = ctypes.CDLL(None)
        mallctl = lib.mallctl
        epoch = ctypes.c_size_t(0)
        esz = ctypes.c_size_t(ctypes.sizeof(epoch))
        mallctl(b"epoch", ctypes.byref(epoch), ctypes.byref(esz), ctypes.byref(epoch), esz)
        mb = 1048576
        stats = {}
        for name in (
            "stats.allocated",
            "stats.active",
            "stats.resident",
            "stats.retained",
            "stats.mapped",
        ):
            val = ctypes.c_size_t(0)
            sz = ctypes.c_size_t(ctypes.sizeof(val))
            if mallctl(name.encode(), ctypes.byref(val), ctypes.byref(sz), None, 0) == 0:
                stats[name.split(".")[1] + "_mb"] = round(val.value / mb, 1)
        out["jemalloc"] = stats
    except AttributeError:
        out["jemalloc"] = None

    rollup = _read("/proc/self/smaps_rollup")
    out["smaps_rollup"] = {
        k: int(v.split()[0]) // 1024
        for line in rollup.splitlines()
        if ":" in line and line.split(":")[0] in {"Rss", "Pss", "Anonymous", "Private_Clean", "Private_Dirty", "Shared_Clean", "Shared_Dirty"}
        for k, v in [line.split(":")]
    }

    big_regions = []
    cur: dict = {}
    for line in _read("/proc/self/smaps").splitlines():
        parts = line.split()
        if not parts:
            continue
        if "-" in parts[0] and len(parts) >= 5 and all(c in "0123456789abcdef-" for c in parts[0]):
            if cur.get("rss", 0) >= 16 * 1024:
                big_regions.append(cur)
            perms = parts[1] if len(parts) > 1 else ""
            name = parts[-1] if len(parts) >= 6 else ""
            cur = {"perms": perms, "name": name, "rss": 0, "anon": 0}
        elif line.startswith("Rss:"):
            cur["rss"] = int(parts[1])
        elif line.startswith("Anonymous:"):
            cur["anon"] = int(parts[1])
    if cur.get("rss", 0) >= 16 * 1024:
        big_regions.append(cur)
    big_regions.sort(key=lambda r: -r["rss"])
    out["top_regions"] = [
        {"rss_mb": round(r["rss"] / 1024, 1), "anon_mb": round(r["anon"] / 1024, 1), "perms": r["perms"], "name": r["name"][:80]}
        for r in big_regions[:15]
    ]

    gc.collect()
    out["gc_objects"] = len(gc.get_objects())
    if tracemalloc.is_tracing():
        cur_tm, peak_tm = tracemalloc.get_traced_memory()
        out["tracemalloc_mb"] = {"current": round(cur_tm / 1048576, 1), "peak": round(peak_tm / 1048576, 1)}
    out["threads"] = len(glob.glob("/proc/self/task/*"))

    try:
        from app.core.config import settings

        out["embedding_model_name"] = settings.EMBEDDING_MODEL_NAME
    except Exception as exc:
        out["embedding_model_name"] = f"err:{exc}"
    try:
        from app.services.agent.memory.vector_store import EmbeddingService

        svc = EmbeddingService()
        out["embedding_loaded"] = svc._model is not None
        out["embedding_load_error"] = svc._load_error
    except Exception as exc:
        out["embedding_loaded"] = f"err:{exc}"

    try:
        from app.core.config import settings as _s

        data_files = {}
        for path in (
            os.environ.get("SQLITE_DATABASE_URL", "").replace("sqlite:///", ""),
            _s.CHROMA_PERSIST_DIR,
            os.environ.get("AGENT_STATE_STORE_PATH", ""),
            os.environ.get("ROBOT_CONVERSATION_MEMORY_DIR", ""),
        ):
            if not path:
                continue
            try:
                if os.path.isfile(path):
                    data_files[path] = round(os.path.getsize(path) / 1048576, 1)
                elif os.path.isdir(path):
                    total = sum(
                        os.path.getsize(os.path.join(dp, f))
                        for dp, _, fns in os.walk(path)
                        for f in fns
                    )
                    data_files[path + "/"] = round(total / 1048576, 1)
            except Exception:
                pass
        out["data_files_mb"] = data_files
    except Exception as exc:
        out["data_files_mb"] = f"err:{exc}"

    return out


@router.get("/jemalloc-stats/")
async def jemalloc_stats():
    """jemalloc mallctl 统计：allocated=活跃分配，retained=已释放但未归还 OS。
    retained 远大于 allocated 说明 decay 未生效。"""
    import ctypes

    def vmrss_kb():
        try:
            for line in open("/proc/self/status"):
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
        except Exception:
            return -1
        return -1

    mb = 1024 * 1024
    out = {"rss_mb": round(vmrss_kb() / 1024, 1), "jemalloc": False}
    try:
        lib = ctypes.CDLL(None)
        mallctl = lib.mallctl
    except AttributeError:
        return out
    out["jemalloc"] = True
    try:
        epoch = ctypes.c_size_t(0)
        esz = ctypes.c_size_t(ctypes.sizeof(epoch))
        mallctl(
            b"epoch",
            ctypes.byref(epoch),
            ctypes.byref(esz),
            ctypes.byref(epoch),
            esz,
        )
    except Exception:
        pass
    for name in (
        "stats.allocated",
        "stats.active",
        "stats.resident",
        "stats.retained",
        "stats.mapped",
    ):
        val = ctypes.c_size_t(0)
        size = ctypes.c_size_t(ctypes.sizeof(val))
        try:
            if lib.mallctl(name.encode(), ctypes.byref(val), ctypes.byref(size), None, 0) == 0:
                out[name.split(".")[1] + "_mb"] = round(val.value / mb, 1)
        except Exception:
            pass
    return out


@router.get("/gc-diff/")
async def gc_diff(action: str = "diff", top: int = 30):
    import gc
    gc.collect()
    objs = gc.get_objects()
    counts = {}
    for o in objs:
        t = type(o).__name__
        counts[t] = counts.get(t, 0) + 1
    if action == "baseline":
        _GC_BASELINE.clear()
        _GC_BASELINE.update(counts)
        return {"action": "baseline", "total": len(objs), "types": len(counts)}
    base = _GC_BASELINE or {}
    rows = []
    for t in set(counts) | set(base):
        d = counts.get(t, 0) - base.get(t, 0)
        if d:
            rows.append({"type": t, "now": counts.get(t, 0), "base": base.get(t, 0), "diff": d})
    rows.sort(key=lambda r: r["diff"], reverse=True)
    return {"total_now": len(objs), "total_base": sum(base.values()), "top_growth": rows[:top], "top_shrink": rows[-top:]}


@router.get(
    "/backend-runtime/",
    response_model=BackendRuntimeStatsResponse,
    dependencies=[Depends(get_current_active_superuser)],
)
def backend_runtime_stats() -> BackendRuntimeStatsResponse:
    return collect_backend_runtime_stats()


def _daemon_runtime_services(session: SessionDep) -> list:
    items = session.exec(select(Item)).all()
    daemons: dict[str, tuple[str, str]] = {}
    for item in items:
        if not item.socket_host or not item.socket_port or not item.api_key:
            continue
        daemon_url = f"http://{item.socket_host}:{item.socket_port}"
        daemon_key = f"{daemon_url}:{item.api_key}"
        daemons[daemon_key] = (daemon_url, item.api_key)

    services = []
    with httpx.Client(timeout=2.0) as client:
        for index, (daemon_url, api_key) in enumerate(daemons.values(), start=1):
            label = f"Daemon {index}" if len(daemons) > 1 else "Daemon"
            try:
                response = client.get(
                    f"{daemon_url.rstrip('/')}/api/runtime",
                    headers={"X-API-Key": api_key},
                )
                response.raise_for_status()
                payload = response.json()
                services.append(
                    runtime_service_stats(
                        service=f"daemon:{index}",
                        label=label,
                        kind="daemon",
                        runtime=payload,
                        url=daemon_url,
                        metadata={"daemon_url": daemon_url},
                    )
                )
            except Exception as exc:
                services.append(
                    runtime_service_stats(
                        service=f"daemon:{index}",
                        label=label,
                        kind="daemon",
                        status="error",
                        url=daemon_url,
                        error=str(exc),
                        metadata={"daemon_url": daemon_url},
                    )
                )
    return services


def _robot_runtime_service() -> list:
    try:
        bridge_health = robot_bridge_client.get_health(timeout=2.0)
        runtime = bridge_health.get("runtime")
        if isinstance(runtime, dict):
            return [
                runtime_service_stats(
                    service="robot",
                    label="Robot Bridge",
                    kind="robot",
                    runtime=runtime,
                    url=robot_bridge_client.base_url,
                    metadata={
                        "loaded_robot_count": bridge_health.get("loaded_robot_count", 0),
                        "connected_bot_count": bridge_health.get(
                            "connected_bot_count", 0
                        ),
                    },
                )
            ]
        return [
            runtime_service_stats(
                service="robot",
                label="Robot Bridge",
                kind="robot",
                status="error",
                url=robot_bridge_client.base_url,
                error="Robot bridge did not report runtime metrics",
            )
        ]
    except Exception as exc:
        return [
            runtime_service_stats(
                service="robot",
                label="Robot Bridge",
                kind="robot",
                status="error",
                url=robot_bridge_client.base_url,
                error=str(exc),
            )
        ]


@router.get(
    "/TermPaws-runtime/",
    response_model=TermPawsRuntimeStatsResponse,
    dependencies=[Depends(get_current_active_superuser)],
)
def TermPaws_runtime_stats(session: SessionDep) -> TermPawsRuntimeStatsResponse:
    services = [
        runtime_service_stats(
            service="backend",
            label="Backend API",
            kind="backend",
            runtime=collect_backend_runtime_stats(),
        )
    ]
    services.extend(_daemon_runtime_services(session))
    services.extend(_robot_runtime_service())
    return build_TermPaws_runtime_response(services)


@router.get("/mem-top/")
async def mem_top(top: int = 25):
    """Shallow-size scan of live gc objects, run in a worker thread."""
    import asyncio

    return await asyncio.to_thread(_mem_top_sync, top)


def _mem_top_sync(top: int):
    import gc, sys

    gc.collect()
    objs = gc.get_objects()
    by_type: dict = {}
    for o in objs:
        try:
            sz = sys.getsizeof(o)
        except Exception:
            continue
        t = type(o).__name__
        agg = by_type.get(t)
        if agg is None:
            by_type[t] = [1, sz, sz, ""]
        else:
            agg[0] += 1
            agg[1] += sz
            if sz > agg[2]:
                agg[2] = sz
                if isinstance(o, str):
                    agg[3] = repr(o[:120])
                elif isinstance(o, bytes):
                    agg[3] = repr(o[:120])
                else:
                    try:
                        ln = len(o)
                    except Exception:
                        ln = -1
                    agg[3] = f"len={ln}"

    def rss_kb():
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])
        except Exception:
            return -1
        return -1

    types_sorted = sorted(by_type.items(), key=lambda kv: -kv[1][1])[:top]
    return {
        "rss_mb": round(rss_kb() / 1024, 1),
        "gc_objects": len(objs),
        "note": "shallow sizes (containers exclude their elements)",
        "top_types_by_total": [
            {"type": k, "count": v[0], "total_kb": round(v[1] / 1024, 1),
             "largest_kb": round(v[2] / 1024, 1), "largest_info": v[3][:160]}
            for k, v in types_sorted
        ],
    }


_TM_STATE: dict = {"baseline": None}


@router.get("/tracemalloc-ctl/")
async def tracemalloc_ctl(action: str = "status", top: int = 20, frames: int = 1):
    """start | status | top | clear | stop. top = diff vs baseline snapshot."""
    import tracemalloc

    def rss_kb():
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])
        except Exception:
            return -1
        return -1

    if action == "start":
        if not tracemalloc.is_tracing():
            tracemalloc.start(max(1, min(int(frames), 30)))
        _TM_STATE["baseline"] = tracemalloc.take_snapshot()
        return {"tracing": True, "rss_mb": round(rss_kb() / 1024, 1)}
    if action == "clear":
        if tracemalloc.is_tracing():
            _TM_STATE["baseline"] = tracemalloc.take_snapshot()
            return {"ok": True, "rss_mb": round(rss_kb() / 1024, 1)}
        return {"ok": False, "error": "not tracing"}
    if action == "top":
        if not tracemalloc.is_tracing():
            return {"error": "not tracing, call action=start first"}
        if _TM_STATE["baseline"] is None:
            return {"error": "no baseline, call action=start first"}
        current = tracemalloc.take_snapshot()
        stats = current.compare_to(_TM_STATE["baseline"], "lineno")[:top]
        return {
            "rss_mb": round(rss_kb() / 1024, 1),
            "top_growth": [
                {"diff_kb": round(s.size_diff / 1024, 1), "total_kb": round(s.size / 1024, 1), "location": str(s)}
                for s in stats
            ],
        }
    if action == "stop":
        tracemalloc.stop()
        _TM_STATE["baseline"] = None
        return {"tracing": False, "rss_mb": round(rss_kb() / 1024, 1)}
    return {"tracing": tracemalloc.is_tracing(), "has_baseline": _TM_STATE["baseline"] is not None, "rss_mb": round(rss_kb() / 1024, 1)}
