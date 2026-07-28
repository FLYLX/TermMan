path = '/app/backend/app/services/agent/prompts/builder.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Make installed software conditional on active workflow
old = '''    installed_software_context = _build_installed_software_context(item_id)
    if installed_software_context:
        extra_prompt_parts.append(installed_software_context)'''

new = '''    if active_task_ledger_context:
        installed_software_context = _build_installed_software_context(item_id)
        if installed_software_context:
            extra_prompt_parts.append(installed_software_context)'''

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("OK: installed software now conditional on active workflow")
else:
    print("ERROR: pattern not found")
