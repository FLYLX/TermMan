filepath = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\session.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Add debug at the start of _process_chat_input
old = '''    def _process_chat_input(self, input_msg: InputMessage, agent: Agent):
        if input_msg.callback:
            self.add_output_callback(input_msg.callback)'''
new = '''    def _process_chat_input(self, input_msg: InputMessage, agent: Agent):
        with open("/tmp/token_debug.log", "a") as _tdf:
            _tdf.write(f"_process_chat_input called\\n")
        if input_msg.callback:
            self.add_output_callback(input_msg.callback)'''
if old in content:
    content = content.replace(old, new, 1)
    print("1. _process_chat_input entry: patched")
else:
    print("1. NOT FOUND")

# Also add debug right before _call_llm call in _process_chat_input
old2 = '''                response = self._call_llm(agent, messages, tools=tools)
                message = self._normalize_dsml_tool_message(
                    response.choices[0].message,
                    tools,
                )

                if not (hasattr(message, "tool_calls") and message.tool_calls):
                    if message.content:
                        final_content = strip_think_tags(guard_fabricated_tool_trace(message.content))
                        self.emit_output(
                            append_tool_call_footer(
                                final_content,
                                turn_guard.tool_names,
                            ),
                            "agent_response",
                        )
                    break'''
new2 = '''                with open("/tmp/token_debug.log", "a") as _tdf:
                    _tdf.write(f"about to call _call_llm\\n")
                response = self._call_llm(agent, messages, tools=tools)
                with open("/tmp/token_debug.log", "a") as _tdf:
                    _tdf.write(f"_call_llm returned\\n")
                message = self._normalize_dsml_tool_message(
                    response.choices[0].message,
                    tools,
                )

                if not (hasattr(message, "tool_calls") and message.tool_calls):
                    if message.content:
                        final_content = strip_think_tags(guard_fabricated_tool_trace(message.content))
                        self.emit_output(
                            append_tool_call_footer(
                                final_content,
                                turn_guard.tool_names,
                            ),
                            "agent_response",
                        )
                    break'''
if old2 in content:
    content = content.replace(old2, new2, 1)
    print("2. _call_llm call site: patched")
else:
    print("2. NOT FOUND")

with open(filepath, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)