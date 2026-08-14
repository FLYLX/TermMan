import io
path = r"E:\dev\TermPaws\dev\TermPaws\de_bug\mock_napcat.py"
with io.open(path, "r", encoding="utf-8") as handle:
    text = handle.read()
old = "HEADERS = {'X-Self-ID': '10001', 'X-Client-Role': 'Universal'}"
new = "HEADERS = {'X-Self-ID': '10001', 'X-Client-Role': 'Universal', 'Authorization': 'Bearer x0SA-6tPi_ZbWciyKDr7F6e_arctgnMbRRWsK-lwQBs'}"
assert text.count(old) == 1, "anchor count=%d" % text.count(old)
text = text.replace(old, new, 1)
with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(text)
print("mock updated")