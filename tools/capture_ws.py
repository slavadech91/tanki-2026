"""Record WebSocket frames of the Tanki tab via CDP into a JSONL file (user-consented capture).

Each line: {"t": seconds, "ev": "created"|"handshake"|"sent"|"recv"|"closed"|"error", "id": requestId, ...}
Binary frames (opcode 2) keep payload as base64 in "b64"; text frames in "text".

usage: python -I capture_ws.py <out.jsonl>     (runs until Ctrl+C or the process is stopped)
"""
import asyncio, json, sys, time, urllib.request
import websockets

OUT = sys.argv[1]
EVENTS = {
    'Network.webSocketCreated': 'created',
    'Network.webSocketHandshakeResponseReceived': 'handshake',
    'Network.webSocketFrameSent': 'sent',
    'Network.webSocketFrameReceived': 'recv',
    'Network.webSocketClosed': 'closed',
    'Network.webSocketFrameError': 'error',
}
counts = {'sent': 0, 'recv': 0, 'created': 0}


def find_tab():
    tabs = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list'))
    return next(t for t in tabs if t['type'] == 'page' and 'tankionline.com' in t['url'])


def record(p, ev):
    rec = {'t': round(time.time(), 4), 'ev': ev, 'id': p.get('requestId')}
    if ev == 'created':
        rec['url'] = p.get('url')
    elif ev == 'handshake':
        rec['status'] = p.get('response', {}).get('status')
    elif ev in ('sent', 'recv'):
        r = p['response']
        rec['op'] = r['opcode']
        rec['b64' if r['opcode'] == 2 else 'text'] = r['payloadData']
    elif ev == 'error':
        rec['msg'] = p.get('errorMessage')
    return rec


async def session(out):
    tab = find_tab()
    async with websockets.connect(tab['webSocketDebuggerUrl'], max_size=None) as ws:
        await ws.send(json.dumps({'id': 1, 'method': 'Network.enable'}))
        print('connected to', tab['url'], flush=True)
        last = 0
        while True:
            if time.time() - last > 15:
                print('[%s] sockets %d, sent %d, recv %d' % (time.strftime('%H:%M:%S'), counts['created'],
                                                            counts['sent'], counts['recv']), flush=True)
                last = time.time()
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            except asyncio.TimeoutError:
                continue
            ev = EVENTS.get(msg.get('method'))
            if ev:
                if ev in counts:
                    counts[ev] += 1
                out.write(json.dumps(record(msg['params'], ev)) + '\n')
                out.flush()


async def main():
    with open(OUT, 'a', encoding='utf-8') as out:
        while True:
            try:
                await session(out)
            except Exception as e:
                print('reconnecting:', type(e).__name__, e, flush=True)
                await asyncio.sleep(2)


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
