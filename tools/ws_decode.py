"""Decrypt and split a capture_ws.py JSONL into protocol packets (Alternativa protocol, HTML5 client).

Per socket:
  - control commands (1 hash request, 2 hash response, 3 open space, 32 open space / client log) are plain;
  - after the client's "open space" (cmd 3: hash[32] + spaceId[8]) both directions are a byte stream cipher:
      key byte o = xor of the 4 bytes of (lo(spaceId) ^ hi(spaceId) ^ int32be(hash[0:4]) ^ ... ^ int32be(hash[28:32]))
      server->client keys k[i] = o ^ (i << 3);  client->server keys m[i] = o ^ (i << 3) ^ 87
      decrypt: p = c ^ key[idx]; key[idx] = p; idx ^= p & 7          (bundle: ir.j7n / ir.i7n @3058250)
Packet (bundle @1557432): header 2 bytes ((b0 & 63) << 8 | b1) or, if b0 & 0x80, 4 bytes ((b0 ^ 0x80) << 24 | ...);
bit 0x40 of b0 = zlib-compressed payload. Payload = null map + one or more commands.

usage: python -I ws_decode.py <capture.jsonl> <out_packets.jsonl>
"""
import base64, collections, json, struct, sys, zlib

SPACE_CMD_OPEN = 3


def key_byte(hash32, space_id):
    e = (space_id & 0xFFFFFFFF) ^ (space_id >> 32 & 0xFFFFFFFF)
    for i in range(8):
        e ^= struct.unpack_from('>I', hash32, 4 * i)[0]
    return (e >> 24 ^ e >> 16 ^ e >> 8 ^ e) & 0xFF


class Cipher:
    def __init__(self, o, salt):
        self.key = [(o ^ (i << 3) ^ salt) & 0xFF for i in range(8)]
        self.idx = 0

    def decrypt(self, data):
        out = bytearray(len(data))
        key, idx = self.key, self.idx
        for n, c in enumerate(data):
            p = c ^ key[idx]
            key[idx] = p
            idx ^= p & 7
            out[n] = p
        self.idx = idx
        return bytes(out)


def null_map_len(buf, pos):
    """Bytes taken by the null map at buf[pos] (bundle: n7i @1555485)."""
    r = buf[pos]
    if r & 0x80:
        n = r & 63
        if r & 0x40:
            n = (n << 16) | (buf[pos + 1] << 8) | buf[pos + 2]
            return 3 + n
        return 1 + n
    return 1 + ((r & 0x60) >> 5)


def split_packets(stream):
    """Yield (payload, compressed, header_len) while whole packets are available; return the rest."""
    pos, out = 0, []
    while pos + 2 <= len(stream):
        b0 = stream[pos]
        if b0 & 0x80:
            if pos + 4 > len(stream):
                break
            ln = ((b0 ^ 0x80) & 0x3F) << 24 | stream[pos + 1] << 16 | stream[pos + 2] << 8 | stream[pos + 3]
            hl = 4
        else:
            ln = (b0 & 63) << 8 | stream[pos + 1]
            hl = 2
        if pos + hl + ln > len(stream):
            break
        out.append((stream[pos + hl:pos + hl + ln], bool(b0 & 0x40)))
        pos += hl + ln
    return out, stream[pos:]


def main(src, dst):
    recs = [json.loads(l) for l in open(src, encoding='utf-8')]
    socks = collections.OrderedDict()
    session_hash, stats = None, collections.Counter()
    packets = []
    for r in recs:
        if r['ev'] not in ('sent', 'recv', 'created'):
            continue
        s = socks.setdefault(r['id'], {'url': None, 'space': None, 'cipher': {}, 'buf': {'sent': b'', 'recv': b''}})
        if r['ev'] == 'created':
            s['url'] = r['url']
            continue
        d = r['ev']
        data = base64.b64decode(r['b64']) if 'b64' in r else r['text'].encode()
        if d in s['cipher']:
            data = s['cipher'][d].decrypt(data)
        stream = s['buf'][d] + data
        pk, rest = split_packets(stream)
        s['buf'][d] = rest
        for payload, comp in pk:
            stats['packets'] += 1
            if comp:
                try:
                    payload = zlib.decompress(payload)
                except zlib.error:
                    payload = zlib.decompress(payload, -15)
                stats['compressed'] += 1
            nm = null_map_len(payload, 0) if payload else 0
            body = payload[nm:]
            packets.append({'t': r['t'], 'sock': r['id'], 'dir': '>' if d == 'sent' else '<', 'space': s['space'],
                            'comp': comp, 'nullmap': payload[:nm].hex(), 'body': body.hex()})
            # control commands on plain sockets
            if s['space'] is None and body:
                cmd = body[0]
                if d == 'recv' and cmd == 2 and len(body) >= 34:
                    session_hash = body[1:33]
                    stats['hash_response'] += 1
                if d == 'sent' and cmd == SPACE_CMD_OPEN and len(body) >= 41:
                    h, sid = body[1:33], struct.unpack_from('>Q', body, 33)[0]
                    o = key_byte(h, sid)
                    s['space'] = '%016x' % sid
                    s['cipher'] = {'recv': Cipher(o, 0), 'sent': Cipher(o, 87)}
                    stats['spaces_opened'] += 1
                    # anything already buffered after the open-space packet is ciphertext
                    for dd in ('sent', 'recv'):
                        if s['buf'][dd]:
                            s['buf'][dd] = s['cipher'][dd].decrypt(s['buf'][dd])
    leftovers = {sid: {k: len(v) for k, v in s['buf'].items() if v} for sid, s in socks.items()}
    leftovers = {k: v for k, v in leftovers.items() if v}
    with open(dst, 'w', encoding='utf-8') as fh:
        for p in packets:
            fh.write(json.dumps(p) + '\n')
    print(dict(stats))
    print('sockets', len(socks), 'with space', sum(1 for s in socks.values() if s['space']))
    print('leftover bytes (should be empty or tiny):', leftovers)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
