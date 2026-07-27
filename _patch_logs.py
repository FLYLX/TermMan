path = '/app/backend/app/services/socket_pool/agent_bridge.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Change the source=job skip log from DEBUG to INFO
content = content.replace(
    'logger.debug("[AgentInputBridge] Skipping daemon job stream for item %s", item_uuid)',
    'logger.info("[AgentInputBridge] Skipping daemon job stream for item %s", item_uuid)'
)

# Change the "no handler" log from DEBUG to INFO
content = content.replace(
    'logger.debug("[AgentInputBridge] No handler found for item %s", item_uuid)',
    'logger.info("[AgentInputBridge] No handler found for item %s", item_uuid)'
)

# Change the "processed stream" log from DEBUG to INFO
content = content.replace(
    '''logger.debug(
                "[AgentInputBridge] Processed stream for item=%s, handler=%s, output_len=%s",
                item_uuid,
                handler_id,
                len(filtered_output),
            )''',
    '''logger.info(
                "[AgentInputBridge] Processed stream for item=%s, handler=%s, filtered_len=%s, raw_len=%s",
                item_uuid,
                handler_id,
                len(filtered_output),
                len(raw_output),
            )'''
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("OK: agent_bridge logs -> INFO")

# Also make stream_manager process_stream log INFO
path2 = '/app/backend/app/services/agent/stream_manager.py'
with open(path2, 'r', encoding='utf-8') as f:
    content2 = f.read()

content2 = content2.replace(
    '''logger.debug(
            f"[StreamManager] process_stream: item={item_id}, handler={handler_id}, "
            f"output_len={len(filtered_output) if filtered_output else 0}"
        )''',
    '''logger.info(
            f"[StreamManager] process_stream: item={item_id}, handler={handler_id}, "
            f"filtered_len={len(filtered_output) if filtered_output else 0}, "
            f"raw_len={len(raw_output) if raw_output else 0}"
        )'''
)

# Also make the "No usable output" log INFO
content2 = content2.replace(
    'logger.debug("[StreamManager] No usable output for agent processing, skipping")',
    'logger.info("[StreamManager] No usable output for agent processing, skipping: item=%s", item_id)'
)

with open(path2, 'w', encoding='utf-8') as f:
    f.write(content2)
print("OK: stream_manager logs -> INFO")
print("DONE")
