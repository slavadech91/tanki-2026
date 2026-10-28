"""Local Tanki Online HTML5 client host + replay server (no game logic: replays a recorded session).

HTTP (default :8090)
  /play/            local copy of the play page (CSP removed, bundle served locally)
  /static/...       tanki-src/static (bundle + UI files)
  /config.xml       points the client at ws://127.0.0.1:<ws_port>/
  /resources/...    tanki-assets/files; missing files are fetched once from s.eu.tankionline.com and cached
WebSocket (default :9096)
  Answers HashRequest itself (encryption flag 0), then replays the recorded server packets of one session.
  Recorded client packets (minus analytics) form a progress line; each recorded server packet waits until the
  live client has progressed past the client packet that preceded it, so the replay follows the client
  instead of a clock and tolerates a few skipped or extra client calls. Recorded pauses (up to MAX_GAP) and
  socket closes (from the raw <name>.jsonl next to <name>.packets.jsonl) are replayed too.

The client picks resources/config from its own origin when not on tankionline.com (bundle @1134473).

--regen: every server packet of a space is decoded with server-notes/proto_schema.json and encoded again
(proto_codec.py) instead of sending the recorded bytes; --patch=<file.json> edits the decoded data first:
  [{"model": "<model id>", "field": "<CC field>", "value": ...}, {"replace": "<text>", "with": "<text>"}]

usage: python -I replay_server.py <packets.jsonl> <socket ids comma-separated> [http_port] [ws_port]
                                  [--regen] [--patch=<file.json>]
"""
import asyncio, collections, json, os, struct, sys, time, urllib.parse, urllib.request

from aiohttp import web, WSMsgType

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'tanki-src')
FILES = os.path.join(ROOT, 'tanki-assets', 'files')
CDN = 'https://s.eu.tankionline.com/'

FLAGS = [a for a in sys.argv[1:] if a.startswith('--')]
ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
PACKETS, SOCKS = ARGS[0], ARGS[1].split(',')
HTTP_PORT = int(ARGS[2]) if len(ARGS) > 2 else 8090
WS_PORT = int(ARGS[3]) if len(ARGS) > 3 else 9096
REGEN = '--regen' in FLAGS or any(f.startswith('--patch=') for f in FLAGS)
PATCH = next((json.load(open(f[8:], encoding='utf-8')) for f in FLAGS if f.startswith('--patch=')), [])
SCHEMA = None
if REGEN:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from proto_codec import Schema
    SCHEMA = Schema(os.path.join(ROOT, 'server-notes', 'proto_schema.json'))
CTRL_CLIENT_LOG = 32
# client methods that only report UI events (count depends on clicks): never gate on them
LOG_METHODS = {'25589c81fefa4670'}
MAX_GAP = 3.0   # seconds: longest recorded pause kept between a trigger and the server packet
PING = bytes([0x00, 0x01, 0x00])  # empty packet: header len 1 + empty null map

def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ---------------------------------------------------------------- packets
def pack(nullmap_hex, body_hex):
    payload = bytes.fromhex(nullmap_hex) + bytes.fromhex(body_hex)
    n = len(payload)
    if n < 16384:
        return bytes([n >> 8, n & 0xFF]) + payload
    return bytes([0x80 | (n >> 24) & 0x3F, n >> 16 & 0xFF, n >> 8 & 0xFF, n & 0xFF]) + payload


def pack_payload(payload):
    n = len(payload)
    if n < 16384:
        return bytes([n >> 8, n & 0xFF]) + payload
    return bytes([0x80 | (n >> 24) & 0x3F, n >> 16 & 0xFF, n >> 8 & 0xFF, n & 0xFF]) + payload


def apply_patch(cmds):
    """Edit decoded commands in place; returns the number of changed values."""
    changed = 0

    def repl(v):
        nonlocal changed
        if isinstance(v, str):
            for rule in PATCH:
                if 'replace' in rule and rule['replace'] in v:
                    v = v.replace(rule['replace'], rule['with'])
                    changed += 1
            return v
        if isinstance(v, list):
            return [repl(x) for x in v]
        if isinstance(v, dict):
            return {k: repl(x) for k, x in v.items()}
        return v

    for c in cmds:
        c['args'] = repl(c['args'])
        if c['name'] != 'loadObjectsData':
            continue
        for entry in c['args'][0]['modelsData']:
            for rule in PATCH:
                if 'model' in rule and rule['model'] == entry.get('model') and rule['field'] in entry['data']:
                    entry['data'][rule['field']] = rule['value']
                    changed += 1
    return changed


def regenerate(nullmap_hex, body_hex, aliases):
    """Recorded server packet -> decoded commands -> (patched) -> freshly encoded packet."""
    cmds, _ = SCHEMA.decode_packet(bytes.fromhex(nullmap_hex + body_hex), 'in', aliases)
    n = apply_patch(cmds)
    REGEN_STATS['packets'] += 1
    REGEN_STATS['patched values'] += n
    return pack_payload(SCHEMA.encode_packet(cmds, 'in'))


REGEN_STATS = collections.Counter()


def split(buf):
    out, pos = [], 0
    while pos + 2 <= len(buf):
        b0 = buf[pos]
        if b0 & 0x80:
            if pos + 4 > len(buf):
                break
            ln, hl = ((b0 ^ 0x80) & 0x3F) << 24 | buf[pos + 1] << 16 | buf[pos + 2] << 8 | buf[pos + 3], 4
        else:
            ln, hl = (b0 & 63) << 8 | buf[pos + 1], 2
        if pos + hl + ln > len(buf):
            break
        out.append(buf[pos + hl:pos + hl + ln])
        pos += hl + ln
    return out, buf[pos:]


def null_map_len(p):
    r = p[0]
    if r & 0x80:
        return 3 + ((r & 63) << 16 | p[1] << 8 | p[2]) if r & 0x40 else 1 + (r & 63)
    return 1 + ((r & 0x60) >> 5)


def key_of(space, body):
    """What identifies a client packet for gating: control command, or first method id in a space."""
    if not body:
        return None
    if space is None:
        return ('ctrl', body[0])
    return (space, body[8:16].hex()) if len(body) >= 16 else (space, 'short')


# ---------------------------------------------------------------- script from the recording
def build_script():
    pk = [json.loads(l) for l in open(PACKETS, encoding='utf-8')]
    pk = [p for p in pk if p['sock'] in SOCKS]
    # socket closes are only in the raw capture; closing the entrance space is what moves the client from the
    # login form to System.Loader, and endLayoutSwitch only opens the lobby from System.Loader
    raw = PACKETS.replace('.packets.jsonl', '.jsonl')
    if raw != PACKETS and os.path.isfile(raw):
        for line in open(raw, encoding='utf-8'):
            d = json.loads(line)
            if d['ev'] == 'closed' and d['id'] in SOCKS:
                pk.append({'t': d['t'], 'sock': d['id'], 'dir': 'x', 'space': None, 'body': '', 'nullmap': ''})
        pk.sort(key=lambda p: p['t'])
    # socket -> space as known at the end; control packets of a space socket belong to that socket
    sock_space = {}
    for p in pk:
        if p['space']:
            sock_space[p['sock']] = p['space']
    main_socks = [s for s in SOCKS if s not in sock_space]
    script, last, tlast = [], -1, collections.defaultdict(lambda: -1)
    t_event, t_sent = 0.0, collections.defaultdict(float)
    aliases = collections.defaultdict(dict)
    for p in pk:
        body = bytes.fromhex(p['body'])
        space = p['space']
        if p['dir'] == 'x':
            if p['sock'] in sock_space:
                target = sock_space[p['sock']]
                script.append({'target': target, 'trigger': last, 'ttrigger': tlast[target], 'delay': 0.0,
                               'close': True, 'data': b'', 'what': 'close'})
            continue
        if p['dir'] == '>':
            k = key_of(space, body)
            if k == ('ctrl', 3):
                k = (sock_space.get(p['sock']), 'connect')  # sockets open in parallel: gate per space
            if k is None or k == ('ctrl', CTRL_CLIENT_LOG) or k[1] in LOG_METHODS:
                continue  # analytics, depends on clicks
            EVENTS.append(k)
            last = len(EVENTS) - 1
            t_event = p['t']
            t = 'main' if p['sock'] in main_socks else sock_space.get(p['sock'])
            TEVENTS[t].append(k)
            tlast[t] = len(TEVENTS[t]) - 1
        else:
            if not body:
                continue  # pings: sent by our own timer
            if space is None and body[0] == 2 and p['sock'] in main_socks:
                continue  # HashResponse: we answer it ourselves
            target = sock_space.get(p['sock']) if p['sock'] not in main_socks else 'main'
            if space is None and p['sock'] not in main_socks:
                continue  # control packets on space sockets before open (none expected)
            # keep the recorded pause after the trigger (or the previous packet of this socket): the client
            # handles some packets asynchronously, e.g. endLayoutSwitch must not overtake the lobby objects
            delay = min(MAX_GAP, max(0.0, p['t'] - max(t_event, t_sent[target]))) if t_event else 0.0
            t_sent[target] = p['t']
            data = pack(p['nullmap'], p['body'])
            if REGEN and space is not None:
                data = regenerate(p['nullmap'], p['body'], aliases[target])
            script.append({'target': target, 'trigger': last, 'ttrigger': tlast[target], 'delay': delay,
                           'data': data,
                           'what': body[:1].hex() if space is None else body[8:16].hex()[-6:]})
    return script


EVENTS = []   # recorded client events (keys) in order; server packets point at the index they followed
TEVENTS = collections.defaultdict(list)   # the same, per target socket ('main' or spaceId)
SCRIPT = build_script()
MATCH_WINDOW = 40
METHODS = {}
try:
    ids = json.load(open(os.path.join(ROOT, 'server-notes', 'proto_ids.json'), encoding='utf-8'))
    METHODS = {k[-6:]: (v.get('name') or k[-6:]) for k, v in ids['methods'].items()}
except OSError:
    pass


class Replay:
    """Live client events advance `progress` along the recorded event list: an event jumps to its nearest
    recorded occurrence ahead (skipped recorded events don't block, unknown live events are ignored).
    The same is tracked per socket, and a packet needs both: global order (e.g. lobby spaces only after login)
    and its own socket's order (e.g. objects only after that space acked its resources)."""

    def __init__(self):
        self.counts = collections.Counter()
        self.progress = -1
        self.tprogress = collections.defaultdict(lambda: -1)
        self.sockets = {}          # target -> ws
        self.queues = collections.defaultdict(collections.deque)
        for i, s in enumerate(SCRIPT):
            self.queues[s['target']].append(i)
        self.lock = asyncio.Lock()
        self.armed = {}            # script index -> monotonic time it became ready

    @staticmethod
    def advance(events, pos, k):
        for j in range(pos + 1, min(len(events), pos + 1 + MATCH_WINDOW)):
            if events[j] == k:
                return j
        return None

    def event(self, k, target):
        self.counts[k] += 1
        j = self.advance(TEVENTS[target], self.tprogress[target], k)
        if j is not None:
            self.tprogress[target] = j
        g = self.advance(EVENTS, self.progress, k)
        if g is not None:
            self.progress = g
        return g is not None or j is not None

    def ready(self, item):
        if item['trigger'] is None:
            return True
        return item['trigger'] <= self.progress and item['ttrigger'] <= self.tprogress[item['target']]

    async def pump(self):
        async with self.lock:
            for target, q in self.queues.items():
                ws = self.sockets.get(target)
                if ws is None or ws.closed:
                    continue
                while q and self.ready(SCRIPT[q[0]]):
                    item, now = SCRIPT[q[0]], time.monotonic()
                    armed = self.armed.setdefault(q[0], now)
                    if now < armed + item['delay']:
                        asyncio.get_running_loop().call_later(armed + item['delay'] - now + 0.01,
                                                              lambda: asyncio.ensure_future(self.pump()))
                        break
                    q.popleft()
                    if item.get('close'):
                        log('  x ', target, 'closed as recorded')
                        await ws.close()
                        break
                    await ws.send_bytes(item['data'])
                    log('  <-', target, METHODS.get(item['what'], item['what']), len(item['data']), 'B')

    def waiting(self):
        out = ['progress %d of %d recorded client events' % (self.progress, len(EVENTS))]
        for target, q in self.queues.items():
            if q:
                t = SCRIPT[q[0]]['trigger']
                if t is None:
                    out.append('%s released, %d left' % (target, len(q)))
                    continue
                tt = SCRIPT[q[0]]['ttrigger']
                out.append('%s waits for global event %d %s (at %d) and own event %d %s (at %d), %d left'
                           % (target, t, EVENTS[t] if t >= 0 else '-', self.progress, tt,
                              TEVENTS[target][tt] if tt >= 0 else '-', self.tprogress[target], len(q)))
        return out


REPLAY = Replay()


async def ws_handler(request):
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(request)
    buf, target = b'', None
    log('ws connect', request.remote)

    async def pinger():
        while not ws.closed:
            await asyncio.sleep(10)
            if not ws.closed:
                await ws.send_bytes(PING)

    ping_task = asyncio.create_task(pinger())
    try:
        async for msg in ws:
            if msg.type != WSMsgType.BINARY:
                continue
            packets, buf = split(buf + msg.data)
            for p in packets:
                body = p[null_map_len(p):] if p else b''
                if target is None and body[:1] == b'\x01':      # HashRequest on the main socket
                    target = 'main'
                    REPLAY.sockets['main'] = ws
                    REPLAY.event(('ctrl', 1), 'main')
                    hash32 = os.urandom(32)
                    await ws.send_bytes(pack('00', '02' + hash32.hex() + '00'))   # flag 0: no encryption
                    log('-> HashRequest, sent HashResponse (no cipher)')
                elif target is None and body[:1] == b'\x03':    # OpenSpaceConnect(hash, spaceId)
                    target = '%016x' % struct.unpack_from('>Q', body, 33)[0]
                    REPLAY.sockets[target] = ws
                    REPLAY.event((target, 'connect'), target)
                    log('-> OpenSpaceConnect', target)
                else:
                    space = None if target == 'main' else target
                    k = key_of(space, body)
                    if k == ('ctrl', CTRL_CLIENT_LOG):
                        log('-> ClientLog', ''.join(chr(c) if 32 <= c < 127 else '.' for c in body[1:])[:120])
                    if k and k != ('ctrl', CTRL_CLIENT_LOG) and k[1] not in LOG_METHODS:
                        hit = REPLAY.event(k, target)
                        log('->', target, METHODS.get(k[1][-6:], k[1]) if space else 'ctrl %s' % k[1],
                            len(body), 'B', 'progress %d' % REPLAY.progress if hit else '(not in recording)')
                        if not hit:
                            log('   ', body[16:].hex()[:80], ''.join(chr(c) if 32 <= c < 127 else '.' for c in body[16:])[:400])
                await REPLAY.pump()
    finally:
        ping_task.cancel()
        log('ws closed', target)
    return ws


# ---------------------------------------------------------------- HTTP
def play_page():
    html = open(os.path.join(SRC, 'play', 'index.html'), encoding='utf-8').read()
    a = html.find('<meta http-equiv="Content-Security-Policy"')
    if a != -1:
        html = html[:a] + html[html.find('>', a) + 1:]
    # the recording has a password login only: drop the saved "remember me" hash so the client never tries hash login
    reset = ("<script>try{localStorage.removeItem('entrance_hash_key');localStorage.removeItem('name-userHash')}"
             "catch(e){}</script>")
    # embedded/automated browsers deny the screen wake lock; the client then rejects an awaited promise
    reset += ("<script>try{if(navigator.wakeLock)navigator.wakeLock.request=function(){var s=new EventTarget();"
              "s.released=false;s.type='screen';s.release=function(){s.released=true;return Promise.resolve()};"
              "return Promise.resolve(s)}}catch(e){}</script>")
    # keep error reports and analytics local: Sentry events land in window.__sentry and the console
    reset += ("<script>(function(){window.__sentry=[];var ext=/sentry\\.|mc\\.yandex|google-analytics|googletagmanager/;"
              "function keep(u,b){if(/sentry\\./.test(u)){window.__sentry.push(b);console.warn('[sentry]',String(b).slice(0,3000))}}"
              "var f=window.fetch;window.fetch=function(u,o){var s=String(u&&u.url||u);if(ext.test(s)){keep(s,o&&o.body);"
              "return Promise.resolve(new Response('{}'))}return f.apply(this,arguments)};"
              "var op=XMLHttpRequest.prototype.open,sd=XMLHttpRequest.prototype.send;"
              "XMLHttpRequest.prototype.open=function(m,u){this.__u=String(u);return op.apply(this,arguments)};"
              "XMLHttpRequest.prototype.send=function(b){if(ext.test(this.__u||'')){keep(this.__u,b);return}return sd.apply(this,arguments)};"
              "if(navigator.sendBeacon){var sb=navigator.sendBeacon.bind(navigator);navigator.sendBeacon=function(u,b){"
              "if(ext.test(String(u))){keep(String(u),b);return true}return sb(u,b)}}})()</script>")
    html = html.replace('<head>', '<head>' + reset, 1)
    return html.replace('https://s.eu.tankionline.com/static/js/main.289a5d50.js', '/static/js/main.289a5d50.js')


async def play(request):
    return web.Response(text=play_page(), content_type='text/html')


async def config(request):
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cfg xmlns="http://alternativaplatform.com/core/config.xsd">'
           '<server address="127.0.0.1" version="local" mode="simple" wsProtocol="WS"><ports/>'
           '<webSocketPorts><port>%d</port></webSocketPorts></server><status>normal</status></cfg>' % WS_PORT)
    return web.Response(text=xml, content_type='application/xml')


async def static(request):
    rel = request.match_info['path']
    path = os.path.join(SRC, 'static', *rel.split('/'))
    if rel == 'js/main.289a5d50.js':
        path = os.path.join(SRC, 'main.289a5d50.js')
    if not os.path.isfile(path):
        raise web.HTTPNotFound()
    return web.FileResponse(path)


async def resources(request):
    rel = request.match_info['path'].split('?')[0]
    # some resource names contain spaces; download_urls.py stored them with the URL-encoded name (bg1%201024.webp)
    raw = request.raw_path.split('?')[0][len('/resources/'):]
    path = os.path.join(FILES, *raw.split('/'))
    if not os.path.isfile(path):
        path = os.path.join(FILES, *rel.split('/'))
    if not os.path.isfile(path):
        url = CDN + urllib.parse.quote(rel, safe='/')
        path = os.path.join(FILES, *raw.split('/'))
        try:
            data = await asyncio.to_thread(lambda: urllib.request.urlopen(url, timeout=30).read())
        except Exception as e:
            log('resource miss', rel, e)
            raise web.HTTPNotFound()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'wb').write(data)
        log('resource fetched', rel)
    return web.FileResponse(path, headers={'Access-Control-Allow-Origin': '*'})


async def status(request):
    return web.json_response({'waiting': REPLAY.waiting(), 'counts': {str(k): v for k, v in REPLAY.counts.items()},
                              'events': [str(e) for e in EVENTS]})


async def release(request):
    """Manual escape hatch: drop the trigger of the next waiting packet of every queue."""
    for q in REPLAY.queues.values():
        if q:
            SCRIPT[q[0]]['trigger'] = None
    await REPLAY.pump()
    return web.json_response({'waiting': REPLAY.waiting()})


async def main():
    http = web.Application()
    http.add_routes([web.get('/play/', play), web.get('/play', play), web.get('/config.xml', config),
                     web.get('/static/{path:.*}', static), web.get('/resources/{path:.*}', resources),
                     web.get('/replay/status', status), web.get('/replay/release', release)])
    wsapp = web.Application()
    wsapp.add_routes([web.get('/', ws_handler), web.get('/{tail:.*}', ws_handler)])
    for app, port in ((http, HTTP_PORT), (wsapp, WS_PORT)):
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, '127.0.0.1', port).start()
    log('script: %d server packets for %s' % (len(SCRIPT), sorted(REPLAY.queues)))
    if REGEN:
        log('regenerated from the schema: %s' % dict(REGEN_STATS))
    log('open http://127.0.0.1:%d/play/  (status: /replay/status, unblock: /replay/release)' % HTTP_PORT)
    await asyncio.Event().wait()


asyncio.run(main())
