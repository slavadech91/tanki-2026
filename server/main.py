"""Local Tanki Online HTML5 server. First milestone: registration -> tank builder -> tutorial battle, driving.

HTTP (default :8100): play page, client bundle, config.xml, resources (web.py; downloaded once from the official
CDN into cache/)
WebSocket (default :9100): the control socket (HashRequest -> HashResponse without encryption, OpenSpace) and
one socket per space (spaces.py). Accounts: server/data/accounts.json.

usage: python main.py [http_port] [ws_port]
"""
import asyncio, os, sys, time

from aiohttp import web, WSMsgType

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import protocol  # noqa: E402
import spaces  # noqa: E402
import web as pages  # noqa: E402
from accounts import Accounts  # noqa: E402

HTTP_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8100
WS_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9100
ACCOUNTS = Accounts()
SESSIONS = {}   # session hash -> Session


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


class Session:
    """One client: the control socket plus the spaces it opened."""

    def __init__(self, main_ws):
        self.hash = os.urandom(32)
        self.main = main_ws
        self.accounts = ACCOUNTS
        self.user = None
        self.spaces = {}            # space id -> Space
        self.battle_ready = False
        self.tasks = set()

    @property
    def uid(self):
        return self.user['uid'] if self.user else None

    def log(self, *a):
        log('[%s]' % (self.uid or self.hash.hex()[:8]), *a)

    def later(self, delay, coro_fn):
        async def run():
            await asyncio.sleep(delay)
            await coro_fn()
        task = asyncio.create_task(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def open_spaces(self, *ids):
        if not self.main.closed:
            await self.main.send_bytes(protocol.open_space(*ids))
            self.log('<- OpenSpace', ' '.join(ids))

    async def attach(self, space_id, ws):
        cls = spaces.SPACES.get(space_id)
        if cls is None:
            self.log('unknown space', space_id)
            return None
        space = self.spaces[space_id] = cls(self, ws)
        self.log('space connected:', space.name)
        await space.on_open()
        return space

    async def enter_tutorial(self):
        """After the tank builder: system, lobby, shop and the tutorial battle, spaced as in the capture."""
        await self.open_spaces(spaces.SYSTEM)
        await asyncio.sleep(1)
        await self.open_spaces(spaces.LOBBY)
        await asyncio.sleep(1)
        await self.open_spaces(spaces.SHOP, spaces.TUTORIAL)

    async def battle_loaded(self):
        self.battle_ready = True
        lobby = self.spaces.get(spaces.LOBBY)
        if lobby is not None and lobby.began:
            await lobby.end_battle_switch()


async def ws_handler(request):
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(request)
    buf, session, space = b'', None, None

    async def pinger():
        while not ws.closed:
            await asyncio.sleep(10)
            if not ws.closed:
                await ws.send_bytes(protocol.PING)

    ping_task = asyncio.create_task(pinger())
    try:
        async for msg in ws:
            if msg.type != WSMsgType.BINARY:
                continue
            payloads, buf = protocol.split(buf + msg.data)
            for p in payloads:
                if space is not None:
                    await space.handle(p)
                    continue
                body = protocol.control_body(p)
                if not body:
                    continue
                if body[0] == protocol.HASH_REQUEST and session is None:
                    session = Session(ws)
                    SESSIONS[session.hash] = session
                    await ws.send_bytes(protocol.hash_response(session.hash))
                    session.log('HashRequest from', request.remote)
                    await session.open_spaces(spaces.ENTRANCE)
                elif body[0] == protocol.OPEN_SPACE_CONNECT and session is None:
                    h, space_id = protocol.parse_open_space_connect(body)
                    owner = SESSIONS.get(h)
                    space = await owner.attach(space_id, ws) if owner else None
                    if space is None:
                        log('OpenSpaceConnect to %s without a session or space: closing' % space_id)
                        await ws.close()
                elif body[0] == protocol.CLIENT_LOG and session is not None:
                    session.log('ClientLog', ' '.join(protocol.client_log(body))[:150])
                else:
                    log('unexpected control packet', body[:40].hex())
    finally:
        ping_task.cancel()
        if space is not None:
            space.on_close()
            space.session.log('space closed:', space.name)
        if session is not None:
            for t in session.tasks:
                t.cancel()
            SESSIONS.pop(session.hash, None)
            session.log('control socket closed')
    return ws


async def main():
    wsapp = web.Application()
    wsapp.add_routes([web.get('/', ws_handler), web.get('/{tail:.*}', ws_handler)])
    for app, port in ((pages.make_app(WS_PORT, log), HTTP_PORT), (wsapp, WS_PORT)):
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, '127.0.0.1', port).start()
    log('accounts: %d; cache: %s' % (len(ACCOUNTS.users), pages.CACHE))
    log('open http://127.0.0.1:%d/play/' % HTTP_PORT)
    await asyncio.Event().wait()


asyncio.run(main())
