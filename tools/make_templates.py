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
           'battle': '18384.11000'}

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
    return {'open': cmds(pk[0]), 'begin_battle': cmds(pk[1]), 'end_battle': cmds(pk[2])}


def shop():
    pk = packets('shop')
    return {'open': cmds(server(pk)[0]), 'objects': cmds(server(pk)[1]),
            'reply_b6f461': first_with(pk, '137105'), 'reply_announcements': first_with(pk, 'announcements')}


def battle():
    pk = packets('battle')
    return {'open': cmds(server(pk)[0]), 'objects': cmds(server(pk)[1]),
            'prepare': first_with(pk, 'prepareToSpawn'), 'spawn': first_with(pk, 'spawn'),
            'activate': first_with(pk, 'cb856a')}


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
for name, make in (('entrance', entrance), ('system', system), ('lobby', lobby), ('shop', shop), ('battle', battle)):
    t = scrub(make(), secrets)
    path = os.path.join(out_dir, name + '.json')
    json.dump(t, open(path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('%-8s %7d B  %s' % (name, os.path.getsize(path), ', '.join(
        '%s(%d)' % (k, len(v)) for k, v in t.items())))
