

@router.get("/mem-top/")
async def mem_top(top: int = 25):
    """Shallow-size scan of live gc objects: aggregate by type + biggest individuals."""
    import gc, sys

    gc.collect()
    objs = gc.get_objects()
    by_type: dict[str, list] = {}
    for o in objs:
        try:
            sz = sys.getsizeof(o)
        except Exception:
            continue
        t = type(o).__name__
        agg = by_type.get(t)
        if agg is None:
            by_type[t] = [1, sz, o]
        else:
            agg[0] += 1
            agg[1] += sz
            if sz > sys.getsizeof(agg[2]):
                agg[2] = o
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
    biggest = sorted(((v[1], k) for k, v in by_type.items()), reverse=True)[:top]
    out_types = []
    for name, (count, total, sample) in types_sorted:
        rep = ""
        try:
            rep = repr(sample)[:140]
        except Exception:
            rep = "<unrepr>"
        out_types.append({"type": name, "count": count, "total_kb": round(total / 1024, 1), "largest_sample": rep})
    return {
        "rss_mb": round(rss_kb() / 1024, 1),
        "gc_objects": len(objs),
        "note": "shallow sizes (containers exclude their elements)",
        "top_types_by_total": out_types,
    }


_TM_STATE: dict = {"baseline": None}


@router.get("/tracemalloc-ctl/")
async def tracemalloc_ctl(action: str = "status", top: int = 20):
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
            tracemalloc.start(25)
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