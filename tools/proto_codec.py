"""Read and write Tanki HTML5 protocol packets using the schema made by proto_schema.py.

Wire format (server-notes/protocol-codecs.md):
  packet  = header | null map | commands...      (header handled by ws_decode.py / replay_server.py)
  command = [server->client: 1 null-map bit: 1 -> alias byte, 0 -> objectId i64 + methodId i64]
            [client->server: objectId i64 + methodId i64] | arguments
  optional values take one null-map bit (1 = null) before the value; all bits of a packet share one map.

Values in decoded form: ids as 16-hex strings, numbers as int/float, enums as entry names, structs as dicts
in field order, lists as lists, maps as [[key, value], ...], bytes as hex strings, null as None.

usage (library): from proto_codec import Schema; s = Schema(path); s.decode_packet(nullmap+body, 'in', aliases)
"""
import json, math, struct


class NullMap:
    @staticmethod
    def decode(data, pos=0):
        """-> (list of bits, position after the map)."""
        r = data[pos]
        pos += 1
        if r & 0x80:
            n = r & 63
            if r & 0x40:
                n = (n << 16) | (data[pos] << 8) | data[pos + 1]
                pos += 2
            raw = data[pos:pos + n]
            pos += n
            return [(raw[i >> 3] >> (7 - (i & 7))) & 1 for i in range(n * 8)], pos
        extra = (r & 0x60) >> 5
        bits = [(r >> (4 - i)) & 1 for i in range(5)]
        for k in range(extra):
            b = data[pos]
            pos += 1
            bits += [(b >> (7 - i)) & 1 for i in range(8)]
        return bits, pos

    @staticmethod
    def encode(bits):
        w = len(bits)
        raw = bytearray((w + 7) // 8 or 1)
        for i, v in enumerate(bits):
            if v:
                raw[i >> 3] |= 1 << (7 - (i & 7))
        if w <= 29:
            extra = 0 if w <= 5 else 1 if w <= 13 else 2 if w <= 21 else 3
            raw += bytes(4)
            out = bytearray([(raw[0] >> 3) + (extra << 5)])
            for k in range(extra):
                out.append(((raw[k + 1] >> 3) + (raw[k] << 5)) & 0xFF)
            return bytes(out)
        n = (w + 7) // 8
        if w <= 504:
            return bytes([0x80 + n]) + bytes(raw[:n])
        v = n + 0xC00000
        return bytes([v >> 16 & 0xFF, v >> 8 & 0xFF, v & 0xFF]) + bytes(raw[:n])


class Reader:
    def __init__(self, data, bits):
        self.d, self.p, self.bits, self.bp = data, 0, bits, 0

    def bit(self):
        if self.bp >= len(self.bits):
            raise ValueError('null map exhausted at bit %d' % self.bp)
        v = self.bits[self.bp]
        self.bp += 1
        return v

    def _u(self, fmt, n):
        if self.p + n > len(self.d):
            raise ValueError('read past end at %d (+%d of %d)' % (self.p, n, len(self.d)))
        v = struct.unpack_from(fmt, self.d, self.p)[0]
        self.p += n
        return v

    def byte(self): return self._u('>b', 1)
    def short(self): return self._u('>h', 2)
    def int(self): return self._u('>i', 4)
    def long(self): return self._u('>q', 8)
    def float(self): return self._u('>f', 4)
    def double(self): return self._u('>d', 8)
    def boolean(self): return self.byte() != 0

    def raw(self, n):
        if self.p + n > len(self.d):
            raise ValueError('read past end')
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def length(self):
        n = self.byte() & 0xFF
        if not n & 0x80:
            return n
        i = self.byte() & 0xFF
        if n & 0x40:
            return ((n & 63) << 16) + (i << 8) + (self.byte() & 0xFF)
        return ((n & 63) << 8) + i

    def eof(self):
        return self.p >= len(self.d)


class Writer:
    def __init__(self):
        self.d, self.bits = bytearray(), []

    def bit(self, v): self.bits.append(1 if v else 0)
    def byte(self, v): self.d += struct.pack('>b', v)
    def short(self, v): self.d += struct.pack('>h', v)
    def int(self, v): self.d += struct.pack('>i', v)
    def long(self, v): self.d += struct.pack('>q', v)
    def float(self, v): self.d += struct.pack('>f', v)
    def double(self, v): self.d += struct.pack('>d', v)
    def boolean(self, v): self.byte(1 if v else 0)
    def raw(self, b): self.d += b

    def length(self, n):
        if n < 128:
            self.d.append(n)
        elif n < 16384:
            v = 0x8000 + n
            self.d += bytes([v >> 8, v & 0xFF])
        elif n < 4194304:
            v = 0xC00000 + n
            self.d += bytes([v >> 16 & 0xFF, v >> 8 & 0xFF, v & 0xFF])
        else:
            raise ValueError('length too big')


def hex64(v):
    return '%016x' % (v & 0xFFFFFFFFFFFFFFFF)


def unhex64(s):
    v = int(s, 16)
    return v - (1 << 64) if v >= 1 << 63 else v


class Schema:
    def __init__(self, path):
        d = json.load(open(path, encoding='utf-8'))
        self.types, self.models, self.methods = d['types'], d['models'], d['methods']
        self.enum_codes = {n: {v: int(k) for k, v in t['values'].items()}
                           for n, t in self.types.items() if t['kind'] == 'enum'}

    # ------------------------------------------------------------ values
    def read(self, r, t):
        if t.get('opt') and r.bit():
            return None
        k = t['t']
        if k == 'string':
            return r.raw(r.length()).decode('utf-8')
        if k in ('byte', 'short', 'int', 'long', 'float', 'double', 'boolean'):
            return getattr(r, k)()
        if k == 'bytes':
            return r.raw(r.length()).hex()
        if k == 'long_ints':
            hi, lo = r.int(), r.int()
            return (hi << 32) | (lo & 0xFFFFFFFF)
        if k in ('list', 'set', 'array'):
            return [self.read(r, t['of']) for _ in range(r.length())]
        if k == 'map':
            return [[self.read(r, t['key']), self.read(r, t['val'])] for _ in range(r.length())]
        td = self.types[k]
        kind = td['kind']
        if kind == 'alias':
            return self.read(r, {'t': td['of']})
        if kind == 'enum':
            code = r.int()
            return td['values'].get(str(code), code)
        if kind == 'struct':
            return {f['name']: self.read(r, f['type']) for f in td['fields']}
        if kind == 'special':
            return getattr(self, 'read_' + td['codec'])(r)
        raise ValueError('cannot read type %s (%s)' % (k, kind))

    def write(self, w, t, v):
        if t.get('opt'):
            w.bit(v is None)
            if v is None:
                return
        k = t['t']
        if k == 'string':
            b = v.encode('utf-8')
            w.length(len(b))
            w.raw(b)
        elif k in ('byte', 'short', 'int', 'long', 'float', 'double', 'boolean'):
            getattr(w, k)(v)
        elif k == 'bytes':
            b = bytes.fromhex(v)
            w.length(len(b))
            w.raw(b)
        elif k == 'long_ints':
            w.int(v >> 32)
            w.int(v & 0xFFFFFFFF if v & 0x80000000 == 0 else (v & 0xFFFFFFFF) - (1 << 32))
        elif k in ('list', 'set', 'array'):
            w.length(len(v))
            for x in v:
                self.write(w, t['of'], x)
        elif k == 'map':
            w.length(len(v))
            for a, c in v:
                self.write(w, t['key'], a)
                self.write(w, t['val'], c)
        else:
            td = self.types[k]
            kind = td['kind']
            if kind == 'alias':
                self.write(w, {'t': td['of']}, v)
            elif kind == 'enum':
                w.int(self.enum_codes[k][v] if isinstance(v, str) else v)
            elif kind == 'struct':
                for f in td['fields']:
                    self.write(w, f['type'], v[f['name']])
            elif kind == 'special':
                getattr(self, 'write_' + td['codec'])(w, v)
            else:
                raise ValueError('cannot write type %s (%s)' % (k, kind))

    # ------------------------------------------------------------ space loading (hand-written client codecs)
    def read_ObjectsDependencies(self, r):
        cb = r.int()
        classes = []
        for _ in range(r.int()):
            cid = r.long()
            classes.append({'id': hex64(cid), 'models': [hex64(r.long()) for _ in range(r.int())]})
        res = []
        for _ in range(r.int()):
            x = {'id': r.long(), 'type': r.short(), 'subType': r.short(), 'version': r.long(), 'isLazy': r.boolean()}
            x['deps'] = [r.long() for _ in range(r.byte())]
            res.append(x)
        return {'callbackId': cb, 'classes': classes, 'resources': res}

    def write_ObjectsDependencies(self, w, v):
        w.int(v['callbackId'])
        w.int(len(v['classes']))
        for c in v['classes']:
            w.long(unhex64(c['id']))
            w.int(len(c['models']))
            for m in c['models']:
                w.long(unhex64(m))
        w.int(len(v['resources']))
        for x in v['resources']:
            w.long(x['id'])
            w.short(x['type'])
            w.short(x['subType'])
            w.long(x['version'])
            w.boolean(x['isLazy'])
            w.byte(len(x['deps']))
            for dep in x['deps']:
                w.long(dep)

    def read_ObjectsData(self, r):
        objects = [{'id': hex64(r.long()), 'class': hex64(r.long())} for _ in range(r.int())]
        data = []
        for _ in range(r.int()):
            mid = r.long()
            if mid == 0:
                data.append({'object': hex64(r.long())})
                continue
            mh = hex64(mid)
            m = self.models.get(mh)
            if not m or 'cc' not in m:
                raise ValueError('no data codec for model %s' % mh)
            data.append({'model': mh, 'data': self.read(r, m['cc'])})
        return {'objects': objects, 'modelsData': data}

    def write_ObjectsData(self, w, v):
        w.int(len(v['objects']))
        for o in v['objects']:
            w.long(unhex64(o['id']))
            w.long(unhex64(o['class']))
        w.int(len(v['modelsData']))
        for x in v['modelsData']:
            if 'object' in x:
                w.long(0)
                w.long(unhex64(x['object']))
            else:
                w.long(unhex64(x['model']))
                self.write(w, self.models[x['model']]['cc'], x['data'])

    # ------------------------------------------------------------ TankState: 23 bytes of bit-packed vectors
    TANK_STATE = (('position', 19, .25), ('orientation', 13, .0007669904), ('linearVelocity', 13, 1),
                  ('angularVelocity', 13, .005))

    def read_TankState(self, r):
        raw = r.raw(23)
        pos = 0
        out = {}
        for name, n, scale in self.TANK_STATE:
            vec = []
            for _ in range(3):
                v = 0
                for i in range(n):
                    v = (v << 1) | ((raw[(pos + i) >> 3] >> (7 - ((pos + i) & 7))) & 1)
                pos += n
                vec.append((v - (1 << n - 1)) * scale)
            out[name] = vec
        return out

    def write_TankState(self, w, v):
        bits = []
        for name, n, scale in self.TANK_STATE:
            half = 1 << n - 1
            for x in v[name]:
                e = max(-2147483648, min(2147483647, math.floor(x / scale + .5)))    # roundToInt (Math.round)
                s = min(half, 0 if e < -half else e - half)                          # client's C5()
                s &= (1 << n) - 1
                bits += [(s >> (n - 1 - i)) & 1 for i in range(n)]
        raw = bytearray(23)
        for i, bit in enumerate(bits):
            if bit:
                raw[i >> 3] |= 1 << (7 - (i & 7))
        w.raw(bytes(raw))

    # ------------------------------------------------------------ commands
    def method_name(self, mh):
        m = self.methods.get(mh)
        return (m.get('name') or mh[-6:]) if m else mh[-6:]

    def read_command(self, r, direction, aliases):
        if direction == 'in' and r.bit():
            alias = r.byte() & 0xFF
            obj, meth = aliases.get(alias, (None, None))
            if meth is None:
                raise ValueError('unknown command alias %d' % alias)
            cmd = {'alias': alias}
        else:
            obj, meth = hex64(r.long()), hex64(r.long())
            cmd = {}
        m = self.methods.get(meth)
        if not m:
            raise ValueError('unknown method %s' % meth)
        if m['dir'] != direction:
            raise ValueError('method %s has direction %s' % (meth, m['dir']))
        args = [self.read(r, a['type']) for a in m['args']]
        cmd.update({'object': obj, 'method': meth, 'name': self.method_name(meth), 'args': args})
        if m.get('name') == 'setModelCommandAlias':
            aliases[args[0] & 0xFF] = (hex64(args[1]), hex64(args[2]))
        return cmd

    def write_command(self, w, direction, cmd):
        if direction == 'in':
            w.bit('alias' in cmd)
            if 'alias' in cmd:
                w.byte(cmd['alias'] if cmd['alias'] < 128 else cmd['alias'] - 256)
            else:
                w.long(unhex64(cmd['object']))
                w.long(unhex64(cmd['method']))
        else:
            w.long(unhex64(cmd['object']))
            w.long(unhex64(cmd['method']))
        m = self.methods[cmd['method']]
        for a, v in zip(m['args'], cmd['args']):
            self.write(w, a['type'], v)

    def decode_packet(self, payload, direction, aliases=None):
        """payload = null map + body (packet header removed). -> (commands, unused null-map bits)."""
        aliases = {} if aliases is None else aliases
        bits, pos = NullMap.decode(payload)
        r = Reader(payload[pos:], bits)
        cmds = []
        while not r.eof():
            cmds.append(self.read_command(r, direction, aliases))
        return cmds, bits[r.bp:]

    def encode_packet(self, cmds, direction, pad_bits=()):
        w = Writer()
        for c in cmds:
            self.write_command(w, direction, c)
        return NullMap.encode(w.bits + list(pad_bits)) + bytes(w.d)
