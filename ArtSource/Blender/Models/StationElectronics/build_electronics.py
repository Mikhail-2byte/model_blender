"""Build and recheck the DRONEWORKS electronics station with Blender Python."""
import argparse
import json
import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CHECKS = ROOT / ".local/checks/station-electronics"
STEM = "SM_StationElectronics"
PALETTE = ROOT / "ArtSource/Textures/T_Palette_DRONEWORKS.png"
REFERENCE = ROOT / "References/station_stamping_press.png"
PIVOTS = {
    "Base": (0, 0, 0),
    "Cabinet": (0, 1.45, 0),
    "IntakeTray": (0, .875, 1.175),
    "OutputTray": (-1.25, .875, 0),
    "Light_0": (-.30, 1.75, .465),
    "Light_1": (0, 1.75, .465),
    "Light_2": (.30, 1.75, .465),
    "Lamp": (.55, 2.15, .15),
    "SignBoard": (0, 2.78, .24),
}
SWATCHES = {
    "steel_dark": (0, 0), "steel": (1, 0), "steel_light": (2, 0),
    "ochre": (4, 0), "yellow": (5, 0), "gold": (6, 0),
    "black": (0, 1), "graphite": (1, 1), "graphite_light": (2, 1),
    "navy": (4, 1), "rubber": (5, 3), "rubber_light": (6, 3),
    "reflect": (0, 7),
}
INTAKE = (0, 1.175, 1.30, 1.15)
OUTPUT = (-1.25, 0, .90, 1.00)
DECK = .90
LIP = .98
WALL = .03
TOL = .0001


def basis(point):
    """Map Blender coordinates to the Unity importer basis for this export profile."""
    x, y, z = point
    return Vector((-x, z, -y))


def blender(point):
    x, y, z = point
    return Vector((-x, -z, y))


def uv(color):
    col, row = SWATCHES[color]
    return ((col + .5) / 8, 1 - (row + .5) / 8)


def material(name, color, roughness, emission=0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*color, 1)
    shader = mat.node_tree.nodes["Principled BSDF"]
    shader.inputs["Base Color"].default_value = mat.diffuse_color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Emission Color"].default_value = mat.diffuse_color
    shader.inputs["Emission Strength"].default_value = emission
    return mat


def bounds(points):
    return tuple(Vector(func(point[axis] for point in points) for axis in range(3))
                 for func in (min, max))


def near(actual, expected):
    return all(abs(a - b) < TOL for a, b in zip(actual, expected, strict=True))


def numbers(values):
    return [round(value, 5) for value in values]


class Assembly:
    def __init__(self, collection, palette):
        self.collection = collection
        self.palette = palette
        self.pieces = []

    def mesh(self, name, points, faces, paint, bevel=0, segments=1, mat=None, smooth=False):
        data = bpy.data.meshes.new(name)
        data.from_pydata([blender(point) for point in points], [], faces)
        obj = bpy.data.objects.new(name, data)
        self.collection.objects.link(obj)
        bm = bmesh.new()
        bm.from_mesh(data)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(data)
        bm.free()
        data.materials.append(mat or self.palette)
        bpy.context.view_layer.objects.active = obj
        if bevel:
            edge = obj.modifiers.new("Cast edge", "BEVEL")
            edge.width = bevel
            edge.segments = segments
            bpy.ops.object.modifier_apply(modifier=edge.name)
            degenerate = [edge.index for edge in data.edges
                          if (data.vertices[edge.vertices[0]].co - data.vertices[edge.vertices[1]].co).length < 1e-6]
            assert not degenerate, (name, degenerate)
        uv_data = data.uv_layers.new(name="UVMap").data
        colors = [paint] * len(data.polygons) if isinstance(paint, str) else paint
        for face, color in zip(data.polygons, colors, strict=True):
            face.use_smooth = bool(bevel or smooth)
            for loop in face.loop_indices:
                uv_data[loop].uv = uv(color)
        if bevel or smooth:
            normal = obj.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
            bpy.ops.object.modifier_apply(modifier=normal.name)
        self.pieces.append(obj)
        return obj

    def sections(self, name, center, axis, profile, color, bevel=0, segments=1, mat=None, smooth=False):
        count = len(profile[0][1])
        vertices = []
        for offset, contour in profile:
            for u, v in contour:
                point = [u, v]
                point.insert(axis, offset)
                vertices.append(tuple(a + b for a, b in zip(center, point, strict=True)))
        faces = [tuple(range(count))]
        for start in range(0, len(vertices) - count, count):
            for j in range(count):
                a, b = start + j, start + (j + 1) % count
                faces.append((a, b, b + count, a + count))
        faces.append(tuple(range(len(vertices) - count, len(vertices))))
        paints = ([color[0]] + [entry for entry in color[1:-1] for _ in range(count)]
                  + [color[-1]]) if isinstance(color, tuple) else color
        return self.mesh(name, vertices, faces, paints, bevel, segments, mat, smooth)

    def box(self, name, center, size, color, bevel=.01, segments=1):
        w, h, d = size
        contour = rectangle(w, d)
        return self.sections(name, center, 1, [(-h / 2, contour), (h / 2, contour)],
                             color, min(bevel, min(size) * .45), segments)

    def round(self, name, center, axis, profile, color, sides=16, mat=None, phase=0):
        contours = [
            (offset, [(r * math.cos(math.tau * i / sides + phase),
                       r * math.sin(math.tau * i / sides + phase)) for i in range(sides)])
            for offset, r in profile
        ]
        return self.sections(name, center, axis, contours, color, mat=mat, smooth=sides > 6)

    def bolt(self, center, axis, scale=1, direction=1):
        self.round("Shouldered hex bolt", center, axis,
                   [(direction * d * scale, r * scale)
                    for d, r in [(-.004, .037), (.003, .037), (.013, .031), (.018, .025)]],
                   ("steel_dark", "steel_dark", "steel", "steel_light", "reflect"),
                   sides=6, phase=math.pi / 6)

    def finish(self, name, parent=None):
        bpy.ops.object.select_all(action="DESELECT")
        for part in self.pieces:
            part.select_set(True)
        root = self.pieces[0]
        bpy.context.view_layer.objects.active = root
        if len(self.pieces) > 1:
            bpy.ops.object.join()
        pivot = blender(PIVOTS[name])
        root.data.transform(root.matrix_world.copy())
        for vertex in root.data.vertices:
            vertex.co -= pivot
        root.location = pivot
        root.name = root.data.name = name
        root.parent = parent
        self.pieces.clear()
        return root


def rectangle(w, d, clip=0):
    x, y = w / 2, d / 2
    if not clip:
        return [(-x, -y), (x, -y), (x, y), (-x, y)]
    return [(-x + clip, -y), (x - clip, -y), (x, -y + clip), (x, y - clip),
            (x - clip, y), (-x + clip, y), (-x, y - clip), (-x, -y + clip)]


def make_base(kit, blockout):
    box = kit.box
    if blockout:
        box("Main foundation", (0, .425, .575), (1.60, .85, 2.35), "steel", 0)
        box("Output pedestal", (-1.25, .425, 0), (.90, .85, 1), "steel", 0)
    else:
        for i, (x, z, w, d) in enumerate([(0, .575, 1.60, 2.35), (-1.25, 0, .90, 1)]):
            kit.sections("Cast plinth", (x, 0, z), 1,
                         [(y, rectangle(w - inset, d - inset, clip)) for y, inset, clip in [
                             (.089, .17, .07), (.13, .095, .065), (.23, .045, .06),
                             (.685, .045, .06), (.747, 0, .057), (.802, 0, .057),
                             (.85, .096, .04)]],
                         ("steel_dark", "black", "steel_dark", "steel", "steel",
                          "steel_light", "steel_light", "steel"))
            for sx in (-1, 1):
                for sz in (-1, 1):
                    foot = (x + sx * (w / 2 - .16), .057, z + sz * (d / 2 - .18))
                    box("Signal yellow cast foot", foot, (.31, .114, .34), "yellow", .025)
                    box("Foot isolator", (foot[0], .018, foot[2]), (.26, .036, .29),
                        "black", 0)
            if i == 0:
                # The front door and guide stay inside the plinth envelope.
                box("Intake service recess", (0, .442, 1.729), (1.18, .425, .037), "steel_dark", .017)
                box("Intake service panel", (0, .423, 1.740), (1.035, .288, .019), "steel", .008)
                kit.sections("Intake edge marker", (0, .636, 1.73), 2, [
                    (-.02, [(-.58, .068), (.58, .068), (.52, -.052), (-.52, -.052)]),
                    (.018, [(-.58, .068), (.58, .068), (.52, -.052), (-.52, -.052)])],
                    "yellow", .011)
                box("Recessed intake grip", (0, .638, 1.739), (.36, .039, .022), "graphite", .01)
                for bx in (-.46, .46):
                    kit.bolt((bx, .43, 1.737), 2, .63)
            else:
                box("Output access cover", (-1.684, .448, 0), (.028, .47, .75), "steel_dark", .013)
                box("Output cover inset", (-1.695, .432, 0), (.01, .34, .59), "steel", .004)
                for dz in (-.255, .255):
                    kit.bolt((-1.689, .43, dz), 0, .58, -1)
                for dz in (-.305, .305):
                    box("Output edge cleat", (-1.686, .661, dz), (.028, .15, .18), "yellow", .012)
                box("Output edge recess", (-1.685, .691, 0), (.027, .062, .38), "graphite", .012)
        for side in (-1, 1):
            box("Main side armor", (side * .768, .425, .93), (.036, .435, 1.19),
                "steel_dark", .016)
            box("Raised side inset", (side * .788, .428, .93), (.022, .335, 1.025),
                "steel", .01)
            for z in (.465, 1.395):
                kit.bolt((side * .789, .43, z), 0, .6, side)
        for x in (-.56, .56):
            kit.bolt((x, .422, -.583), 2, .77, -1)
            box("Rear base bumper", (x, .244, -.58), (.172, .14, .039), "black")
    if not blockout:
        kit.round("Beacon socket", (.55, 2.05, .15), 1,
                  [(-.012, .133), (.003, .133), (.028, .117), (.045, .086), (.051, .073)],
                  ("steel_dark", "steel_dark", "steel", "steel_light", "black", "black"), sides=20)
    for x in (-.52, .52):
        box("Sign mast", (x, 2.321, -.193), (.112, .595, .134), "steel_dark", 0 if blockout else .013)
        if not blockout:
            box("Mast clamping shoe", (x, 2.059, -.193), (.195, .065, .189), "steel", .017)
            box("Mast inset", (x, 2.321, -.119), (.052, .466, .026), "steel", .01)
            box("Panel rear bracket", (x, 2.599, -.055), (.136, .127, .38), "steel_dark", .015)
    return kit.finish("Base")


def make_cabinet(kit, root, blockout):
    box = kit.box
    if blockout:
        box("Cabinet volume", (0, 1.45, 0), (1.4, 1.2, .9), "steel", 0)
        return kit.finish("Cabinet", root)
    box("Closed cabinet casting", (0, 1.45, -.029), (1.34, 1.20, .774), "steel", .060, 2)
    box("Lower cabinet gasket", (0, .893, -.064), (1.31, .083, .744), "steel_dark", .025)
    box("Service door gasket", (0, 1.263, .352), (1.24, .661, .073), "navy", .03)
    box("Service door", (0, 1.267, .389), (1.166, .583, .071), "steel_light", .04, 2)
    box("Recessed access latch", (.368, 1.269, .424), (.186, .22, .021), "steel_dark", .009)
    box("Latch bracket upper", (.368, 1.324, .433), (.101, .046, .03), "ochre", .012)
    box("Latch bracket lower", (.368, 1.216, .433), (.101, .046, .03), "ochre", .012)
    box("Latch bar", (.368, 1.269, .436), (.079, .133, .028), "yellow", .013)
    for y in (1.098, 1.438):
        box("Door hinge", (-.567, y, .383), (.124, .103, .084), "steel_dark", .018)
        kit.round("Hinge barrel", (-.58, y, .411), 1,
                  [(-.058, .022), (-.048, .031), (.048, .031), (.058, .022)],
                  "steel", sides=8)
    for x in (-.428, .428):
        kit.bolt((x, 1.058, .423), 2, .68)
    box("Status fascia", (0, 1.75, .365), (1.265, .288, .105), "steel_dark", .028, 2)
    box("Status fascia inset", (0, 1.75, .413), (1.065, .202, .031), "navy", .013)
    for x in (-.563, .563):
        kit.bolt((x, 1.75, .414), 2, .7)
    for x in (-.30, 0, .30):
        kit.round("Status lens bezel", (x, 1.75, 0), 2,
                  [(.424, .095), (.438, .095), (.45, .080)],
                  ("steel_dark", "steel_dark", "steel_light", "black"), sides=16)
    for side in (-1, 1):
        box("Vent surround", (side * .668, 1.551, -.055), (.03, .576, .555), "steel_dark", .012)
        box("Vent shadow", (side * .683, 1.551, -.055), (.009, .397, .413), "navy", .003)
        for y in (1.436, 1.551, 1.666):
            slat = [(side * x, h) for x, h in [(-.011, .033), (.014, .017), (.014, -.028), (-.011, -.022)]]
            kit.sections("Vent louver", (side * .686, y, -.055), 2,
                         [(z, slat) for z in (-.191, .191)],
                         "steel_light", .004)
        for y in (1.315, 1.787):
            kit.bolt((side * .682, y, -.055), 0, .6, side)
    box("Rear panel seat", (0, 1.455, -.410), (1.151, .821, .044), "steel_dark", .018)
    box("Rear service panel", (0, 1.455, -.426), (1.028, .708, .022), "steel", .009)
    for x in (-.442, .442):
        for y in (1.181, 1.728):
            kit.bolt((x, y, -.43884), 2, .62, -1)
    return kit.finish("Cabinet", root)


def make_tray(kit, root, name, dimensions, blockout):
    x, z, w, d = dimensions
    if blockout:
        kit.box("Deck", (x, .875, z), (w, .05, d), "graphite", 0)
        for sign in (-1, 1):
            kit.box("Side rim", (x + sign * (w - WALL) / 2, .94, z),
                    (WALL, .08, d - 2 * WALL), "rubber", 0)
            kit.box("End rim", (x, .94, z + sign * (d - WALL) / 2),
                    (w, .08, WALL), "rubber", 0)
    else:
        # Single closed tray. The inner wall stays square at its full clear size.
        kit.sections("Folded tray with flat deck", (x, 0, z), 1, [
            (.85, rectangle(w - .023, d - .023)),
            (.867, rectangle(w, d)),
            (.967, rectangle(w, d)),
            (LIP, rectangle(w - .018, d - .018)),
            (LIP, rectangle(w - 2 * WALL + .012, d - 2 * WALL + .012)),
            (.971, rectangle(w - 2 * WALL, d - 2 * WALL)),
            (DECK, rectangle(w - 2 * WALL, d - 2 * WALL)),
        ], ("black", "black", "graphite", "graphite_light", "graphite_light",
            "graphite_light", "graphite", "rubber"))
    return kit.finish(name, root)


def make_sign(kit, root, blockout):
    if blockout:
        kit.box("Sign envelope", (0, 2.78, .195), (1.90, .50, .101), "graphite", 0)
    else:
        kit.sections("Cast bezel and recessed sign face", (0, 2.78, 0), 2, [
            (z, rectangle(w, h, c)) for z, w, h, c in [
                (.13, 1.834, .448, .029), (.153, 1.90, .50, .036),
                (.228, 1.90, .50, .036), (.248, 1.869, .480, .029),
                (.248, 1.834, .456, .016), (.231, 1.813, .444, .012)
            ]
        ], ("steel_dark", "steel_dark", "steel", "steel_light", "steel", "black", "graphite"))
        kit.box("Rear sign stiffener", (0, 2.691, .111), (1.43, .163, .105), "steel_dark", .023)
        for x in (-.67, .67):
            kit.bolt((x, 2.689, .067), 2, .73, -1)
    return kit.finish("SignBoard", root)


def make_lights(kit, root, blockout):
    for index in range(3):
        name = f"Light_{index}"
        lens = material(f"DRONEWORKS_Electronics_{name}", (.57, .57, .57), .235)
        kit.round("Status lens", PIVOTS[name], 2,
                  [(-.015, .063), (-.009, .07), (.004, .07), (.015, .059)],
                  "reflect", sides=12 if blockout else 24, mat=lens)
        kit.finish(name, root)
    lamp = material("DRONEWORKS_Electronics_Lamp", (.071, .61, .124), .24, .26)
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=16 if blockout else 24, ring_count=8 if blockout else 12,
        radius=.10, location=blender(PIVOTS["Lamp"]))
    obj = bpy.context.object
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    kit.collection.objects.link(obj)
    obj.data.materials.append(lamp)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    kit.pieces.append(obj)
    kit.finish("Lamp", root)


def render_setup(scene, blockout):
    studio = bpy.data.collections.new("PREVIEW")
    scene.collection.children.link(studio)

    def add(name, data):
        obj = bpy.data.objects.new(name, data)
        studio.objects.link(obj)
        return obj

    floor_mesh = bpy.data.meshes.new("Studio floor")
    floor_mesh.from_pydata([(-200, -200, 0), (200, -200, 0), (200, 200, 0), (-200, 200, 0)],
                           [], [(0, 1, 2, 3)])
    floor = add("Studio floor", floor_mesh)
    floor.location.z = -.003
    floor_mesh.materials.append(material("Studio slate", (.044, .056, .080), .83))
    floor.hide_set(True)

    def aim(obj, position, target):
        obj.location = blender(position)
        obj.rotation_euler = (blender(target) - obj.location).to_track_quat("-Z", "Y").to_euler()

    def camera(name, position, target, lens=52, ortho=None):
        data = bpy.data.cameras.new(name)
        data.clip_end = 450
        obj = add(name, data)
        aim(obj, position, target)
        if ortho:
            data.type = "ORTHO"
            data.ortho_scale = ortho
        data.lens = lens
        obj.hide_set(True)
        return obj

    scene.camera = camera("Front", (-.74, 3.09, 7.32), (-.29, 1.47, .52), ortho=3.85)
    camera("Output", (-5.78, 3.58, 4.03), (-.32, 1.47, .52), ortho=4.10)
    camera("Reference_Stamping", (4.05, 3.51, 6.12), (-.28, 1.49, .5), ortho=4.23)
    camera("Intake_Eye", (0, 1.65, 2.55), (0, .97, 1.175), 29)
    camera("Output_Eye", (-2.56, 1.65, .07), (-1.25, 1.10, 0), 30)
    camera("Top", (-.36, 7.1, .58), (-.36, 0, .575), ortho=3.35)
    camera("Rear", (3.45, 2.65, -5.35), (-.37, 1.44, .4), ortho=4.05)

    for name, loc, target, power, size, rgb in [
        ("Warm key", (-3.24, 6.1, 4.86), (0, 1.1, .25), 790, 4.2, (1, .88, .75)),
        ("Cool fill", (4.2, 3.7, 3.1), (0, 1.3, .4), 585, 4.0, (.77, .86, 1)),
        ("Soft rear rim", (-.65, 5.8, -3.7), (0, 1.5, .4), 1000, 3.4, (.79, .88, 1)),
        ("Output fill", (-4.3, 1.8, -.3), (-1.25, .75, .0), 85, 3.0, (.84, .90, 1)),
    ]:
        data = bpy.data.lights.new(name, "AREA")
        data.energy, data.size, data.color = power, size, rgb
        obj = add(name, data)
        aim(obj, loc, target)
        obj.hide_set(True)

    scene.world = bpy.data.worlds.new("Studio ambient")
    scene.world.use_nodes = True
    world = scene.world.node_tree.nodes["Background"]
    world.inputs["Color"].default_value = (.19, .22, .28, 1)
    world.inputs["Strength"].default_value = .36
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 40
    scene.cycles.use_denoising = True
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.render.resolution_x, scene.render.resolution_y = (1450, 1450)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    if blockout:
        scene.view_layers[0].material_override = material("Graybox", (.40, .43, .49), .53)


def placeholders(scene):
    guides = bpy.data.collections["REFERENCES"]
    guide = Assembly(guides, None)
    for name, loc, dims, color in [
        ("Fit_Frame", (0, .995, 1.175), (.73, .19, .73), (.13, .36, .57)),
        ("Fit_Drone", (-1.25, 1.10, 0), (.73, .35, .73), (.63, .31, .05)),
        ("UI_Progress", (0, 2.40, .24), (1.20, .09, .02), (.13, .36, .57)),
        ("UI_Heat", (0, 3.08, .24), (1.20, .09, .02), (.63, .31, .05)),
    ]:
        mat = material(name + "_Guide", color, .50)
        w, h, d = dims
        obj = guide.sections(name, loc, 1, [(-h / 2, rectangle(w, d)), (h / 2, rectangle(w, d))],
                             "reflect", mat=mat)
        obj.display_type = "WIRE"
        obj.show_in_front = True
        obj.hide_set(True)
        obj.hide_render = True
    source = bpy.data.objects.new("Reference · Stamping (style)", None)
    guides.objects.link(source)
    source.empty_display_type = "IMAGE"
    source.data = bpy.data.images.load(str(REFERENCE), check_existing=True)
    source.empty_display_size = 3.3
    source.location = (3.4, 1.5, 1.7)
    source.rotation_euler = (math.pi / 2, 0, 0)
    source.hide_set(True)


def export_objects():
    return {obj.name: obj for obj in bpy.context.scene.objects if obj.type == "MESH"
            and obj.name in PIVOTS}


def mesh_points(obj):
    return [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]


def fit(objects):
    """Check full rectangular clearances and lifted paths against actual mesh faces."""
    geometry = []
    for obj in objects.values():
        vertices = mesh_points(obj)
        polygons = [tuple(poly.vertices) for poly in obj.data.polygons]
        geometry.append((obj.name, bounds(vertices), BVHTree.FromPolygons(vertices, polygons)))

    def box_hits(center, size):
        half = Vector(size) / 2 - Vector((.0002,) * 3)
        corners = [blender(tuple(Vector(center) + Vector((sx * half.x, sy * half.y, sz * half.z))))
                   for sz in (-1, 1) for sy in (-1, 1) for sx in (-1, 1)]
        faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3),
                 (0, 4, 6, 2), (1, 3, 7, 5)]
        probe = BVHTree.FromPolygons(corners, faces)
        lo, hi = bounds(corners)
        hits = []
        for name, (a, b), tree in geometry:
            if all(lo[i] < b[i] and hi[i] > a[i] for i in range(3)):
                if tree.overlap(probe):
                    hits.append(name)
                elif all(lo[i] <= a[i] <= b[i] <= hi[i] for i in range(3)):
                    hits.append(name)
        return sorted(hits)

    checks = {
        "intake_clear_rectangle": ((0, .94, 1.175), (1.24, .08, 1.09)),
        "output_clear_rectangle": ((-1.25, .94, 0), (.84, .08, .94)),
        "frame_on_deck": ((0, .995, 1.175), (.73, .19, .73)),
        "frame_straight_in_above_rim": ((0, 1.095, 1.8625), (.73, .19, 2.105)),
        "drone_at_prefab_output": ((-1.25, 1.1, 0), (.73, .35, .73)),
        "drone_lift_75_mm": ((-1.25, 1.1375, 0), (.73, .425, .73)),
        "drone_slide_outside_after_lift": ((-1.75, 1.175, 0), (1.73, .35, .73)),
        "sign_label_plane": ((0, 2.78, .255), (1.80, .44, .009)),
        "progress_bar": ((0, 2.40, .246), (1.20, .09, .031)),
        "heat_bar": ((0, 3.08, .246), (1.20, .09, .031)),
    }
    results = {}
    for name, (center, size) in checks.items():
        hits = box_hits(center, size)
        results[name] = {"center_unity": center, "size_unity": size, "intersections": hits}
        assert not hits, f"{name}: {hits}"

    for name, eye, target, expected in [
        ("intake_eye", (0, 1.65, 2.55), (0, .9, 1.175), "IntakeTray"),
        ("output_eye", (-2.56, 1.65, .07), (-1.25, .9, 0), "OutputTray"),
    ]:
        start, end = blender(eye), blender(target)
        length = (end - start).length
        hits = []
        for part, _, tree in geometry:
            hit, _, _, dist = tree.ray_cast(start, (end - start).normalized(), length + .01)
            if hit is not None:
                hits.append((dist, part, hit))
        dist, part, hit = min(hits)
        assert part == expected and abs(dist - length) < .002, (name, part, dist, length)
        assert dist < 2.5
        results[name] = {"distance_m": round(dist, 3), "surface": part, "hit_unity": numbers(basis(hit))}
    return results


def inspect(objects, output):
    bpy.context.view_layer.update()
    assert set(objects) == set(PIVOTS), set(objects)
    measured, all_points = {}, []
    for name, obj in objects.items():
        assert obj.parent == (None if name == "Base" else objects["Base"]), name
        points = [basis(point) for point in mesh_points(obj)]
        lo, hi = bounds(points)
        all_points.extend(points)
        pivot = basis(obj.matrix_world.translation)
        assert near(pivot, PIVOTS[name]), (name, pivot)
        obj.data.calc_loop_triangles()
        assert obj.data.uv_layers.active and all(obj.data.materials), name
        expected_material = (f"DRONEWORKS_Electronics_{name}" if name.startswith("Light_") or name == "Lamp"
                             else "DRONEWORKS_Palette")
        assert [m.name for m in obj.data.materials] == [expected_material], name
        if expected_material == "DRONEWORKS_Palette":
            actual_uv = {(round(loop.uv.x, 6), round(loop.uv.y, 6))
                         for loop in obj.data.uv_layers.active.data}
            assert actual_uv <= {uv(color) for color in SWATCHES}, (name, actual_uv)
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        assert all(edge.is_manifold and edge.calc_length() > 1e-6 for edge in bm.edges), name
        assert all(face.calc_area() > 1e-9 for face in bm.faces), name
        bm.free()
        measured[name] = {"unity_min": numbers(lo), "unity_max": numbers(hi),
                          "unity_size": numbers(hi - lo), "unity_pivot": numbers(pivot),
                          "triangles": len(obj.data.loop_triangles),
                          "materials": [m.name for m in obj.data.materials]}
    boxes = {
        "Cabinet": ((-.70, .85, -.45), (.70, 2.05, .45)),
        "IntakeTray": ((-.65, .85, .60), (.65, .98, 1.75)),
        "OutputTray": ((-1.70, .85, -.50), (-.80, .98, .50)),
        "Lamp": ((.45, 2.05, .05), (.65, 2.25, .25)),
        "SignBoard": ((-.95, 2.53), (.95, 3.03)),
    }
    for name, (lo, hi) in boxes.items():
        actual = measured[name]
        assert near(actual["unity_min"][:len(lo)], lo), (name, actual)
        assert near(actual["unity_max"][:len(hi)], hi), (name, actual)
    for name in ("Light_0", "Light_1", "Light_2"):
        assert near(measured[name]["unity_size"], (.14, .14, .03)), measured[name]
    low, high = bounds(all_points)
    assert near(low, (-1.7, 0, -.60)) and near(high, (.95, 3.03, 1.75)), (low, high)
    triangles = sum(row["triangles"] for row in measured.values())
    assert triangles <= 6000, triangles
    report = {"blender": bpy.app.version_string, "triangles": triangles,
              "unity_size": numbers(high - low), "mesh": measured, "fit": fit(objects)}
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{output.name}: {triangles} triangles, {report['unity_size']} in Unity axes")


def save(path):
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = "NONE"
    bpy.ops.wm.save_as_mainfile(filepath=str(path), relative_remap=True, compress=True)


def render(camera, path, size=1450, samples=40):
    scene = bpy.context.scene
    scene.camera = bpy.data.objects[camera]
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.cycles.samples = samples
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def build(blockout):
    scene = bpy.context.scene
    palette = bpy.data.materials["DRONEWORKS_Palette"]
    shader = palette.node_tree.nodes["Principled BSDF"]
    shader.inputs["Roughness"].default_value = .42
    image = next(node.image for node in palette.node_tree.nodes if node.type == "TEX_IMAGE")
    image.filepath = str(PALETTE)
    image.reload()
    image.pack()
    kit = Assembly(bpy.data.collections["EXPORT"], palette)
    root = make_base(kit, blockout)
    make_cabinet(kit, root, blockout)
    make_tray(kit, root, "IntakeTray", INTAKE, blockout)
    make_tray(kit, root, "OutputTray", OUTPUT, blockout)
    make_lights(kit, root, blockout)
    make_sign(kit, root, blockout)
    render_setup(scene, blockout)
    placeholders(scene)
    scene.unit_settings.scale_length = 1.0
    scene["Art direction"] = "DRONEWORKS | Station Electronics | Blender front -Y | Unity front +Z"
    scene["Unity bounds with gameplay UI"] = "2.65 x 3.125 x 2.35 m"
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = root
    preferred_rotation = scene.camera.rotation_euler.to_quaternion()
    for screen in bpy.data.screens:
        for area in (area for area in screen.areas if area.type == "VIEW_3D"):
            region = area.spaces.active.region_3d
            region.view_distance = 5.6
            region.view_location = blender((-.34, 1.52, .48))
            region.view_rotation = preferred_rotation
            region.view_perspective = "ORTHO"
            area.spaces.active.overlay.show_floor = False
            area.spaces.active.overlay.show_axis_x = False
            area.spaces.active.overlay.show_axis_y = False
            area.spaces.active.shading.color_type = "TEXTURE"
    inspect(export_objects(), CHECKS / ("blockout.json" if blockout else "blend.json"))
    save(CHECKS / f"{STEM}.blockout.blend" if blockout else HERE / f"{STEM}.blend")
    if blockout:
        for name in ("Front", "Output", "Top", "Intake_Eye", "Output_Eye"):
            render(name, CHECKS / f"Blockout_{name}.png", 420, 8)


def reimport(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(path), use_image_search=False)
    objects = export_objects()
    assert set(bpy.context.scene.objects.keys()) == set(PIVOTS)
    inspect(objects, CHECKS / "fbx.json")
    palette = bpy.data.materials["DRONEWORKS_Palette"]
    palette.use_nodes = True
    shader = palette.node_tree.nodes["Principled BSDF"]
    image_node = next((node for node in palette.node_tree.nodes if node.type == "TEX_IMAGE"), None)
    if image_node is None:
        image_node = palette.node_tree.nodes.new("ShaderNodeTexImage")
    image_node.image = bpy.data.images.load(str(PALETTE), check_existing=True)
    image_node.interpolation = "Closest"
    palette.node_tree.links.new(image_node.outputs["Color"], shader.inputs["Base Color"])
    shader.inputs["Roughness"].default_value = .42
    render_setup(bpy.context.scene, False)
    for name in ("Front", "Output", "Rear", "Top"):
        render(name, CHECKS / f"FBX_{name}.png", 500, 12)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("blockout", "build", "preview", "render", "reimport"))
    parser.add_argument("--fbx", type=Path, default=ROOT / f"Exports/Unity/{STEM}.fbx")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    CHECKS.mkdir(parents=True, exist_ok=True)
    if args.mode in ("blockout", "build"):
        build(args.mode == "blockout")
    elif args.mode in ("preview", "render"):
        final = args.mode == "render"
        views = ("Front", "Output") if final else ("Front", "Output", "Rear", "Top", "Intake_Eye", "Output_Eye")
        guides = {"Intake_Eye": "Fit_Frame", "Output_Eye": "Fit_Drone"}
        for name in views:
            dest = HERE / f"{STEM}_{name}.png" if final else CHECKS / f"Preview_{name}.png"
            for view, guide in guides.items():
                bpy.data.objects[guide].hide_render = view != name
            render(name, dest, 1450 if final else 570, 40 if final else 12)
    else:
        reimport(args.fbx)


if __name__ == "__main__":
    main()
