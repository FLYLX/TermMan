filepath = r"E:\dev\TermMan\dev\TermMan\backend\app\api\routes\chat.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Add usage accumulator before the chunk loop
old_loop_start = '''            iteration_content = ""
            iteration_reasoning = ""
            tool_calls_map: dict[int, dict[str, Any]] = {}

            for chunk in response:'''
new_loop_start = '''            iteration_content = ""
            iteration_reasoning = ""
            tool_calls_map: dict[int, dict[str, Any]] = {}
            _chunk_usage = None

            for chunk in response:'''
if old_loop_start in content:
    content = content.replace(old_loop_start, new_loop_start, 1)
    print("1. Added _chunk_usage accumulator")
else:
    print("1. NOT FOUND")

# Capture usage from chunks (last chunk with stream_options has usage)
old_delta = '''                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                if not delta:
                    continue'''
new_delta = '''                _cu = getattr(chunk, "usage", None)
                if _cu:
                    _chunk_usage = _cu
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                if not delta:
                    continue'''
if old_delta in content:
    content = content.replace(old_delta, new_delta, 1)
    print("2. Added chunk usage capture")
else:
    print("2. NOT FOUND")

# Update the tracking code to use _chunk_usage
old_track = '''            # Track token usage from streaming response
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
                pass'''
new_track = '''            try:
                from app.services.agent.token_usage import token_usage_tracker as _tt
                _su = _chunk_usage or getattr(response, "usage", None)
                if _su:
                    _tt.record(
                        str(item_id),
                        str(handler.model or "unknown"),
                        int(getattr(_su, "prompt_tokens", 0) or 0),
                        int(getattr(_su, "completion_tokens", 0) or 0),
                        int(getattr(_su, "total_tokens", 0) or 0),
                    )
            except Exception:
                pass'''
if old_track in content:
    content = content.replace(old_track, new_track, 1)
    print("3. Updated tracking to use _chunk_usage")
else:
    print("3. NOT FOUND")

with open(filepath, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)