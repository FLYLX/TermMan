# -*- coding: utf-8 -*-
p = r"daemon\src\service\job_runner.py"
raw = open(p, encoding="utf-8", newline="").read()
crlf = "\r\n" in raw
t = raw.replace("\r\n", "\n")

old = """            if pending_line.strip():
                self._append_output_line(item_uuid, job_id, pending_line, tail)

        except Exception as exc:"""
new = """            if pending_line.strip():
                self._append_output_line(item_uuid, job_id, pending_line, tail)

            # cancel_job terminates the process immediately; the loop above can
            # break on the same iteration before re-checking the cancel flag.
            # Re-check here (the job is still registered) so the finished
            # result is authoritatively marked cancelled.
            if not cancelled:
                cancelled = self._is_cancel_requested(job_id)

        except Exception as exc:"""
n = t.count(old)
assert n == 1, "anchor expected 1, found %d" % n
t = t.replace(old, new)
if crlf:
    t = t.replace("\n", "\r\n")
open(p, "w", encoding="utf-8", newline="").write(t)
print("job_runner.py OK")
