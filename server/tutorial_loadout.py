"""Assemble the player's tutorial tank from builder previews and captured battle parts."""

from copy import deepcopy

CONFIGURATION = '2e08888737beaaee'
PART_ITEMS = '4ced44c5bf312832'
ITEM_3D = '67b1f230feef85f9'
COLORING = '3876a2ebea9b63a7'
SKIN = '06aea5e23512d856'
EMISSION = '154ac1e9556f89eb'
HULL_GEOMETRY = '09e1da85b2ab53da'
WEAPON_COMMON = '112e2d8502a754ed'
SPECIFICATION = '6368b2d4ca388c58'

HUNTER = 920009631039
TWINS = 920009630997
SMOKY = 920009630969
FIREBIRD = 920009630983
RICOCHET = 920009631088
DEFAULT_PAINT = 1931009779879
# Dimensions of the boundbox meshes in the builder resources, in client units.
TRACKED_HULL_SIZES = {
    920009630941: (342.8, 540.6, 125.8),  # Viking
    920009630962: (384.0, 594.8, 207.7),  # Dictator
}
WEAPON_KINDS = {SMOKY: 'smoky', FIREBIRD: 'firebird', RICOCHET: 'ricochet'}


def parts(load_objects):
    result = {}
    for entry in load_objects['modelsData']:
        if 'object' in entry:
            models = result[entry['object']] = {}
        else:
            models[entry['model']] = entry['data']
    return result


def replace_part(load_objects, object_id, models):
    entries = load_objects['modelsData']
    start = entries.index({'object': object_id}) + 1
    end = next((i for i in range(start, len(entries)) if 'object' in entries[i]), len(entries))
    entries[start:end] = [{'model': model, 'data': data} for model, data in models.items()]


class TutorialLoadout:
    def __init__(self, entrance, battle):
        self.previews = dict(entrance['previews'])
        self.weapons = {}
        for item, kind in WEAPON_KINDS.items():
            bot = next(bot for bot in [battle['target'], *battle['bots']] if bot['kind'] == kind)
            data = bot['objects']['args'][0]
            models = parts(data)
            configuration = models[bot['id']][CONFIGURATION]
            skin = models[f"{configuration['weaponSkinId']:016x}"]
            weapon_class = next(obj['class'] for obj in data['objects'] if obj['id'] == bot['weapon'])
            self.weapons[item] = (weapon_class, models[bot['weapon']], skin, bot['load'])

        # The Ricochet skin is present in the battle capture. Reuse it for the builder.
        _, _, skin, loads = self.weapons[RICOCHET]
        preview = deepcopy(self.previews[str(SMOKY)])
        object_id = f'{RICOCHET:016x}'
        preview['data']['objects'][0]['id'] = object_id
        preview['data']['modelsData'][0]['object'] = object_id
        resource = skin[SKIN]['visualLods'][0]
        parts(preview['data'])[object_id][ITEM_3D].update(
            itemId=RICOCHET, resource=resource, emissionColor=skin[EMISSION])
        preview['deps']['resources'] = [
            r for load in loads for r in load['args'][0]['resources'] if r['id'] == resource
        ]
        self.previews[str(RICOCHET)] = preview

        build = next(c for c in entrance['register'] if c['name'] == 'buildTank')
        self.builder_args = deepcopy(build['args'])
        hulls, items, paints, paint_info, _ = self.builder_args
        self.allowed = {
            group['hullId']: [item for item in group['weaponsIds'] if item == TWINS or item in self.weapons]
            for group in hulls if group['hullId'] == HUNTER or group['hullId'] in TRACKED_HULL_SIZES
        }
        self.paints = {item for item in paints if str(item) in self.previews}
        hulls[:] = [{'hullId': hull, 'weaponsIds': weapons} for hull, weapons in self.allowed.items()]
        allowed_items = self.allowed.keys() | {item for weapons in self.allowed.values() for item in weapons}
        items[:] = [item for item in items if item['itemId'] in allowed_items]
        paints[:] = [item for item in paints if item in self.paints]
        paint_info[:] = [item for item in paint_info if item['itemId'] in self.paints]

    def selection(self, saved):
        saved = saved or {}
        hull = saved.get('hull', HUNTER)
        weapon = saved.get('weapon', TWINS)
        paint = saved.get('paint', DEFAULT_PAINT)
        if hull not in self.allowed:
            hull = HUNTER
        if weapon not in self.allowed[hull]:
            weapon = self.allowed[hull][0]
        if paint not in self.paints:
            paint = DEFAULT_PAINT
        return hull, weapon, paint

    def apply(self, battle, player_id, hull, weapon, paint):
        """Build per-session packets, leaving bot objects and the shared templates intact."""
        opening = deepcopy(battle['open'])
        objects = deepcopy(battle['objects'])
        deps = opening[0]['args'][0]
        data = objects[0]['args'][0]
        models = parts(data)
        config = models[player_id][CONFIGURATION]
        item_ids = models[player_id][PART_ITEMS]
        item_ids.update(hullId=hull, hullBaseId=hull, weaponId=weapon, weaponBaseId=weapon)

        if hull != HUNTER:
            hull_skin = models[f"{config['hullSkinId']:016x}"]
            preview = self.previews[str(hull)]
            geometry = hull_skin[HULL_GEOMETRY]
            size = dict(zip(('x', 'y', 'z'), TRACKED_HULL_SIZES[hull]))
            scale = {axis: size[axis] / geometry['bodySize'][axis] for axis in size}
            geometry['bodySize'] = size
            for box in [geometry['mainCollisionBox'], *geometry['staticCollisionBoxes']]:
                for index, axis in enumerate(size):
                    box['halfSize'][axis] *= scale[axis]
                    box['localTransform'][9 + index] *= scale[axis]
            for anchor in geometry['trackAnchors'] + geometry['trailAnchors']:
                for axis in size:
                    anchor[axis] *= scale[axis]
            item = parts(preview['data'])[preview['data']['objects'][0]['id']][ITEM_3D]
            geometry.update(leftTrackTextureToWorldRatio=item['leftTrackTexToWorldRatio'],
                            rightTrackTextureToWorldRatio=item['rightTrackTexToWorldRatio'],
                            skinOffset=item['skinOffset'], turretMountPoint=item['turretMountPoint'],
                            ultimatePoint=item['turretMountPoint'])
            hull_skin[SKIN].update(visualLods=[item['resource']], detailedCollisionGeometry=None)
            replace_part(data, f"{config['hullSkinId']:016x}", {**hull_skin, EMISSION: item['emissionColor']})
            self.add_dependencies(deps, preview['deps'], classes=False)

        if weapon != TWINS:
            weapon_class, weapon_models, skin, loads = self.weapons[weapon]
            weapon_id = f"{config['weaponId'] & ((1 << 64) - 1):016x}"
            next(obj for obj in data['objects'] if obj['id'] == weapon_id)['class'] = weapon_class
            replace_part(data, weapon_id, deepcopy(weapon_models))
            replace_part(data, f"{config['weaponSkinId']:016x}", deepcopy(skin))
            for load in loads:
                self.add_dependencies(deps, load['args'][0])
            rotation = weapon_models[WEAPON_COMMON]['turretRotationSpeed']
            spec = models[player_id][SPECIFICATION]
            spec.update(baseTurretRotationSpeed=rotation, currentTurretRotationSpeed=rotation)

        if paint != DEFAULT_PAINT:
            preview = self.previews[str(paint)]
            paint_id = f"{config['coloringId'] & ((1 << 64) - 1):016x}"
            coloring = parts(preview['data'])[preview['data']['objects'][0]['id']][COLORING]
            replace_part(data, paint_id, {COLORING: deepcopy(coloring)})
            self.add_dependencies(deps, preview['deps'], classes=False)
        return opening, objects, models[player_id][SPECIFICATION]['currentTurretRotationSpeed']

    @staticmethod
    def add_dependencies(target, source, classes=True):
        for kind in ('classes', 'resources') if classes else ('resources',):
            present = {item['id'] for item in target[kind]}
            target[kind].extend(deepcopy(item) for item in source[kind] if item['id'] not in present)
