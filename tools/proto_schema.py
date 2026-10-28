"""Extract the binary protocol schema of the Tanki HTML5 client from the minified bundle.

What it reads (see server-notes/protocol-codecs.md):
  - codec registrations `protocol.p7g(<CodecInfo>, codec)` / `protocol.q7g(<KClass>, codec)`
  - CodecInfo constructors from module 24635: TypeCodecInfo(e) EnumCodecInfo(b) ListCodecInfo(c) MapCodecInfo(d)
  - generated struct codecs: `u7h` sets `this.<p>=t.r7g(<CodecInfo>)`, getter `function G(t){var n=t.<p>;...
    ("codec_<field>")}`, `t7h` reads fields in wire order: `G(this).t7h(t)` or inline `t.e7h_1.<read>()`
  - generated enum codecs: `var n=t.e7h_1.r2u();switch(n){case 0:return A();...}` (int code)
  - models: ctor `this.<f>=new Long(lo,hi)`, `vay()`: `modelRegistry.n7o(this.<f>, protocol.r7g(<CC info>))`
  - incoming methods: `u7j(t,n)` branches `(t,this.<methodField>)` reading `_<method>_<arg>Codec` codecs
  - outgoing methods: server proxy created in `vay()`, its methods write args with `this.<c>.s7h(buf, arg)`

usage: python -I proto_schema.py <bundle.js> <out.json>
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kjs import Bundle, match_brace, split_top, PROTO, STDLIB

PRIM_KEYS = {'pb': 'boolean', 'qb': 'byte', 'rb': 'short', 'sb': 'int', 'ub': 'float', 'vb': 'double',
             'xb': 'string', 'mb': 'any'}
READS = {'xy': 'byte', 'p2u': 'byte', 'u2t': 'short', 'q2u': 'short', 'v2t': 'int', 'r2u': 'int',
         'w2t': 'long', 's2u': 'long', 'x2t': 'float', 't2u': 'float', 'y2t': 'double', 'u2u': 'double'}
WRITES = {'z2t': 'byte', 'k2u': 'byte', 'e2u': 'short', 'l2u': 'short', 'f2u': 'int', 'm2u': 'int',
          'h2u': 'long', 'p1s': 'long', 'i2u': 'float', 'n2u': 'float', 'j2u': 'double', 'o2u': 'double'}
# codecs whose wire format is written by hand (checked against the bundle, see protocol-codecs.md)
BASE = {(PROTO, 'Xt'): 'long', (PROTO, 'Qt'): 'string', (PROTO, 'tn'): 'boolean', (PROTO, 'nn'): 'byte',
        (PROTO, 'sn'): 'short', (PROTO, 'un'): 'int', (PROTO, 'en'): 'float', (PROTO, 'rn'): 'double',
        (PROTO, 'Vt'): 'bytes', ('61860', 'cr'): 'long', ('61860', 'Ne'): 'long_ints', ('71105', 'ds'): 'long'}
SPECIAL = {('45686', 'lt'): 'ModelData', ('45686', 'wt'): 'ObjectsData', ('45686', 'jt'): 'ObjectsDependencies',
           ('61860', 'or'): 'ControlCommand', ('61860', 'fr'): 'SpaceCommand', ('87072', 'T5'): 'TankState'}

b = Bundle(sys.argv[1])


def export_gid(mid, key):
    mod = b.modules.get(mid)
    if mod is None or mod.exports.get(key) is None:
        return (mid, '$' + key)
    return b.resolve(mid, mod.exports[key])


DESC_KIND = {b.resolve(PROTO, 'gn'): 'type', b.resolve(PROTO, 'vn'): 'enum', b.resolve(PROTO, 'pn'): 'list',
             b.resolve(PROTO, 'wn'): 'map', b.resolve(PROTO, 'dn'): 'set', b.resolve(PROTO, 'an'): 'array'}
LONG_CLASS = export_gid(STDLIB, 'sj')
BYTES_CLASS = export_gid('72834', 'a')
PRIMS = export_gid(STDLIB, 'w4')
GET_KCLASS = export_gid(STDLIB, 'nf')


def gid(x):
    return '%s:%s' % x


def imp(mid, alias):
    """Resolved global id of an alias/local name in module mid."""
    return b.resolve(mid, alias)


def kclass(mid, expr):
    expr = expr.strip()
    m = re.fullmatch(r'([\w$]+)\(\)\.([\w$]+)\(\)', expr)
    if m and imp(mid, m.group(1)) == PRIMS:
        return ('prim', PRIM_KEYS.get(m.group(2), '?' + m.group(2)))
    m = re.fullmatch(r'([\w$]+)\(([\w$]+)\)', expr)
    if m and imp(mid, m.group(1)) == GET_KCLASS:
        c = imp(mid, m.group(2))
        if c == LONG_CLASS:
            return ('prim', 'long')
        if c == BYTES_CLASS:
            return ('prim', 'bytes')
        return ('class', c)
    return ('?', expr)


def desc(mid, expr):
    """Parse a CodecInfo expression into a dict."""
    expr = expr.strip()
    m = re.fullmatch(r'new ([\w$]+)\((.*)\)', expr, re.S)
    if not m:
        return {'k': '?', 'expr': expr}
    kind = DESC_KIND.get(imp(mid, m.group(1)))
    args = split_top(m.group(2))
    opt = args[-1].strip() == '!0'
    if kind in ('type', 'enum'):
        c = kclass(mid, args[0])
        if c[0] == 'prim':
            return {'k': 'prim', 't': c[1], 'opt': opt}
        if c[0] == 'class':
            return {'k': kind, 'cls': c[1], 'opt': opt}
        return {'k': '?', 'expr': expr}
    if kind in ('list', 'set', 'array'):
        return {'k': kind, 'of': desc(mid, args[0]), 'opt': opt}
    if kind == 'map':
        return {'k': 'map', 'key': desc(mid, args[0]), 'val': desc(mid, args[1]), 'opt': opt}
    return {'k': '?', 'expr': expr}


def codec_info_call(mid, call):
    """`t.r7g(<desc>)`, `t.s7g(<kclass>,<opt>)` or `t.t7g(<kclass>)` -> desc."""
    m = re.fullmatch(r'(?:[\w$]+(?:\([\w$]*\))?)\.(r7g|s7g|t7g)\((.*)\)', call.strip(), re.S)
    if not m:
        return None
    if m.group(1) == 'r7g':
        return desc(mid, m.group(2))
    args = split_top(m.group(2))
    c = kclass(mid, args[0])
    opt = len(args) > 1 and args[1].strip() == '!0'
    if c[0] == 'prim':
        return {'k': 'prim', 't': c[1], 'opt': opt}
    if c[0] == 'class':
        return {'k': 'type', 'cls': c[1], 'opt': opt}
    return {'k': '?', 'expr': call}


# ------------------------------------------------------------------ registrations
REG = {}          # ('type'|'enum', class gid) -> codec gid | ('alias', kind, class gid)
REG_ALL = {}
RES_TYPES = {}    # resource class gid -> type id expression
REG_SRC = {}
for mid, mod in b.modules.items():
    t = mod.text
    for m in re.finditer(r'\.(p7g|q7g)\(', t):
        j = m.end() - 1
        try:
            e = match_brace(t, j)
        except ValueError:
            continue
        args = split_top(t[j + 1:e - 1])
        if len(args) != 2:
            continue
        cexpr = args[1].strip()
        cm = re.fullmatch(r'new ([\w$]+)(?:\(\))?', cexpr)
        ali = codec_info_call(mid, cexpr) if re.match(r'[\w$]+(?:\([\w$]*\))?\.(?:r7g|s7g|t7g)\(', cexpr) else None
        if cm:
            codec = imp(mid, cm.group(1))
        elif ali:
            codec = ('alias', ali['k'] if ali['k'] != 'prim' else 'prim', ali.get('cls') or ali.get('t'))
        else:
            var = re.fullmatch(r'(?:[\w$]+\()?([\w$]+)\)?', cexpr)
            if not var:
                continue
            last = None
            lo = max(0, j - 600)
            for vm in re.finditer(r'(?<![\w$.])' + re.escape(var.group(1)) + r'=new ([\w$]+)(?![\w$])', t[lo:j]):
                last = vm
            if not last:
                continue
            codec = imp(mid, last.group(1))
        if m.group(1) == 'q7g':
            c = kclass(mid, args[0])
            if c[0] != 'class':
                key = ('prim', c[1])
            else:
                key = ('type', c[1])
        else:
            d = desc(mid, args[0])
            if d['k'] in ('type', 'enum'):
                key = (d['k'], d['cls'])
            elif d['k'] == 'prim':
                key = ('prim', d['t'])
            else:
                continue
        if 'opt' in args[0] and False:
            pass
        REG_ALL.setdefault(key, []).append(codec)
        REG_SRC.setdefault(key, (mid, mod.pos(j)))
    # resource classes: resourceRegistry.y84(typeId, KClass, ctor) also registers `new ds(registry)` (reads a long id)
    for m in re.finditer(r'\.y84\(([^,]+),([\w$]+)\(([\w$]+)\),', mod.text):
        if imp(mid, m.group(2)) == GET_KCLASS:
            c = imp(mid, m.group(3))
            REG_ALL.setdefault(('type', c), []).append(('71105', 'ds'))
            RES_TYPES[gid(c)] = m.group(1)
# a later registration replaces an earlier one (map put); hand-written codecs are installed after the generated ones
for key, codecs in REG_ALL.items():
    hand = [c for c in codecs if c in BASE or c in SPECIAL]
    REG[key] = hand[-1] if hand else codecs[-1]


# ------------------------------------------------------------------ class helpers
def class_name(cg):
    """Data class name from its toString ("Name [" / "Name(" / "[Name ")."""
    mod = b.modules.get(cg[0])
    if not mod:
        return None
    ts = mod.method_body(cg[1], 'toString')
    if not ts:
        return None
    m = re.search(r'"\[?([A-Z][\w]*)(?: \[| \(|\(| )', ts)
    return m.group(1) if m else None


def prop_names(cg, depth=0):
    """property -> field name of a data class (getters and toString, parents included)."""
    mod = b.modules.get(cg[0])
    out = {}
    if not mod or depth > 5:
        return out
    getters = {}
    for meth in mod.methods.get(cg[1], {}):
        body = mod.method_body(cg[1], meth) or ''
        m = re.fullmatch(r'var t=this\.([\w$]+);if\(null!=t\)return t;[\w$]+\("(\w+)"\)', body)
        if m:
            getters[meth] = m.group(1)
            out[m.group(1)] = m.group(2)
    ts = mod.method_body(cg[1], 'toString') or ''
    for m in re.finditer(r'(\w+) ?= ?"\+', ts):
        rest = ts[m.end():]
        k = rest.find('+"')
        name, ex = m.group(1), rest[:k] if k != -1 else rest
        g = re.search(r'this\.([\w$]+)\(\)', ex)
        if g and g.group(1) in getters:
            out.setdefault(getters[g.group(1)], name)
            continue
        p = re.search(r'this\.([\w$]+_\d+)', ex)
        if p:
            out.setdefault(p.group(1), name)
    for pm in re.finditer(r'([\w$]+)\(([\w$]+)\)\.toString\.call\(this\)', ts):
        parent = b.resolve(cg[0], pm.group(2))
        if parent and parent != cg:
            for k, v in prop_names(parent, depth + 1).items():
                out.setdefault(k, v)
    return out


def getter_fields(mod):
    """codec getter function -> (property, field name)."""
    out = {}
    for name, (s, e) in mod.funcs.items():
        body = mod.text[s:e]
        m = re.fullmatch(r'function [\w$]+\(t\)\{var n=t\.([\w$]+);if\(null!=n\)return n;[\w$]+\("([\w$]+)"\)\}', body)
        if m:
            out[name] = (m.group(1), m.group(2))
    return out


GETTERS = {mid: getter_fields(mod) for mid, mod in b.modules.items()}


def u7h_props(mid, mod, cls):
    """codec property -> desc from u7h."""
    out = {}
    body = mod.method_body(cls, 'u7h') or ''
    for st in split_top(body):
        m = re.fullmatch(r'this\.([\w$]+)=(.+)', st.strip(), re.S)
        if m:
            d = codec_info_call(mid, m.group(2))
            if d:
                out[m.group(1)] = d
    return out


EVENT = re.compile(r'([\w$]+)\(this\)\.t7h\(t\)'
                   r'|function\(t\)\{var n=t\.([\w$]+);if\(null!=n\)return n;[\w$]+\("([\w$]+)"\)\}\(this\)\.t7h\(t\)'
                   r'|(?:([\w$]+)\.([\w$]+)=)?t\.e7h_1\.([\w$]+)\(\)')


def analyze_codec(cg):
    """-> type definition dict."""
    if cg in BASE:
        return {'kind': 'prim', 't': BASE[cg]}
    if cg in SPECIAL:
        return {'kind': 'special', 'name': SPECIAL[cg]}
    mod = b.modules.get(cg[0])
    if not mod or 't7h' not in mod.methods.get(cg[1], {}):
        return {'kind': 'unknown', 'codec': gid(cg)}
    mid, cls = cg
    body = mod.method_body(cls, 't7h')
    if re.match(r'var n=t\.e7h_1\.r2u\(\);(switch|if)', body):
        codes = {}
        for m in re.finditer(r'(?:case (-?\d+):|(-?\d+)===n\))return ([\w$]+)\(\)(?:,([\w$]+))?', body):
            codes[int(m.group(1) or m.group(2))] = (m.group(3), m.group(4))
        return {'kind': 'enum', 'codes': codes, 'mid': mid}
    if re.search(r'do\{|for\(|while\(|switch\(|g7h_1|h7h_1|f7h_1', body):
        return {'kind': 'unknown', 'codec': gid(cg), 'body': body[:200]}
    props = u7h_props(mid, mod, cls)
    fields = []
    for m in EVENT.finditer(body):
        if m.group(1):
            g = GETTERS[mid].get(m.group(1))
            if not g:
                return {'kind': 'unknown', 'codec': gid(cg), 'why': 'getter ' + m.group(1)}
            prop, cname = g
            d = props.get(prop, {'k': '?', 'prop': prop})
            fields.append({'name': cname[6:] if cname.startswith('codec_') else cname, 'type': d})
        elif m.group(2):
            d = props.get(m.group(2), {'k': '?', 'prop': m.group(2)})
            fields.append({'name': m.group(3), 'type': d})
        else:
            rd = READS.get(m.group(6))
            if not rd:
                return {'kind': 'unknown', 'codec': gid(cg), 'why': 'read ' + m.group(6)}
            fields.append({'name': None, 'prop': m.group(5), 'type': {'k': 'prim', 't': rd, 'opt': False}})
    return {'kind': 'struct', 'fields': fields}


def enum_entries(cg):
    """ordinal -> entry name, from `new <Enum>("NAME",ord` in the enum's module."""
    mod = b.modules.get(cg[0])
    out = {}
    if not mod:
        return out
    for m in re.finditer(r'(?<![\w$])([\w$]+)=new ' + re.escape(cg[1]) + r'\("(\w+)",(\d+)', mod.text):
        out[int(m.group(3))] = (m.group(1), m.group(2))
    return out


# ------------------------------------------------------------------ build types
TYPES = {}      # name -> definition
NAME_OF = {}    # class gid -> type name


FIXED_FIELDS = {'Vector3': ['x', 'y', 'z']}    # toString prints "Vector3 (x, y, z)" without names
FIXED_NAMES = {('61860', 'xr'): 'GameObject', ('71105', '$v'): 'ImageResource', ('71105', 'Ev'): 'ImageX20Resource',
               ('71105', 'Nv'): 'SvgImageResource', ('71105', 'Hh'): 'LightmapModelResource',
               ('71105', 'ca'): 'VideoResource'}


def type_name(cg, kind):
    if cg in NAME_OF:
        return NAME_OF[cg]
    n = FIXED_NAMES.get(cg) or (('Resource%s_%s' % (RES_TYPES[gid(cg)], cg[1])) if gid(cg) in RES_TYPES else None) or class_name(cg) or ('Enum_%s_%s' % cg if kind == 'enum' else 'T_%s_%s' % cg)
    base, k = n, 2
    while n in TYPES:
        n = '%s_%d' % (base, k)
        k += 1
    NAME_OF[cg] = n
    TYPES[n] = None
    return n


def build(d):
    """Turn a parsed desc into a schema TypeRef, defining referenced types on the way."""
    k = d['k']
    if k == 'prim':
        return {'t': d['t'], 'opt': d['opt']} if d['opt'] else {'t': d['t']}
    if k in ('list', 'set', 'array'):
        r = {'t': k, 'of': build(d['of'])}
    elif k == 'map':
        r = {'t': 'map', 'key': build(d['key']), 'val': build(d['val'])}
    elif k in ('type', 'enum'):
        cg = d['cls']
        codec = REG.get((k, cg)) or REG.get(('type', cg)) or REG.get(('enum', cg))
        while codec and codec[0] == 'alias':
            codec = REG.get((codec[1], codec[2])) if codec[1] != 'prim' else (PROTO, '?prim')
        if codec is None:
            r = {'t': 'unregistered', 'cls': gid(cg)}
        else:
            name = define(cg, codec, k)
            r = {'t': name}
    else:
        r = {'t': 'unparsed', 'expr': d.get('expr') or d.get('prop')}
    if d.get('opt'):
        r['opt'] = True
    return r


def define(cg, codec, kind):
    if cg in NAME_OF and TYPES.get(NAME_OF[cg]) is not None:
        return NAME_OF[cg]
    name = type_name(cg, kind)
    a = analyze_codec(codec)
    TYPES[name] = {'kind': 'pending'}
    if a['kind'] == 'prim':
        TYPES[name] = {'kind': 'alias', 'of': a['t'], 'cls': gid(cg)}
    elif a['kind'] == 'special':
        TYPES[name] = {'kind': 'special', 'codec': a['name'], 'cls': gid(cg)}
    elif a['kind'] == 'enum':
        ents = enum_entries(cg)
        acc = {}
        mod = b.modules.get(a['mid'])
        values = {}
        for code, (fn, var) in sorted(a['codes'].items()):
            entry = None
            if var:
                entry = next((nm for o, (v, nm) in ents.items() if v == var), None)
            if entry is None and mod:
                f = mod.func_text(fn) or ''
                vm = re.search(r'return (?:[\w$]+\(\),)?([\w$]+)\}$', f)
                if vm:
                    entry = next((nm for o, (v, nm) in ents.items() if v == vm.group(1)), None)
            values[code] = entry or ('?' + fn)
        TYPES[name] = {'kind': 'enum', 'values': values, 'cls': gid(cg)}
    elif a['kind'] == 'struct':
        names = prop_names(cg)
        fields = []
        for f in a['fields']:
            fname = f['name'] or names.get(f.get('prop'), f.get('prop'))
            fields.append({'name': fname, 'type': build(f['type'])})
        for f, fixed in zip(fields, FIXED_FIELDS.get(name, [])):
            f['name'] = fixed
        TYPES[name] = {'kind': 'struct', 'fields': fields, 'cls': gid(cg), 'codec': gid(codec)}
    else:
        TYPES[name] = dict(a, cls=gid(cg), kind='unknown')
    return name


LONG = r'new [\w$]+\((-?\d{1,10}),(-?\d{1,10})\)'


def as_id(lo, hi):
    return '%016x' % (((int(hi) & 0xFFFFFFFF) << 32) | (int(lo) & 0xFFFFFFFF))


def ctor_ids(mod, cls):
    """this.<f>=new Long(lo,hi) in a class constructor -> {field: id}."""
    body = mod.func_text(cls) or ''
    return {m.group(1): as_id(m.group(2), m.group(3)) for m in re.finditer(r'this\.([\w$]+)=' + LONG, body)}


MODELS, METHODS = {}, {}
for mid, mod in b.modules.items():
    for cls, meths in mod.methods.items():
        if 'vay' not in meths:
            continue
        vay = mod.method_body(cls, 'vay')
        ids = ctor_ids(mod, cls)
        model_id = None
        # model data (CC)
        for m in re.finditer(r'\.n7o\(this\.([\w$]+),', vay):
            j = m.end() - len('this.' + m.group(1) + ',') - 1
            e = match_brace(vay, j)
            args = split_top(vay[j + 1:e - 1])
            model_id = ids.get(m.group(1))
            d = codec_info_call(mid, args[1])
            if model_id and d:
                MODELS.setdefault(model_id, {})['cc'] = build(d)
                MODELS[model_id]['cls'] = gid((mid, cls))
        # incoming methods
        props = {}
        for st in split_top(vay):
            m = re.fullmatch(r'this\.([\w$]+)=(.+)', st.strip(), re.S)
            if m:
                d = codec_info_call(mid, m.group(2))
                if d:
                    props[m.group(1)] = d
        u7j = mod.method_body(cls, 'u7j') or ''
        branches = list(re.finditer(r'\(t,this\.([\w$]+)\)', u7j))
        x57 = re.search(r'return this\.([\w$]+)', mod.method_body(cls, 'x57') or '')
        own = None
        if x57:
            al = re.search(r'this\.' + re.escape(x57.group(1)) + r'=this\.([\w$]+)', mod.func_text(cls) or '')
            own = ids.get(al.group(1) if al else x57.group(1))
        for k, bm in enumerate(branches):
            seg = u7j[bm.end():branches[k + 1].start() if k + 1 < len(branches) else len(u7j)]
            mth = ids.get(bm.group(1))
            if not mth:
                continue
            args, mname = [], None
            for am in re.finditer(r'function\(t\)\{var n=t\.([\w$]+);if\(null!=n\)return n;[\w$]+\("_(\w+?)_(\w+)Codec"\)\}'
                                  r'\(this\)\.t7h\(n\)|n\.e7h_1\.([\w$]+)\(\)', seg):
                if am.group(1):
                    mname = am.group(2)
                    args.append({'name': am.group(3), 'type': build(props.get(am.group(1), {'k': '?', 'prop': am.group(1)}))})
                else:
                    args.append({'name': None, 'type': {'t': READS.get(am.group(4), '?' + am.group(4))}})
            METHODS[mth] = {'dir': 'in', 'model': own, 'name': mname, 'args': args}
        # outgoing (server proxy built in vay)
        pm = re.search(r'=\(t=this,n=[\w$]+\([\w$]+\(([\w$]+)\)\),\1\.call\(n\),(.*?),n\)', vay)
        if pm:
            pcls = pm.group(1)
            pprops = {}
            for st in split_top(pm.group(2)):
                m = re.fullmatch(r'n\.([\w$]+)=(.+)', st.strip(), re.S)
                if m:
                    d = codec_info_call(mid, m.group(2).replace('(n)', '(x)'))
                    if d:
                        pprops[m.group(1)] = d
            pids = ctor_ids(mod, pcls)
            for meth in mod.methods.get(pcls, {}):
                body = mod.method_body(pcls, meth) or ''
                cm = re.search(r'new [\w$]+\([\w$]+\(\)\.k7k\(\)\.x57\(\),this\.([\w$]+),', body)
                if not cm or cm.group(1) not in pids:
                    continue
                args = []
                for am in re.finditer(r'this\.([\w$]+)\.s7h\(this\.[\w$]+,[\w$]+\)|this\.[\w$]+\.e7h_1\.([\w$]+)\([\w$]+\)', body):
                    if am.group(1):
                        args.append({'name': None, 'type': build(pprops.get(am.group(1), {'k': '?', 'prop': am.group(1)}))})
                    else:
                        args.append({'name': None, 'type': {'t': WRITES.get(am.group(2), '?' + am.group(2))}})
                METHODS[pids[cm.group(1)]] = {'dir': 'out', 'model': own, 'name': None, 'args': args, 'proxy': meth}
        if own:
            MODELS.setdefault(own, {}).setdefault('cls', gid((mid, cls)))

# names from the earlier ID table (outgoing / model names), when available
try:
    old = json.load(open(sys.argv[2].replace('proto_schema.json', 'proto_ids.json'), encoding='utf-8'))
    for k, v in old['methods'].items():
        if k in METHODS and not METHODS[k]['name'] and v.get('name'):
            METHODS[k]['name'] = v['name']
    for k, v in old['models'].items():
        if k in MODELS and v.get('name'):
            MODELS[k]['name'] = v['name']
except OSError:
    pass

for k, v in MODELS.items():
    if 'cc' in v and 'name' not in v:
        v['name'] = v['cc'].get('t')

out = {'types': TYPES, 'models': MODELS, 'methods': METHODS,
       'resource_types': {NAME_OF.get(b.resolve(*k.split(':')), k): v for k, v in RES_TYPES.items()}}
json.dump(out, open(sys.argv[2], 'w', encoding='utf-8'), indent=1, sort_keys=True)

kinds = {}
for v in TYPES.values():
    kinds[v['kind']] = kinds.get(v['kind'], 0) + 1
print('types', len(TYPES), kinds)
print('models', len(MODELS), 'with CC', sum(1 for v in MODELS.values() if 'cc' in v))
print('methods in', sum(1 for v in METHODS.values() if v['dir'] == 'in'),
      'out', sum(1 for v in METHODS.values() if v['dir'] == 'out'))
bad = [(n, v) for n, v in TYPES.items() if v['kind'] == 'unknown']
for n, v in bad[:20]:
    print('  unknown', n, {k: x for k, x in v.items() if k != 'kind'})


def walk(r, acc):
    if isinstance(r, dict):
        if r.get('t') in ('unregistered', 'unparsed') or str(r.get('t', '')).startswith('?'):
            acc.append(r)
        for x in r.values():
            walk(x, acc)
    elif isinstance(r, list):
        for x in r:
            walk(x, acc)


acc = []
walk(out, acc)
print('unresolved refs', len(acc))
for r in acc[:15]:
    print('  ', r)
