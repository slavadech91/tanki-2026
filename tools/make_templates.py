"""Cut space templates for the local server (server/) out of a decoded capture (proto_verify.py dump).

The registration session of captures/session1 (registration -> tank builder -> tutorial battle) gives:
  entrance  05f691cc          first packets, registration reply, builder previews per item, builder completion
  system    d634b693fb        first packets
  lobby     05f7b228          first packets, layout switch to the battle
  shop      05f6fdcf          first packets, replies to its startup requests
  battle    2aaaaabafeae733d  first packets, spawn sequence
A template is a list of commands in proto_codec's decoded form ({object, method, name, args}); one template
is sent as one packet. Commands that came through an alias get their full object/method ids back.
What belongs to the captured account is scrubbed: its nickname becomes UID (the server puts the player's
nickname there), its "remember me" hash becomes HASH, and signed tokens in links (state=...) are dropped.

usage: python -I make_templates.py <decoded.jsonl> <out dir>
"""
import json, os, re, sys

UID, HASH = '%uid%', '%hash%'    # placeholders; server/spaces.py replaces UID
TOKEN = re.compile(r'([?&](?:state|token|hash|sig|signature|session|auth)=)[^&"]*')

# sockets of the registration session in captures/session1 (server-notes/registration-to-tutorial.md)
SOCKETS = {'entrance': '18384.9982', 'system': '18384.10274', 'lobby': '18384.10275', 'shop': '18384.10276',
           'battle': '18384.11000', 'chat': '18384.11548'}
# weapon CC model -> kind, and the class of bot tank objects (tutorial bots, registration-to-tutorial.md part 5)
WEAPONS = {'1e24fd4b0c6e92fb': 'smoky', '234fc2564fd0fccf': 'ricochet', '3dac48bd48435a31': 'firebird'}
TANK_CLASS = 'ffffffff80000493'

dump = [json.loads(line) for line in open(sys.argv[1], encoding='utf-8')]
out_dir = sys.argv[2]


def packets(name):
    return [p for p in dump if p['sock'] == SOCKETS[name]]


def cmds(p):
    return [{k: c[k] for k in ('object', 'method', 'name', 'args')} for c in p['commands']]


def server(pk):
    return [p for p in pk if p['dir'] == '<']


def first_with(pk, name):
    return next(cmds(p) for p in server(pk) if any(c['name'] == name for c in p['commands']))


def entrance():
    pk = packets('entrance')
    t = {'open': cmds(server(pk)[0]), 'objects': cmds(server(pk)[1]),
         'register': first_with(pk, 'rememberUsersHash'), 'complete': first_with(pk, '76be15'), 'previews': {}}
    # builder previews: each df32fd(item) is answered by one loadDependencies (one class), then the object of that
    # class comes in a loadObjectsData and is unloaded again; requests are answered in order
    asked, by_class, previews = [], {}, t['previews']
    for p in pk:
        for c in p['commands']:
            if p['dir'] == '>' and c['name'] == 'df32fd':
                asked.append(c['args'][0])
            elif p['dir'] == '<' and c['name'] == 'loadDependencies' and asked:
                item, deps = asked.pop(0), c['args'][0]
                previews[str(item)] = {'deps': {'classes': deps['classes'], 'resources': deps['resources']}}
                for k in deps['classes']:
                    by_class[k['id']] = str(item)
            elif p['dir'] == '<' and c['name'] == 'loadObjectsData' and by_class:
                data, owner = c['args'][0], {}
                for o in data['objects']:
                    if o['class'] in by_class:
                        owner[o['id']] = by_class[o['class']]
                        previews[owner[o['id']]]['data'] = {'objects': [o], 'modelsData': []}
                current = None
                for entry in data['modelsData']:
                    current = owner.get(entry['object'], current) if 'object' in entry else current
                    if current is not None:
                        previews[current]['data']['modelsData'].append(entry)
    for item, v in list(previews.items()):
        if 'data' not in v:
            del previews[item]
    return t


def system():
    pk = server(packets('system'))
    return {'open': cmds(pk[0]), 'objects': cmds(pk[1])}


def lobby():
    pk = server(packets('lobby'))
    switches = [[c for c in cmds(p) if c['name'].endswith('LayoutSwitch')] for p in pk
                if any(c['name'].endswith('LayoutSwitch') for c in p['commands'])]
    return {'open': cmds(pk[0]), 'begin_battle': cmds(pk[1]), 'end_battle': cmds(pk[2]),
            'begin_lobby': switches[2], 'end_lobby': switches[3]}     # after the tutorial: MATCHMAKING


def shop():
    pk = packets('shop')
    return {'open': cmds(server(pk)[0]), 'objects': cmds(server(pk)[1]),
            'reply_b6f461': first_with(pk, '137105'), 'reply_announcements': first_with(pk, 'announcements')}


def missions():
    pk = packets('shop')
    start = next(i for i, p in enumerate(pk) if p['dir'] == '>' and
                 any(c['name'] == 'e75976' for c in p['commands']))
    tail = server(pk[start:])
    categories = [c for c in first_with(pk[start:], 'categoriesStatistic') if c['name'] == 'categoriesStatistic']
    sets = {}
    for p in tail:
        for c in cmds(p):
            if c['name'] == 'setQuests' and c['args'][0]:
                category = str(c['args'][0][0]['categoryId'])
                sets.setdefault(category, c)
    categories[0]['args'][0] = [s for s in categories[0]['args'][0] if str(s['questCategoryId']) in sets]
    content = [c for c in first_with(pk[start:], 'elementContent') if c['name'] == 'elementContent']
    completion = next(cmds(p) for p in server(pk) if
                      any(c['name'] == 'updateMainQuest' and c['args'][0] == 1931009801849
                          for c in p['commands']))
    return {'categories': categories, 'sets': sets, 'content': content, 'completion': completion}


def signed(hex_id):
    v = int(hex_id, 16)
    return v - (1 << 64) if v >= 1 << 63 else v


def bot(pk, i, connect, classes):
    """A tutorial bot from its userConnect in packet i: loads, objects, first spawn, weapon, lobby user info."""
    user_id = connect['args'][0]
    tank = '%016x' % user_id
    info = next(u for u in connect['args'][1] if u['user'] == user_id)
    objects = next(c for p in server(pk[i:]) for c in cmds(p) if c['name'] == 'loadObjectsData'
                   and any(o['id'] == tank for o in c['args'][0]['objects']))
    spawn = []
    for name in ('setActive', 'setSpecification', 'spawn'):
        spawn += [next(c for p in server(pk[i:]) for c in cmds(p) if c['name'] == name and c['object'] == tank)]
    weapon, kind = next((o['id'], WEAPONS[m]) for o in objects['args'][0]['objects']
                        for m in classes.get(o['class'], []) if m in WEAPONS)
    lobby_info = [c for p in server(packets('lobby')) for c in cmds(p) if c['args'] and isinstance(c['args'][0], list)
                  and c['args'][0] and isinstance(c['args'][0][0], dict) and c['args'][0][0].get('userId') == user_id]
    return {'id': tank, 'uid': info['uid'], 'rank': info['rank'], 'weapon': weapon, 'kind': kind,
            'load': [c for c in cmds(pk[i]) if c['name'] == 'loadDependencies'], 'objects': objects, 'spawn': spawn,
            'unload': [signed(o['id']) for o in objects['args'][0]['objects']], 'lobby': lobby_info}


def battle():
    pk = packets('battle')
    t = {'open': cmds(server(pk)[0]), 'objects': cmds(server(pk)[1]),
         'prepare': first_with(pk, 'prepareToSpawn'), 'spawn': first_with(pk, 'spawn'),
         'activate': first_with(pk, 'cb856a')}
    # tutorial stages after the movement stage: the target, the bonus, six bots (registration-to-tutorial.md part 5)
    classes = {k['id']: k['models'] for p in pk for c in p['commands'] if c['name'] == 'loadDependencies'
               for k in c['args'][0]['classes']}
    bots = [bot(pk, i, c, classes) for i, p in enumerate(pk) if p['dir'] == '<'
            for c in cmds(p) if c['name'] == 'userConnect']
    t['target'], t['bots'] = bots[0], bots[1:]
    spawns = [c for p in server(pk) for c in cmds(p) if c['name'] == 'spawnBonuses']
    t['bonus_first'], t['bonus_more'] = [spawns[0]], [spawns[1]]
    taken = next(i for i, p in enumerate(pk) if any(c['name'] == 'f5d182' for c in p['commands']))
    # the reply to the first pickup: heal effect, its objects, tutorial event, bonus taken; health comes from the server
    t['bonus_pickup'] = [c for c in cmds(server(pk[taken:])[0]) if c['name'] not in ('b30f91', 'userConnect')
                         and not (c['name'] == 'loadDependencies' and c['args'][0]['callbackId'])]
    t['battle_signal'] = [c for c in first_with(pk, '618bf6') if c['name'] == '618bf6']
    # Shift (e5f70d): the reply, and 2 s later Hunter's EMP on the bot next to the player, up to its kill
    used = next(i for i, p in enumerate(pk) if any(c['name'] == 'e5f70d' for c in p['commands']))
    t['overdrive_use'] = cmds(server(pk[used:])[0])
    emp = first_with(pk, 'dispel')
    t['overdrive_emp'] = emp[:next(i for i, c in enumerate(emp) if c['name'] == 'refreshUsersStat')]
    t['finish'] = [c for c in first_with(pk, 'roundFinish') if c['name'] in ('38bbe3', 'roundFinish')]
    t['progress'] = first_with(pk, 'updatedProgress')
    return t


def chat():
    return {'open': cmds(server(packets('chat'))[0])}


def scrub(value, secrets):
    if isinstance(value, str):
        for old, new in secrets:
            value = value.replace(old, new)
        return TOKEN.sub(r'\1', value)
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v, secrets) for k, v in value.items()}
    return value


registration = entrance()['register']
secrets = [(next(c['args'][0] for c in registration if c['name'] == 'rememberUsersHash'), HASH),
           (next(c['args'][0] for c in registration if c['name'] == 'setUid'), UID)]
os.makedirs(out_dir, exist_ok=True)
for name, make in (('entrance', entrance), ('system', system), ('lobby', lobby), ('shop', shop), ('battle', battle),
                   ('chat', chat), ('missions', missions)):
    t = scrub(make(), secrets)
    path = os.path.join(out_dir, name + '.json')
    json.dump(t, open(path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('%-8s %7d B  %s' % (name, os.path.getsize(path), ', '.join(
        '%s(%d)' % (k, len(v)) for k, v in t.items())))
