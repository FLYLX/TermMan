path = '/app/backend/app/services/agent/mcp/local_server.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Update the QQ robot message - add NRN instruction
old_qq = '''                "\u4e0d\u8981\u4e3a\u4e2d\u95f4\u7ed3\u679c\u53d1\u9001 QQ \u6d88\u606f\u3002"
                "\u53ea\u5728\u5230\u8fbe\u6c47\u62a5\u6b65\u9aa4\u3001\u6700\u7ec8\u5931\u8d25\u4e14\u65e0\u66f4\u591a\u65b9\u6cd5\u3001\u6216\u91cd\u5927\u65b9\u5411\u53d8\u66f4\u65f6\u624d\u53d1 QQ\u3002"'''

new_qq = '''                "\u4e0d\u8981\u4e3a\u4e2d\u95f4\u7ed3\u679c\u53d1\u9001 QQ \u6d88\u606f\u3002"
                "\u53ea\u5728\u5230\u8fbe\u6c47\u62a5\u6b65\u9aa4\u3001\u6700\u7ec8\u5931\u8d25\u4e14\u65e0\u66f4\u591a\u65b9\u6cd5\u3001\u6216\u91cd\u5927\u65b9\u5411\u53d8\u66f4\u65f6\u624d\u53d1 QQ\u3002"
                "\u5982\u679c\u4e0d\u9700\u8981\u56de\u590d\u7528\u6237\uff0c\u6700\u7ec8\u53ea\u8f93\u51fa NRN \u5373\u53ef\u3002"'''

if old_qq in content:
    content = content.replace(old_qq, new_qq)
    print("OK: added NRN hint to QQ callback")
else:
    print("WARN: QQ callback text not found, trying alternative")
    # Try finding it differently
    import sys; sys.exit(1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("DONE")
