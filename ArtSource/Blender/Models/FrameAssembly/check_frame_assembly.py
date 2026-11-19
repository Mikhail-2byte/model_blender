"""Validate the saved Blender project and a fresh import of its FBX."""

import json
from math import hypot, radians
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_frame_assembly import CENTERS, FBX, MODEL, ROOT

EPS = .00005
CHECKS = ROOT / '.local/checks/frame-assembly'


def near(actual, expected):
    assert abs(actual - expected) < EPS, (actual, expected)


def points(obj):
    return [obj.matrix_world @ v.co for v in obj.data.vertices]


def bounds(vertices):
    return [tuple(f(v[i] for v in vertices) for i in range(3)) for f in (min, max)]


def size(vertices):
    lower, upper = bounds(vertices)
    return tuple(hi - lo for lo, hi in zip(lower, upper))


def triangle_count(obj):
    obj.data.calc_loop_triangles()
    assert all(face.area > 1e-10 for face in obj.data.polygons), obj.name
    assert all(tri.area > 1e-10 for tri in obj.data.loop_triangles), obj.name
    return len(obj.data.loop_triangles)


def surface(obj):
    return BVHTree.FromPolygons(points(obj), [tuple(p.vertices) for p in obj.data.polygons])


def height(bvh, x, y, *, from_below=False):
    z = -.2 if from_below else 2
    result, *_ = bvh.ray_cast((x, y, z), (0, 0, 1 if from_below else -1))
    assert result is not None, (x, y)
    return result.z


def unity(p):
    return (-p[0], p[2], -p[1])


def verify(meshes, imported=False):
    by_name = {obj.name: obj for obj in meshes}
    assert len(meshes) == 18
    frame = by_name['Frame']
    assert frame.parent is None
    near(frame.matrix_world.translation.length, 0)
    frame_bounds = bounds(points(frame))
    for p in zip(*frame_bounds):
        near(sum(p), 0)
    for measured, target in zip(size(points(frame)), (.6, .6, .05)):
        near(measured, target)
    top = surface(frame)
    assert height(top, -.036, -.041) > height(top, -.036, .041) + .001, 'Frame front must be -Y'

    prop_diameters = []
    for i, xy in enumerate(CENTERS):
        motor = by_name[f'Motor_{i}']
        prop = by_name[f'Propeller_{i}']
        for obj, z in ((motor, .085), (prop, .155)):
            assert obj.parent == frame, obj.name
            near((obj.matrix_world.translation - Vector((*xy, z))).length, 0)
        for measured, target in zip(size(points(motor)), (.15, .15, .12)):
            near(measured, target)
        near(bounds(points(motor))[0][2], .025)
        near(height(top, *xy), .025)
        near(height(surface(motor), *xy), .145)
        near(height(surface(prop), *xy, from_below=True), .145)
        sx, sy, _ = size(points(prop))
        assert (sy > sx) == (i % 2 == 0), prop.name
        diameter = 2 * max(hypot(p.x - xy[0], p.y - xy[1]) for p in points(prop))
        assert diameter <= .4
        prop_diameters.append(diameter)

    per_part = {}
    for obj in meshes:
        crack = obj.name == 'Crack' or obj.name.startswith('Crack.')
        if crack:
            assert obj.parent is not None and not obj.children
            key = obj.parent.name + '/Crack'
        else:
            assert sum(child.name.split('.')[0] == 'Crack' for child in obj.children) == 1, obj.name
            key = obj.name
        assert key not in per_part
        assert obj.parent is None or obj.parent in meshes
        assert len(obj.data.uv_layers) == len(obj.data.materials) == 1, obj.name
        assert obj.data.materials[0].name == 'DRONEWORKS_Palette', obj.name
        # The FBX reader restores its axis conversion on the root and decal nodes.
        for axis in obj.matrix_local.to_3x3().col:
            near(axis.length, 1)
        if not imported or (obj.parent == frame and not crack):
            for measured, basis in zip(obj.matrix_local.to_3x3().col, Matrix.Identity(3).col):
                near((measured - basis).length, 0)
        vertices = points(obj)
        uv = obj.data.uv_layers.active.data
        per_part[key] = {
            'triangles': triangle_count(obj),
            'pivot_unity': unity(obj.matrix_world.translation),
            'world_vertices': sorted({tuple(round(v, 5) for v in p) for p in vertices}),
            'palette_uvs': sorted({tuple(round(c, 5) for c in u.uv) for u in uv}),
        }
    vertices = [p for obj in meshes for p in points(obj)]
    dimensions = size([unity(p) for p in vertices])
    total = sum(entry['triangles'] for entry in per_part.values())
    assert total <= 3000 and all(v <= limit + EPS for v, limit in zip(dimensions, (.73, .19, .73)))
    return {'triangles': total, 'size_unity': dimensions, 'rotation_diameter': prop_diameters,
            'mesh_objects': per_part}


def table_check():
    table_scene = bpy.data.scenes['02 Assembly table']
    bpy.context.window.scene = table_scene
    frame = table_scene.objects['02 Assembly table | Frame']
    table_scene.frame_set(1)
    first = {obj.name: points(obj) for obj in [frame, *frame.children]}
    top = surface(table_scene.objects['SM_StationAssembly | Table'])
    for p in first[frame.name]:
        if abs(p.z - .900) < EPS:
            near(height(top, p.x, p.y), .900)
    table_scene.frame_set(2)
    for obj in [frame, *frame.children]:
        for a, b in zip(first[obj.name], points(obj), strict=True):
            near((b - a - Vector((0, 0, .015))).length, 0)
    near(bounds(points(frame))[0][2], .915)
    return {'installed_pivot_y': .925, 'output_pivot_y': .94, 'output_lift': .015,
            'transition': 'every vertex shifts 15 mm vertically; pose and relative offsets match'}


def tray_check():
    scene = bpy.data.scenes['03 Electronics intake']
    bpy.context.window.scene = scene
    frame = scene.objects['03 Electronics intake | Frame']
    tray = scene.objects['SM_StationElectronics | IntakeTray']
    cx, cy = tray.location.xy
    near(cx, 0)
    near(cy, -1.175)
    floor = [p for p in points(tray) if abs(p.z - .9) < EPS]
    clear_w, clear_d, _ = size(floor)
    near(clear_w, 1.24)
    near(clear_d, 1.09)
    for measured, target in zip(size(points(tray))[:2], (1.30, 1.15)):
        near(measured, target)
    test = {}
    for step, angle in ((1, 0), (2, 28)):
        scene.frame_set(step)
        near(frame.location.z, .925)
        surface_mesh = surface(tray)
        for p in points(frame):
            if abs(p.z - .900) < EPS:
                near(height(surface_mesh, p.x, p.y), .900)
        vertices = [p for obj in [frame, *frame.children] for p in points(obj)]
        test[str(angle)] = (clear_w / 2 - max(abs(p.x - cx) for p in vertices),
                            clear_d / 2 - max(abs(p.y - cy) for p in vertices))
    assert all(gap > 0 for fit in test.values() for gap in fit)
    radial = max(hypot(p.x - cx, p.y - cy) for p in vertices)
    all_angles_gap = min(clear_w, clear_d) / 2 - radial
    assert all_angles_gap > 0
    return {'inside_xz': (clear_w, clear_d), 'floor_y': .90, 'clearance_xz': test,
            'minimum_clearance_any_centered_yaw': all_angles_gap}


if __name__ == '__main__':
    if '--fbx' in sys.argv:
        bpy.ops.import_scene.fbx(filepath=str(FBX))
        objects = list(bpy.context.scene.objects)
        toggles = [obj for obj in objects if obj.type == 'EMPTY']
        assert len(toggles) == 9
        for toggle in toggles:
            assert toggle.name.split('.')[0] == 'Crack' and toggle.hide_viewport
            assert toggle.parent.type == 'MESH' and len(toggle.children) == 1
            damage = toggle.children[0]
            assert damage.type == 'MESH' and damage.name == toggle.parent.name + '_Damage'
            toggle.hide_viewport = damage.hide_viewport = False
        bpy.context.view_layer.update()
        for toggle in toggles:
            damage = toggle.children[0]
            world = damage.matrix_world.copy()
            damage.parent = toggle.parent
            damage.matrix_world = world
            bpy.data.objects.remove(toggle, do_unlink=True)
            damage.name = 'Crack'
        bpy.context.view_layer.update()
        result = verify(list(bpy.context.scene.objects), imported=True)
        source = json.loads((CHECKS / 'blend.json').read_text(encoding='utf-8'))
        for key, asset in result['mesh_objects'].items():
            original = source['mesh_objects'][key]
            assert asset['triangles'] == original['triangles'], key
            assert json.loads(json.dumps(asset['palette_uvs'])) == original['palette_uvs'], key
            for current, previous in zip(asset['world_vertices'], original['world_vertices'], strict=True):
                near((Vector(current) - Vector(previous)).length, 0)
        name = 'fbx'
    else:
        assert Path(bpy.data.filepath) == MODEL
        scene = bpy.context.scene
        meshes = list(scene.collection.children['EXPORT'].all_objects)
        assert all(obj.hide_get() and obj.hide_render for obj in meshes if obj.get('Damage'))
        result = verify(meshes)
        result['table'] = table_check()
        result['tray'] = tray_check()
        name = 'blend'
    CHECKS.mkdir(parents=True, exist_ok=True)
    (CHECKS / f'{name}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(name, {key: value for key, value in result.items() if key != 'mesh_objects'})
