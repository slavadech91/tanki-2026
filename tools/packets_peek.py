"""Peek at decoded packets: per space counts, first packets as hex, and printable strings found.

usage: python -I packets_peek.py <packets.jsonl> [space_or_all] [n=5]
"""
import collections, json, re, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
pk =[json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
want = sys.argv[2] if len(sys.argv) > 2 else 'all'
n = int(sys.argv[3]) if len(sys.argv) > 3 else 5
by = collections.OrderedDict()
for p in pk:
    by.setdefault(p['space'], []).append(p)
for sp, ps in by.items():
    if want != 'all' and sp != want:
        continue
    up = sum(1 for p in ps if p['dir'] == '>')
    print('\n== space %s: %d packets (%d up, %d down), %d bytes' % (sp, len(ps), up, len(ps) - up,
                                                                   sum(len(p['body']) // 2 for p in ps)))
    for p in ps[:n]:
        b = bytes.fromhex(p['body'])
        print('  %s len=%-6d %s' % (p['dir'], len(b), b[:40].hex(' ')))
    strings = collections.Counter()
    for p in ps:
        for s in re.findall(rb'[\x20-\x7e\xd0\xd1\x80-\xbf]{6,}', bytes.fromhex(p['body'])):
            strings[s.decode('utf-8', 'replace')[:70]] += 1
    print('  strings:', [s for s, _ in strings.most_common(25)])
