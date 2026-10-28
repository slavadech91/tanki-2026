"""Summarize a capture_ws.py JSONL: sockets, frame counts/sizes, first frames per socket as hex.

usage: python -I ws_summary.py <capture.jsonl> [first_n=6]
"""
import base64, collections, json, sys

recs = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
first_n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
socks = collections.OrderedDict()
for r in recs:
    s = socks.setdefault(r['id'], {'url': None, 'sent': [], 'recv': [], 't0': r['t'], 'closed': False})
    if r['ev'] == 'created':
        s['url'] = r['url']
    elif r['ev'] in ('sent', 'recv'):
        data = base64.b64decode(r['b64']) if 'b64' in r else r['text'].encode()
        s[r['ev']].append((r['t'], r.get('op'), data))
    elif r['ev'] == 'closed':
        s['closed'] = True
print('records', len(recs), 'sockets', len(socks))
for sid, s in socks.items():
    sent, recv = s['sent'], s['recv']
    print('\n== socket %s %s closed=%s' % (sid, s['url'], s['closed']))
    print('   sent %d frames %d B, recv %d frames %d B, opcodes %s' % (
        len(sent), sum(len(d) for _, _, d in sent), len(recv), sum(len(d) for _, _, d in recv),
        dict(collections.Counter(op for _, op, _ in sent + recv))))
    merged = sorted([(t, '>', op, d) for t, op, d in sent] + [(t, '<', op, d) for t, op, d in recv])
    for t, dirn, op, d in merged[:first_n]:
        print('   %s %.3f len=%-6d %s' % (dirn, t - s['t0'], len(d), d[:48].hex(' ')))
