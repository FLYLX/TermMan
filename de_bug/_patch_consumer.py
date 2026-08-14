import sys
path = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\session.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

changes = 0

# 1. Add _wake_event and consumer thread to __init__
old_init = '''        self._daemon_jobs_snapshot: list[dict[str, Any]] = []
        self._daemon_jobs_snapshot_at: datetime | None = None
        self._recent_finished_jobs: list[dict[str, Any]] = []

        logger.info(f"[AgentSession] Created session for item={item_id}, handler={handler_id}")'''

new_init = '''        self._daemon_jobs_snapshot: list[dict[str, Any]] = []
        self._daemon_jobs_snapshot_at: datetime | None = None
        self._recent_finished_jobs: list[dict[str, Any]] = []

        self._wake_event = threading.Event()
        self._consumer_shutdown = False
        self._consumer_thread = threading.Thread(
            target=self._consumer_loop, daemon=True, name=f"agent-consumer-{item_id[:8]}"
        )
        self._consumer_thread.start()

        logger.info(f"[AgentSession] Created session for item={item_id}, handler={handler_id}")'''

if old_init not in content:
    print("ERROR: __init__ block not found")
    sys.exit(1)
content = content.replace(old_init, new_init)
changes += 1

# 2. Replace process_input with queue-only version
old_pi = '''    def process_input(self, input_msg: InputMessage):
        with self.lock:
            if self.state in {SessionState.RUNNING, SessionState.INTERRUPTING, SessionState.COOLDOWN}:
                self.queue_input(input_msg)
                return

        self._begin_turn(input_msg)

        process_error = ""
        try:
            self._process_input(input_msg)
        except Exception as exc:
            process_error = str(exc)
            raise
        finally:
            self._finish_turn()
            self._notify_input_complete(input_msg, not process_error, process_error)

            if not self.input_queue.empty():
                threading.Thread(target=self.process_queue, daemon=True).start()'''

new_pi = '''    def process_input(self, input_msg: InputMessage):
        self.queue_input(input_msg)
        self._wake_event.set()'''

if old_pi not in content:
    print("ERROR: process_input block not found")
    sys.exit(1)
content = content.replace(old_pi, new_pi)
changes += 1

# 3. Replace process_queue with _consumer_loop
old_pq = '''    def process_queue(self):
        """Drain all pending inputs, merge into one batch, process as a single turn."""
        while True:
            batch: list[InputMessage] = []
            # Drain: first item with 1s timeout, then 0.3s to collect stragglers
            try:
                first = self.input_queue.get(timeout=1)
                batch.append(first)
            except queue.Empty:
                with self.lock:
                    self.state = SessionState.IDLE
                self._emit_idle_or_waiting_status(0)
                return
            while True:
                try:
                    batch.append(self.input_queue.get(timeout=0.3))
                except queue.Empty:
                    break

            # Filter stale inputs
            batch = [msg for msg in batch if not self._is_stale_input(msg)]
            if not batch:
                continue

            merged = batch[0] if len(batch) == 1 else self._merge_input_batch(batch)

            self._begin_turn(merged)
            process_error = ""
            try:
                self._process_input(merged)
            except Exception as exc:
                process_error = str(exc)
                logger.error(f"[AgentSession] Error processing queue: {exc}")
                self.emit_output(f"处理失败: {exc}", "agent_error")
            finally:
                self._finish_turn()
                for msg in batch:
                    self._notify_input_complete(msg, not process_error, process_error)'''

new_pq = '''    def _consumer_loop(self):
        """Single consumer: wait for wake signal, drain queue, process one turn, repeat."""
        while not self._consumer_shutdown:
            self._wake_event.wait(timeout=1.0)
            self._wake_event.clear()

            if self._consumer_shutdown:
                break

            batch: list[InputMessage] = []
            try:
                first = self.input_queue.get(timeout=0.1)
                batch.append(first)
            except queue.Empty:
                continue
            while True:
                try:
                    batch.append(self.input_queue.get(timeout=0.3))
                except queue.Empty:
                    break

            batch = [msg for msg in batch if not self._is_stale_input(msg)]
            if not batch:
                with self.lock:
                    if self.input_queue.empty():
                        self.state = SessionState.IDLE
                        self._emit_idle_or_waiting_status(0)
                continue

            merged = batch[0] if len(batch) == 1 else self._merge_input_batch(batch)

            self._begin_turn(merged)
            process_error = ""
            try:
                self._process_input(merged)
            except Exception as exc:
                process_error = str(exc)
                logger.error(f"[AgentSession] Error processing queue: {exc}")
                self.emit_output(f"处理失败: {exc}", "agent_error")
            finally:
                self._finish_turn()
                for msg in batch:
                    self._notify_input_complete(msg, not process_error, process_error)

        with self.lock:
            self.state = SessionState.IDLE

    def process_queue(self):
        """Legacy compat: wake the consumer."""
        self._wake_event.set()'''

if old_pq not in content:
    print("ERROR: process_queue block not found")
    sys.exit(1)
content = content.replace(old_pq, new_pq)
changes += 1

# 4. Update shutdown to stop consumer
old_sd = '''    def shutdown(self):
        self._abort_flag = True
        self._cancel_pending_command_recheck()'''

new_sd = '''    def shutdown(self):
        self._abort_flag = True
        self._consumer_shutdown = True
        self._wake_event.set()
        self._cancel_pending_command_recheck()'''

if old_sd not in content:
    print("ERROR: shutdown block not found")
    sys.exit(1)
content = content.replace(old_sd, new_sd)
changes += 1

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print(f"OK: {changes} changes applied - single consumer pattern")
