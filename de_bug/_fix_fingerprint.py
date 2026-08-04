import pathlib
p = pathlib.Path(r"E:\dev\TermMan\dev\TermMan\backend\app\api\routes\chat.py")
text = p.read_text(encoding="utf-8")
old = '''    normalized = dict(payload)
    normalized.pop("item_id", None)
    normalized.pop("_reply_ticket_id", None)

    return json.dumps('''
new = '''    normalized = dict(payload)
    normalized.pop("item_id", None)
    normalized.pop("_reply_ticket_id", None)
    # Descriptive fields vary even when the model repeats the same state
    # transition without making progress, so they stay out of loop fingerprints.
    for _volatile_key in ("note", "explanation"):
        normalized.pop(_volatile_key, None)

    return json.dumps('''
assert text.count(old) == 1
text = text.replace(old, new)
p.write_text(text, encoding="utf-8")
print("fingerprint volatile-field exclusion done")
