"""Passive recorder: lists resource URLs the Tanki page loads (no WebSocket frames, no cookies)
and downloads each new one right away.

usage: python -I record_cdp.py <urls_file> <out_dir> [seconds]   (no seconds = until Ctrl+C)
"""
import asyncio, json, os, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from download_urls import get

URLS, OUT = sys.argv[1], sys.argv[2]
END = time.time() + int(sys.argv[3]) if len(sys.argv) > 3 else float('inf')
SKIP = ('/static/', 'config.xml', 'status.js', '/api/')

seen = set()
try:
    with open(URLS, encoding='utf-8') as fh:
        seen = {l.strip() for l in fh if l.strip()}
except FileNotFoundError:
    pass
pool = ThreadPoolExecutor(8)
stats = {'new': 0, 'ok': 0, 'fail': 0}


def keep(url):
    u = urllib.parse.urlsplit(url)
    return (u.scheme == 'https' and u.hostname and u.hostname.endswith('.tankionline.com')
            and not u.hostname.startswith(('sentry.', 'billing.')) and not any(s in url for s in SKIP))


def done(fut):
    r = fut.result()
    if r == 'ok':
        stats['ok'] += 1
    elif r.startswith('FAIL'):
        stats['fail'] += 1
        print(r, flush=True)


def add(url, out):
    if keep(url) and url not in seen:
        seen.add(url)
        out.write(url + '\n')
        out.flush()
        stats['new'] += 1
        pool.submit(get, url, OUT).add_done_callback(done)


def find_tab():
    tabs = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list'))
    return next(t for t in tabs if t['type'] == 'page' and 'tankionline.com' in t['url'])


async def session(out):
    tab = find_tab()
    async with websockets.connect(tab['webSocketDebuggerUrl'], max_size=None) as ws:
        await ws.send(json.dumps({'id': 1, 'method': 'Network.enable'}))
        await ws.send(json.dumps({'id': 2, 'method': 'Runtime.evaluate', 'params': {
            'expression': "JSON.stringify(performance.getEntriesByType('resource').map(r=>r.name))",
            'returnByValue': True}}))
        print('connected to', tab['url'], flush=True)
        last = 0
        while time.time() < END:
            if time.time() - last > 30:
                print('[%s] urls %d, new %d, downloaded %d, failed %d'
                      % (time.strftime('%H:%M:%S'), len(seen), stats['new'], stats['ok'], stats['fail']), flush=True)
                last = time.time()
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            except asyncio.TimeoutError:
                continue
            if msg.get('id') == 2:
                for u in json.loads(msg['result']['result']['value']):
                    add(u, out)
            elif msg.get('method') == 'Network.requestWillBeSent':
                add(msg['params']['request']['url'], out)


async def main():
    with open(URLS, 'a', encoding='utf-8') as out:
        while time.time() < END:
            try:
                await session(out)
            except Exception as e:
                # tab reloaded or Brave not ready yet: reconnect
                print('reconnecting:', type(e).__name__, e, flush=True)
                await asyncio.sleep(3)


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
pool.shutdown(wait=True)
print('stopped. urls %d, new %d, downloaded %d, failed %d'
      % (len(seen), stats['new'], stats['ok'], stats['fail']))
