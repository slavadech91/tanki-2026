"""Wire level of the local server: packet framing, control commands, space commands via tools/proto_codec.py.

packet  = header | null map | body                         (server-notes/protocol.md)
header  = 2 bytes (b0 & 0x80 == 0) or 4 bytes; length in the low bits, b0 & 0x40 = body compressed with zlib
control = body[0] is the command: 1 HashRequest, 2 HashResponse, 3 OpenSpaceConnect, 32 OpenSpace (server)
          or ClientLog (client)
space   = commands (objectId, methodId, arguments) in the schema's decoded form (protocol-codecs.md)
The server answers HashRequest with encryption off, so nothing here ciphers.
"""
import os, struct, sys, zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from proto_codec import Schema  # noqa: E402

SCHEMA = Schema(os.path.join(ROOT, 'server-notes', 'proto_schema.json'))

HASH_REQUEST, HASH_RESPONSE, OPEN_SPACE_CONNECT, OPEN_SPACE, CLIENT_LOG = 1, 2, 3, 32, 32
PING = bytes([0x00, 0x01, 0x00])   # empty packet: length 1 + empty null map


def frame(payload):
    n = len(payload)
    if n < 16384:
        return bytes([n >> 8, n & 0xFF]) + payload
    return bytes([0x80 | (n >> 24) & 0x3F, n >> 16 & 0xFF, n >> 8 & 0xFF, n & 0xFF]) + payload


def split(buf):
    """Cut whole packets off a byte stream -> (payloads, rest); payload = null map + body, decompressed."""
    out, pos = [], 0
    while pos + 2 <= len(buf):
        b0 = buf[pos]
        if b0 & 0x80:
            if pos + 4 > len(buf):
                break
            ln, hl = (b0 & 0x3F) << 24 | buf[pos + 1] << 16 | buf[pos + 2] << 8 | buf[pos + 3], 4
        else:
            ln, hl = (b0 & 0x3F) << 8 | buf[pos + 1], 2
        if pos + hl + ln > len(buf):
            break
        p = buf[pos + hl:pos + hl + ln]
        if b0 & 0x40:
            try:
                p = zlib.decompress(p)
            except zlib.error:
                p = zlib.decompress(p, -15)
        out.append(p)
        pos += hl + ln
    return out, buf[pos:]


def null_map_len(p):
    r = p[0]
    if r & 0x80:
        return 3 + ((r & 63) << 16 | p[1] << 8 | p[2]) if r & 0x40 else 1 + (r & 63)
    return 1 + ((r & 0x60) >> 5)


def control_body(payload):
    """Control packets carry no optional values: skip the null map."""
    return payload[null_map_len(payload):] if payload else b''


def hash_response(session_hash):
    return frame(b'\x00' + bytes([HASH_RESPONSE]) + session_hash + b'\x00')   # last byte 0: no encryption


def open_space(*space_ids):
    return frame(b'\x00' + b''.join(bytes([OPEN_SPACE]) + struct.pack('>Q', int(s, 16)) for s in space_ids))


def parse_open_space_connect(body):
    """OpenSpaceConnect = 3 | session hash[32] | spaceId[8] -> (hash, spaceId as 16 hex digits)."""
    return body[1:33], '%016x' % struct.unpack_from('>Q', body, 33)[0]


def client_log(body):
    """ClientLog = 32 | strings; keep the printable text for the log."""
    return ''.join(chr(c) if 32 <= c < 127 else ' ' for c in body[1:]).split()


def encode(cmds):
    return frame(SCHEMA.encode_packet(cmds, 'in'))


def decode(payload):
    """Client space packet -> commands (decoded form); raises ValueError on methods the schema lacks."""
    return SCHEMA.decode_packet(payload, 'out')[0]
