"""Build SM_Frame and its Blender-only review scenes from DRONEWORKS.blend."""

from math import cos, pi, sin
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CHECKS = ROOT / '.local/checks/frame'
TEMPLATE = ROOT / 'ArtSource/Blender/DRONEWORKS.blend'
STAMPING = ROOT / 'Exports/Unity/SM_StationStamping.fbx'
ASSEMBLY = ROOT / 'Exports/Unity/SM_StationAssembly.fbx'
BLOCKOUT = '--blockout' in sys.argv
AXES = ((.29, 0), (0, -.29), (-.29, 0), (0, .29))
UV = {
    'side': (.5625, .5625),  # RUBBER dark  #1E1D24
    'body': (.6875, .5625),  # RUBBER base  #34323D
    'edge': (.8125, .5625),  # RUBBER light #4C4A57
}


def turn(point, index):
    x, y = point
    return ((x, y), (y, -x), (-x, -y), (-y, x))[index]


def arm(root, tip, half_width, cut):
    return [(root, -half_width), (tip - cut, -half_width),
            (tip, -half_width + cut), (tip, half_width - cut),
            (tip - cut, half_width), (root, half_width)]


def octagon(x0, x1, y0, y1, cut):
    return [(x0 + cut, y0), (x1 - cut, y0), (x1, y0 + cut), (x1, y1 - cut),
            (x1 - cut, y1), (x0 + cut, y1), (x0, y1 - cut), (x0, y0 + cut)]


def circle(x, y, radius, sides):
    return [(x + radius * cos(2 * pi * n / sides),
             y + radius * sin(2 * pi * n / sides)) for n in range(sides)]


def frame_mesh(palette):
    # Clockwise rotation follows the motor order in ART_SPEC from Blender +X.
    mid = arm(.080, .300, .060, .011)
    profile = [(-.025, arm(.080, .298, .058, .010)), (-.022, mid), (.013, mid),
               (.022, arm(.078, .297, .051, .010)),
               (.025, arm(.077, .295, .048, .009))]
    if BLOCKOUT:
        profile = [(-.025, mid), (.025, mid)]
    vertices, faces, paints, indices = [], [], [], {}

    def face(points, paint):
        ids = []
        for point in points:
            key = tuple(round(v, 7) for v in point)
            if key not in indices:
                indices[key] = len(vertices)
                vertices.append(key)
            ids.append(indices[key])
        faces.append(ids)
        paints.append(paint)

    def level(points, height):
        return [(x, y, height) for x, y in points]

    def bridge(lower, upper, paint):
        for i in range(len(lower)):
            j = (i + 1) % len(lower)
            face((lower[i], lower[j], upper[j], upper[i]), paint)

    def full_ring(section):
        return [turn(point, i) for i in (0, 3, 2, 1) for point in section]

    def inset_panel(outline, recesses):
        # Keep each pocket integral to the surface. CDT tessellates the deck around its openings.
        points = list(outline)
        polygons = [list(range(len(outline)))]
        for rim, levels in recesses:
            polygons.append(list(range(len(points), len(points) + len(rim))))
            points.extend(rim)
            previous = level(rim, .025)
            for contour, height, paint in levels:
                current = level(contour, height)
                bridge(previous, current, paint)
                previous = current
            face(previous, 'side')
        planar, _, triangles, _, _, sources = delaunay_2d_cdt(
            [Vector(point) for point in points], [], polygons, 1, 1e-7)
        for triangle, owners in zip(triangles, sources):
            if owners == [0]:
                face(level([planar[i] for i in triangle], .025), 'body')

    rings = [level(full_ring(section), height) for height, section in profile]
    face(list(reversed(rings[0])), 'side')
    if BLOCKOUT:
        bridge(*rings, 'side')
        face(rings[-1], 'body')
    else:
        for lower, upper, paint in zip(rings, rings[1:], ('body', 'side', 'edge', 'body')):
            bridge(lower, upper, paint)
        top = profile[-1][1]
        channel = (octagon(.102, .204, -.024, .024, .010),
                   [(octagon(.105, .201, -.021, .021, .008), .023, 'body'),
                    (octagon(.106, .200, -.020, .020, .008), .021, 'side')])
        seats = [(circle(.255, lateral, .009, 8),
                  [(circle(.255, lateral, .0055, 8), .020, 'side')])
                 for lateral in (-.023, .023)]
        for i in range(4):
            recesses = [([turn(point, i) for point in rim],
                         [([turn(point, i) for point in contour], z, paint) for contour, z, paint in levels])
                        for rim, levels in (channel, *seats)]
            inset_panel([turn(point, i) for point in top], recesses)
        hub = [turn(point, i) for i in (0, 3, 2, 1) for point in (top[0], top[-1])]

        def keyed_recess(half, front_cut, rear_cut):
            # The larger cuts at -Y identify the front of the central pocket.
            return [(-half + front_cut, -half), (half - front_cut, -half),
                    (half, -half + front_cut), (half, half - rear_cut),
                    (half - rear_cut, half), (-half + rear_cut, half),
                    (-half, half - rear_cut), (-half, -half + front_cut)]

        inset_panel(hub, [(keyed_recess(.049, .022, .010),
                           [(keyed_recess(.045, .020, .008), .023, 'body'),
                            (keyed_recess(.0435, .019, .0075), .020, 'side')])])

    mesh = bpy.data.meshes.new('Frame')
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(palette)
    uv = mesh.uv_layers.new(name='UVMap')
    for polygon, paint in zip(mesh.polygons, paints):
        for index in polygon.loop_indices:
            uv.uv[index].vector = UV[paint]
    editable = bmesh.new()
    editable.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(editable, faces=list(editable.faces))
    assert all(edge.is_manifold for edge in editable.edges), 'Frame mesh must be closed'
    assert editable.calc_volume(signed=True) > 0
    editable.to_mesh(mesh)
    editable.free()
    mesh.calc_loop_triangles()
    assert len(mesh.loop_triangles) <= 800, len(mesh.loop_triangles)
    return mesh


def collection(scene, name):
    result = bpy.data.collections.new(name)
    scene.collection.children.link(result)
    return result


def link(name, data, target, position=(0, 0, 0)):
    obj = bpy.data.objects.new(name, data)
    target.objects.link(obj)
    obj.location = position
    return obj


def material(name, color, roughness=.65, metal=0):
    result = bpy.data.materials.new(name)
    result.diffuse_color = (*color, 1)
    result.use_nodes = True
    shader = result.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = roughness
    shader.inputs['Metallic'].default_value = metal
    return result


def move_to(obj, dest):
    for source in list(obj.users_collection):
        source.objects.unlink(obj)
    dest.objects.link(obj)


def cube(name, target, center, size, paint):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(paint)
    move_to(obj, target)
    return obj


def cylinder(name, target, xy, bottom, depth, radius, paint, sides=32):
    bpy.ops.mesh.primitive_cylinder_add(vertices=sides, radius=radius, depth=depth,
                                        location=(*xy, bottom + depth / 2))
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(paint)
    move_to(obj, target)
    return obj


def camera(target, name, position, aim, *, ortho=None, lens=45):
    data = bpy.data.cameras.new(name)
    obj = link(name, data, target, position)
    obj.rotation_euler = (Vector(aim) - obj.location).to_track_quat('-Z', 'Y').to_euler()
    data.lens = lens
    if ortho is not None:
        data.type = 'ORTHO'
        data.ortho_scale = ortho
    return obj


def lighting(scene, rig, height):
    scene.world = bpy.data.worlds.new(scene.name + ' world')
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get('Background')
    background.inputs['Color'].default_value = (.23, .29, .40, 1)
    background.inputs['Strength'].default_value = .28
    for name, position, watts, size, color in (
        ('Key', (-.58, -.62, 1.05), 68, .80, (1.0, .89, .76)),
        ('Fill', (.64, -.18, .61), 26, .71, (.66, .79, 1.0)),
        ('Rim', (.28, .62, .90), 71, .65, (.78, .89, 1.0)),
    ):
        light = bpy.data.lights.new(scene.name + ' ' + name, 'AREA')
        obj = link(light.name, light, rig, (position[0], position[1], position[2] + height))
        obj.rotation_euler = (Vector((0, 0, height)) - obj.location).to_track_quat('-Z', 'Y').to_euler()
        light.energy, light.size, light.color = watts, size, color
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 40
    scene.cycles.use_denoising = True
    scene.render.threads_mode, scene.render.threads = 'FIXED', 2
    scene.render.resolution_x, scene.render.resolution_y = (1120, 900)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'AgX'


def set_viewports(center):
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                space.region_3d.view_distance = 1.20
                space.region_3d.view_location = center
                space.region_3d.view_rotation = (Vector(center) - Vector((.74, -.93, .75))).to_track_quat('-Z', 'Y')
                space.shading.color_type = 'TEXTURE'


def build():
    CHECKS.mkdir(parents=True, exist_ok=True)
    assert Path(bpy.data.filepath).resolve() == TEMPLATE.resolve()
    master = bpy.context.scene
    master.name = 'SM_Frame'
    palette = bpy.data.materials['DRONEWORKS_Palette']
    palette.diffuse_color = (.070, .063, .084, 1)
    palette.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value = .58
    texture = palette.node_tree.nodes.get('Image Texture')
    texture.image.pack()
    palette.node_tree.nodes.active = texture
    source = link('Frame', frame_mesh(palette), master.collection.children['EXPORT'])
    source['Front'] = '-Y in Blender, +Z in Unity'
    source['Palette'] = 'DRONEWORKS_Palette / RUBBER shadow, base, highlight'

    if not BLOCKOUT:
        make_reviews(master, source, palette)
    bpy.context.window.scene = master
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    set_viewports((0, 0, 0))
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = 'NONE'
    path = (CHECKS / 'SM_Frame.blockout.blend') if BLOCKOUT else (HERE / 'SM_Frame.blend')
    bpy.ops.wm.save_as_mainfile(filepath=str(path), relative_remap=True)
    print('FRAME_TRIANGLES', len(source.data.loop_triangles))


def make_reviews(master, source, palette):
    refs = master.collection.children['REFERENCES']
    for filename in ('drone_quadcopter.png', 'storyboard_02_hud.jpg'):
        reference = link(filename, None, refs)
        reference.empty_display_type = 'IMAGE'
        reference.data = bpy.data.images.load(str(ROOT / 'References' / filename))
        reference.data.pack()
    refs.hide_viewport = True
    refs.hide_render = True

    def review(name, position):
        scene = bpy.data.scenes.new(name)
        scene.unit_settings.system = 'METRIC'
        scene.unit_settings.scale_length = 1.0
        bpy.context.window.scene = scene
        items = collection(scene, 'FIT_CHECK' if position[2] > .5 else 'PREVIEW')
        rig = collection(scene, 'CAMERAS_AND_LIGHTS')
        frame = link(name + ' | Frame', source.data, items, position)
        lighting(scene, rig, position[2])
        return scene, items, rig, frame

    studio, items, rig, _ = review('01 Empty frame', (0, 0, 0))
    stage = material('Preview | Blue-gray backdrop', (.13, .19, .25), .84)
    cube('Preview stage', items, (0, 0, -.076), (200, 200, .1), stage)
    studio.camera = camera(rig, 'Empty frame | Three-quarter', (.48, -.69, .61), (0, 0, -.008), ortho=.82)
    camera(rig, 'Drone reference | Three-quarter above', (.71, -.92, .58), (0, 0, 0), ortho=.86)

    assembly, items, rig, _ = review('02 Assembly fit', (0, 0, .925))
    worktop = material('Fit | Worktop', (.125, .17, .20), .72)
    if ASSEMBLY.is_file():
        import_fixture(ASSEMBLY, items, palette, 'Table', 'Backboard')
    else:
        cube('Assembly worktop | top 0.900 m', items, (0, 0, .87), (1.60, 1.00, .06), worktop)
    dark = material('Fit | Motor graphite', (.035, .037, .047), .45)
    white = material('Fit | Motor casing', (.61, .64, .73), .35, .20)
    signal = material('Fit | Motor ring', (.89, .31, .012), .42, .15)
    motors = collection(assembly, 'Fit motors')
    propellers = collection(assembly, 'Fit propellers | toggle to inspect')
    for i, xy in enumerate(AXES):
        name = f'Fit Motor_{i}'
        cylinder(name, motors, xy, .950, .018, .075, dark)
        cylinder(name + ' | Ring', motors, xy, .968, .012, .075, signal)
        sleeve = cylinder(name + ' | Housing', motors, xy, .980, .068, .075, white)
        bevel = sleeve.modifiers.new('Machined housing edge', 'BEVEL')
        bevel.width, bevel.segments = .005, 2
        cylinder(name + ' | Rotor', motors, xy, 1.048, .012, .056, dark)
        cylinder(name + ' | Shaft', motors, xy, 1.060, .010, .022, white)
        screw = cylinder(f'Fit Propeller_{i} | Hub', propellers, xy, 1.070, .014, .032, dark)
        blade = cube(f'Fit Propeller_{i} | Blades', propellers, (*xy, 1.077), (.280, .042, .010), dark)
        blade.rotation_euler.z = (i + 1) * pi / 4
        bevel = blade.modifiers.new('Blade edge', 'BEVEL')
        bevel.width, bevel.segments = .004, 2
        screw['Purpose'] = 'Visual fit check only'
    propellers.hide_viewport = True
    propellers.hide_render = True
    assembly.render.resolution_x = 960
    assembly.render.resolution_y = 960
    assembly.camera = camera(rig, 'Motor fit | Top', (0, 0, 2.6), (0, 0, .9), ortho=.88)
    camera(rig, 'Storyboard | Player eye over table', (.39, -.84, 1.57), (0, 0, .93), lens=50)

    tray, items, rig, _ = review('03 Stamping fit', (0, 0, .925))
    tray.camera = camera(rig, 'Output tray | Three-quarter', (.78, -.95, 1.82), (0, 0, .89), ortho=1.28)
    if STAMPING.is_file():
        output, = import_fixture(STAMPING, items, palette, 'OutputTray')
        output.location.xy = (0, 0)
    else:
        cube('Proxy tray | 0.90 × 1.00 m', items, (0, 0, .875), (.90, 1, .05), worktop)
        for side in (-1, 1):
            cube('Proxy tray | Side lip', items, (side * .435, 0, .94), (.03, 1, .08), worktop)
            cube('Proxy tray | End lip', items, (0, side * .485, .94), (.84, .03, .08), worktop)


def import_fixture(path, items, palette, *names):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path))
    imported = set(bpy.data.objects) - before
    selected = {obj.name: obj for obj in imported if obj.name in names and obj.type == 'MESH'}
    assert set(selected) == set(names), (path.name, names)
    transforms = {name: obj.matrix_world.copy() for name, obj in selected.items()}
    for name, obj in selected.items():
        obj.parent = None
        obj.matrix_world = transforms[name]
        obj.data.materials.clear()
        obj.data.materials.append(palette)
        obj.name = f'{path.stem} | {name}'
        move_to(obj, items)
    for obj in imported.difference(selected.values()):
        bpy.data.objects.remove(obj, do_unlink=True)
    return tuple(selected[name] for name in names)


if __name__ == '__main__':
    build()
