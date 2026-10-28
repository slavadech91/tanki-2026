"""Decode every space packet of a capture with the schema, encode it back and compare bytes.

usage: python -I proto_verify.py <packets.jsonl> <proto_schema.json> [dump.jsonl]
  dump.jsonl (optional) gets one decoded packet per line: {t, sock, space, dir, commands}
"""
import collections, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proto_codec import Schema, NullMap, Reader

schema = Schema(sys.argv[2])
dump = open(sys.argv[3], 'w', encoding='utf-8') if len(sys.argv) > 3 else None
aliases = collections.defaultdict(dict)
stats = collections.Counter()
fails = collections.defaultdict(list)
methods = collections.Counter()

for line in open(sys.argv[1], encoding='utf-8'):
    p = json.loads(line)
    if not p['space'] or not p['body']:
        continue
    direction = 'in' if p['dir'] == '<' else 'out'
    payload = bytes.fromhex(p['nullmap'] + p['body'])
    stats['packets'] += 1
    bits, pos = NullMap.decode(payload)
    r = Reader(payload[pos:], bits)
    cmds, err = [], None
    while not r.eof():
        start = r.p
        try:
            cmds.append(schema.read_command(r, direction, aliases[p['sock']]))
        except Exception as e:  # noqa: BLE001 - report and continue with the next packet
            mh = payload[pos + start + 8:pos + start + 16].hex() if direction == 'out' or not bits[r.bp - 1:r.bp] else '?'
            err = '%s: %s' % (schema.method_name(mh) if len(mh) == 16 else mh, e)
            break
    if err:
        stats['decode_fail'] += 1
        fails[err.split(':')[0]].append((p['sock'], p['dir'], len(payload), err))
        continue
    for c in cmds:
        methods[(direction, c['name'])] += 1
    left = bits[r.bp:]
    if any(left):
        stats['nonzero_leftover_bits'] += 1
    again = schema.encode_packet(cmds, direction)
    if again == payload:
        stats['exact'] += 1
    elif schema.encode_packet(cmds, direction, left) == payload:
        stats['exact_with_padding'] += 1
    else:
        stats['encode_mismatch'] += 1
        k = next((i for i in range(min(len(again), len(payload))) if again[i] != payload[i]), None)
        fails['mismatch ' + cmds[0]['name']].append((p['sock'], p['dir'], len(payload), 'first diff at %s' % k))
    if dump:
        dump.write(json.dumps({'t': p['t'], 'sock': p['sock'], 'space': p['space'], 'dir': p['dir'],
                               'commands': cmds}, ensure_ascii=False) + '\n')

print(dict(stats))
for k, v in sorted(fails.items(), key=lambda kv: -len(kv[1])):
    print('%4d  %s' % (len(v), k))
    for x in v[:2]:
        print('        ', x)
print('methods seen:', len(methods))
