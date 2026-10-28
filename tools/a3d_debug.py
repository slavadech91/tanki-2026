"""Trace the mesh section of one .a3d: attrs, submeshes and the bytes after them.

usage: python -I a3d_debug.py <object.a3d>
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import a3d

data = open(sys.argv[1], 'rb').read()
r = a3d.R(data, 16)
while r.p < len(data):
    stype, size = r.u32(), r.u32()
    print('section', stype, 'at %#x size %#x end %#x' % (r.p - 8, size, r.p + size))
    end = r.p + size
    if stype == 2:
        n = r.u32()
        print(' meshes', n)
        for k in range(n):
            print(' mesh', k, 'at %#x' % r.p)
            name = r.str()
            r.f32(7)
            nv, na = r.u32(), r.u32()
            print('  name %r nverts %d nattrs %d' % (name, nv, na))
            for i in range(na):
                t = r.u32()
                r.p += nv * a3d.ATTR_WIDTH[t] * 4
            ns = r.u32()
            print('  nsub', ns, 'at %#x' % (r.p - 4))
            for s in range(ns):
                ni = r.u32()
                print('   sub', s, 'nidx', ni, 'max idx', max(struct.unpack_from('<%dH' % ni, data, r.p)) if ni < 1e6 else '?')
                r.p += 2 * ni + (-2 * ni) % 4
            print('  next bytes at %#x:' % r.p, data[r.p:r.p + 48].hex(' '))
    r.p = end
