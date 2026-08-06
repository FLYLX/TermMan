p = r'frontend\src\components\Items\ChatPanel.tsx'
src = open(p, encoding='utf-8').read()
old = r'终端任务运行中，等当前会话结束后继续发送'
new = r'终端任务运行中，消息将排队合并处理'
old_escaped = old.encode('unicode_escape').decode('ascii').replace('\\u', '\\u')
# file stores \uXXXX escape sequences as literal text
old_lit = old.encode('unicode_escape').decode('ascii')
new_lit = new.encode('unicode_escape').decode('ascii')
if old_lit in src:
    open(p, 'w', encoding='utf-8').write(src.replace(old_lit, new_lit))
    print('patched (escaped form)')
elif old in src:
    open(p, 'w', encoding='utf-8').write(src.replace(old, new))
    print('patched (raw form)')
else:
    print('NOT FOUND')
