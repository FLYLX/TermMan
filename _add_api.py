path = '/app/backend/app/api/routes/items.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

endpoint = '''


@router.get("/{id}/token-usage")
def get_token_usage(
    current_user: CurrentUser,
    id: uuid.UUID,
) -> dict[str, Any]:
    from app.services.agent.token_usage import token_usage_tracker

    stats = token_usage_tracker.get_item_stats(str(id))
    if stats is None:
        return {
            "item_id": str(id),
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "total_turns": 0,
            "first_seen": "",
            "last_seen": "",
            "models": [],
        }
    return stats
'''

content = content.rstrip() + endpoint
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("OK: added token-usage endpoint")
