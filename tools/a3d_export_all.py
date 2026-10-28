"""Convert every v3 object.a3d under <root> to <out>/models/<id>.glb and write <out>/models.json.

usage: python -I a3d_export_all.py <root> <out>
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import a3d

root, out = sys.argv[1], sys.argv[2]
os.makedirs(os.path.join(out, 'models'), exist_ok=True)
items, failed = [], 0
for d, _, fs in os.walk(root):
    if 'object.a3d' not in fs:
        continue
    src = os.path.join(d, 'object.a3d')
    try:
        model = a3d.parse(open(src, 'rb').read())
        glb = a3d.to_glb(model, a3d.folder_textures(model, d))
    except Exception as e:
        failed += 1
        print('FAIL', src, e)
        continue
    rid = os.path.basename(d)
    open(os.path.join(out, 'models', rid + '.glb'), 'wb').write(glb)
    names = [n['name'] for n in model['nodes']]
    low = [n.lower() for n in names]
    kind = ('hull' if 'mount' in low and 'hull' in low else
            'turret' if any(n.startswith('muzzle') for n in low) or 'turret' in low else 'other')
    items.append({'id': rid, 'kind': kind, 'path': os.path.relpath(d, root).replace('\\', '/'),
                  'verts': sum(m['nverts'] for m in model['meshes']), 'kb': len(glb) // 1024,
                  'nodes': names, 'files': sorted(os.listdir(d))})
items.sort(key=lambda x: (x['kind'], -x['verts']))
json.dump(items, open(os.path.join(out, 'models.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('exported', len(items), 'failed', failed, {k: sum(i['kind'] == k for i in items) for k in ('hull', 'turret', 'other')})
