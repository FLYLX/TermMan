path = r'E:\dev\TermMan\dev\TermMan\backend\tests\services\test_reply_ticket_lifecycle.py'
content = open(path, encoding='utf-8').read()

# Fix: CQ codes are stripped from request_message in snapshots
old = '''        assert snapshot[0]["request_message"] == (
            "[CQ:at,qq=2900669542] install temurin 17"
        )'''
new = '''        assert snapshot[0]["request_message"] == "install temurin 17"'''

assert old in content, 'CQ code test fix target not found'
content = content.replace(old, new, 1)

open(path, 'w', encoding='utf-8').write(content)
print('CQ code test fix applied')
