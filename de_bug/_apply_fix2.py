import re

# Fix 1: Add tini to Dockerfile
path = r"E:\dev\TermMan\dev\TermMan\daemon\Dockerfile"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Add tini installation before the CMD
old_cmd = '# 设置启动命令\nCMD ["python", "src/main.py"]'
new_cmd = '''# Install tini for proper PID 1 zombie reaping
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*

# 设置启动命令
ENTRYPOINT ["tini", "--"]
CMD ["python", "src/main.py"]'''

if old_cmd in content:
    content = content.replace(old_cmd, new_cmd, 1)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"[OK] Added tini to Dockerfile")
else:
    print(f"[SKIP] CMD pattern not found in Dockerfile")

# Fix 2: Add zombie reaper to job_runner.py
path2 = r"E:\dev\TermMan\dev\TermMan\daemon\src\service\job_runner.py"
with open(path2, "r", encoding="utf-8") as f:
    content = f.read()

# Add reap_zombies method and call it in _run_job_impl finally block
old_finally = '''        finally:
            self._unregister_active_job(job_id)
            if process and process.stdout:
                try:
                    process.stdout.close()
                except Exception:
                    pass'''

new_finally = '''        finally:
            self._unregister_active_job(job_id)
            if process and process.stdout:
                try:
                    process.stdout.close()
                except Exception:
                    pass
            self._reap_zombies()'''

if old_finally in content:
    content = content.replace(old_finally, new_finally, 1)
    print("[OK] Added _reap_zombies call to finally block")
else:
    print("[SKIP] finally block pattern not found")

# Add the _reap_zombies method before _terminate_process
old_terminate = '    def _terminate_process(self, pid: int | None):'
new_terminate = '''    @staticmethod
    def _reap_zombies() -> None:
        """Reap any zombie child processes to prevent accumulation."""
        try:
            while True:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
        except ChildProcessError:
            pass

    def _terminate_process(self, pid: int | None):'''

if old_terminate in content:
    content = content.replace(old_terminate, new_terminate, 1)
    with open(path2, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print("[OK] Added _reap_zombies method to job_runner.py")
else:
    print("[SKIP] _terminate_process pattern not found")