import re

path = r'E:\dev\TermMan\dev\TermMan\backend\app\api\routes\chat.py'
content = open(path, encoding='utf-8').read()

# Fix 1: Update INTERNAL_QQ_BACKGROUND_JOB_PREFIX to match Chinese prefix
old = 'INTERNAL_QQ_BACKGROUND_JOB_PREFIX = (\n    "[Background terminal job result for this QQ conversation]"\n)'
new = 'INTERNAL_QQ_BACKGROUND_JOB_PREFIX = (\n    "[\u540e\u53f0\u7ec8\u7aef\u4efb\u52a1\u7ed3\u679c - \u672c QQ \u4f1a\u8bdd]"\n)\nINTERNAL_QQ_BACKGROUND_JOB_BATCH_PREFIX = "[Background job results batch:"'
assert old in content, 'Fix 1 target not found'
content = content.replace(old, new, 1)

# Fix 2: Update _is_internal_agent_callback to also check batch prefix
old2 = '    return text.startswith(INTERNAL_QQ_BACKGROUND_JOB_PREFIX) or text.startswith(\n        INTERNAL_AGENT_RETRY_PREFIX\n    )'
new2 = '    return (\n        text.startswith(INTERNAL_QQ_BACKGROUND_JOB_PREFIX)\n        or text.startswith(INTERNAL_QQ_BACKGROUND_JOB_BATCH_PREFIX)\n        or text.startswith(INTERNAL_AGENT_RETRY_PREFIX)\n    )'
assert old2 in content, 'Fix 2 target not found'
content = content.replace(old2, new2, 1)

open(path, 'w', encoding='utf-8').write(content)
print('chat.py patched successfully')
