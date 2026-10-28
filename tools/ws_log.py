"""Readable log of decoded packets using the ID table from proto_ids.py.

Each space packet body starts with objectId (i64) + methodId (i64) + args. A packet may hold several commands;
args are not decoded yet, so only the first command of a packet is named (the rest stays in the byte count).

usage: python -I ws_log.py <packets.jsonl> <proto_ids.json> <out.txt>
"""
import collections, json, re, sys

pk = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
ids = json.load(open(sys.argv[2], encoding='utf-8'))
models, methods = ids['models'], ids['methods']
CTRL = {1: 'HashRequest', 2: 'HashResponse', 3: 'OpenSpaceConnect', 32: 'OpenSpace/ClientLog'}


def label(mid):
    m = methods.get(mid)
    if not m:
        return '?' + mid
    model = models.get(m['model'] or '', {})
    mname = model.get('name') or (m['model'] and 'model_' + m['model'][-6:]) or 'model?'
    return '%s.%s%s' % (mname, m['name'] or mid[-6:], '' if m['dir'] == 'in' else ' (out)')


def strings(b, n=3):
    return [s.decode('utf-8', 'replace')[:60] for s in re.findall(rb'[\x20-\x7e\xd0\xd1\x80-\xbf]{5,}', b)][:n]


seen, known = collections.Counter(), collections.Counter()
t0 = pk[0]['t'] if pk else 0
with open(sys.argv[3], 'w', encoding='utf-8') as out:
    for p in pk:
        b = bytes.fromhex(p['body'])
        if not b:
            continue
        head = '%8.3f %s %-16s' % (p['t'] - t0, p['dir'], p['space'] or 'control')
        if p['space'] is None:
            out.write('%s %s %d B %s\n' % (head, CTRL.get(b[0], 'cmd%d' % b[0]), len(b), strings(b[1:], 2)))
            continue
        if len(b) < 16:
            out.write('%s raw %s\n' % (head, b.hex(' ')))
            continue
        obj, mid = b[:8].hex(), b[8:16].hex()
        seen[mid] += 1
        if mid in methods:
            known[mid] += 1
        out.write('%s obj=%s %s  %d B %s\n' % (head, obj.lstrip('0') or '0', label(mid), len(b) - 16, strings(b[16:])))
print('distinct method ids', len(seen), 'found in table', sum(1 for m in seen if m in methods),
      '| packets', sum(seen.values()), 'resolved', sum(known.values()))
print('unknown:', [m for m in seen if m not in methods][:15])
