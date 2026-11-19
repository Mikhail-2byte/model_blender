"""Build from DRONEWORKS.blend. Run with -- --export on the saved model to export FBX."""

from math import cos, radians, sin, tau
from pathlib import Path
import re
import sys

import bpy
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EXPORTS = ROOT / 'Exports/Unity'
MODEL = HERE / 'SM_FrameAssembly.blend'
FBX = EXPORTS / 'SM_FrameAssembly.fbx'
CENTERS = ((-.29, 0), (0, -.29), (.29, 0), (0, .29))
CRACK_UV = (.0625, .8125)  # HAZARD dark, in the shared palette.

sys.path.insert(0, str(HERE.parent / 'Frame'))
from build_frame import camera, collection, cube, lighting, link, material, set_viewports


def import_meshes(asset, names):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(EXPORTS / f'{asset}.fbx'))
    imported = set(bpy.data.objects) - before
    result = {}
    for obj in sorted(imported, key=lambda item: item.name):
        if obj.name not in names or obj.type != 'MESH':
            continue
        world = obj.matrix_world.copy()
        mesh = obj.data.copy()
        mesh.name = f'{asset} | {obj.name}'
        mesh.transform(world.to_3x3().to_4x4())
        assert [slot.name.split('.')[0] for slot in mesh.materials] == ['DRONEWORKS_Palette']
        mesh.materials[0] = bpy.data.materials['DRONEWORKS_Palette']
        result[obj.name] = (mesh, world.translation)
    for obj in imported:
        bpy.data.objects.remove(obj, do_unlink=True)
    assert result.keys() == set(names), (asset, result.keys(), names)
    return result


def painted_mesh(name, verts, faces, colors, smooth_sides=False):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(bpy.data.materials['DRONEWORKS_Palette'])
    uv = mesh.uv_layers.new(name='UVMap')
    for face, swatch in zip(mesh.polygons, colors, strict=True):
        face.use_smooth = smooth_sides and len(face.vertices) == 4
        for loop in face.loop_indices:
            uv.data[loop].uv = swatch
    return mesh


def motor_mesh():
    # Simplified turned profile of SM_DroneQuad: dark base, orange band, white shell and rotor.
    profile = ((-.060, .063), (-.049, .075), (-.032, .075), (-.027, .072),
               (.037, .070), (.047, .055), (.060, .034))
    count = 16
    vertices = [(radius * cos(tau*i/count), radius * sin(tau*i/count), height)
                for height, radius in profile for i in range(count)]
    faces = [tuple(reversed(range(count)))]
    for j in range(len(profile) - 1):
        for i in range(count):
            a = j * count + i
            b = j * count + (i + 1) % count
            faces.append((a, b, b + count, a + count))
    faces.append(tuple(range(len(vertices) - count, len(vertices))))
    bands = ((0, 1), (5, 0), (6, 0), (1, 2), (2, 2), (1, 1))
    cells = [(0, 1)] + [cell for cell in bands for _ in range(count)] + [(0, 1)]
    colors = [((col + .5)/8, 1 - (row + .5)/8) for col, row in cells]
    return painted_mesh('Motor shell', vertices, faces, colors, smooth_sides=True)


# One branched silhouette. The outline fits on a single facet of the motor shell.
FRACTURE = ((-.008, .020), (-.002, .008), (-.003, .002), (.005, .009), (.009, .012),
            (.006, .005), (.001, -.001), (.004, -.009), (.001, -.022),
            (.001, -.010), (-.005, -.001), (-.005, .008))


def crack_mesh(name, parent, on_motor=False):
    vertices = []
    angle = -radians(78.75)
    outward = Vector((cos(angle), sin(angle), 0))
    tangent = Vector((-outward.y, outward.x, 0))
    for across, along in FRACTURE:
        if on_motor:
            start = outward * .13 + tangent * across + Vector((0, 0, along))
            ray = -outward
        else:
            start = Vector((across, -.163 + along, .10))
            ray = Vector((0, 0, -1))
        hit, point, _normal, _index = parent.ray_cast(start, ray)
        assert hit, (name, start)
        vertices.append(point - ray * .00055)
    face = tuple(reversed(range(len(vertices))))
    return painted_mesh(name, vertices, [face], [CRACK_UV])


def child(parent, name, mesh, dest, offset=(0, 0, 0)):
    obj = link(name, mesh, dest)
    obj.parent, obj.location = parent, offset
    return obj


def damage(parent, mesh, dest, offset=(0, 0, 0)):
    obj = child(parent, 'Crack', mesh, dest, offset)
    obj['Damage'] = True
    obj.hide_render = True
    obj.hide_set(True)
    return obj


def build_parts(scene):
    dest = scene.collection.children['EXPORT']
    frame_data, _ = import_meshes('SM_Frame', ('Frame',))['Frame']
    propeller_parts = import_meshes('SM_Propeller', ('Propeller', 'Crack'))
    propeller_source, prop_pivot = propeller_parts['Propeller']
    crack_source, crack_pivot = propeller_parts['Crack']
    frame = link('Frame', frame_data, dest)
    damage(frame, crack_mesh('Frame crack', frame), dest)
    motor_data = motor_mesh()
    motor_crack = None
    for i, xy in enumerate(CENTERS):
        motor = child(frame, f'Motor_{i}', motor_data, dest, (*xy, .085))
        if motor_crack is None:
            motor_crack = crack_mesh('Motor crack', motor, on_motor=True)
        damage(motor, motor_crack, dest)
        rotation = Matrix.Rotation(radians(90 if i % 2 == 0 else 0), 4, 'Z')
        propeller_data, crack_data = propeller_source.copy(), crack_source.copy()
        propeller_data.transform(rotation)
        crack_data.transform(rotation)
        prop = child(frame, f'Propeller_{i}', propeller_data, dest, (*xy, .155))
        damage(prop, crack_data, dest, rotation.to_3x3() @ (crack_pivot - prop_pivot))
    return frame


def review(name, frame, position):
    scene = bpy.data.scenes.new(name)
    bpy.context.window.scene = scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.length_unit = 'METERS'
    items = collection(scene, 'FIT_CHECK')
    rig = collection(scene, 'CAMERAS_AND_LIGHTS')
    copy = link(name + ' | Frame', frame.data, items, position)
    for part in frame.children:
        if not part.get('Damage'):
            child(copy, name + ' | ' + part.name, part.data, items, part.location)
    lighting(scene, rig, position[2])
    shift = Vector((position[0], position[1], 0))
    for obj in rig.objects:
        obj.location += shift
    scene.view_settings.view_transform = 'Khronos PBR Neutral'
    scene.render.resolution_x, scene.render.resolution_y = (1400, 1100)
    return scene, items, rig, copy


def fixture(asset, names, items):
    for name, (mesh, position) in import_meshes(asset, names).items():
        link(f'{asset} | {name}', mesh, items, position)


def build_reviews(frame):
    scene, items, rig, _ = review('01 Overview', frame, (0, 0, 0))
    floor = material('Preview | Slate backdrop', (.115, .167, .222), .8)
    cube('Preview stage', items, (0, 0, -.065), (200, 200, .05), floor)
    scene.camera = camera(rig, 'Overview | Above', (.61, -.82, .95), (0, 0, .045), ortho=.95)

    scene, items, rig, copy = review('02 Assembly table', frame, (0, 0, .925))
    fixture('SM_StationAssembly', ('Table', 'Backboard', 'SignBoard'), items)
    scene.camera = camera(rig, 'Storyboard | Player over table', (.38, -.91, 1.61), (0, 0, 1), lens=35)
    for time, z in ((1, .925), (2, .940)):
        copy.location.z = z
        copy.keyframe_insert(data_path='location', frame=time)
    scene.timeline_markers.new('Installed on worktop', frame=1)
    scene.timeline_markers.new('Output pivot +15 mm', frame=2)
    scene.frame_end = 2
    scene.frame_set(1)

    scene, items, rig, copy = review('03 Electronics intake', frame, (0, -1.175, .925))
    fixture('SM_StationElectronics', ('Base', 'Cabinet', 'IntakeTray'), items)
    scene.camera = camera(rig, 'Electronics | Intake close-up', (.47, -1.98, 2.18),
                          (0, -1.16, .94), ortho=1.61)
    for time, yaw in ((1, 0), (2, 28)):
        copy.rotation_euler.z = radians(yaw)
        copy.keyframe_insert(data_path='rotation_euler', frame=time)
    scene.timeline_markers.new('Straight', frame=1)
    scene.timeline_markers.new('Yaw 28 degrees', frame=2)
    scene.frame_end = 2
    scene.frame_set(2)


def build():
    master = bpy.context.scene
    master.name = 'SM_FrameAssembly'
    master['Front'] = 'Blender -Y / Unity +Z'
    palette = bpy.data.materials['DRONEWORKS_Palette']
    texture = palette.node_tree.nodes['Image Texture']
    texture.image.pack()
    palette.node_tree.nodes.active = texture
    palette.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = .57
    frame = build_parts(master)
    refs = master.collection.children['REFERENCES']
    for name in ('drone_quadcopter.png', 'storyboard_02_hud.jpg'):
        obj = link(name, None, refs)
        obj.empty_display_type = 'IMAGE'
        obj.data = bpy.data.images.load(str(ROOT / 'References' / name))
        obj.data.pack()
    refs.hide_viewport = refs.hide_render = True
    build_reviews(frame)
    bpy.context.window.scene = master
    bpy.ops.object.select_all(action='DESELECT')
    frame.select_set(True)
    bpy.context.view_layer.objects.active = frame
    set_viewports((0, 0, .055))
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = 'NONE'
    bpy.ops.wm.save_as_mainfile(filepath=str(MODEL), relative_remap=True)


def export():
    from io_scene_fbx import export_fbx_bin, fbx_utils

    dest = bpy.context.scene.collection.children['EXPORT']
    for obj in list(dest.all_objects):
        if obj.get('Damage'):
            owner = obj.parent
            # Keep Crack as the toggle node and give its mesh a stable Unity subasset name.
            toggle = child(owner, 'Crack', None, dest, obj.location.copy())
            toggle['Damage'] = True
            obj.name = owner.name + '_Damage'
            obj.parent = toggle
            obj.location.zero()

    # Object names are global in Blender, but each parent can have its own Crack in FBX.
    original_name = export_fbx_bin.fbx_name_class
    original_matrix = fbx_utils.ObjectWrapper.fbx_object_matrix
    original_hide = fbx_utils.ObjectWrapper.hide

    def per_parent_name(name, kind):
        if kind == b'Model' and re.fullmatch(rb'Crack\.\d+', name):
            name = b'Crack'
        return original_name(name, kind)

    def rigid_baked_matrix(obj, scene_data, rest=False, local_space=False, global_space=False):
        # The stock Apply Transform recurses in incompatible bases at depth two.
        # Geometry is already baked into FBX axes, so conjugate each rigid transform once.
        settings = scene_data.settings
        relative = local_space or (not global_space and obj.has_valid_parent(scene_data.objects))
        if relative:
            transform = obj.matrix_rest_local if rest else obj.matrix_local
        else:
            transform = obj.matrix_rest_global if rest else obj.matrix_global
        return settings.global_matrix @ transform @ settings.global_matrix_inv

    export_fbx_bin.fbx_name_class = per_parent_name
    fbx_utils.ObjectWrapper.fbx_object_matrix = rigid_baked_matrix
    fbx_utils.ObjectWrapper.hide = property(lambda obj: obj.bdata.get('Damage', False) or original_hide.fget(obj))
    try:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in dest.all_objects:
            obj.hide_set(False)
            if obj.data and obj.data.users > 1:
                obj.data = obj.data.copy()
            obj.select_set(True)
        # Mirror the workshop rigid profile and include only the Crack toggle empties.
        result = bpy.ops.export_scene.fbx(
            filepath=str(FBX), use_selection=True, object_types={'MESH', 'EMPTY'},
            axis_forward='-Z', axis_up='Y', apply_unit_scale=True,
            apply_scale_options='FBX_SCALE_UNITS', bake_space_transform=True,
            use_mesh_modifiers=True, bake_anim=False, path_mode='STRIP',
        )
        assert result == {'FINISHED'} and FBX.is_file(), result
    finally:
        export_fbx_bin.fbx_name_class = original_name
        fbx_utils.ObjectWrapper.fbx_object_matrix = original_matrix
        fbx_utils.ObjectWrapper.hide = original_hide


if __name__ == '__main__':
    export() if '--export' in sys.argv else build()
