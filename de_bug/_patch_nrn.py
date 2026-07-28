path = '/app/backend/app/services/agent/session.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add "NRN" to TERMINAL_NO_REPLY_MARKERS
old_markers = '''TERMINAL_NO_REPLY_MARKERS = (
    "[no_terminal_reply]",
    "[no_reply]",
    "[no_qq_reply]",
    "\u4e0d\u56de\u590d",
    "\u4e0d\u7528\u56de\u590d",
    "\u4e0d\u7528\u56de",
    "\u4e0d\u6253\u6270",
)'''

new_markers = '''TERMINAL_NO_REPLY_MARKERS = (
    "[no_terminal_reply]",
    "[no_reply]",
    "[no_qq_reply]",
    "nrn",
    "\u4e0d\u56de\u590d",
    "\u4e0d\u7528\u56de\u590d",
    "\u4e0d\u7528\u56de",
    "\u4e0d\u6253\u6270",
)'''

if old_markers in content:
    content = content.replace(old_markers, new_markers)
    print("OK: added NRN to markers")
else:
    print("ERROR: markers not found")
    import sys; sys.exit(1)

# 2. Add no-reply check in _send_pending_integration_response
old_send = '''    def _send_pending_integration_response(
        self,
        pending: PendingCommand | None,
        content: str,
        *,
        message_sent: bool = False,
    ) -> bool:
        contexts = self._copy_pending_integration_contexts(pending)
        if not contexts or not content.strip():
            return False'''

new_send = '''    def _send_pending_integration_response(
        self,
        pending: PendingCommand | None,
        content: str,
        *,
        message_sent: bool = False,
    ) -> bool:
        contexts = self._copy_pending_integration_contexts(pending)
        if not contexts or not content.strip():
            return False
        if is_terminal_no_reply_intent(content):
            if pending:
                self._mark_pending_integration_response_sent(pending)
            return True'''

if old_send in content:
    content = content.replace(old_send, new_send)
    print("OK: added no-reply check to _send_pending_integration_response")
else:
    print("ERROR: _send_pending_integration_response not found")
    import sys; sys.exit(1)

# 3. Add no-reply check in _deliver_terminal_reply_ticket
old_deliver = '''    def _deliver_terminal_reply_ticket(
        self,
        ticket_id: str,
        content: str,
    ) -> bool:
        ticket = self._get_reply_ticket(ticket_id)
        if not ticket or not content.strip():
            return False'''

new_deliver = '''    def _deliver_terminal_reply_ticket(
        self,
        ticket_id: str,
        content: str,
    ) -> bool:
        ticket = self._get_reply_ticket(ticket_id)
        if not ticket or not content.strip():
            return False
        if is_terminal_no_reply_intent(content):
            return True'''

if old_deliver in content:
    content = content.replace(old_deliver, new_deliver)
    print("OK: added no-reply check to _deliver_terminal_reply_ticket")
else:
    print("ERROR: _deliver_terminal_reply_ticket not found")
    import sys; sys.exit(1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("DONE")
