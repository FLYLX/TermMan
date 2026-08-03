# Passive overnight memory monitor: samples backend RSS/threads every N seconds
# and writes a timestamped CSV. Generates NO load; run alongside real workload.
import os, subprocess, time
from datetime import datetime

CONTAINER = "termman-backend-1"
INTERVAL = float(os.environ.get("MON_INTERVAL", "120"))     # sample every 2 min
DURATION_HOURS = float(os.environ.get("MON_HOURS", "14"))
HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "_overnight_mem.csv")
LOG = os.path.join(HERE, "_overnight_mon.log")

def log(m):
    line = "[%s] %s" % (datetime.now().isoformat(timespec="seconds"), m)
    print(line, flush=True)
    try:
        open(LOG, "a", encoding="utf-8").write(line + "\n")
    except Exception:
        pass

def sample():
    sh = (
        'for p in $(ls /proc | grep -E "^[0-9]+$"); do [ "$p" = "$$" ] && continue; '
        'if [ -r "/proc/$p/cmdline" ] && tr "\\0" " " < "/proc/$p/cmdline" 2>/dev/null | grep -q "app[.]main:app"; then '
        'rss=$(awk \'/VmRSS:/{print $2}\' /proc/$p/status); '
        'th=$(awk \'/Threads:/{print $2}\' /proc/$p/status); '
        'echo "$rss $th"; exit 0; fi; done; echo "0 0"'
    )
    try:
        out = subprocess.run(["docker", "exec", CONTAINER, "sh", "-c", sh],
                             capture_output=True, text=True, timeout=30).stdout.strip().split()
        rss = round(int(out[0]) / 1024, 1) if out and out[0].isdigit() else -1
        th = int(out[1]) if len(out) > 1 and out[1].isdigit() else -1
        return rss, th
    except Exception:
        return -1, -1

def main():
    log("START passive monitor interval=%.0fs hours=%.1f" % (INTERVAL, DURATION_HOURS))
    new = not os.path.exists(CSV)
    f = open(CSV, "a", encoding="utf-8", newline="\n")
    if new:
        f.write("timestamp,elapsed_min,rss_mb,threads\n"); f.flush()
    start = time.time()
    while (time.time() - start) < DURATION_HOURS * 3600:
        rss, th = sample()
        el = round((time.time() - start) / 60, 1)
        f.write("%s,%s,%s,%s\n" % (datetime.now().isoformat(timespec="seconds"), el, rss, th))
        f.flush()
        log("elapsed=%.1fmin rss=%.1fMB threads=%d" % (el, rss, th))
        time.sleep(INTERVAL)
    f.close()
    log("STOP passive monitor")

if __name__ == "__main__":
    main()
