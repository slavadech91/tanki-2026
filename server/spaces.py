"""Spaces of the local server: entrance (registration, tank builder), system, lobby, shop, tutorial battle.

Every space has its own socket. Packets come from server/templates (tools/make_templates.py cuts them out of
the capture) and are adjusted to the session before sending; the order follows the capture
(server-notes/registration-to-tutorial.md). Methods without a name in the schema are named after the last
6 hex digits of their id, as in the notes.
"""
import asyncio, copy, json, math, os, random, re, time, traceback

import protocol
from proto_codec import unhex64
from tutorial_loadout import CONFIGURATION, TutorialLoadout, TWINS, SMOKY, FIREBIRD, RICOCHET, parts

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
TEMPLATE_UID = '%uid%'          # where the templates had the captured account's nickname (make_templates.py)

ENTRANCE, SYSTEM, LOBBY, SHOP = '0000000005f691cc', '000000d634b693fb', '0000000005f7b228', '0000000005f6fdcf'
CHAT = '0000000005f69398'
TUTORIAL = '2aaaaabafeae733d'   # tutorial battle of the captured account (its user id + 3)
LOCAL_BATTLE = '2aaaaabafeae733e'
PLAYER_TANK = '2aaaaabafeae733a'    # the player's tank object; its id is the captured account's user id
PLAYER_ID = int(PLAYER_TANK, 16)

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
TARGET_SHOWN = '722b4a451998d2d0'    # 98d2d0(): the client began the target practice (BattleTutorialCC)
SHOT_HIT = '035ddeaca9d00907'        # d00907(clientTimeMs, shotId, target, hitPoint, origin): own shot hit a tank
SMOKY_HIT = '220b0bb3ba61f109'       # clientTimeMs, shotId, target, hitPoint, trajectory
RICOCHET_HIT = '6757ea6952c142d3'   # clientTimeMs, target, shotId, hitPoint, trajectory
FIREBIRD_HIT = '4915d91e70c7ce9c'   # clientTimeMs, targets, incarnations, hitPoints, positions
BOT_SHOT_HIT = '6ba3d91dabb5a86f'    # b5a86f(int, shotId, target, hitPoint, points): a bot's shot hit a tank
BOT_STATE = '51ab830176962b6d'       # 962b6d(clientTimeMs, TankState): a bot; the client simulates the bots
BONUS_TAKE = '6380a744c5f5d182'      # f5d182(bonusId)
LAYOUT_CHOICE = '52b3c5ac295567de'   # 5567de(layout): MATCHMAKING after the tutorial results
OVERDRIVE = '3880c61d14e5f70d'       # e5f70d(clientTimeMs) (UltimateCC): Shift
LOGIN = '0181d81f8d4d6d3a'           # 4d6d3a(uid, password, rememberMe)
LOGIN_WRONG_PASSWORD = '557ff96e2fdbe2c1'
LOGIN_TOKEN = '6ec46e04f12f1029'
LOGIN_TOKEN_INVALID = '78c29b6d1e163fb2'
REMEMBER_TOKEN = '034a7519bddbb2cc'
MATCHMAKING_JOIN = '16dc80ec90b3d1a0'
MATCHMAKING_LAYOUT = '5253eebd3a5f79b3'
QUEST_CATEGORIES = '3909a309bfe75976'
QUEST_LIST = '11389e45e236464f'
QUEST_HELP = '6c08dfd3285106d5'
QUEST_HELP_SEEN = '37130e9b9db9f188'
QUEST_CLAIM = '008e3ac48f0cea75'
SET_QUESTS = '42d143269948473f'
TUTORIAL_QUEST = 1931009801849
CRYSTALS = '03d4d1da34844690'
CHANGE_KEYS = '7b736847caa7e756'
GRENADE_STATE = '017e4fdb3a9c1172'
QUEST_REWARD_KEYS = {921009681254: 'STANDARD', 921009681374: 'EPIC'}
# arguments that are passwords: logged as ***
SECRET_ARGS = {PASSWORD_CHECK: {0}, REGISTER: {1}, LOGIN: {1}, LOGIN_TOKEN: {0},
               '752e41262e099112': {0}}
# reports that need no answer here; not logged
QUIET = {TANK_STATE, '711e4f0028314036', '6852c2c4158e67ff', BOT_STATE, TIME_REPLY,
         '41556c01bff5d967', '25589c81fefa4670', OBJECT_LOADED, SHOT_HIT, BOT_SHOT_HIT,
         '4c1dc500ead589a3', '07c95e80167b2884', '23e1a3da0919b692'}    # own shots, shell hits, 19b692
# server -> client
LOAD_DEPENDENCIES, LOAD_OBJECTS_DATA, UNLOAD_OBJECTS = '2ca2091458b7bc93', '6a09fce46efe601a', '7d701d63033cf397'
UID_BUSY, UID_FREE, UID_INVALID = '114edf6488168f19', '114edf648818538c', '3c4ea212dced917b'
PASSWORD_WEAK, PASSWORD_OK = '0a9143251fa8a2c3', '55c42d7ccbbdfcf8'
TIME_SYNC = '313e2d3c89ad6cb1'       # ad6cb1(serverTimeMs, pingMs)
USER_CONNECT = '31389f9ea340ec91'    # userConnect(userId, usersInfo)
USER_DISCONNECT = '13a8f5aa4d90f3f7' # 90f3f7(userId) (StatisticsDMCC)
CHANGE_USER_STAT, REFRESH_USERS_STAT = '398826071fecda41', '77d11b3d80c65eef'
ACTIVATE = '437b3755b6cb856a'        # cb856a(): the tank becomes active
SET_HEALTH = '297d8dcfcab30f91'      # b30f91(health) (TankCC)
KILL = '30a02c532861ceb5'            # kill(killer, respawnDelayMs, damageType, isCritical)
DAMAGE_FOR_SHOOTER = '162aba28333e3558'  # showDamageForShooter(damages): numbers over the target
HIT = '4eac34910a67150a'             # hit(critical): own tank was hit
DAMAGE_POINTER = '6cadc1e034bd55c1'  # bd55c1(attacker, damage / maxHealth) (TankPointersCC)
TARGET_KILLED = '276b9f025db3ec1b'   # b3ec1b() (BattleTutorialCC): target practice done
BATTLE_PROGRESS = '18d64d2d422aa25a' # 2aa25a(kills) (BattleTutorialCC)
BOT_MOVE_BY, BOT_STOP = '1123ea4e693f7bd2', '513b19dcc14cc9a8'     # moveBy(path), 4cc9a8() (BotNavigationCC)
TURRET = '1b097f994d858f42'          # 858f42(packed turret state) on a bot's weapon (RotatingTurretCC)
SMOKY_FIRE = '0ab9e5f6e93da710'      # fire(shooter, shotId, direction)
RICOCHET_FIRE = '7602d61bbcfe2826'   # fire(shooter, shotId, x, y, z): direction * 32767 as shorts
BONUS_TAKEN, REMOVE_BONUSES = '3872b4f20fce344e', '6815e0b423ed6a3d'
REMOVE_EFFECT = '21ac80433d363f71'   # 363f71(effectId) (StatusEffectCC)
EFFECT_END = '25e45c90d72c2a59'      # 2c2a59() (EffectDescriptionCC)
ULTIMATE_CHARGE = '623a32cdbbfb0907' # fb0907(int, float) (UltimateCC): (0, 0.0) on use, (0, 0.333) 1.7 s later
DISPEL = '4b6b6551028c4e4b'          # dispel(positions of the tanks hit) (HunterUltimateCC)

# tutorial numbers from the capture (registration-to-tutorial.md part 5); reload and ranges are a guess
MAX_HEALTH = 2250.0                  # SimpleArmorCC of the player's hull
PLAYER_DAMAGE = {TWINS: (180.0, 'TWINS'), SMOKY: (525.0, 'SMOKY'), RICOCHET: (255.0, 'RICOCHET'),
                 FIREBIRD: (180.0, 'FIREBIRD')}    # tutorial damage per hit/tick
BOT_DAMAGE = {'smoky': 525.0, 'ricochet': 255.0}    # bot hits on the player; the firebird bot does not shoot here
BOT_RELOAD = {'smoky': 2.5, 'ricochet': 1.2, 'target': 3.0}
BOT_FIRE_RANGE, BOT_KEEP_DISTANCE = 4500, 1800      # map units
RESPAWN_MS = 6000
EMP_DELAY = 2.05                     # DeferredOverdriveCC delayMs 2000; dispel came 2.135 s after e5f70d
EMP_RADIUS = 2000                    # guess: the captured EMP hit a bot 1541 away and missed one 2771 away
KILLS_TO_WIN = 4                     # 2aa25a(1..4), then roundFinish
PI = 3.1415927                       # the client's constant

# the official server rejected nicknames ending with "-" or "_" (ed917b); other rules are a guess
VALID_UID = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,18}[A-Za-z0-9])?')


def template(name):
    return json.load(open(os.path.join(TEMPLATES, name + '.json'), encoding='utf-8'))


def cmd(obj, method, *args):
    return {'object': obj, 'method': method, 'args': list(args)}


def wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


def quantize(x, bits):
    """Angle in [-pi, pi] -> sign-magnitude steps around the middle (client lC, bundle @3333011)."""
    s = (1 << bits) - 1
    step = 2 * PI / (s - 1)
    h = int((min(max(x, -PI), PI) + PI + step / 2 + step / 1000) // step)
    return h - s // 2 if h >= s // 2 else (s // 2 - h) | 1 << (bits - 1)


def turret_state(world, local):
    """858f42 argument: control 2, world angle (14 bits), angle to the hull (12 bits), 8; every capture value
    has control 2 and 8 (client c1ws/d1ws, bundle @3333011)."""
    v = 2 << 30 | quantize(world, 14) << 16 | quantize(local, 12) << 4 | 8
    return v - (1 << 32) if v >= 1 << 31 else v


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
        """Send a packet with loadDependencies, each under a free callbackId; `then` runs once the client acked
        them all."""
        cmds = copy.deepcopy(cmds)
        pending, cid = set(), 1
        for c in cmds:
            if c['method'] == LOAD_DEPENDENCIES:
                while cid in self.callbacks:
                    cid += 1
                c['args'][0]['callbackId'] = cid
                pending.add(cid)
                self.callbacks[cid] = (pending, then)
        await self.send(cmds)

    def later(self, delay, coro_fn):
        async def run():
            await asyncio.sleep(delay)
            try:
                await coro_fn()
            except Exception:  # noqa: BLE001 - log it; a lost task exception says nothing
                self.session.log('%s: delayed task failed\n%s' % (self.name, traceback.format_exc()))
        task = asyncio.create_task(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def ack(self, obj, callback_id):
        pending, then = self.callbacks.pop(callback_id, (None, None))
        if pending is not None:
            pending.discard(callback_id)
            if not pending:
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
                hidden = SECRET_ARGS.get(c['method'], ())
                args = ['***' if i in hidden else a for i, a in enumerate(c['args'])]
                self.session.log('->', self.name, c['name'], json.dumps(args, ensure_ascii=False)[:160],
                                 '' if h else '(no handler)')
            if h:
                try:
                    await h(c['object'], *c['args'])
                except Exception:  # noqa: BLE001 - one broken handler must not drop the space
                    self.session.log('-> %s %s: handler failed\n%s' % (self.name, c['name'], traceback.format_exc()))

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
                              ENTRANCE_DONE: self.done, LOGIN: self.login, LOGIN_TOKEN: self.login_token})

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
        if self.session.user is not None:
            return
        if not VALID_UID.fullmatch(uid):
            await self.uid_check(obj, uid)
            return
        if len(password) < 6:
            await self.password_check(obj, password)
            return
        accounts = self.session.accounts
        if accounts.get(uid) is not None:   # the client checks the nickname before; registering never logs in
            self.session.log('register: nickname taken', uid)
            await self.uid_check(obj, uid)
            return
        self.session.user = accounts.create(uid, password)
        self.session.log('registered', uid)
        await self.show_builder()

    async def show_builder(self, remember=True):
        reply = copy.deepcopy(self.T['register'])   # rememberUsersHash, 706715(userId), setUid, initHangar, buildTank
        if not remember:
            reply = [c for c in reply if c['method'] != REMEMBER_TOKEN]
        for c in reply:
            if c['name'] == 'rememberUsersHash':
                c['args'] = [self.session.user['hash']]
            elif c['name'] == 'buildTank':
                c['args'] = TUTORIAL_LOADOUT.builder_args
        await self.send(reply)

    async def builder_item(self, obj, item):
        preview = TUTORIAL_LOADOUT.previews.get(str(item))
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
            if (hull, weapon, paint) != TUTORIAL_LOADOUT.selection({'hull': hull, 'weapon': weapon, 'paint': paint}):
                self.session.log('invalid tutorial loadout', hull, weapon, paint)
                return
            user['tank'] = {'hull': hull, 'weapon': weapon, 'paint': paint}
            self.session.accounts.save()
        await self.send(self.T['complete'])     # 76be15(userId)

    async def login(self, obj, uid, password, remember):
        if self.session.user is not None:
            return
        user = self.session.accounts.check(uid, password)
        if user is None:
            await self.send([cmd(ENTRANCE, LOGIN_WRONG_PASSWORD)])
            return
        await self.authenticated(user, remember)

    async def login_token(self, obj, token):
        if self.session.user is not None:
            return
        user = self.session.accounts.check_token(token)
        if user is None:
            await self.send([cmd(ENTRANCE, LOGIN_TOKEN_INVALID)])
            return
        await self.authenticated(user, False)

    async def authenticated(self, user, remember):
        self.session.user = user
        if user.get('tank'):
            reply = [cmd(ENTRANCE, REMEMBER_TOKEN, user['hash'])] if remember else []
            await self.send(reply + self.T['complete'])
        else:
            await self.show_builder(remember)

    async def done(self, obj):
        if not self.session.user or not self.session.user.get('tank'):
            return
        # closing the entrance socket moves the client to System.Loader (login-to-lobby.md)
        await self.ws.close()
        enter = self.session.enter_lobby if (self.session.user or {}).get('tutorial_done') else self.session.enter_tutorial
        self.session.later(0.5, enter)


class System(Space):
    id, name = SYSTEM, 'system'
    T = template('system')

    def __init__(self, session, ws):
        super().__init__(session, ws)
        self.handlers[MATCHMAKING_JOIN] = self.join

    async def on_open(self):
        await self.send_loading(self.T['open'], self.loaded)

    async def loaded(self):
        objects = copy.deepcopy(self.T['objects'])
        for command in objects:
            if command['method'] == LOAD_OBJECTS_DATA:
                for entry in command['args'][0]['modelsData']:
                    if entry.get('model') == MATCHMAKING_LAYOUT:
                        config = entry['data']
                        config['disabledModes'] = [mode['matchmakingMode'] for mode in config['matchmakingModeRanks']
                                                   if mode['matchmakingMode'] != 'QUICK_BATTLE']
        await self.send(objects)

    async def join(self, obj, mode, platform, origin):
        if mode == 'QUICK_BATTLE':
            await self.session.start_local_battle()


class Lobby(Space):
    """Lobby layout: shows the battle screen once the battle space is loaded (endLayoutSwitch BATTLE)."""
    id, name = LOBBY, 'lobby'
    T = template('lobby')

    def __init__(self, session, ws):
        super().__init__(session, ws)
        self.began = False
        self.handlers[LAYOUT_CHOICE] = self.layout_choice

    async def on_open(self):
        await self.send(self.T['open'])
        self.later(0.2, self.begin)

    async def layout_choice(self, obj, layout):
        """The player left the tutorial results: back to the lobby (capture 193-196 s); Chat ends the switch."""
        if layout == 'MATCHMAKING' and self.began:
            self.began = False
            await self.send(self.T['begin_lobby'])
            await self.session.leave_battle()

    async def begin(self):
        if self.session.start_in_lobby:
            await self.send(self.T['begin_lobby'])
            return
        await self.begin_battle()

    async def begin_battle(self):
        await self.send(self.T['begin_battle'])
        self.began = True
        if self.session.battle_ready:
            await self.end_battle_switch()

    async def end_battle_switch(self):
        await self.send(self.T['end_battle'])


class Shop(Space):
    id, name = SHOP, 'shop'
    T = template('shop')
    MISSIONS = template('missions')

    def __init__(self, session, ws):
        super().__init__(session, ws)
        self.handlers.update({SHOP_B6F461: lambda obj, n: self.send(self.T['reply_b6f461']),
                              ANNOUNCEMENTS: lambda obj: self.send(self.T['reply_announcements']),
                              QUEST_CATEGORIES: self.quest_categories, QUEST_LIST: self.quest_list,
                              QUEST_HELP: self.quest_help, QUEST_HELP_SEEN: self.quest_help_seen,
                              QUEST_CLAIM: self.quest_claim})

    async def on_open(self):
        await self.send_loading(self.T['open'], self.loaded)

    async def loaded(self):
        await self.send(self.T['objects'])
        user = self.session.user or {}
        if user.get('tutorial_done'):
            await self.send(self.MISSIONS['completion'])
        updates = [cmd(PLAYER_TANK, CHANGE_KEYS, kind, amount) for kind, amount in user.get('quest_keys', {}).items()]
        if user.get('quest_crystals'):
            updates.append(cmd(PLAYER_TANK, CRYSTALS, user['quest_crystals']))
        if user.get('quest_grenades'):
            updates.append(cmd(PLAYER_TANK, GRENADE_STATE, True))
        if updates:
            await self.send(updates)

    async def quest_categories(self, obj):
        reply = copy.deepcopy(self.MISSIONS['categories'])
        for category in reply[0]['args'][0]:
            category['quests'] = len(self.quests(category['questCategoryId']))
        await self.send(reply)

    def quests(self, category):
        reply = self.MISSIONS['sets'].get(str(category))
        user = self.session.user or {}
        claimed = set(user.get('claimed_quests', []))
        quests = [copy.deepcopy(q) for q in reply['args'][0] if q['id'] not in claimed] if reply else []
        for quest in quests:
            if quest['id'] == TUTORIAL_QUEST and not user.get('tutorial_done'):
                quest['completed'] = False
                quest['progress'] = {}
        return quests

    async def quest_list(self, obj, category):
        await self.send([cmd(PLAYER_TANK, SET_QUESTS, self.quests(category))])

    async def quest_help(self, obj, element):
        reply = next((c for c in self.MISSIONS['content'] if c['args'][0] == element), None)
        await self.send([reply or cmd(SHOP, '74adbadee06c80fd', element, [])])

    async def quest_help_seen(self, obj, element):
        pass  # The client tracks which contextual tips it has already shown.

    async def quest_claim(self, obj, ids):
        user = self.session.user
        if user is None:
            return
        ids = set(ids)
        updates, categories = [], set()
        for category in self.MISSIONS['sets']:
            for quest in self.quests(category):
                if quest['id'] not in ids or not quest['active'] or not quest['completed']:
                    continue
                user.setdefault('claimed_quests', []).append(quest['id'])
                categories.add(category)
                for reward in quest['rewards']:
                    item, amount = reward['id'], reward['count']
                    if item in QUEST_REWARD_KEYS:
                        kind = QUEST_REWARD_KEYS[item]
                        keys = user.setdefault('quest_keys', {})
                        keys[kind] = keys.get(kind, 0) + amount
                        updates.append(cmd(PLAYER_TANK, CHANGE_KEYS, kind, amount))
                    elif item == 920009658998:
                        user['quest_crystals'] = user.get('quest_crystals', 0) + amount
                        updates.append(cmd(PLAYER_TANK, CRYSTALS, user['quest_crystals']))
                    elif item == 1931009780012:
                        user['quest_grenades'] = user.get('quest_grenades', 0) + amount
                        updates.append(cmd(PLAYER_TANK, GRENADE_STATE, True))
        if categories:
            self.session.accounts.save()
            updates.extend(cmd(PLAYER_TANK, SET_QUESTS, self.quests(category)) for category in sorted(categories))
            await self.send(updates)
            await self.quest_categories(obj)


class Bot:
    """A tutorial bot: the client simulates it; the server drives it (path, turret, shots) and keeps its health."""

    def __init__(self, data):
        self.data, self.tank, self.weapon, self.kind = data, data['id'], data['weapon'], data['kind']
        self.user = int(data['id'], 16)     # the tank object id is the bot's user id
        self.health, self.alive, self.active, self.ai = 0.0, False, False, False
        self.spawns = self.shots = 0
        self.state = None                   # last TankState the client reported (962b6d)
        self.turret = None                  # last turret angle sent
        self.next_fire = self.next_move = 0.0


class TutorialBattle(Space):
    """The tutorial battle (registration-to-tutorial.md, parts 4-5): load, time sync, spawn; then the target,
    the bonus and the bots; the round ends after KILLS_TO_WIN kills."""
    id, name = TUTORIAL, 'battle'
    T = template('battle')
    frag_limit = KILLS_TO_WIN

    def __init__(self, session, ws):
        super().__init__(session, ws)
        hull, self.weapon, paint = TUTORIAL_LOADOUT.selection((session.user or {}).get('tank'))
        self.opening, self.objects, self.turret_speed = TUTORIAL_LOADOUT.apply(
            self.T, PLAYER_TANK, hull, self.weapon, paint)
        self.session.log(self.name, 'loadout', hull, self.weapon, paint)
        self.t0 = time.monotonic()
        self.incarnation = 0
        self.sync_sent = {}     # serverTimeMs -> monotonic time sent
        self.ping = 0.0
        self.logged_at = (0.0, None)    # (monotonic time, position) of the last logged tank state
        self.stage = 'movement'         # movement -> target -> bonus -> battle -> finished
        self.users = {PLAYER_ID: self.new_user(session.uid, 1)}     # user id -> info and stats, in join order
        self.bots = {}                  # tank object -> Bot
        self.health, self.alive = MAX_HEALTH, False
        self.player = None              # last own TankState
        self.kills = 0                  # player kills in the battle stage
        self.bonuses = set()            # bonus ids on the map
        self.overdrive = False          # charged: the first bonus pickup gives it (008521 in bonus_pickup)
        self.effect_objects = []        # effect objects loaded in the battle; unloaded at the finish
        self.handlers.update({READY_TO_SPAWN: self.ready_to_spawn, SPAWN_REQUEST: self.spawn,
                              SPAWNED: self.spawned, TIME_REPLY: self.time_reply, STAGE_DONE: self.stage_done,
                              TANK_STATE: self.tank_state, TARGET_SHOWN: self.target_shown,
                              SHOT_HIT: self.shot_hit, SMOKY_HIT: self.shot_hit, RICOCHET_HIT: self.ricochet_hit,
                              FIREBIRD_HIT: self.firebird_hit, BOT_SHOT_HIT: self.bot_shot_hit, BOT_STATE: self.bot_state,
                              BONUS_TAKE: self.bonus_take, OVERDRIVE: self.overdrive_use})

    async def on_open(self):
        await self.send_loading(self.opening, self.loaded)

    async def loaded(self):
        await self.send(self.objects)
        self.later(0, self.time_sync)
        self.later(0, self.ai)
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

    # --- the player's tank

    async def ready_to_spawn(self, obj):
        self.later(1.0 if self.incarnation == 0 else 0.1, lambda: self.send(self.T['prepare']))

    async def spawn(self, obj):
        self.incarnation += 1
        cmds = copy.deepcopy(self.T['spawn'])   # setSpecification(.., n, immediately), spawn(.., health, n)
        for c in cmds:
            if c['name'] == 'spawn':
                c['args'][-1] = self.incarnation
            elif c['name'] == 'setSpecification':
                c['args'][2] = self.turret_speed
                c['args'][4] = self.incarnation
        self.health = MAX_HEALTH
        await self.send(cmds)

    async def spawned(self, obj, incarnation):
        async def activate():
            self.alive = True
            await self.send(self.T['activate'])
        self.later(3.0, activate)

    async def tank_state(self, obj, client_ms, incarnation, state):
        """Remember where the tank is; log it at most once a second and only after it moved."""
        self.player = state
        t, last = self.logged_at
        pos = state['position']
        if time.monotonic() - t >= 1 and (last is None or sum((a - b) ** 2 for a, b in zip(pos, last)) > 100):
            self.logged_at = (time.monotonic(), pos)
            self.session.log('   tank at (%.0f, %.0f, %.0f), speed (%d, %d, %d)'
                             % (*pos, *state['linearVelocity']))

    # --- users and stats

    @staticmethod
    def new_user(uid, rank):
        return {'uid': uid, 'rank': rank, 'kills': 0, 'deaths': 0, 'killScore': 0, 'score': 0}

    def users_info(self):
        return [{'chatModeratorLevel': 'NONE', 'clanTag': None, 'deaths': u['deaths'], 'hasPremium': False,
                 'killScore': u['killScore'], 'kills': u['kills'], 'partnerUid': None, 'rank': u['rank'],
                 'score': u['score'], 'uid': u['uid'], 'user': user} for user, u in self.users.items()]

    def stat(self, user):
        u = self.users[user]
        return {'deaths': u['deaths'], 'killScore': u['killScore'], 'kills': u['kills'], 'score': u['score'],
                'user': user}

    def stats(self):
        return [self.stat(user) for user in self.users]

    # --- bots

    async def connect_bot(self, data, then):
        """userConnect with the bot's loads, its objects after the acks, its name in the lobby space."""
        bot = self.bots[data['id']] = Bot(data)
        self.users[bot.user] = self.new_user(data['uid'], data['rank'])

        async def loaded():
            await self.send([data['objects']])
            lobby = self.session.spaces.get(LOBBY)
            if lobby is not None:
                await lobby.send(data['lobby'])     # sendData, setOnline, setRank, setUid
            await then(bot)
        await self.send_loading([cmd(TUTORIAL, USER_CONNECT, bot.user, self.users_info())] + data['load'], loaded)

    async def spawn_bot(self, bot):
        if self.stage == 'finished' or bot.tank not in self.bots:
            return
        bot.spawns += 1
        cmds = copy.deepcopy(bot.data['spawn'])     # setActive(true), setSpecification(.., n, ..), spawn(.., n)
        if bot.spawns > 1:
            cmds = cmds[1:]
        for c in cmds:
            if c['name'] == 'setSpecification':
                c['args'][4] += bot.spawns - 1
            elif c['name'] == 'spawn':
                c['args'][-1] = bot.spawns
                bot.health = float(c['args'][3])
        bot.alive, bot.active, bot.state, bot.turret = True, False, None, None
        await self.send(cmds)

        async def activate():
            # the round may have finished and unloaded the bot in the meantime
            if bot.alive and self.bots.get(bot.tank) is bot and self.stage != 'finished':
                bot.active = True
                bot.ai = bot.ai or self.stage == 'battle'
                await self.send([cmd(bot.tank, ACTIVATE)])
        self.later(3.0, activate)

    async def spawn_soon(self, bot):
        self.later(5.8, lambda: self.spawn_bot(bot))

    async def disconnect_bot(self, bot):
        self.bots.pop(bot.tank, None)
        self.users.pop(bot.user, None)
        unload = sorted(bot.data['unload'], key=lambda o: o != bot.user)     # the tank before its parts
        await self.send([cmd(TUTORIAL, USER_DISCONNECT, bot.user)]
                        + [cmd(TUTORIAL, UNLOAD_OBJECTS, [o]) for o in unload])

    async def bot_state(self, obj, client_ms, state):
        bot = self.bots.get(obj)
        if bot is not None:
            bot.state = state

    async def ai(self):
        """Every 0.25 s: turn the turrets of active bots to the player, move them closer, shoot in range."""
        while not self.ws.closed:
            await asyncio.sleep(0.25)
            if self.player is None or self.stage == 'finished':
                continue
            now = time.monotonic()
            for bot in list(self.bots.values()):
                if bot.ai and bot.active and bot.alive and bot.state is not None:
                    cmds = self.drive(bot, now)
                    if cmds:
                        await self.send(cmds, quiet=True)

    def drive(self, bot, now):
        target_state = self.aim_state(bot)
        if target_state is None:
            return []
        px, py, pz = target_state['position']
        bx, by, bz = bot.state['position']
        dx, dy = px - bx, py - by
        dist = math.hypot(dx, dy) or 1.0
        yaw = math.atan2(-dx, dy)           # tank yaw: forward is (-sin, cos)
        target = bot.tank == self.T['target']['id']
        out = []
        if bot.turret is None or abs(wrap(yaw - bot.turret)) > 0.02:
            if bot.turret is None or abs(wrap(yaw - bot.turret)) > 0.3:
                bot.next_fire = max(bot.next_fire, now + 0.8)   # let the turret come round first
            out.append(cmd(bot.weapon, TURRET, turret_state(yaw, wrap(yaw - bot.state['orientation'][2]))))
            bot.turret = yaw
        if not target and now >= bot.next_move:     # the practice target stays where it is
            bot.next_move = now + 3.0
            if dist > BOT_KEEP_DISTANCE:
                k = (dist - BOT_KEEP_DISTANCE * 0.8) / dist
                out.append(cmd(bot.tank, BOT_MOVE_BY, [{'x': bx + dx * k, 'y': by + dy * k, 'z': pz}]))
            else:
                out.append(cmd(bot.tank, BOT_STOP))
        if self.can_fire(target_state) and bot.kind in BOT_DAMAGE and dist < BOT_FIRE_RANGE and now >= bot.next_fire:
            bot.next_fire = now + BOT_RELOAD['target' if target else bot.kind] + random.uniform(0, 1)
            a = yaw + random.uniform(-0.04, 0.04)
            d = [-math.sin(a), math.cos(a), max(-0.3, min(0.3, (pz - bz) / dist))]
            n = math.sqrt(sum(v * v for v in d))
            d = [v / n for v in d]
            if bot.kind == 'smoky':
                out.append(cmd(bot.weapon, SMOKY_FIRE, bot.user, bot.shots, {'x': d[0], 'y': d[1], 'z': d[2]}))
            else:
                out.append(cmd(bot.weapon, RICOCHET_FIRE, bot.user, bot.shots, *(round(v * 32767) for v in d)))
            bot.shots += 1
        return out

    def aim_state(self, bot):
        return self.player

    def can_fire(self, target_state):
        return self.alive

    # --- hits

    async def shot_hit(self, obj, client_ms, shot, target, point, origin):
        await self.player_hit(target)

    async def ricochet_hit(self, obj, client_ms, target, shot, point, trajectory):
        await self.player_hit(target)

    async def firebird_hit(self, obj, client_ms, targets, incarnations, hit_points, positions):
        for target in targets:
            await self.player_hit(target)

    async def player_hit(self, target):
        bot = next((b for b in self.bots.values() if b.user == target), None)
        if bot is not None and bot.alive and self.stage != 'finished':
            await self.damage_bot(bot, *PLAYER_DAMAGE[self.weapon])

    async def damage_bot(self, bot, amount, damage_type, before=()):
        """Damage numbers over the bot; at zero health the kill. `before` goes first in the same packet."""
        bot.health -= amount
        fatal = bot.health <= 0
        damage = cmd(PLAYER_TANK, DAMAGE_FOR_SHOOTER, [{'critical': False, 'damageAmount': amount,
                                                        'damageIndicatorType': 'DAMAGE', 'debugInfo': None,
                                                        'fatal': fatal, 'target': bot.user}])
        if not fatal:
            await self.send(list(before) + [damage], quiet=not before)
            return
        bot.alive = bot.active = bot.ai = False
        player = self.users[PLAYER_ID]
        player['kills'] += 1
        player['killScore'] += 1
        self.users[bot.user]['deaths'] += 1
        kill = cmd(bot.tank, KILL, PLAYER_ID, RESPAWN_MS, damage_type, False)
        if self.stage == 'target':
            await self.send(list(before) + [cmd(TUTORIAL, CHANGE_USER_STAT, self.stat(bot.user)),
                                            cmd(TUTORIAL, TARGET_KILLED), kill, damage])
            self.session.log('   tutorial: target destroyed')
            self.later(0.8, self.bonus_stage)
            self.later(RESPAWN_MS / 1000, lambda: self.disconnect_bot(bot))
            return
        self.kills += 1
        await self.send(list(before) + [cmd(TUTORIAL, REFRESH_USERS_STAT, self.stats())]
                        + self.frag_progress() + [kill, damage])
        self.session.log(self.name, '%s destroyed (%d of %d)' % (bot.data['uid'], self.kills, self.frag_limit))
        if self.kills >= self.frag_limit:
            self.later(1.0, self.finish)
        else:
            self.later(RESPAWN_MS / 1000, lambda: self.spawn_bot(bot))

    def frag_progress(self):
        return [cmd(TUTORIAL, BATTLE_PROGRESS, self.kills)]

    async def bot_shot_hit(self, obj, client_ms, shot, target, point, points):
        """A bot's shell hit the player (the client simulates the bots and reports it)."""
        bot = next((b for b in self.bots.values() if b.weapon == obj), None)
        if bot is None or target != PLAYER_ID or not self.alive or self.stage == 'finished':
            return
        damage = BOT_DAMAGE.get(bot.kind, 0.0)
        self.health = max(0.0, self.health - damage)
        cmds = [cmd(PLAYER_TANK, SET_HEALTH, self.health), cmd(PLAYER_TANK, HIT, False)]
        if self.health > 0:
            await self.send(cmds + [cmd(PLAYER_TANK, DAMAGE_POINTER, bot.user, damage / MAX_HEALTH)], quiet=True)
            return
        self.alive = False
        self.users[PLAYER_ID]['deaths'] += 1
        killer = self.users.get(bot.user)
        if killer is not None:
            killer['kills'] += 1
            killer['killScore'] += 1
        await self.send(cmds + [cmd(TUTORIAL, REFRESH_USERS_STAT, self.stats()),
                                cmd(PLAYER_TANK, KILL, bot.user, RESPAWN_MS, bot.kind.upper(), False)])
        self.session.log(self.name, 'the player was destroyed by', bot.data['uid'])

    # --- stages

    async def stage_done(self, obj):
        """411f12: the client finished TankMovementStage; the target comes next."""
        if self.stage != 'movement':
            return
        self.stage = 'target'
        self.session.log('   tutorial: target practice')
        await self.connect_bot(self.T['target'], self.spawn_bot)

    async def target_shown(self, obj):
        """98d2d0: the target starts turning to the player and shooting (capture 138 s)."""
        bot = self.bots.get(self.T['target']['id'])
        if bot is not None:
            bot.ai = True

    async def bonus_stage(self):
        self.stage = 'bonus'
        self.session.log('   tutorial: bonus')
        self.bonuses.update(b['bonusId'] for c in self.T['bonus_first'] for b in c['args'][0])
        await self.send(self.T['bonus_first'])

    async def bonus_take(self, obj, bonus_id):
        if bonus_id not in self.bonuses or not self.alive:
            return
        self.bonuses.discard(bonus_id)
        self.later(0, self.heal)
        if self.stage != 'bonus':
            await self.send([cmd(TUTORIAL, BONUS_TAKEN, bonus_id)])
            return
        self.stage = 'battle'
        # heal effect and its objects, tutorial event ff84d1, overdrive charged (008521, "overdrive ready"),
        # bonus taken; effects end on their own timers
        self.overdrive = True
        self.effect_objects += self.loaded_objects(self.T['bonus_pickup'])
        await self.send(self.T['bonus_pickup'])
        for c in self.T['bonus_pickup']:
            if c['name'] == 'addEffect' and c['args'][1] > 0:
                self.later(c['args'][1] / 1000,
                           lambda e=c['args'][0]: self.send([cmd(PLAYER_TANK, REMOVE_EFFECT, e)]))
            elif c['name'] == '089bfa':
                self.later(c['args'][0] / 1000, lambda o=c['object']: self.send([cmd(o, EFFECT_END)]))
        self.later(0.1, self.battle_stage)

    async def heal(self):
        """First aid: +500 at once, then +150 every 0.2 s while the 6 s effect lasts (capture 156-162 s)."""
        self.health = min(MAX_HEALTH, self.health + 500)
        await self.send([cmd(PLAYER_TANK, SET_HEALTH, self.health)], quiet=True)
        for _ in range(30):
            await asyncio.sleep(0.2)
            if not self.alive or self.health >= MAX_HEALTH:
                return
            self.health = min(MAX_HEALTH, self.health + 150)
            await self.send([cmd(PLAYER_TANK, SET_HEALTH, self.health)], quiet=True)

    @staticmethod
    def loaded_objects(cmds):
        return [signed(o['id']) for c in cmds if c['name'] == 'loadObjectsData' for o in c['args'][0]['objects']]

    async def overdrive_use(self, obj, client_ms):
        """Shift: Hunter's overdrive (capture 175-177 s). The reply at once, the charge rate back after 1.7 s,
        the EMP after the 2 s delay."""
        if not self.overdrive or not self.alive:
            return
        self.overdrive = False
        self.session.log('   tutorial: overdrive')
        await self.send(self.T['overdrive_use'])    # 70f860 on the hull, "overdrive ready" off, 623ab1, fb0907(0, 0)
        self.later(1.7, lambda: self.send([cmd(PLAYER_TANK, ULTIMATE_CHARGE, 0, 0.333)]))
        self.later(EMP_DELAY, self.emp)

    async def emp(self):
        """Hunter's EMP: every bot within EMP_RADIUS is stunned, loses its supplies and, in the tutorial, dies
        at once (kill CHAOS_HUNTER, its whole health as damage)."""
        if not self.alive or self.player is None or self.stage == 'finished':
            return
        px, py, _ = self.player['position']
        hit = [b for b in self.bots.values() if b.alive and b.active and b.state is not None
               and math.hypot(b.state['position'][0] - px, b.state['position'][1] - py) <= EMP_RADIUS]
        t = self.T['overdrive_emp']
        dispel, captured_bot = t[0], t[1]['object']
        await self.send([cmd(dispel['object'], DISPEL, [dict(zip('xyz', b.state['position'])) for b in hit])])
        self.session.log('   tutorial: EMP hit', len(hit), 'bot(s)')
        for i, bot in enumerate(hit):
            # stun and supplies off with their effect objects (loaded once), both effects off again: the bot dies
            before = [dict(c, object=bot.tank) if c['object'] == captured_bot else c for c in t[1:]
                      if i == 0 or c['object'] == captured_bot]
            if i == 0:
                self.effect_objects += self.loaded_objects(before)
            await self.damage_bot(bot, bot.health, 'CHAOS_HUNTER', before)

    async def battle_stage(self):
        """Six bots join every 1.5 s and spawn about 6 s after joining; more bonuses appear (capture 156-170 s)."""
        self.session.log('   tutorial: battle')
        for i, data in enumerate(self.T['bots']):
            if i:
                await asyncio.sleep(1.5)
            if self.stage != 'battle':
                return
            await self.connect_bot(data, self.spawn_soon)
            if i == 3:
                await self.send(self.T['battle_signal'])
        await asyncio.sleep(0.3)
        self.bonuses.update(b['bonusId'] for c in self.T['bonus_more'] for b in c['args'][0])
        await self.send(self.T['bonus_more'])

    async def finish(self):
        """roundFinish with the results table; bots and effect objects go (capture 190 s)."""
        if self.stage == 'finished':
            return
        self.stage = 'finished'
        user = self.session.user
        newly_completed = user is not None and not user.get('tutorial_done')
        if newly_completed:
            user['tutorial_done'] = True
            self.session.accounts.save()
        cmds = [cmd(TUTORIAL, REMOVE_BONUSES, sorted(self.bonuses))] if self.bonuses else []
        self.bonuses.clear()
        cmds += [cmd(TUTORIAL, UNLOAD_OBJECTS, [o]) for o in self.effect_objects]
        self.effect_objects = []
        await self.send(cmds + self.T['finish'])    # 38bbe3(), roundFinish(true, rewards, 30)
        for bot in list(self.bots.values()):
            await self.disconnect_bot(bot)
        await asyncio.sleep(0.2)
        await self.send(self.T['progress'])         # updatedProgress: main quest
        if newly_completed:
            shop = self.session.spaces.get(SHOP)
            if shop is not None:
                await shop.send(shop.MISSIONS['completion'])
        self.session.log('   tutorial: round finished')


class LocalBattle(TutorialBattle):
    """An independent deathmatch using the available arena and tank models."""

    id, name = LOCAL_BATTLE, 'local deathmatch'
    frag_limit = 8
    duration = 180

    def __init__(self, session, ws):
        super().__init__(session, ws)
        self.stage = 'battle'
        self.handlers.pop(STAGE_DONE)
        self.handlers.pop(TARGET_SHOWN)
        data = self.objects[0]['args'][0]
        battle_class = next(obj['class'] for obj in data['objects'] if obj['id'] == TUTORIAL)
        classes = self.opening[0]['args'][0]['classes']
        models = next(cls['models'] for cls in classes if cls['id'] == battle_class)
        tutorial_model = '7e7cc3e04725ad33'
        models.remove(tutorial_model)
        models[models.index('62f19a09a775ed2c')] = '2d487e5a3fde7531'  # tutorial mode -> DM
        data['modelsData'] = [entry for entry in data['modelsData'] if entry.get('model') != tutorial_model]
        for entry in data['modelsData']:
            if entry.get('model') == '1cf14a01fef1653d':
                entry['data'].update(modeName='DM', timeLeft=self.duration,
                                     battleName='Local Deathmatch',
                                     limits={'scoreLimit': self.frag_limit, 'timeLimitInSec': self.duration})
            elif entry.get('model') == '66b71fab7366f25d':
                entry['data']['battleOptions'] = ['Bonuses', 'Bots']
            elif entry.get('model') == '5972a8f99711dac2':
                entry['data']['ultimateEnabled'] = False

    def adjust(self, value):
        # The wire templates refer to the tutorial space's own object by id.
        return self.id if value == TUTORIAL else super().adjust(value)

    async def loaded(self):
        await super().loaded()
        self.later(self.duration, self.finish)
        self.later(1, self.populate)

    async def populate(self):
        participants = iter(self.deathmatch_roster())

        async def join_next():
            data = next(participants, None)
            if data is not None and self.stage == 'battle':
                await self.connect_bot(data, bot_ready)

        async def bot_ready(bot):
            await self.spawn_bot(bot)
            self.later(0.5, join_next)

        await join_next()
        bonuses = self.T['bonus_more']
        self.bonuses.update(b['bonusId'] for c in bonuses for b in c['args'][0])
        await self.send(bonuses)

    def deathmatch_roster(self):
        initial = self.objects[0]['args'][0]
        default_color = parts(initial)[PLAYER_TANK][CONFIGURATION]['coloringId']
        loaded_objects = {signed(obj['id']) for obj in initial['objects']}
        for template_bot in self.T['bots']:
            if template_bot['kind'] not in BOT_DAMAGE:
                continue
            bot = copy.deepcopy(template_bot)
            packet = bot['objects']['args'][0]
            loaded_objects.update(signed(obj['id']) for obj in packet['objects'])
            config = parts(packet)[bot['id']][CONFIGURATION]
            # A bot may reuse a paint whose original owner was omitted from this match.
            if config['coloringId'] not in loaded_objects:
                config['coloringId'] = default_color
            yield bot

    def frag_progress(self):
        return []

    def stat(self, user):
        stat = super().stat(user)
        stat['score'] = stat['kills']
        return stat

    def aim_state(self, bot):
        candidates = [other.state for other in self.bots.values()
                      if other is not bot and other.alive and other.active and other.state is not None]
        if self.alive and self.player is not None:
            candidates.append(self.player)
        position = bot.state['position']
        return min(candidates, key=lambda state: math.dist(position, state['position']), default=None)

    def can_fire(self, target_state):
        return True

    async def bot_shot_hit(self, obj, client_ms, shot, target, point, points):
        if target == PLAYER_ID:
            await super().bot_shot_hit(obj, client_ms, shot, target, point, points)
            attacker = next((b for b in self.bots.values() if b.weapon == obj), None)
            if attacker is not None and self.users[attacker.user]['kills'] >= self.frag_limit:
                await self.finish()
            return
        if self.stage != 'battle':
            return
        attacker = next((b for b in self.bots.values() if b.weapon == obj), None)
        victim = next((b for b in self.bots.values() if b.user == target), None)
        if attacker is None or victim is None or attacker is victim or not victim.alive:
            return
        victim.health = max(0, victim.health - BOT_DAMAGE[attacker.kind])
        packets = [cmd(victim.tank, SET_HEALTH, victim.health)]
        if victim.health > 0:
            await self.send(packets, quiet=True)
            return
        victim.alive = victim.active = victim.ai = False
        self.users[victim.user]['deaths'] += 1
        winner = self.users[attacker.user]
        winner['kills'] += 1
        winner['killScore'] += 1
        await self.send(packets + [cmd(TUTORIAL, REFRESH_USERS_STAT, self.stats()),
                                   cmd(victim.tank, KILL, attacker.user, RESPAWN_MS, attacker.kind.upper(), False)])
        if winner['kills'] >= self.frag_limit:
            await self.finish()
        else:
            self.later(RESPAWN_MS / 1000, lambda: self.spawn_bot(victim))

    async def finish(self):
        if self.stage == 'finished':
            return
        self.stage = 'finished'
        self.alive = False
        rewards = [{'experiencePremiumBonusByActions': [], 'partnerUid': None, 'premiumBonusReward': 0,
                    'reward': 0, 'starsReward': 0, 'starsRewardForPremium': 0, 'userId': user}
                   for user in self.users]
        await self.send([cmd(TUTORIAL, REMOVE_BONUSES, sorted(self.bonuses)),
                         cmd(TUTORIAL, REFRESH_USERS_STAT, self.stats()),
                         cmd(TUTORIAL, '4ca692487638bbe3'),
                         cmd(TUTORIAL, '5d96382b26309b29', True, rewards, 30)])
        self.bonuses.clear()
        self.session.log(self.name, 'round finished', self.stats())


class Chat(Space):
    """Chat space; opening it after the tutorial ends the lobby's layout switch (capture 195.7 s)."""
    id, name = CHAT, 'chat'
    T = template('chat')

    async def on_open(self):
        await self.send(self.T['open'])
        lobby = self.session.spaces.get(LOBBY)
        if lobby is not None:
            await lobby.send(lobby.T['end_lobby'])


def signed(hex_id):
    v = int(hex_id, 16)
    return v - (1 << 64) if v >= 1 << 63 else v


TUTORIAL_LOADOUT = TutorialLoadout(Entrance.T, TutorialBattle.T)
SPACES = {s.id: s for s in (Entrance, System, Lobby, Shop, TutorialBattle, LocalBattle, Chat)}
