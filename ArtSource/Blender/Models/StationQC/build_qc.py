"""Build the QC stand from the workshop template with Blender Python."""

import argparse
import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CHECKS = ROOT / ".local/checks/station-qc"
STEM = "SM_StationQC"
REFERENCE = ROOT / "References/drone_quadcopter.png"
PALETTE = ROOT / "ArtSource/Textures/T_Palette_DRONEWORKS.png"
PIVOTS = {
    "Table": (0, 0, 0), "Platform": (0, .925, 0),
    "Backboard": (0, 1.50, -.48), "Lamp": (.55, 2.20, -.45),
    "SignBoard": (0, 1.92, -.44),
}
SWATCH = {
    "steel shade": (0, 0), "steel": (1, 0), "steel light": (2, 0),
    "ochre": (4, 0), "yellow": (5, 0), "gold": (6, 0),
    "black": (0, 1), "graphite": (1, 1), "graphite light": (2, 1),
    "white shade": (0, 2), "white": (1, 2), "white light": (2, 2),
    "rubber": (5, 3), "rubber light": (6, 3),
    "glass": (1, 4), "glass light": (2, 4), "silver": (1, 7),
}
ROTOR_AXES = ((.29, 1.28, 0), (0, 1.28, .29),
              (-.29, 1.28, 0), (0, 1.28, -.29))


def blender(point):
    """Convert Unity coordinates through the workshop's rigid FBX basis."""
    x, y, z = point
    return Vector((-x, -z, y))


def unity(point):
    x, y, z = point
    return (-x, z, -y)


def uv(paint):
    col, row = SWATCH[paint]
    return ((col + .5) / 8, 1 - (row + .5) / 8)


def flat_material(name, rgb, roughness, emission=0):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*rgb, 1)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = material.diffuse_color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Emission Color"].default_value = material.diffuse_color
    shader.inputs["Emission Strength"].default_value = emission
    return material


def contour(width, depth, clip, runners=False):
    x, z = width / 2, depth / 2
    corners = [(-x + clip, -z), (x - clip, -z), (x, -z + clip), (x, z - clip),
               (x - clip, z), (-x + clip, z), (-x, z - clip), (-x, -z + clip)]
    if not runners:
        return corners
    perimeter = []
    for i, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1])):
        perimeter.append(a)
        if i % 2 == 0:
            perimeter.extend(tuple(p + t * (q - p) for p, q in zip(a, b)) for t in (.16, .84))
    return perimeter


class Mesh:
    def __init__(self):
        self.vertices = []
        self.faces = []
        self.paint = []
        self.smooth = []

    def add(self, vertices, faces, colors, smooth=False):
        base = len(self.vertices)
        self.vertices.extend(vertices)
        self.faces.extend(tuple(i + base for i in face) for face in faces)
        self.paint.extend(colors)
        self.smooth.extend([smooth] * len(faces))

    def loft(self, center, axis, rings, colors, smooth=False):
        count = len(rings[0][1])
        vertices = []
        for offset, outline in rings:
            assert len(outline) == count
            for u, v in outline:
                point = [u, v]
                point.insert(axis, offset)
                vertices.append(tuple(a + b for a, b in zip(center, point)))
        faces = [tuple(range(count))]
        paints = [colors[0]]
        for ring, color in enumerate(colors[1:-1]):
            first = ring * count
            for i in range(count):
                a, b = first + i, first + (i + 1) % count
                faces.append((a, b, b + count, a + count))
                paints.append(color if isinstance(color, str) else color[i])
        faces.append(tuple(range(len(vertices) - count, len(vertices))))
        paints.append(colors[-1])
        self.add(vertices, faces, paints, smooth)

    def box(self, center, size, color, bevel=.012, trim=None, axis=1):
        plane = [value for i, value in enumerate(size) if i != axis]
        w, d = plane
        h = size[axis] / 2
        b = min(bevel, min(size) / 5)
        outer = contour(w, d, b * 1.6)
        inner = contour(w - 2*b, d - 2*b, b * .75)
        self.loft(center, axis, [(-h, inner), (-h + b, outer), (h - b, outer), (h, inner)],
                  (color, color, color, trim or color, color))

    def round(self, center, axis, profile, paints, sides=12, smooth=False):
        rings = [(offset, [(radius * math.cos(math.tau * i / sides),
                            radius * math.sin(math.tau * i / sides)) for i in range(sides)])
                 for offset, radius in profile]
        self.loft(center, axis, rings, paints, smooth)

    def bolt(self, center):
        self.round(center, 2, [(0, .032), (.009, .032), (.016, .025)],
                   ("steel shade", "steel light", "silver", "steel light"), sides=6)

    def object(self, name, collection, material, pivot=(0, 0, 0), parent=None):
        mesh = bpy.data.meshes.new(name)
        origin = blender(pivot)
        mesh.from_pydata([blender(point) - origin for point in self.vertices], [], self.faces)
        mesh.materials.append(material)
        layer = mesh.uv_layers.new(name="UVMap")
        for face, paint, smooth in zip(mesh.polygons, self.paint, self.smooth, strict=True):
            face.use_smooth = smooth
            for index in face.loop_indices:
                layer.data[index].uv = uv(paint)
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        obj.parent = parent
        obj.location = origin
        return obj


def table(blockout):
    mesh = Mesh()
    mesh.loft((0, 0, 0), 1, [(.84, contour(1.334, .934, .029)),
                              (.854, contour(1.40, 1.00, .044)),
                              (.884, contour(1.40, 1.00, .044)),
                              (.90, contour(1.35, .95, .031))],
              ("steel shade", "steel shade", "steel", "steel light", "steel"))
    for side in (-1, 1):
        for end in (-1, 1):
            x, z = side * .557, end * .362
            rings = []
            for height, width, depth, inset in [(.047, .167, .141, 0), (.071, .193, .167, 0),
                                                (.62, .175, .15, .022), (.84, .231, .193, .042)]:
                rings.append((height, [(u - side * inset, v - end * inset)
                                       for u, v in contour(width, depth, .027)]))
            mesh.loft((x, 0, z), 1, rings,
                      ("steel shade", "steel shade", "steel", "steel", "steel light"))
            mesh.loft((x, 0, z), 1, [(0, contour(.209, .193, .026)),
                                      (.020, contour(.233, .209, .034)),
                                      (.068, contour(.233, .209, .034)),
                                      (.088, contour(.196, .177, .026))],
                      ("black", "black", "steel shade", "steel light", "steel"))
        mesh.box((side * .547, .245, 0), (.108, .105, .691), "steel shade", bevel=.024, trim="steel")
    mesh.box((0, .251, -.365), (1.10, .142, .09), "steel shade", bevel=.019, trim="steel")
    mesh.box((0, .794, .326), (1.176, .154, .177), "steel shade", bevel=.031, trim="steel")
    if not blockout:
        for side in (-1, 1):
            mesh.box((side * .509, .736, .406), (.206, .195, .048), "steel", .020, "steel light", axis=2)
            mesh.bolt((side * .514, .765, .429))
            mesh.box((side * .557, .098, .446), (.154, .037, .014), "ochre", .008, "yellow", axis=2)
        mesh.box((0, .793, .420), (.46, .073, .018), "steel", .014, "steel light", axis=2)
    return mesh


def platform():
    mesh = Mesh()
    # The colored corners share the deck's plane. They have no height above it.
    edge = ["yellow" if i % 4 != 1 else "graphite light" for i in range(16)]
    paint_top = ["gold" if i % 4 != 1 else "rubber light" for i in range(16)]
    mesh.loft((0, 0, 0), 1, [(y, contour(w, w, c, runners=True)) for y, w, c in
                             [(.90, .814, .037), (.908, .85, .044), (.937, .85, .044),
                              (.95, .822, .038), (.95, .744, .032)]],
              ("steel shade", "steel shade", edge, edge, paint_top, "rubber light"))
    return mesh


def backboard(blockout):
    mesh = Mesh()
    for side in (-1, 1):
        x = side * .615
        mesh.loft((x, 0, -.475), 1,
                  [(y, [(u + side * shift, v - (.016 if y >= 1.50 else 0))
                        for u, v in contour(w, d, c)])
                   for y, w, d, c, shift in [(.895, .131, .145, .021, 0),
                                               (.947, .152, .15, .025, 0),
                                               (1.076, .127, .12, .020, 0),
                                               (1.50, .082, .105, .017, .031),
                                               (1.81, .082, .105, .017, .031),
                                               (2.046, .096, .093, .017, 0)]],
                  ("steel shade", "steel shade", "steel light", "steel", "steel", "steel", "steel light"))
        if not blockout:
            mesh.box((x, 1.031, -.409), (.112, .134, .036), "steel shade", .013, "steel light", axis=2)
            mesh.bolt((x, 1.039, -.392))
            mesh.box((side * .645, 1.722, -.435), (.082, .071, .015), "ochre", .008, "yellow", axis=2)
    # Low splash plate and high tie rail define the through-opening at rotor height.
    mesh.box((0, 1.014, -.475), (1.222, .176, .070), "steel shade", .022, "steel")
    mesh.box((0, 1.619, -.494), (1.223, .121, .085), "steel shade", .020, "steel")
    if not blockout:
        mesh.box((0, 1.041, -.437), (.78, .062, .021), "steel", .010, "steel light", axis=2)
    mesh.box((.579, 2.044, -.494), (.195, .079, .092), "steel shade", .018, "steel")
    mesh.round((.55, 0, -.45), 1, [(2.079, .072), (2.089, .077), (2.106, .076), (2.12, .066)],
               ("steel shade", "steel shade", "yellow", "gold", "steel shade"), sides=16)
    return mesh


def signboard():
    mesh = Mesh()
    mesh.loft((0, 1.92, 0), 2, [(-.45, contour(1.324, .294, .025)),
                                 (-.446, contour(1.35, .32, .03)),
                                 (-.434, contour(1.35, .32, .03)),
                                 (-.43, contour(1.324, .294, .022)),
                                 (-.43, contour(1.263, .232, .014))],
              ("steel shade", "steel shade", "steel", "steel light", "steel shade", "black"))
    return mesh


def lamp(collection, parent):
    # Dedicated URP material slot. Green represents the waiting state in the renders.
    mat = flat_material("DRONEWORKS_QC_Lamp", (.046, .66, .12), .23, .29)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=.10)
    obj = bpy.context.object
    for linked in list(obj.users_collection):
        linked.objects.unlink(obj)
    collection.objects.link(obj)
    obj.name = obj.data.name = "Lamp"
    obj.parent = parent
    obj.location = blender(PIVOTS["Lamp"])
    obj.data.materials.append(mat)
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj


def aim_profile(angle, outline):
    c, s = math.cos(angle), math.sin(angle)
    return [(u * c - v * s, u * s + v * c) for u, v in outline]


def drone(collection, palette, blockout):
    model = Mesh()
    rotors = []
    model.box((0, 1.115, .015), (.274, .15, .358), "graphite", .027, "rubber light")
    model.loft((0, 0, .022), 1, [(1.163, contour(.277, .355, .044)),
                                   (1.198, contour(.284, .345, .045)),
                                   (1.244, contour(.240, .300, .041)),
                                   (1.266, contour(.177, .237, .029))],
               ("white shade", "white shade", "white", "white shade", "white"))
    for i, (x, _, z) in enumerate(ROTOR_AXES):
        axis = 0 if i % 2 == 0 else 2
        model.box((x / 2, 1.157, z / 2), (.294, .055, .070) if axis == 0 else (.070, .055, .294),
                  "rubber", .013, "rubber light", axis=1)
        model.round((x, 0, z), 1, [(1.164, .060), (1.177, .073), (1.189, .075), (1.229, .075),
                                     (1.247, .059), (1.263, .035)],
                    ("black", "rubber", "yellow", "white shade", "white", "rubber", "graphite"), sides=16)
        rotor = Mesh()
        rotor.round((x, 0, z), 1, [(1.257, .030), (1.271, .041), (1.292, .041), (1.30, .034)],
                    ("black", "rubber", "graphite", "rubber light", "graphite light"), sides=12)
        if blockout:
            rotor.box((x, 1.28, z), (.06, .02, .50) if axis == 0 else (.50, .02, .06), "graphite")
        else:
            for angle in (math.pi / 2, 3 * math.pi / 2) if axis == 0 else (0, math.pi):
                blade = [(.025, -.012), (.082, -.026), (.209, -.031), (.229, -.024),
                         (.229, .027), (.174, .035), (.073, .027), (.025, .012)]
                tip = [(.228, -.024), (.243, -.018), (.25, -.008), (.25, .009),
                       (.242, .018), (.228, .027)]
                for shape, paint in ((blade, "graphite light"), (tip, "yellow")):
                    outline = aim_profile(angle, shape)
                    rotor.loft((x, 1.28, z), 1, [(-.008, outline), (.008, outline)],
                               (paint, paint, paint))
        rotors.append(rotor.object(f"Test_Propeller_{i}", collection, palette, (x, 1.28, z)))
    for x in (-.114, .114):
        for z in (-.116, .142):
            sign = math.copysign(1, x)
            model.loft((x, 0, z), 1, [(.95, [(u + sign * .022, v) for u, v in contour(.045, .065, .009)]),
                                       (.973, [(u + sign * .021, v) for u, v in contour(.055, .072, .010)]),
                                       (1.088, contour(.060, .066, .012))],
                       ("black", "rubber", "graphite", "steel shade"))
    model.box((0, 1.035, .205), (.139, .103, .10), "black", .023, "rubber light", axis=2)
    model.round((0, 1.035, 0), 2, [(.249, .039), (.262, .038), (.275, .030)],
                ("rubber", "rubber", "glass", "glass light"), sides=16)
    body = model.object("Test_Drone", collection, palette, (0, 1.125, 0))
    for rotor in rotors:
        rotor.parent = body
        rotor.location -= body.location


def setup_studio(scene):
    studio = bpy.data.collections.new("PREVIEWS")
    scene.collection.children.link(studio)
    studio.hide_select = True
    studio.hide_viewport = True

    def add(name, data, position):
        obj = bpy.data.objects.new(name, data)
        studio.objects.link(obj)
        obj.location = position
        return obj

    def aim(obj, target):
        obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()

    for name, pos, target, scale in (
        ("Front", (0, -6, 1.60), (0, 0, 1.15), 2.73),
        ("High", (3.4, -5.1, 4.42), (0, 0, 1.13), 2.93),
    ):
        camera = bpy.data.cameras.new(name)
        camera.type = "ORTHO"
        camera.ortho_scale = scale
        aim(add(name, camera, pos), target)

    ground_mesh = bpy.data.meshes.new("Studio ground")
    ground_mesh.from_pydata([(-200, -200, -.002), (200, -200, -.002),
                             (200, 200, -.002), (-200, 200, -.002)], [], [(0, 1, 2, 3)])
    ground_mesh.materials.append(flat_material("Studio ground", (.052, .073, .113), .73))
    add("Ground", ground_mesh, (0, 0, 0))
    for name, pos, energy, size, color in (
        ("Key", (-3.1, -4.4, 5.6), 550, 4.2, (1, .86, .71)),
        ("Fill", (3.5, -2.2, 3.1), 340, 3.8, (.67, .81, 1)),
        ("Rim", (1.8, 3.0, 4.5), 720, 3.0, (.74, .85, 1)),
    ):
        light = bpy.data.lights.new(name, "AREA")
        light.energy = energy
        light.size = size
        light.color = color
        aim(add(name, light, pos), (0, 0, 1.05))
    scene.world = bpy.data.worlds.new("Soft factory daylight")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes["Background"]
    background.inputs[0].default_value = (.38, .48, .67, 1)
    background.inputs[1].default_value = .25
    scene.camera = bpy.data.objects["High"]
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 40
    scene.cycles.use_denoising = True
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    scene.render.resolution_x = scene.render.resolution_y = 1360
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = .15


def build(blockout=False):
    scene = bpy.context.scene
    palette = bpy.data.materials["DRONEWORKS_Palette"]
    palette.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = .43
    texture = next(n for n in palette.node_tree.nodes if n.type == "TEX_IMAGE")
    palette.node_tree.nodes.active = texture
    image = texture.image
    image.filepath = str(PALETTE)
    image.reload()
    export = bpy.data.collections["EXPORT"]
    root = table(blockout).object("Table", export, palette)
    for name, mesh in (("Platform", platform()), ("Backboard", backboard(blockout)), ("SignBoard", signboard())):
        mesh.object(name, export, palette, PIVOTS[name], root)
    lamp(export, root)

    test = bpy.data.collections.new("TEST_DRONE")
    scene.collection.children.link(test)
    drone(test, palette, blockout)

    refs = bpy.data.collections["REFERENCES"]
    refs.hide_viewport = refs.hide_render = True
    ref = bpy.data.objects.new("Quadcopter reference", None)
    ref.empty_display_type = "IMAGE"
    ref.data = bpy.data.images.load(str(REFERENCE), check_existing=True)
    refs.objects.link(ref)

    setup_studio(scene)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.region_3d.view_perspective = "ORTHO"
                space.region_3d.view_distance = 3.85
                space.region_3d.view_location = (0, 0, 1.13)
                space.region_3d.view_rotation = bpy.data.objects["High"].rotation_euler.to_quaternion()
                space.shading.color_type = "TEXTURE"
                space.overlay.show_floor = False
                space.overlay.show_axis_x = space.overlay.show_axis_y = False
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = root
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = "NONE"
    path = CHECKS / f"{STEM}.blockout.blend" if blockout else HERE / f"{STEM}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path), relative_remap=True)
    for asset in (image, ref.data):
        asset.filepath = bpy.path.relpath(bpy.path.abspath(asset.filepath))
        asset.pack()
    bpy.ops.wm.save_as_mainfile(filepath=str(path), relative_remap=True)


def render(output, size, samples):
    scene = bpy.context.scene
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.cycles.samples = samples
    output.mkdir(parents=True, exist_ok=True)
    for angle in ("Front", "High"):
        scene.camera = bpy.data.objects[angle]
        scene.render.filepath = str(output / f"{STEM}_{angle}.png")
        bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("blockout", "build", "draft", "render"))
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.mode in {"blockout", "build"}:
        build(args.mode == "blockout")
    else:
        draft = args.mode == "draft"
        render(CHECKS / "draft" if draft else HERE, 664 if draft else 1360, 16 if draft else 40)
