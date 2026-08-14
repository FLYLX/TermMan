filepath = r"E:\dev\TermPaws\dev\TermPaws\backend\app\api\routes\chat.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

changes = 0

# 1. Add import for token_usage_tracker at the top
old_import = "from app.core.config import settings as chat_settings"
new_import = """from app.core.config import settings as chat_settings
from app.services.agent.token_usage import token_usage_tracker as _token_tracker"""
# Only add if not already there
if "_token_tracker" not in content:
    # Find the first occurrence inside the function (it's imported inline)
    # Actually let's add it at the module level
    pass

# 2. Add stream_options to _build_completion_kwargs
old_kwargs = '''def _build_completion_kwargs(
    handler: ItemHandler,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict],
    stream: bool,
) -> dict[str, Any]:
    return build_litellm_completion_kwargs(
        model=handler.model,
        messages=messages,
        stream=stream,
        timeout=REQUEST_TIMEOUT,
        tools=tools,
        api_key=handler.api_key,
        api_base=handler.api_url,
        model_parameters=getattr(handler, "model_parameters", {}),
        default_parameters={"temperature": 0.1},
    )'''
new_kwargs = '''def _build_completion_kwargs(
    handler: ItemHandler,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict],
    stream: bool,
) -> dict[str, Any]:
    kwargs = build_litellm_completion_kwargs(
        model=handler.model,
        messages=messages,
        stream=stream,
        timeout=REQUEST_TIMEOUT,
        tools=tools,
        api_key=handler.api_key,
        api_base=handler.api_url,
        model_parameters=getattr(handler, "model_parameters", {}),
        default_parameters={"temperature": 0.1},
    )
    if stream:
        kwargs["stream_options"] = {"include_usage": True}
    return kwargs'''
if old_kwargs in content:
    content = content.replace(old_kwargs, new_kwargs, 1)
    changes += 1
    print("1. _build_completion_kwargs: added stream_options")
else:
    print("1. _build_completion_kwargs: NOT FOUND")

# 3. Add usage tracking after the stream chunk loop
# Find the pattern after the chunk loop where iteration_content is processed
old_after_stream = '''            iteration_content, dsml_tool_calls = extract_dsml_tool_calls(
                iteration_content,'''
new_after_stream = '''            # Track token usage from streaming response
            try:
                from app.services.agent.token_usage import token_usage_tracker as _tt
                _stream_usage = getattr(response, "usage", None)
                if _stream_usage is None:
                    # Check last chunk for usage (litellm puts it there with stream_options)
                    pass
                if _stream_usage:
                    _tt.record(
                        str(item_id),
                        str(handler.model or "unknown"),
                        int(getattr(_stream_usage, "prompt_tokens", 0) or 0),
                        int(getattr(_stream_usage, "completion_tokens", 0) or 0),
                        int(getattr(_stream_usage, "total_tokens", 0) or 0),
                    )
            except Exception:
                pass

            iteration_content, dsml_tool_calls = extract_dsml_tool_calls(
                iteration_content,'''
if old_after_stream in content:
    content = content.replace(old_after_stream, new_after_stream, 1)
    changes += 1
    print("2. After stream loop: added token tracking")
else:
    print("2. After stream loop: NOT FOUND")

with open(filepath, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
print(f"\nTotal changes: {changes}")