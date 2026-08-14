import asyncio, json, time, traceback
try:
    import websockets
except ImportError:
    import subprocess, sys
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'websockets', '-q'])
    import websockets

LOG = r'E:\dev\TermPaws\dev\TermPaws\de_bug\_mock_qq.log'
WS_URL = 'ws://127.0.0.1:33333/onebot/v11/ws'
HEADERS = {'X-Self-ID': '10001', 'X-Client-Role': 'Universal', 'Authorization': 'Bearer x0SA-6tPi_ZbWciyKDr7F6e_arctgnMbRRWsK-lwQBs'}

def log(msg):
    with open(LOG, 'a', encoding='utf-8', errors='replace') as f:
        f.write(f'[{time.strftime("%H:%M:%S")}] {msg}\n')

async def run():
    while True:
        try:
            async with websockets.connect(WS_URL, additional_headers=HEADERS, ping_interval=20, ping_timeout=10) as ws:
                log('CONNECTED')
                async for raw in ws:
                    data = json.loads(raw)
                    action = data.get('action', '')
                    echo = data.get('echo', '')
                    if 'send' in action:
                        params = data.get('params', {})
                        msg = str(params.get('message', ''))[:300]
                        target = params.get('group_id') or params.get('user_id') or '?'
                        log(f'QQ [{action}] -> {target}: {msg}')
                        await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {'message_id': int(time.time())}, 'echo': echo}))
                    else:
                        log(f'[{action}]')
        except Exception as e:
            log(f'DISCONNECTED: {e}, reconnecting in 3s...')
            await asyncio.sleep(3)

# Clear old log
with open(LOG, 'w') as f:
    f.write('')

asyncio.run(run())