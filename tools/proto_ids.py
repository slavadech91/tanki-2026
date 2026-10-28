"""Extract model / method IDs (Kotlin Long constants) from the minified bundle and name what can be named.

Facts used (see server-notes/protocol.md):
  - Long constant: `new <alias>(lo, hi)` -> id = (hi << 32) | lo (both as u32)
  - incoming (server->client) methods are registered as `<svc>.l7o(new X(model), new X(method))`
  - a model's dispatch `u7j(t, n)` compares `t` with `this.<field>` and reads args with codecs whose lazy-init
    error string is "_<method>_<arg>Codec" -> gives the method name
  - model constructor data classes print "<Name>CC [" in toString -> nearest one names the model (heuristic)

usage: python -I proto_ids.py <bundle.js> <out.json>
"""
import bisect, json, re, sys

src = open(sys.argv[1], encoding='utf-8').read()
LONG = re.compile(r'new [A-Za-z$_][\w$]{0,3}\((-?\d{1,10}),(-?\d{1,10})\)')


def as_id(lo, hi):
    return '%016x' % (((int(hi) & 0xFFFFFFFF) << 32) | (int(lo) & 0xFFFFFFFF))


# 1. registrations: model -> incoming methods
reg = {}
for m in re.finditer(r'\.l7o\(' + LONG.pattern + ',' + LONG.pattern + r'\)', src):
    reg.setdefault(as_id(m.group(1), m.group(2)), []).append(as_id(m.group(3), m.group(4)))
method_model = {meth: model for model, ms in reg.items() for meth in ms}

# 2. field assignments `this.F=new X(lo,hi)` -> id, positions
fields = {}   # id -> list of (pos, field)
for m in re.finditer(r'this\.([\w$]+)=' + LONG.pattern, src):
    fields.setdefault(as_id(m.group(2), m.group(3)), []).append((m.start(), m.group(1)))

# 3. CC names for model naming
cc = [(m.start(), m.group(1)) for m in re.finditer(r'"([A-Z][A-Za-z0-9]+CC) \[', src)]
cc_pos = [p for p, _ in cc]


def nearest_cc(pos, window=60000):
    i = bisect.bisect_left(cc_pos, pos)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(cc) and abs(cc[j][0] - pos) < window:
            if best is None or abs(cc[j][0] - pos) < abs(best[0] - pos):
                best = cc[j]
    return best[1] if best else None


def incoming_name(field, start):
    """Find `(t,this.<field>)` dispatch after the constructor and the first _<name>_<arg>Codec before the next branch."""
    for m in re.finditer(r'\(t,this\.' + re.escape(field) + r'\)', src[start:start + 2000000]):
        a = start + m.end()
        nxt = src.find('(t,this.', a)
        seg = src[a:nxt if nxt != -1 and nxt - a < 3000 else a + 3000]
        c = re.search(r'"_([A-Za-z0-9]+)_[A-Za-z0-9]+Codec"', seg)
        if c:
            return c.group(1)
        return None
    return None


def nearest(pattern, pos, window=400000):
    """Match of `pattern` closest to pos (minified names repeat across modules, so take the closest)."""
    lo = max(0, pos - window)
    best = None
    for m in re.finditer(pattern, src[lo:pos + window]):
        if best is None or abs(lo + m.start() - pos) < abs(lo + best.start() - pos):
            best = m
    return best


def model_cc_name(pos, field):
    """Model ctor `function X(){... this.<field>=new L(..) ... this.vay() ...}`; X.prototype.vay registers the
    constructor-data class: `.n7o(this.<field>, ...r7g(new P(b(<CC>),!1)))`; that class's toString gives the name."""
    fn = src.rfind('function ', 0, pos)
    m = re.match(r'function ([\w$]+)\(', src[fn:fn + 60])
    if not m:
        return None
    ctor = m.group(1)
    v = nearest(r'\(' + re.escape(ctor) + r'\)\.vay=function\(\)\{', pos)
    if not v:
        return None
    body = src[v.end():v.end() + 4000]
    c = re.search(r'n7o\(this\.' + re.escape(field) + r',[\w$]+\(this\)\.r7g\(new [\w$]+\([\w$]+\(([\w$]+)\)', body)
    if not c:
        return None
    t = nearest(r'\(' + re.escape(c.group(1)) + r'\)\.toString=function\(\)\{var t="([A-Za-z0-9]+) \[', v.start())
    return t.group(1) if t else None


table = {'models': {}, 'methods': {}}
for model, meths in reg.items():
    pos, field = fields.get(model, [(None, None)])[0]
    name = model_cc_name(pos, field) if pos else None
    table['models'][model] = {'name': name, 'pos': pos, 'in': meths}
    for meth in meths:
        name = None
        for p, f in fields.get(meth, []):
            name = incoming_name(f, p) or name
        table['methods'][meth] = {'model': model, 'dir': 'in', 'name': name,
                                  'pos': fields.get(meth, [(None,)])[0][0]}

# outgoing: Long field constants in proxy classes (a proxy method sends `new <Cmd>(<object>, this.<field>, buf)`).
# The model's vay() creates its proxy: `this.<x>=(t=this,n=L(w(<Proxy>)),<Proxy>.call(n),...)`.
def ctor_name(pos):
    fn = src.rfind('function ', 0, pos)
    m = re.match(r'function ([\w$]+)\(', src[fn:fn + 60])
    return m.group(1) if m else None


model_ctors = [(v['pos'], ctor_name(v['pos']), k) for k, v in table['models'].items() if v['pos'] is not None]


def owner_model(p):
    proxy = ctor_name(p)
    if not proxy:
        return None
    v = nearest(r'\(([\w$]+)\)\.vay=function\(\)\{var t,n;[^{}]{0,300}?[^\w$]' + re.escape(proxy) + r'\.call\(n\)', p)
    if not v:
        return None
    cands = [(abs(mpos - v.start()), mid) for mpos, cname, mid in model_ctors if cname == v.group(1)]
    return min(cands)[1] if cands else None


for mid, occ in fields.items():
    if mid in table['methods'] or mid in table['models']:
        continue
    for p, f in occ:
        # prototype methods can sit far from the constructor in Kotlin/JS output
        if re.search(r',this\.' + re.escape(f) + r',', src[p:p + 2000000]) is None:
            continue
        table['methods'][mid] = {'model': owner_model(p), 'dir': 'out', 'name': None, 'pos': p}
        if table['methods'][mid]['model']:
            table['models'][table['methods'][mid]['model']].setdefault('out', []).append(mid)
        break

# models without constructor data: name them by their incoming methods
for k, v in table['models'].items():
    if not v['name']:
        names = [table['methods'][m]['name'] for m in v['in'] if table['methods'][m]['name']]
        v['name'] = ('M[' + ','.join(names[:2]) + ']') if names else None
json.dump(table, open(sys.argv[2], 'w', encoding='utf-8'), indent=1)
named = sum(1 for v in table['methods'].values() if v['name'])
print('models', len(table['models']), 'with CC name', sum(1 for v in table['models'].values() if v['name']))
print('out methods with owner model', sum(1 for v in table['methods'].values() if v['dir'] == 'out' and v['model']))
print('methods', len(table['methods']), 'in', sum(1 for v in table['methods'].values() if v['dir'] == 'in'),
      'out', sum(1 for v in table['methods'].values() if v['dir'] == 'out'), 'named', named)
