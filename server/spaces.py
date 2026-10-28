"""Spaces of the local server: entrance (registration, tank builder), system, lobby, shop, tutorial battle.

Every space has its own socket. Packets come from server/templates (tools/make_templates.py cuts them out of
the capture) and are adjusted to the session before sending; the order follows the capture
(server-notes/registration-to-tutorial.md). Methods without a name in the schema are named after the last
6 hex digits of their id, as in the notes.
"""
import asyncio, copy, json, os, re, time

import protocol
from proto_codec import unhex64

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
TEMPLATE_UID = '%uid%'          # where the templates had the captured account's nickname (make_templates.py)

ENTRANCE, SYSTEM, LOBBY, SHOP = '0000000005f691cc', '000000d634b693fb', '0000000005f7b228', '0000000005f6fdcf'
TUTORIAL = '2aaaaabafeae733d'   # tutorial battle of the captured account (its user id + 3)

# client -> server
ACK = '19368b1c6aca5814'             # loadDependencies done (callbackId)
UID_CHECK = '1b52d240b122e933'       # 22e933(uid)
PASSWORD_CHECK = '0ffb24c5cd3f6e3e'  # 3f6e3e(password)
REGISTER = '1b52d1e135e1a4b8'        # e1a4b8(uid, password, url, Boolean)
BUILDER_ITEM = '27ada92593df32fd'    # df32fd(itemId): preview of a hull, weapon or paint
OBJECT_LOADED = '2316b154734544a9'   # 4544a9() on every loaded item object
BUILDER_DONE = '5ac6aac49bd74105'    # d74105(hullId, weaponId, paintId)
ENTRANCE_DONE = '314f1e6ce318c358'   # 18c358(): reply to 76be15
SHOP_B6F461 = '75a6ef022cb6f461'     # b6f461(Long) at shop start
ANNOUNCEMENTS = '257761bceccbd6ac'
READY_TO_SPAWN = '7fcee6df23c14baa'  # c14baa()
SPAWN_REQUEST = '1638cf8ee2342bed'   # 342bed(): after the camera flight
SPAWNED = '5609d18bde81c733'         # 81c733(incarnation)
TIME_REPLY = '316c237866d0b2bf'      # d0b2bf(clientTimeMs, serverTimeMs)
STAGE_DONE = '31aa895019411f12'      # 411f12(): tutorial stage done (BattleTutorialCC)
TANK_STATE = '44eb92059fda7def'      # da7def(clientTimeMs, incarnation, TankState): own tank (physics.md)
# reports that need no answer here; not logged
QUIET = {TANK_STATE, '711e4f0028314036', '6852c2c4158e67ff', '51ab830176962b6d', TIME_REPLY,
         '41556c01bff5d967', '25589c81fefa4670', OBJECT_LOADED}
# server -> client
LOAD_DEPENDENCIES, LOAD_OBJECTS_DATA, UNLOAD_OBJECTS = '2ca2091458b7bc93', '6a09fce46efe601a', '7d701d63033cf397'
UID_BUSY, UID_FREE, UID_INVALID = '114edf6488168f19', '114edf648818538c', '3c4ea212dced917b'
PASSWORD_WEAK, PASSWORD_OK = '0a9143251fa8a2c3', '55c42d7ccbbdfcf8'
TIME_SYNC = '313e2d3c89ad6cb1'       # ad6cb1(serverTimeMs, pingMs)

# the official server rejected nicknames ending with "-" or "_" (ed917b); other rules are a guess
VALID_UID = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,18}[A-Za-z0-9])?')


def template(name):
    return json.load(open(os.path.join(TEMPLATES, name + '.json'), encoding='utf-8'))


def cmd(obj, method, *args):
    return {'object': obj, 'method': method, 'args': list(args)}


class Space:
    """One space socket of a session: sends templates, answers client commands through `handlers`."""
    id = name = None
    T = {}

    def __init__(self, session, ws):
        self.session, self.ws = session, ws
        self.handlers = {ACK: self.ack}
        self.callbacks = {}             # loadDependencies callbackId -> coroutine function run on the ack
        self.lock = asyncio.Lock()
        self.tasks = set()

    def adjust(self, value):
        """Template value -> value for this session (the captured nickname becomes the player's)."""
        uid = self.session.uid
        if isinstance(value, str):
            return value.replace(TEMPLATE_UID, uid) if uid else value
        if isinstance(value, list):
            return [self.adjust(v) for v in value]
        if isinstance(value, dict):
            return {k: self.adjust(v) for k, v in value.items()}
        return value

    async def send(self, cmds, quiet=False):
        async with self.lock:
            if self.ws.closed:
                return
            await self.ws.send_bytes(protocol.encode(self.adjust(cmds)))
        if not quiet:
            self.session.log('<-', self.name, ' '.join(protocol.SCHEMA.method_name(c['method']) for c in cmds))

    async def send_loading(self, cmds, then):
        """Send a packet with loadDependencies under a free callbackId; `then` runs when the client acks it."""
        cmds = copy.deepcopy(cmds)
        cid = 1
        while cid in self.callbacks:
            cid += 1
        for c in cmds:
            if c['method'] == LOAD_DEPENDENCIES:
                c['args'][0]['callbackId'] = cid
        self.callbacks[cid] = then
        await self.send(cmds)

    def later(self, delay, coro_fn):
        async def run():
            await asyncio.sleep(delay)
            await coro_fn()
        task = asyncio.create_task(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def ack(self, obj, callback_id):
        then = self.callbacks.pop(callback_id, None)
        if then:
            await then()

    async def handle(self, payload):
        try:
            cmds = protocol.decode(payload)
        except ValueError as e:
            self.session.log('->', self.name, 'undecodable packet (%s): %s' % (e, payload[:48].hex()))
            return
        for c in cmds:
            h = self.handlers.get(c['method'])
            if c['method'] not in QUIET:
                self.session.log('->', self.name, c['name'], json.dumps(c['args'], ensure_ascii=False)[:160],
                                 '' if h else '(no handler)')
            if h:
                await h(c['object'], *c['args'])

    async def on_open(self):
        pass

    def on_close(self):
        for task in self.tasks:
            task.cancel()


class Entrance(Space):
    """Registration and the tank builder (registration-to-tutorial.md, parts 1-2)."""
    id, name = ENTRANCE, 'entrance'
    T = template('entrance')

    def __init__(self, session, ws):
        super().__init__(session, ws)
        self.preview_objects = set()    # item objects to unload once the client reports them loaded
        self.handlers.update({UID_CHECK: self.uid_check, PASSWORD_CHECK: self.password_check,
                              REGISTER: self.register, BUILDER_ITEM: self.builder_item,
                              OBJECT_LOADED: self.object_loaded, BUILDER_DONE: self.builder_done,
                              ENTRANCE_DONE: self.done})

    async def on_open(self):
        await self.send_loading(self.T['open'], lambda: self.send(self.T['objects']))

    async def uid_check(self, obj, uid):
        if self.session.accounts.get(uid):
            await self.send([cmd(ENTRANCE, UID_BUSY, [uid + s for s in ('_1', '_2', '_TO', '_PRO', '_777')])])
        elif not VALID_UID.fullmatch(uid):
            await self.send([cmd(ENTRANCE, UID_INVALID)])
        else:
            await self.send([cmd(ENTRANCE, UID_FREE)])

    async def password_check(self, obj, password):
        await self.send([cmd(ENTRANCE, PASSWORD_OK if len(password) >= 6 else PASSWORD_WEAK)])

    async def register(self, obj, uid, password, url, flag):
        accounts = self.session.accounts
        if accounts.get(uid) is not None:   # the client checks the nickname before; registering never logs in
            self.session.log('register: nickname taken', uid)
            await self.uid_check(obj, uid)
            return
        self.session.user = accounts.create(uid, password)
        self.session.log('registered', uid)
        reply = copy.deepcopy(self.T['register'])   # rememberUsersHash, 706715(userId), setUid, initHangar, buildTank
        for c in reply:
            if c['name'] == 'rememberUsersHash':
                c['args'] = [self.session.user['hash']]
        await self.send(reply)

    async def builder_item(self, obj, item):
        preview = self.T['previews'].get(str(item))
        if preview is None:
            self.session.log('   no preview in the templates for item', item)
            return

        async def loaded():
            self.preview_objects.update(o['id'] for o in preview['data']['objects'])
            await self.send([cmd(ENTRANCE, LOAD_OBJECTS_DATA, preview['data'])])
        await self.send_loading([cmd(ENTRANCE, LOAD_DEPENDENCIES, dict(preview['deps']))], loaded)

    async def object_loaded(self, obj):
        if obj in self.preview_objects:     # the builder keeps its own copy; the server unloads the object
            self.preview_objects.discard(obj)
            await self.send([cmd(ENTRANCE, UNLOAD_OBJECTS, [unhex64(obj)])])

    async def builder_done(self, obj, hull, weapon, paint):
        user = self.session.user
        if user is not None:
            user['tank'] = {'hull': hull, 'weapon': weapon, 'paint': paint}
            self.session.accounts.save()
        await self.send(self.T['complete'])     # 76be15(userId)

    async def done(self, obj):
        # closing the entrance socket moves the client to System.Loader (login-to-lobby.md)
        await self.ws.close()
        self.session.later(0.5, self.session.enter_tutorial)


class System(Space):
    id, name = SYSTEM, 'system'
    T = template('system')

    async def on_open(self):
        await self.send_loading(self.T['open'], lambda: self.send(self.T['objects']))


class Lobby(Space):
    """Lobby layout: shows the battle screen once the battle space is loaded (endLayoutSwitch BATTLE)."""
    id, name = LOBBY, 'lobby'
    T = template('lobby')

    def __init__(self, session, ws):
        super().__init__(session, ws)
        self.began = False

    async def on_open(self):
        await self.send(self.T['open'])
        self.later(0.2, self.begin)

    async def begin(self):
        await self.send(self.T['begin_battle'])
        self.began = True
        if self.session.battle_ready:
            await self.end_battle_switch()

    async def end_battle_switch(self):
        await self.send(self.T['end_battle'])


class Shop(Space):
    id, name = SHOP, 'shop'
    T = template('shop')

    def __init__(self, session, ws):
        super().__init__(session, ws)
        self.handlers.update({SHOP_B6F461: lambda obj, n: self.send(self.T['reply_b6f461']),
                              ANNOUNCEMENTS: lambda obj: self.send(self.T['reply_announcements'])})

    async def on_open(self):
        await self.send_loading(self.T['open'], lambda: self.send(self.T['objects']))


class TutorialBattle(Space):
    """Tutorial battle up to driving (registration-to-tutorial.md, part 4): load, time sync, spawn."""
    id, name = TUTORIAL, 'battle'
    T = template('battle')

    def __init__(self, session, ws):
        super().__init__(session, ws)
        self.t0 = time.monotonic()
        self.incarnation = 0
        self.sync_sent = {}     # serverTimeMs -> monotonic time sent
        self.ping = 0.0
        self.logged_at = (0.0, None)    # (monotonic time, position) of the last logged tank state
        self.handlers.update({READY_TO_SPAWN: self.ready_to_spawn, SPAWN_REQUEST: self.spawn,
                              SPAWNED: self.spawned, TIME_REPLY: self.time_reply, STAGE_DONE: self.stage_done,
                              TANK_STATE: self.tank_state})

    async def on_open(self):
        await self.send_loading(self.T['open'], self.loaded)

    async def loaded(self):
        await self.send(self.T['objects'])
        self.later(0, self.time_sync)
        await self.session.battle_loaded()

    async def time_sync(self):
        while not self.ws.closed:
            now = int((time.monotonic() - self.t0) * 1000)
            self.sync_sent[now] = time.monotonic()
            await self.send([cmd(TUTORIAL, TIME_SYNC, now, self.ping)], quiet=True)
            await asyncio.sleep(2)

    async def time_reply(self, obj, client_ms, server_ms):
        sent = self.sync_sent.pop(server_ms, None)
        if sent is not None:
            self.ping = round((time.monotonic() - sent) * 1000, 1)

    async def ready_to_spawn(self, obj):
        self.later(1.0 if self.incarnation == 0 else 0.1, lambda: self.send(self.T['prepare']))

    async def spawn(self, obj):
        self.incarnation += 1
        cmds = copy.deepcopy(self.T['spawn'])   # setSpecification, spawn(team, position, orientation, health, n)
        for c in cmds:
            if c['name'] == 'spawn':
                c['args'][-1] = self.incarnation
        await self.send(cmds)

    async def spawned(self, obj, incarnation):
        self.later(3.0, lambda: self.send(self.T['activate']))

    async def tank_state(self, obj, client_ms, incarnation, state):
        """Log where the tank is: at most once a second and only after it moved."""
        t, last = self.logged_at
        pos = state['position']
        if time.monotonic() - t >= 1 and (last is None or sum((a - b) ** 2 for a, b in zip(pos, last)) > 100):
            self.logged_at = (time.monotonic(), pos)
            self.session.log('   tank at (%.0f, %.0f, %.0f), speed (%d, %d, %d)'
                             % (*pos, *state['linearVelocity']))

    async def stage_done(self, obj):
        self.session.log('   tutorial stage done; the next stages are not implemented yet')


SPACES = {s.id: s for s in (Entrance, System, Lobby, Shop, TutorialBattle)}
