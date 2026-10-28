"""Reader for Tanki Online HTML5 .a3d models (header "A3D\\0", version 3) -> glTF binary (.glb).

Layout (little endian, strings are u32 length + bytes padded to 4):
  header: "A3D\\0" u32 version=3, u32 ?, u32 body_len
  body: sections [u32 type, u32 size, data]
    4 materials: u32 n; {str name, f32 r,g,b, str texture_path}
    2 meshes:    u32 n; {str name, f32 bbox[6], f32 radius, u32 nverts, u32 nattrs,
                        nattrs x {u32 attr_type, f32 data[nverts * width]},
                        u32 nsub, nsub x {u32 nidx, u16 idx[nidx] (padded to 4)}}
    3 nodes:     u32 n; n x {str name, f32 pos[3], f32 quat[4] (x,y,z,w), f32 scale[3]}; n x i32 parent
    5 instances: u32 n; {u32 mesh, u32 node, u32 nmat, u32 mat[nmat]}  (one material per submesh)

usage: python -I a3d.py <object.a3d> [out.glb]   (no out = print structure only)
"""
import json, os, struct, sys

# attribute type -> floats per vertex; 1 position, 2 uv, 3 normal; others guessed from data
ATTR_WIDTH = {1: 3, 2: 2, 3: 3, 6: 3}
ATTR_NAME = {1: 'position', 2: 'uv', 3: 'normal', 6: 'tangent?'}


class R:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v

    def f32(self, n):
        v = struct.unpack_from('<%df' % n, self.d, self.p); self.p += 4 * n; return list(v)

    def raw(self, n):
        v = self.d[self.p:self.p + n]; self.p += n; return v

    def str(self):
        n = self.u32()
        s = self.raw(n).decode('utf-8', 'replace')
        self.p += -n % 4
        return s


def parse(data):
    if data[:4] != b'A3D\0':
        raise ValueError('not A3D')
    r = R(data, 4)
    version, unk, body_len = r.u32(), r.u32(), r.u32()
    if version != 3:
        raise ValueError('version %d' % version)
    end = r.p + body_len
    model = {'materials': [], 'meshes': [], 'nodes': [], 'instances': [], 'unknown_sections': []}
    while r.p < end:
        stype, size = r.u32(), r.u32()
        sec_end = r.p + size
        if stype == 4:
            for _ in range(r.u32()):
                model['materials'].append({'name': r.str(), 'color': r.f32(3), 'texture': r.str()})
        elif stype == 2:
            for _ in range(r.u32()):
                m = {'name': r.str(), 'bbox': r.f32(6), 'radius': r.f32(1)[0], 'attrs': {}, 'submeshes': []}
                nv, na = r.u32(), r.u32()
                m['nverts'] = nv
                for _ in range(na):
                    t = r.u32()
                    if t not in ATTR_WIDTH:
                        raise ValueError('unknown attr type %d at %#x' % (t, r.p - 4))
                    m['attrs'][t] = r.f32(nv * ATTR_WIDTH[t])
                for _ in range(r.u32()):
                    n = r.u32()
                    m['submeshes'].append(list(struct.unpack_from('<%dH' % n, data, r.p)))
                    r.p += 2 * n + (-2 * n) % 4
                model['meshes'].append(m)
        elif stype == 3:
            nodes = [{'name': r.str(), 'pos': r.f32(3), 'rot': r.f32(4), 'scale': r.f32(3)}
                     for _ in range(r.u32())]
            for n in nodes:
                n['parent'] = r.i32()
            model['nodes'] += nodes
        elif stype == 5:
            for _ in range(r.u32()):
                mesh, node, nm = r.u32(), r.u32(), r.u32()
                model['instances'].append({'node': node, 'mesh': mesh, 'materials': [r.u32() for _ in range(nm)]})
        else:
            model['unknown_sections'].append(stype)
        if r.p != sec_end:
            raise ValueError('section %d: parsed to %#x, expected %#x' % (stype, r.p, sec_end))
        r.p = sec_end
    return model


def folder_textures(model, folder):
    """Guess a texture per material from the files next to object.a3d: tracks.webp for track
    materials, otherwise lightmap.webp (baked shading; the paint is a separate resource)."""
    def f(name):
        p = os.path.join(folder, name)
        return p if os.path.isfile(p) else None
    out = []
    for m in model['materials']:
        n = m['name'].lower()
        out.append(f('tracks.webp') if 'track' in n and f('tracks.webp') else f('lightmap.webp'))
    # last entry: texture for meshes without a material
    return out + [f('lightmap.webp')]


def to_glb(model, textures=None):
    """textures: optional list of image file paths (bytes embedded), one per material index."""
    buf = bytearray()
    views, accessors, meshes, nodes, mats, images, gl_tex = [], [], [], [], [], [], []

    def add_view(blob, target=None):
        while len(buf) % 4:
            buf.append(0)
        views.append({'buffer': 0, 'byteOffset': len(buf), 'byteLength': len(blob)})
        if target:
            views[-1]['target'] = target
        buf.extend(blob)
        return len(views) - 1

    def add_acc(values, comps, ctype=5126, target=34962, minmax=False):
        fmt = '<%d%s' % (len(values), 'f' if ctype == 5126 else 'H')
        view = add_view(struct.pack(fmt, *values), target)
        acc = {'bufferView': view, 'componentType': ctype, 'count': len(values) // comps,
               'type': {1: 'SCALAR', 2: 'VEC2', 3: 'VEC3', 4: 'VEC4'}[comps]}
        if minmax:
            acc['min'] = [min(values[i::comps]) for i in range(comps)]
            acc['max'] = [max(values[i::comps]) for i in range(comps)]
        accessors.append(acc)
        return len(accessors) - 1

    tex_index = {}  # image path -> glTF texture index, so a shared image is embedded once
    for i, m in enumerate(model['materials']):
        mat = {'name': m['name'], 'doubleSided': True,
               'pbrMetallicRoughness': {'baseColorFactor': m['color'] + [1.0], 'metallicFactor': 0.0}}
        if textures and i < len(textures) and textures[i]:
            if textures[i] not in tex_index:
                data = open(textures[i], 'rb').read()
                mime = 'image/webp' if data[8:12] == b'WEBP' else 'image/png'
                images.append({'bufferView': add_view(data), 'mimeType': mime})
                gl_tex.append({'source': len(images) - 1})
                tex_index[textures[i]] = len(gl_tex) - 1
            mat['pbrMetallicRoughness'] = {'baseColorTexture': {'index': tex_index[textures[i]]}, 'metallicFactor': 0.0}
        mats.append(mat)

    for m in model['meshes']:
        a = {'POSITION': add_acc(m['attrs'][1], 3, minmax=True)}
        if 3 in m['attrs']:
            a['NORMAL'] = add_acc(m['attrs'][3], 3)
        if 2 in m['attrs']:
            a['TEXCOORD_0'] = add_acc(m['attrs'][2], 2)
        if 5 in m['attrs']:
            a['TEXCOORD_1'] = add_acc(m['attrs'][5], 2)
        prims = [{'attributes': a, 'indices': add_acc(idx, 1, 5123, 34963)} for idx in m['submeshes']]
        meshes.append({'name': m['name'], 'primitives': prims})

    fallback = None
    mesh_of = {}
    for inst in model['instances']:
        mesh_of[inst['node']] = inst
        for p, mi in zip(meshes[inst['mesh']]['primitives'], inst['materials']):
            if mi < len(mats):
                p['material'] = mi
            elif textures and textures[-1]:
                # no material (index -1): use the folder's lightmap
                if fallback is None:
                    data = open(textures[-1], 'rb').read()
                    images.append({'bufferView': add_view(data), 'mimeType': 'image/webp'})
                    gl_tex.append({'source': len(images) - 1})
                    mats.append({'name': 'default', 'doubleSided': True, 'pbrMetallicRoughness': {
                        'baseColorTexture': {'index': len(gl_tex) - 1}, 'metallicFactor': 0.0}})
                    fallback = len(mats) - 1
                p['material'] = fallback
    for i, n in enumerate(model['nodes']):
        node = {'name': n['name'], 'translation': n['pos'], 'rotation': n['rot'], 'scale': n['scale']}
        # BoundBox and 24-vertex BoxNN meshes are collision/culling helpers, not visible geometry
        name = n['name'].lower()
        helper = name == 'boundbox' or (name.startswith('box') and i in mesh_of
                                        and model['meshes'][mesh_of[i]['mesh']]['nverts'] == 24)
        if i in mesh_of and not helper:
            node['mesh'] = mesh_of[i]['mesh']
        nodes.append(node)
    for i, n in enumerate(model['nodes']):
        if 0 <= n['parent'] < len(nodes):
            nodes[n['parent']].setdefault('children', []).append(i)
    roots = [i for i, n in enumerate(model['nodes']) if not 0 <= n['parent'] < len(nodes)]
    for i in roots:
        # root offsets are leftovers from the artists' scenes; models are authored around the origin
        nodes[i]['translation'] = [0.0, 0.0, 0.0]

    gltf = {'asset': {'version': '2.0', 'generator': 'a3d.py'},
            # Alternativa3D is Z-up; glTF is Y-up
            'scene': 0, 'scenes': [{'nodes': [len(nodes)]}],
            'nodes': nodes + [{'name': 'zup', 'rotation': [-0.70710678, 0, 0, 0.70710678], 'children': roots}],
            'meshes': meshes, 'materials': mats, 'accessors': accessors, 'bufferViews': views,
            'buffers': [{'byteLength': len(buf)}]}
    if images:
        gltf['images'], gltf['textures'] = images, gl_tex
    js = json.dumps(gltf).encode()
    js += b' ' * (-len(js) % 4)
    while len(buf) % 4:
        buf.append(0)
    out = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(buf))
    out += struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(buf), 0x004E4942) + bytes(buf)
    return out


if __name__ == '__main__':
    model = parse(open(sys.argv[1], 'rb').read())
    for m in model['materials']:
        print('material', m['name'], '->', m['texture'])
    for m in model['meshes']:
        print('mesh %r verts=%d attrs=%s submeshes=%s' % (m['name'], m['nverts'], sorted(m['attrs']),
                                                       [len(s) // 3 for s in m['submeshes']]))
    for n in model['nodes']:
        print('node', n['name'], 'parent', n['parent'])
    print('instances', model['instances'], 'unknown', model['unknown_sections'])
    if len(sys.argv) > 2:
        open(sys.argv[2], 'wb').write(to_glb(model, folder_textures(model, os.path.dirname(sys.argv[1]))))
