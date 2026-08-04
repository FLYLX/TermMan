# -*- coding: utf-8 -*-
import requests
BASE = "http://127.0.0.1:28888"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
def dispatch(text):
    payload = {"sender_key": "private_2537134688", "text": text,
        "reply_target": {"target_type":"private","target_id":"2537134688",
            "metadata":{"sender_name":"FLY","sender_id":"2537134688","conversation_type":"private"}}}
    return requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload,
        headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
r = dispatch("帮我跑个后台任务：执行命令 sleep 120 && echo ROUND4_DONE，跑完汇报结果")
print("task:", r.status_code, r.json().get("reason"))
