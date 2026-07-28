import sys
path = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\session.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = """    def process_input(self, input_msg: InputMessage):
        with self.lock:
            if self.state in {SessionState.RUNNING, SessionState.INTERRUPTING}:
                self.queue_input(input_msg)
                return"""

new = """    def process_input(self, input_msg: InputMessage):
        with self.lock:
            if self.state in {SessionState.RUNNING, SessionState.INTERRUPTING, SessionState.COOLDOWN}:
                self.queue_input(input_msg)
                return"""

if old not in content:
    print("ERROR: process_input block not found")
    sys.exit(1)
content = content.replace(old, new)
with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("OK: COOLDOWN added to process_input guard")
