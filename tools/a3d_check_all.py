"""Parse every object.a3d under a folder; report failures and attribute types seen.

usage: python -I a3d_check_all.py <root>
"""
import collections, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import a3d

ok, bad, attrs, sects = 0, [], collections.Counter(), collections.Counter()
for d, _, fs in os.walk(sys.argv[1]):
    for f in fs:
        if f.endswith('.a3d'):
            p = os.path.join(d, f)
            try:
                m = a3d.parse(open(p, 'rb').read())
                ok += 1
                for mesh in m['meshes']:
                    attrs.update(mesh['attrs'].keys())
                sects.update(m['unknown_sections'])
            except Exception as e:
                bad.append((p, e))
print('ok', ok, 'failed', len(bad))
print('attr types', dict(attrs), 'unknown sections', dict(sects))
for p, e in bad[:10]:
    print('FAIL', p, e)
