from pathlib import Path
p = Path(r"de_bug\_strip_wf_small.py")
s = p.read_text(encoding="utf-8")
s = s.replace("reply_ticket_manager._ticket_aliases.clear()\n            _persist_aliases(self._ticket_aliases)",
              "self._tickets.clear()\n            self._ticket_aliases.clear()\n            _persist_aliases(self._ticket_aliases)")
s = s.replace('''            reply_ticket_manager._ticket_aliases.clear()
            _persist_aliases(self._ticket_aliases)''',
'''            self._tickets.clear()
            self._ticket_aliases.clear()
            _persist_aliases(self._ticket_aliases)''', 1)
p.write_text(s, encoding="utf-8")
print("fixed")
