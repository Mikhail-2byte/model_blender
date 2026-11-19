"""Build the stamping press from the DRONEWORKS template with Blender's Python."""

import argparse
import json
import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CHECKS = ROOT / ".local/checks/station-stamping"
MODEL = HERE / "SM_StationStamping.blend"
TILE = HERE.parent / "ConveyorSegment/Conveyor_HazardTile.png"
REFERENCE = ROOT / "References/station_stamping_press.png"
DIMENSIONS = (2.65, 3.08, 2.10)
STROKE = .50
PARTS = {
    "Base": (0, 0, 0),
    "Columns": (0, .85, 0),
    "TopBeam": (0, 2.25, 0),
    "PressHead": (0, 1.975, 0),
    "IntakeTray": (0, .85, 1.05),
    "OutputTray": (-1.25, .85, 0),
    "Lamp": (.55, 2.45, .15),
    "SignBoard": (0, 2.92, .24),
}
COLORS = {
    "steel_shadow": (0, 0), "steel": (1, 0), "steel_edge": (2, 0),
    "ochre": (4, 0), "yellow": (5, 0), "yellow_edge": (6, 0),
    "black": (0, 1), "graphite": (1, 1), "graphite_edge": (2, 1),
    "navy": (4, 1), "rubber": (5, 3), "glass": (0, 4),
    "alloy": (0, 7), "silver": (1, 7),
}
TOL = .001


def blender(point):
    # FBX importer converts handedness by reflecting X in Unity. This sign
    # was measured using the same export settings in the workshop truck test.
    x, height, depth = point
    return Vector((-x, -depth, height))


def unity(point):
    return Vector((-point.x, point.z, -point.y))


def span(points):
    return tuple(Vector(operation(p[axis] for p in points) for axis in range(3))
                 for operation in (min, max))


def rounded(vector):
    return [round(float(v), 5) for v in vector]


def near(actual, expected):
    return all(abs(a - b) <= TOL for a, b in zip(actual, expected))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def swatch(name):
    column, row = COLORS[name]
    return (column + .5) / 8, 1 - (row + .5) / 8


def principled(name, color, roughness, metallic=0):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = (*color, 1)
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    return material, shader


def load_materials():
    palette = bpy.data.materials["DRONEWORKS_Palette"]
    palette.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = .42
    hazard, hazard_shader = principled("DRONEWORKS_StampingHazard", (.7, .32, .01), .41, .08)
    tex = hazard.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(TILE), check_existing=True)
    tex.extension = "REPEAT"
    tex.interpolation = "Linear"
    hazard.node_tree.links.new(tex.outputs["Color"], hazard_shader.inputs["Base Color"])

    def linear(value):
        value /= 255
        return ((value + .055) / 1.055) ** 2.4

    green = tuple(linear(value) for value in (60, 214, 90))
    lamp, lamp_shader = principled("DRONEWORKS_StampingLamp", green, .23)
    lamp_shader.inputs["Emission Color"].default_value = (*green, 1)
    lamp_shader.inputs["Emission Strength"].default_value = .32
    return palette, hazard, lamp


class Assembly:
    def __init__(self, export, materials):
        self.collection = export
        self.palette, self.hazard, self.lamp = materials
        self.pieces = []

    def mesh(self, name, points, faces, paints, bevel=0, segments=1):
        data = bpy.data.meshes.new(name)
        data.from_pydata([blender(point) for point in points], [], faces)
        data.update()
        obj = bpy.data.objects.new(name, data)
        self.collection.objects.link(obj)
        bm = bmesh.new()
        bm.from_mesh(data)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(data)
        bm.free()
        data.materials.append(self.palette)
        if bevel:
            bpy.context.view_layer.objects.active = obj
            modifier = obj.modifiers.new("Cast edge", "BEVEL")
            modifier.width = bevel
            modifier.segments = segments
            modifier.limit_method = "ANGLE"
            modifier.affect = "EDGES"
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        self.paint(obj, paints)
        if bevel:
            self.weight_normals(obj)
        self.pieces.append(obj)
        return obj

    def paint(self, obj, paints):
        data = obj.data
        uv = data.uv_layers.new(name="UVMap")
        if isinstance(paints, str):
            paints = [paints] * len(data.polygons)
        for polygon, paint in zip(data.polygons, paints, strict=True):
            for loop in polygon.loop_indices:
                uv.data[loop].uv = swatch(paint)

    def weight_normals(self, obj):
        bpy.context.view_layer.objects.active = obj
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        modifier = obj.modifiers.new("Face-weighted normals", "WEIGHTED_NORMAL")
        modifier.weight = 50
        bpy.ops.object.modifier_apply(modifier=modifier.name)

    def box(self, name, center, size, color="steel", bevel=.015, segments=1):
        signs = ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                 (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))
        vertices = [tuple(c + s * d / 2 for c, s, d in zip(center, corner, size))
                    for corner in signs]
        faces = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
        return self.mesh(name, vertices, faces, color, min(bevel, .46 * min(size)), segments)

    def lathe(self, name, center, profile, color, axis=1, steps=6):
        points = []
        for radius, offset in profile:
            for index in range(steps):
                angle = math.tau * (index + .5) / steps
                point = [radius * math.cos(angle), radius * math.sin(angle)]
                point.insert(axis, offset)
                points.append(tuple(base + delta for base, delta in zip(center, point)))
        faces = [tuple(range(steps))]
        for row in range(len(profile) - 1):
            a = row * steps
            b = a + steps
            for index in range(steps):
                nxt = (index + 1) % steps
                faces.append((a + index, a + nxt, b + nxt, b + index))
        faces.append(tuple(range(len(points) - steps, len(points))))
        obj = self.mesh(name, points, faces, color)
        if steps >= 12:
            self.weight_normals(obj)
        return obj

    def sphere(self):
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=20, ring_count=10, radius=.1, location=blender(PARTS["Lamp"]),
        )
        obj = bpy.context.object
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        self.collection.objects.link(obj)
        obj.data.materials.append(self.lamp)
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        self.pieces.append(obj)

    def join(self, name, parent=None):
        bpy.ops.object.select_all(action="DESELECT")
        for obj in self.pieces:
            obj.select_set(True)
        target = self.pieces[0]
        bpy.context.view_layer.objects.active = target
        if len(self.pieces) > 1:
            bpy.ops.object.join()
        self.pieces.clear()
        target.name = name
        target.data.name = name
        old_origin = target.location.copy()
        new_origin = blender(PARTS[name])
        for vertex in target.data.vertices:
            vertex.co += old_origin - new_origin
        target.location = new_origin
        target.parent = parent
        return target


def graybox(kit):
    box = kit.box
    box("Chassis", (0, .425, .45), (1.60, .85, 2.10), bevel=0)
    box("Anvil", (0, .875, 0), (1.10, .05, .90), "alloy", 0)
    base = kit.join("Base")
    for side in (-1, 1):
        box("Upright", (side * .70, 1.50, 0), (.15, 1.30, .15), bevel=0)
    kit.join("Columns", base)
    box("Crossbeam", (0, 2.25, 0), (1.60, .20, .45), bevel=0)
    kit.join("TopBeam", base)
    box("Press", (0, 1.85, 0), (1.00, .25, .80), "yellow", 0)
    kit.join("PressHead", base)
    for name, x, z, width, depth in (("IntakeTray", 0, 1.05, 1.30, .90),
                                     ("OutputTray", -1.25, 0, .90, 1.00)):
        if name == "OutputTray":
            box("Pedestal", (x, .425, z), (width, .85, depth), bevel=0)
        box("Tray floor", (x, .875, z), (width, .05, depth), "graphite", 0)
        for side in (-1, 1):
            box("Sidewall", (x + side * (width - .03) / 2, .94, z),
                (.03, .08, depth), "steel_shadow", 0)
            box("Endwall", (x, .94, z + side * (depth - .03) / 2),
                (width - .06, .08, .03), "steel_shadow", 0)
        kit.join(name, base)
    kit.sphere()
    kit.join("Lamp", base)
    for x in (-.72, .72):
        box("Sign bracket", (x, 2.558, .06), (.10, .42, .12), "steel_shadow", 0)
    box("Header", (0, 2.92, .19), (1.90, .32, .12), "graphite", 0)
    kit.join("SignBoard", base)


def foot(kit, x, z, width, depth):
    profile = ((0, .025), (.023, .023), (.035, 0), (.083, 0), (.105, .028), (.145, .047))
    points = [(a, y, b) for y, inset in profile
              for a, b in octagon(width - inset, depth - inset, .025, x, z)]
    faces = [tuple(range(8))]
    colors = ["black"]
    for ring, color in enumerate(("black", "graphite", "yellow", "yellow_edge", "ochre")):
        start = ring * 8
        for index in range(8):
            nxt = (index + 1) % 8
            faces.append((start + index, start + nxt, start + nxt + 8, start + index + 8))
            colors.append(color)
    faces.append(tuple(range(40, 48)))
    colors.append("ochre")
    kit.mesh("Safety shoe and isolator", points, faces, colors)


def bolt(kit, center, radius=.035, axis=2, sign=1, color="steel_edge"):
    profile = ((radius * .94, -.009 * sign), (radius, .002 * sign), (radius * .79, .011 * sign))
    kit.lathe("Hex cap", center, profile, color, axis)


def octagon(width, depth, corner, x=0, z=0):
    x0, x1 = x - width / 2, x + width / 2
    z0, z1 = z - depth / 2, z + depth / 2
    return [(x0 + corner, z0), (x1 - corner, z0), (x1, z0 + corner),
            (x1, z1 - corner), (x1 - corner, z1), (x0 + corner, z1),
            (x0, z1 - corner), (x0, z0 + corner)]


def tray(kit, x, z, width, depth, intake):
    start_y, end_y = .85, .98
    contours = [octagon(width - .010, depth - .010, .014, x, z),
                octagon(width, depth, .014, x, z),
                octagon(width, depth, .014, x, z),
                octagon(width - .009, depth - .009, .012, x, z)]
    heights = (start_y, start_y + .006, end_y - .005, end_y)
    points = [(a, y, b) for contour, y in zip(contours, heights) for a, b in contour]
    x0, x1 = x - width / 2 + .03, x + width / 2 - .03
    z0, z1 = z - depth / 2 + .03, z + depth / 2 - .03
    inside = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
    points += [(a, y, b) for y in (end_y, .90) for a, b in inside]
    faces, paints = [tuple(range(8))], ["steel_shadow"]

    def face(indices, paint):
        faces.append(indices)
        paints.append(paint)

    for ring, color in enumerate(("graphite", "steel_shadow", "steel")):
        a = ring * 8
        for index in range(8):
            nxt = (index + 1) % 8
            face((a + index, a + nxt, a + nxt + 8, a + index + 8), color)
    corners = (0, 1, 1, 2, 2, 3, 3, 0)
    for index in range(8):
        nxt = (index + 1) % 8
        a, b = 32 + corners[index], 32 + corners[nxt]
        indices = (24 + index, 24 + nxt, b) if a == b else (24 + index, 24 + nxt, b, a)
        wear_edge = "yellow" if intake and index == 4 else "steel_edge"
        face(indices, wear_edge)
    for index in range(4):
        nxt = (index + 1) % 4
        face((32 + index, 32 + nxt, 36 + nxt, 36 + index), "graphite")
    face((36, 37, 38, 39), "rubber")
    kit.mesh("Welded catch tray", points, faces, paints)


def press_casting(kit):
    profile = (
        (1.753, .904, .704, .036), (1.774, 1.00, .80, .048),
        (1.865, 1.00, .80, .048), (1.950, 1.00, .80, .048),
        (1.968, .974, .774, .042), (1.975, .951, .751, .036),
    )
    points = [(x, y, z) for y, w, d, c in profile for x, z in octagon(w, d, c)]
    faces = [tuple(range(8))]
    paints = ["ochre"]
    stripe_faces = set()
    for ring, color in enumerate(("ochre", "yellow", "yellow", "yellow_edge", "yellow")):
        start = ring * 8
        for index in range(8):
            nxt = (index + 1) % 8
            if ring == 1:
                stripe_faces.add(len(faces))
            faces.append((start + index, start + nxt, start + nxt + 8, start + index + 8))
            paints.append(color)
    faces.append(tuple(range(40, 48)))
    paints.append("yellow")
    casting = kit.mesh("Chamfered press casting", points, faces, paints)
    casting.data.materials.append(kit.hazard)
    rim = octagon(1.00, .80, .048)
    lengths = [math.dist(rim[i], rim[(i + 1) % 8]) for i in range(8)]
    repeat = sum(lengths) / 20
    uv = casting.data.uv_layers.active.data
    for index in stripe_faces:
        face = casting.data.polygons[index]
        first = index - min(stripe_faces)
        face.material_index = 1
        for loop in face.loop_indices:
            vertex_id = casting.data.loops[loop].vertex_index
            x, y, z = points[vertex_id]
            along = sum(lengths[:first]) + math.dist((x, z), rim[first])
            uv[loop].uv = (along / repeat, (y - 1.774) / (1.865 - 1.774))


def finish(kit):
    box = kit.box
    box("Fabricated chassis", (0, .443, .44), (1.548, .692, 2.034), "steel", .065, 2)
    box("Lower skirt", (0, .128, .44), (1.505, .086, 2.00), "steel_shadow", .036)
    box("Working deck", (0, .804, .45), (1.60, .092, 2.10), "steel", .032, 2)
    box("Hardened anvil", (0, .875, 0), (1.10, .05, .90), "alloy", .017)
    box("Intake transfer lip", (0, .841, .524), (1.05, .02, .163), "steel_edge", .009)
    box("Front access cover", (0, .438, 1.459), (1.285, .462, .048), "steel_shadow", .022)
    box("Front access face", (0, .438, 1.482), (1.198, .366, .019), "steel", .009)
    box("Feed marker recess", (0, .587, 1.491), (.61, .132, .016), "navy", .008)
    for x in (-.18, 0, .18):
        marks = [(x - .068, .555), (x - .068, .594), (x, .637),
                 (x + .068, .594), (x + .068, .555), (x, .597)]
        prism(kit, "Raised feed chevron", marks, (1.496, 1.50), 2, "yellow")
    for x in (-.56, .56):
        for y in (.282, .595):
            bolt(kit, (x, y, 1.488), .034)
    for x in (-.685, .685):
        for z in (-.447, 1.328):
            foot(kit, x, z, .23, .276)
    for side in (-1, 1):
        for z in (-.373, 1.242):
            bolt(kit, (side * .778, .575, z), .038, 0, side)
    box("Outer service door", (.77, .437, .49), (.05, .43, 1.30), "steel_shadow", .023)
    box("Outer raised panel", (.787, .437, .49), (.024, .349, 1.206), "steel", .009)
    box("Rear reinforcement", (0, .438, -.568), (1.30, .45, .057), "steel_shadow", .025)
    for x in (-.49, .49):
        bolt(kit, (x, .54, -.585), .033, 2, -1)
    base = kit.join("Base")

    for side in (-1, 1):
        x = side * .70
        box("Upright", (x, 1.50, 0), (.15, 1.30, .15), "steel", .016)
        box("Cast upright rib", (x, 1.507, -.055), (.153, 1.13, .18), "steel_shadow", .018)
        box("Lower upright saddle", (x, .921, 0), (.198, .144, .318), "steel", .027)
        box("Upper upright saddle", (x, 2.065, -.007), (.195, .17, .292), "steel", .02)
        box("Upright front flange", (x, 1.075, .078), (.137, .32, .057), "steel_edge", .015)
        bolt(kit, (x, 1.172, .107), .031, color="steel_shadow")
        bolt(kit, (x, 1.002, .107), .031, color="steel_shadow")

        guide_x = side * .308
        box("Rear guide column", (guide_x, 1.523, -.50), (.148, 1.346, .169), "steel_shadow", .02)
        box("Guide runner", (guide_x, 1.54, -.431), (.094, 1.16, .052), "steel_shadow", .009)
        box("Guide foot", (guide_x, .92, -.493), (.224, .14, .201), "steel", .015)
        box("Guide crown", (guide_x, 2.142, -.304), (.224, .126, .55), "steel_shadow", .021)
        bolt(kit, (guide_x, .945, -.398), .030)
    kit.join("Columns", base)

    box("Beam casting", (0, 2.25, -.018), (1.60, .20, .414), "steel", .031, 2)
    box("Beam front cladding", (0, 2.25, .188), (1.504, .137, .050), "steel", .015)
    box("Beam trim", (0, 2.294, .207), (.97, .018, .019), "steel_edge", .006)
    for x in (-.648, .648):
        bolt(kit, (x, 2.25, .214), .052)
    for side in (-1, 1):
        bolt(kit, (side * .785, 2.25, -.060), .034, 0, side)
    box("Ram saddle", (0, 2.122, -.06), (.46, .088, .48), "steel_shadow", .026)
    kit.lathe("Hydraulic cylinder", (0, 2.08, -.065),
              ((.22, -.05), (.231, -.033), (.231, .057), (.211, .076)),
              "graphite", steps=12)
    kit.lathe("Ram face", (0, 2.004, -.065),
              ((.136, -.023), (.151, -.012), (.151, .042)), "silver", steps=12)
    kit.lathe("Lamp socket", (.55, 2.35, .15),
              ((.073, -.018), (.073, -.005), (.057, .016)),
              "graphite", steps=12)
    kit.join("TopBeam", base)

    press_casting(kit)
    box("Tool steel die", (0, 1.7475, 0), (.757, .045, .529), "steel_shadow", .018)
    box("Tool clamp", (0, 1.774, -.038), (.84, .038, .646), "graphite", .012)
    for x in (-.309, .309):
        box("Rear guide shoe", (x, 1.891, -.363), (.155, .105, .074), "ochre", .012)
    kit.join("PressHead", base)

    tray(kit, 0, 1.05, 1.30, .90, True)
    kit.join("IntakeTray", base)
    box("Pedestal casting", (-1.25, .442, 0), (.852, .686, .96), "steel", .055, 2)
    box("Pedestal deck", (-1.25, .799, 0), (.90, .102, 1.00), "steel", .026, 2)
    box("Pedestal skirt", (-1.25, .131, 0), (.866, .093, .97), "steel_shadow", .026)
    for x in (-1.58, -.92):
        for z in (-.367, .367):
            foot(kit, x, z, .198, .211)
    face_outline = [(.265, -.34), (.20, -.275), (.20, .275), (.265, .34),
                    (.664, .34), (.728, .276), (.728, -.276), (.664, -.34)]
    prism(kit, "Retrieval side access plate", face_outline, (-1.69, -1.661), 0, "steel_shadow", .012)
    box("Retrieval recess", (-1.687, .617, 0), (.019, .131, .505), "navy", .009)
    box("Safety edge above grip", (-1.692, .673, 0), (.016, .035, .440), "yellow", .007)
    box("Lower grip lip", (-1.694, .575, 0), (.012, .036, .402), "steel_edge", .005)
    for z in (-.28, .28):
        bolt(kit, (-1.687, .33, z), .035, 0, -1)
        bolt(kit, (-1.687, .642, z), .035, 0, -1)
    for z in (-.48, .48):
        for x in (-1.56, -1.01):
            bolt(kit, (x, .47, z + math.copysign(.005, z)), .032, 2, math.copysign(1, z))
    tray(kit, -1.25, 0, .90, 1.00, False)
    kit.join("OutputTray", base)

    kit.sphere()
    kit.join("Lamp", base)
    for x in (-.72, .72):
        box("Sign mounting foot", (x, 2.35, .002), (.146, .054, .159), "steel_shadow", .014)
        box("Sign stanchion", (x, 2.561, .016), (.099, .431, .104), "steel", .015)
        box("Display rear bracket", (x, 2.802, .072), (.125, .109, .156), "steel_shadow", .013)
    box("Display housing", (0, 2.92, .176), (1.90, .32, .134), "steel", .029, 2)
    box("Display seal", (0, 2.92, .237), (1.805, .249, .026), "black", .012)
    box("Empty display face", (0, 2.92, .243), (1.75, .206, .010), "graphite", .004)
    kit.join("SignBoard", base)


def scene_collection(name):
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    return collection


def samples(palette):
    collection = scene_collection("FIT_CHECK")
    kit = Assembly(collection, (palette, None, None))
    sheet = kit.box("Fit_Sheet_0800x0500", (0, .925, 1.05), (.80, .05, .50), "silver", .009)
    frame_x = -1.25
    xp = (frame_x - .30, frame_x - .06, frame_x + .06, frame_x + .30)
    zp = (-.30, -.06, .06, .30)
    cross = [(xp[1], zp[0]), (xp[2], zp[0]), (xp[2], zp[1]), (xp[3], zp[1]),
             (xp[3], zp[2]), (xp[2], zp[2]), (xp[2], zp[3]), (xp[1], zp[3]),
             (xp[1], zp[2]), (xp[0], zp[2]), (xp[0], zp[1]), (xp[1], zp[1])]
    frame = prism(kit, "Fit_Frame_0600x0600", cross, (.90, .95), 1, "alloy", .007)
    for obj in (sheet, frame):
        obj["Purpose"] = "Game-size checking proxy. Excluded from FBX."
    return sheet, frame


def prism(kit, name, outline, axis_bounds, axis, color, bevel=0):
    points = []
    for bound in axis_bounds:
        for corner in outline:
            point = list(corner)
            point.insert(axis, bound)
            points.append(point)
    count = len(outline)
    faces = [tuple(range(count)), tuple(range(count, count * 2))]
    for index in range(count):
        nxt = (index + 1) % count
        faces.append((index, nxt, count + nxt, count + index))
    return kit.mesh(name, points, faces, color, bevel)


def evaluated_points(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return [unity(evaluated.matrix_world @ v.co) for v in evaluated.data.vertices]


def limits(objects):
    return span([point for obj in objects for point in evaluated_points(obj)])


def fit_review(parts, sheet, frame):
    scene = bpy.context.scene
    graph = bpy.context.evaluated_depsgraph_get()
    fit_cases = (
        (sheet, (-.62, .90, .63), (.62, .98, 1.47), (0, 1.65, 1.86)),
        (frame, (-1.67, .90, -.47), (-.83, .98, .47), (-2.06, 1.65, 0)),
    )
    approach = {}
    for target, inner_min, inner_max, eye in fit_cases:
        lo, hi = limits((target,))
        for axis in (0, 2):
            require(inner_min[axis] < lo[axis] < hi[axis] < inner_max[axis], target.name)
        require(abs(lo.y - .90) <= TOL, f"{target.name} floor contact")
        origin = blender(eye)
        center = blender(((lo + hi) / 2))
        ray = center - origin
        hit, _, _, _, obj, _ = scene.ray_cast(graph, origin, ray.normalized(), distance=2.50)
        require(hit and obj == target, f"{target.name} obscured from approach: {obj}")
        approach[target.name] = round(ray.length, 4)

    head = parts["PressHead"]
    upper_min, upper_max = limits((head,))
    upper_location = head.location.copy()
    down = head.parent.matrix_world.inverted().to_3x3() @ blender((0, -STROKE, 0))
    head.location += down
    bpy.context.view_layer.update()
    lower_min, lower_max = limits((head,))
    head.location = upper_location
    bpy.context.view_layer.update()
    require(near(upper_min, (-.50, 1.725, -.40)) and near(upper_max, (.50, 1.975, .40)),
            "Upper press head bounds")
    require(near(lower_min, (-.50, 1.225, -.40)) and near(lower_max, (.50, 1.475, .40)),
            "Lower press head bounds")

    # Test evaluated triangles against the interior of the complete stroke
    # envelope. Clipping to its six planes also catches triangles wholly inside.
    low = lower_min + Vector((.0002,) * 3)
    high = upper_max - Vector((.0002,) * 3)
    for name, obj in parts.items():
        if name == "PressHead":
            continue
        evaluated = obj.evaluated_get(graph)
        data = evaluated.data
        data.calc_loop_triangles()
        points = evaluated_points(obj)
        for tri in data.loop_triangles:
            contour = [points[index] for index in tri.vertices]
            require(not intersects_box(contour, low, high), f"Head stroke intersects {name}")

    return {
        "approach_distances_m": approach,
        "press_up": [rounded(upper_min), rounded(upper_max)],
        "press_down": [rounded(lower_min), rounded(lower_max)],
        "clearance_above_anvil_m": round(lower_min.y - .90, 4),
    }


def intersects_box(contour, low, high):
    for axis in range(3):
        for plane, sign in ((low[axis], 1), (high[axis], -1)):
            if not contour:
                return False
            clipped = []
            previous = contour[-1]
            for current in contour:
                a = (previous[axis] - plane) * sign
                b = (current[axis] - plane) * sign
                if (a >= 0) != (b >= 0):
                    clipped.append(previous.lerp(current, a / (a - b)))
                if b >= 0:
                    clipped.append(current)
                previous = current
            contour = clipped
    return bool(contour)


def reference_image():
    image = bpy.data.images.load(str(REFERENCE), check_existing=True)
    ref = bpy.data.objects.new("Reference_Stamping", None)
    bpy.data.collections["REFERENCES"].objects.link(ref)
    ref.empty_display_type = "IMAGE"
    ref.data = image
    ref.empty_display_size = 3.4
    ref.color[3] = .7
    ref.rotation_euler.x = math.pi / 2
    ref.location = (3.5, .4, 1.5)
    ref.hide_set(True)
    ref.hide_render = True


def aim(obj, point):
    obj.rotation_euler = (Vector(point) - obj.location).to_track_quat("-Z", "Y").to_euler()


def stage():
    scene = bpy.context.scene
    studio = scene_collection("PREVIEW")
    ground_mesh = bpy.data.meshes.new("Preview ground")
    ground_mesh.from_pydata([(-100, -100, -.003), (100, -100, -.003),
                             (100, 100, -.003), (-100, 100, -.003)], [], [(0, 1, 2, 3)])
    ground = bpy.data.objects.new("Preview ground", ground_mesh)
    studio.objects.link(ground)
    ground_mesh.materials.append(principled("Preview ground material", (.085, .104, .145), .68)[0])
    ground.hide_set(True)

    def camera(name, position, target, scale=None):
        lens = bpy.data.cameras.new(name)
        obj = bpy.data.objects.new(name, lens)
        studio.objects.link(obj)
        obj.location = blender(position)
        aim(obj, blender(target))
        if scale:
            lens.type = "ORTHO"
            lens.ortho_scale = scale
        else:
            lens.lens = 31
        obj.hide_set(True)
        return obj

    front = camera("Preview_Front", (-.37, 2.90, 6.60), (-.37, 1.53, .32), 4.08)
    camera("Preview_OutputSide", (-5.20, 3.20, 5.00), (-.37, 1.50, .23), 4.20)
    camera("Reference_Camera", (2.56, 2.97, 7.00), (-.33, 1.51, .18), 4.10)
    camera("Check_Intake_Eye", (0, 1.65, 1.86), (0, .92, 1.04))
    camera("Check_Output_Eye", (-2.06, 1.65, 0), (-1.25, .92, 0))
    scene.camera = front
    for name, position, power, size, color in (
        ("Key", (2.6, 6.3, 4.2), 980, 4.0, (1., .87, .73)),
        ("Fill", (-4.0, 3.2, 2.9), 580, 4.0, (.75, .86, 1.)),
        ("Rim", (-1.6, 5.0, -3.4), 1160, 3.1, (.73, .83, 1.)),
        ("Top bounce", (2.0, 4.0, -2.0), 230, 2.1, (1., .80, .56)),
    ):
        data = bpy.data.lights.new(name, "AREA")
        obj = bpy.data.objects.new(name, data)
        studio.objects.link(obj)
        data.energy, data.size, data.color = power * .78, size, color
        obj.location = blender(position)
        aim(obj, blender((-.38, 1.35, .22)))
        obj.hide_set(True)
    scene.world = bpy.data.worlds.new("Preview world")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (.32, .40, .58, 1)
    background.inputs["Strength"].default_value = .32
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 28
    scene.cycles.use_denoising = True
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 4
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Khronos PBR Neutral"
    scene.view_settings.look = "None"


def render(camera, path, resolution, samples_count):
    scene = bpy.context.scene
    scene.camera = bpy.data.objects[camera]
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.cycles.samples = samples_count
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def save(path):
    bpy.context.preferences.filepaths.save_version = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(path), relative_remap=True)


def setup_view():
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = bpy.data.objects["Base"]
    camera = bpy.data.objects["Preview_OutputSide"]
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_location = blender((-.38, 1.44, .22))
                area.spaces.active.region_3d.view_rotation = camera.rotation_euler.to_quaternion()
                area.spaces.active.region_3d.view_distance = 5.6
                area.spaces.active.shading.type = "MATERIAL"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("blockout", "finish"))
    parser.add_argument("--skip-previews", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    CHECKS.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    require(scene.unit_settings.system == "METRIC" and scene.unit_settings.scale_length == 1.0,
            "Expected the DRONEWORKS metric template")
    export = bpy.data.collections["EXPORT"]
    require(not export.all_objects, "Start from the empty DRONEWORKS template")
    materials = load_materials()
    model_fn = graybox if args.stage == "blockout" else finish
    model_fn(Assembly(export, materials))
    reference_image()
    stage()
    sheet, frame = samples(materials[0])
    parts = {obj.name: obj for obj in export.all_objects}
    bpy.context.view_layer.update()
    report = fit_review(parts, sheet, frame)
    lo, hi = limits(parts.values())
    require(near(hi - lo, DIMENSIONS), f"{args.stage} envelope {lo} → {hi}")
    report["dimensions_xyz_m"] = rounded(hi - lo)
    (CHECKS / f"{args.stage}_fit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    setup_view()
    if args.stage == "finish":
        for obj in (sheet, frame):
            obj.hide_set(True)
            obj.hide_render = True
        scene["Art direction"] = "DRONEWORKS / 1 m / front = -Y / output +X in Blender, -X in Unity FBX"
        parts["PressHead"]["Unity stroke m"] = STROKE
        parts["PressHead"]["Origin"] = "Top center of the casting"
        parts["SignBoard"]["Unity UI"] = "Existing Sign and bars remain in Unity"
        for obj in parts.values():
            obj.select_set(False)
        for image in bpy.data.images:
            if image.source == "FILE":
                image.pack()
        scene.render.resolution_x, scene.render.resolution_y = 1080, 1040
        save(MODEL)
        if not args.skip_previews:
            render("Preview_Front", HERE / "SM_StationStamping_Front.png", (1080, 1040), 24)
            render("Preview_OutputSide", HERE / "SM_StationStamping_OutputSide.png", (1080, 1040), 24)
        return
    save(CHECKS / "SM_StationStamping.blockout.blend")
    render("Preview_OutputSide", CHECKS / "Blockout_Overview.png", (760, 720), 10)
    parts["PressHead"].location.z -= STROKE
    render("Preview_Front", CHECKS / "Blockout_PressDown.png", (760, 720), 10)
    parts["PressHead"].location.z += STROKE
    render("Check_Intake_Eye", CHECKS / "Blockout_Intake_Eye.png", (640, 420), 8)
    render("Check_Output_Eye", CHECKS / "Blockout_Output_Eye.png", (640, 420), 8)


if __name__ == "__main__":
    main()
