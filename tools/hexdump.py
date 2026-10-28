"""usage: python -I hexdump.py <file> [offset=0] [length=512]"""
import sys

data = open(sys.argv[1], 'rb').read()
off = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
n = int(sys.argv[3], 0) if len(sys.argv) > 3 else 512
print('size', len(data))
for i in range(off, min(off + n, len(data)), 16):
    row = data[i:i + 16]
    print('%06x  %-48s %s' % (i, ' '.join('%02x' % b for b in row),
                             ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)))
