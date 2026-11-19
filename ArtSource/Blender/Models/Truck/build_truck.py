"""Build from the workshop template with Blender. Pass -- --blockout for the fit scene."""
import argparse
import math
from pathlib import Path
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CHECKS = ROOT / ".local/checks/truck"
PALETTE_FILE = ROOT / "ArtSource/Textures/T_Palette_DRONEWORKS.png"
DECAL_FILE = ROOT / "ArtSource/Textures/T_Truck_Decals.png"
AXLES = (-2.60, -1.00, 1.90)
HINGE = (-1.50, .975, .995)
SPINDLE = Matrix.Rotation(-math.pi / 2, 3, "X")
SWATCHES = {
    name: (start, row)
    for row, families in enumerate((
        ("STEEL", "SIGNAL"), ("HAZARD", "NAVY"), ("WHITE", "OLIVE"),
        ("CAMO", "RUBBER"), ("GLASS", "GREEN"), ("RED", "GLOW"),
        ("SCREEN", "CARTON"), ("REFLECT", "FLOOR"),
    ))
    for start, name in zip((0, 4), families)
}
WORDMARK = {
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "N": ("10001", "11001", "11001", "10101", "10011", "10011", "10001"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
}


def xyz(position):
    x, up, side = position
    # Blender -> Y-up FBX is (x, z, -y). The MayaYUp -> DirectX
    # handedness conversion reflects FBX X, which this mapping anticipates.
    return Vector((-x, -side, up))


def swatch(key):
    name, tone = key.split(".")
    column, row = SWATCHES[name]
    return ((column + "dml".index(tone) + .5) / 8, 1 - (row + .5) / 8)


def collection(name):
    return bpy.data.collections.get(name) or bpy.data.collections.new(name)


def mesh(name, verts, faces, target):
    data = bpy.data.meshes.new(name)
    data.from_pydata([xyz(v) for v in verts], [], faces)
    data.update()
    bm = bmesh.new()
    bm.from_mesh(data)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(data)
    bm.free()
    obj = bpy.data.objects.new(name, data)
    target.objects.link(obj)
    return obj


def activate(objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def join(objects, name):
    activate(objects)
    if len(objects) > 1:
        bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = name
    obj.data.name = name
    return obj


def painted(obj, color, bevel=0.0, segments=2, smooth=False):
    is_decal = color == "DECAL"
    obj.data.materials.append(DECAL if is_decal else PALETTE)
    if bevel:
        bpy.context.view_layer.objects.active = obj
        modifier = obj.modifiers.new("Rounded cast edges", "BEVEL")
        modifier.width = bevel
        # One chamfer handles the small parts. The large compound shapes keep
        # two subdivisions so their edges hold up from first-person range.
        modifier.segments = min(segments, 2) if bevel >= .035 else 1
        modifier.affect = "EDGES"
        modifier.limit_method = "ANGLE"
        modifier.angle_limit = math.radians(23)
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        data = obj.data
        if any((data.vertices[a].co-data.vertices[b].co).length < 1e-6
               for a, b in (edge.vertices for edge in data.edges)):
            # A bevel clamped against a thin wall can land adjacent vertices
            # on one point. Weld only the current part before UVs and normals.
            bm = bmesh.new()
            bm.from_mesh(data)
            bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-6)
            bm.to_mesh(data)
            bm.free()
            data.update()
    uv = obj.data.uv_layers.new(name="UVMap")
    if not is_decal:
        coordinate = swatch(color)
        for datum in uv.data:
            datum.uv = coordinate
    if smooth or bevel:
        for face in obj.data.polygons:
            face.use_smooth = True
    if bevel:
        modifier = obj.modifiers.new("Face-weighted normals", "WEIGHTED_NORMAL")
        modifier.weight = 50
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    return obj


def box(parts, name, center, dims, color, bevel=.018, segments=2, angle=0.0):
    corners = ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
               (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))
    faces = ((3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    cos, sin = math.cos(angle), math.sin(angle)
    verts = []
    for cx, cy, cz in corners:
        x, y, z = [a * b / 2 for a, b in zip((cx, cy, cz), dims)]
        verts.append((center[0] + x, center[1] + y * cos - z * sin, center[2] + y * sin + z * cos))
    obj = painted(mesh(name, verts, faces, EXPORT), color, bevel, segments)
    parts.append(obj)
    return obj


def prism(parts, name, loop, center, depth, color, bevel=.018, segments=2, axis=2):
    def lift(point, fixed):
        vertex = list(point)
        vertex.insert(axis, fixed)
        return vertex

    n = len(loop)
    verts = [lift(p, center + side * depth / 2) for side in (-1, 1) for p in loop]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2*n))]
    faces += [(i, (i+1) % n, (i+1) % n + n, i+n) for i in range(n)]
    obj = painted(mesh(name, verts, faces, EXPORT), color, bevel, segments)
    parts.append(obj)
    return obj


def radial(parts, name, center, profile, color, steps=32, axis=2, capped=False, lip=None):
    """Lathe from (radius, axial offset); uncapped profiles close back to their start."""
    verts = []
    for radius, axial in profile:
        for i in range(steps):
            t = math.tau * i / steps
            vertex = [radius * math.cos(t), radius * math.sin(t)]
            vertex.insert(axis, axial)
            verts.append(tuple(a + b for a, b in zip(center, vertex)))
    faces = [
        (j*steps+i, j*steps+(i+1)%steps, k*steps+(i+1)%steps, k*steps+i)
        for j in range(len(profile) - int(capped))
        for k in ((j+1) % len(profile),)
        for i in range(steps)
    ]
    if capped:
        faces += [tuple(reversed(range(steps))), tuple(range(len(verts)-steps, len(verts)))]
    obj = painted(mesh(name, verts, faces, EXPORT), color, smooth=True)
    if capped:
        for face in list(obj.data.polygons)[-2:]:
            face.use_smooth = False
    if lip:
        uv = obj.data.uv_layers.active.data
        coordinate = swatch(lip)
        for face in list(obj.data.polygons)[:2*steps]:
            for loop in face.loop_indices:
                uv[loop].uv = coordinate
    parts.append(obj)
    return obj


def link(parts, name, start, end, diameter, color, steps=10):
    p1, p2 = xyz(start), xyz(end)
    half = (p2 - p1).length / 2
    radius = diameter / 2
    obj = radial(parts, name, (0, 0, 0), ((radius, -half), (radius, half)),
                 color, steps, axis=1, capped=True)
    obj.data.transform(Matrix.Translation((p1 + p2) / 2) @
                       (p2-p1).to_track_quat("Z", "Y").to_matrix().to_4x4())
    return obj


def assemble(parts, name, origin=(0, 0, 0), parent=None, frame=None):
    # Every staged mesh is built in workshop coordinates. Move vertices into the
    # rigid part's frame without moving its world surface.
    obj = join(parts, name)
    obj.data.transform(Matrix.Translation(-xyz(origin)))
    obj.parent = parent
    obj.location = xyz(origin)
    if frame is not None:
        obj.data.transform(frame.inverted().to_4x4())
        obj.rotation_euler = frame.to_euler()
    return obj


def board(parts, blockout=False):
    # The lip slopes down and out; it stays inside the wheel-width envelope.
    loop = [(.992, .993), (.968, .991), (.908, 1.123), (.928, 1.145)]
    prism(parts, "Folded loading board", loop, -1.50, 3.575, "OLIVE.m",
          bevel=0 if blockout else .008, axis=0)
    if not blockout:
        prism(parts, "Lower steel lip", [(.907, 1.121), (.916, 1.114),
              (.938, 1.135), (.928, 1.147)], -1.50, 3.578, "CAMO.d", 0, axis=0)
        for x in (-3.14, -2.08, -.91, .14):
            radial(parts, "Hinge knuckle", (x, .971, 1.002),
                   ((.021, -.054), (.023, -.049), (.023, .049), (.021, .054)),
                   "STEEL.d", 8, axis=0, capped=True)
            prism(parts, "Hinge leaf", [(.97, 1.019), (.953, 1.045),
                  (.935, 1.096), (.948, 1.09), (.98, 1.024)], x, .055,
                  "CAMO.l", .004, axis=0)


def cargo(parts, blockout=False):
    if blockout:
        box(parts, "Deck", (-1.50, .955, 0), (3.60, .09, 2.00), "CARTON.d", 0)
        for name, center, dims in (
            ("Far rail", (-1.50, 1.50, -.96), (3.58, 1, .08)),
            ("Tail gate", (-3.23, 1.50, 0), (.14, 1, 1.90)),
            ("Headboard", (.22, 1.65, 0), (.16, 1.30, 1.90)),
        ):
            box(parts, name, center, dims, "CAMO.m", 0)
        return
    # Eight individually bevelled lengthwise boards over the sealed steel pan.
    box(parts, "Bed pan", (-1.50, .939, 0), (3.60, .056, 2.00), "CAMO.d", .016)
    for i, color in enumerate(("CARTON.d", "CARTON.d", "CARTON.m", "CARTON.d",
                                "CARTON.d", "CARTON.m", "CARTON.d", "CARTON.d")):
        z = -.825 + .235 * i
        box(parts, "Timber deck plank", (-1.50, .974, z), (3.475, .052, .228),
            color, .004)
        for x in (-3.14, .14):
            # Inset into the deck plane so even the fasteners clear the grid.
            radial(parts, "Flush deck rivet", (x, .997, z),
                   ((.011, -.005), (.011, .002)), "OLIVE.d", 5, axis=1, capped=True)
    for z in (-.955, .963):
        box(parts, "Steel sill", (-1.50, .966, z), (3.59, .068, .074), "CAMO.m", .011)
    box(parts, "Rear decking trim", (-3.27, .967, 0), (.06, .064, 1.95), "CAMO.m", .012)
    box(parts, "Forward decking trim", (.27, .967, 0), (.06, .064, 1.95), "CAMO.m", .012)

    for x in (-3.235, -2.10, -1.0, .226):
        box(parts, "Far-side stake", (x, 1.467, -.949), (.091, 1.014, .102), "CAMO.m", .014)
    for h, size in ((1.126, .24), (1.506, .147), (1.894, .16)):
        box(parts, "Far-side timber rail", (-1.50, h, -.916), (3.48, size, .085),
            "OLIVE.d", .018)
    box(parts, "Far-side cap", (-1.50, 1.976, -.946), (3.545, .048, .104), "CAMO.l", .013)
    for x in (-3.235, -2.10, -1.0, .226):
        for h in (1.20, 1.53, 1.91):
            radial(parts, "Stake bolt", (x, h, -1.006), ((.022, -.004), (.018, .005)),
                   "STEEL.m", 6, capped=True)

    for x, far, top in ((-3.235, False, 2.00), (.225, True, 2.30)):
        for z in (-.856, 0, .886):
            box(parts, "Headboard stake" if far else "Tailgate stake", (x, (top+.938)/2, z),
                (.111, top-.982, .095 if z else .068), "CAMO.m", .016)
        rails = ((1.141, .265), (1.50, .164), (1.83, .163), (2.16, .158)) if far else (
                (1.125, .228), (1.50, .153), (1.869, .160))
        for h, size in rails:
            box(parts, "Headboard timber" if far else "Tailgate timber", (x, h, .005),
                (.092, size, 1.907), "OLIVE.d", .019)
        box(parts, "Headboard cap" if far else "Tailgate cap", (x, top-.029, .004),
            (.125, .058, 1.946), "CAMO.l", .014)
        side = 1 if far else -1
        for z in (-.856, .886):
            for h, _ in rails:
                radial(parts, "End rail bolt", (x + side*.060, h, z),
                       ((.022, -.005), (.018, .007)), "STEEL.m", 6, axis=0, capped=True)


def blockout_body(parts):
    box(parts, "Frame", (-.19, .569, 0), (5.97, .21, 1.10), "HAZARD.m")
    box(parts, "Cab", (.96, 1.555, 0), (1.12, 1.45, 1.81), "CAMO.m", .18, 3)
    box(parts, "Hood", (2.003, 1.157, 0), (1.40, .66, 1.19), "CAMO.l", .13, 3)
    box(parts, "Front bumper", (2.805, .62, 0), (.19, .27, 2.18), "STEEL.d", .055, 3)


def hull(parts, name, rings, color, bevel, segments=3):
    """Loft a symmetric truncated octagon with independently positioned sections."""
    verts = []
    for y, rear, front, halfwidth, cut in rings:
        verts += [(rear+cut, y, -halfwidth), (front-cut, y, -halfwidth),
                  (front, y, -halfwidth+cut), (front, y, halfwidth-cut),
                  (front-cut, y, halfwidth), (rear+cut, y, halfwidth),
                  (rear, y, halfwidth-cut), (rear, y, -halfwidth+cut)]
    faces = [tuple(range(8)), tuple(range(len(verts)-8, len(verts)))]
    faces += [(i+j, i+(j+1)%8, i+(j+1)%8+8, i+j+8)
              for i in range(0, len(verts)-8, 8) for j in range(8)]
    parts.append(painted(mesh(name, verts, faces, EXPORT), color, bevel, segments))


def windshield(parts, name, outline, offset, depth, color, bevel):
    verts = [(1.567 - .409*(y-1.52) + offset + thickness, y, z)
             for thickness in (0, depth) for y, z in outline]
    n = len(outline)
    faces = [tuple(range(n)), tuple(range(n, 2*n))]
    faces += [(i, (i+1)%n, (i+1)%n+n, i+n) for i in range(n)]
    parts.append(painted(mesh(name, verts, faces, EXPORT), color, bevel))


def chassis(parts):
    for side in (-1, 1):
        box(parts, "Boxed frame rail", (-.22, .669, side*.47), (5.88, .245, .15), "HAZARD.m", .029)
    for x in (-3.10, -2.51, -1.10, -.07, 1.03, 2.54):
        box(parts, "Crossmember", (x, .695, 0), (.125, .13, 1.25), "STEEL.d", 0)
    for x in AXLES:
        radial(parts, "Axle tube", (x, .45, 0), ((.065, -.886), (.065, .886)),
               "HAZARD.m", 10, capped=True)
        radial(parts, "Differential", (x, .45, 0),
               ((.10, -.172), (.19, -.105), (.192, .082), (.10, .148)),
               "STEEL.d", 12, capped=True)
        for side in (-1, 1):
            for i in range(2):
                box(parts, "Leaf spring", (x, .513+i*.046, side*.59),
                    (.68+i*.16, .051, .10), "HAZARD.l", 0)
    link(parts, "Rear propshaft", (-2.78, .54, 0), (1.92, .55, 0), .095, "HAZARD.m")
    box(parts, "Rear crash bar", (-3.235, .757, 0), (.13, .176, 1.985), "STEEL.d", .027)
    box(parts, "Tail central number plate recess", (-3.281, .749, 0), (.035, .092, .30),
        "HAZARD.d", .011)
    for side in (-1, 1):
        box(parts, "Rear light mount", (-3.244, .737, side*.777), (.082, .137, .337),
            "HAZARD.m", .026)
        for z, color in ((.714, "RED.m"), (.88, "SIGNAL.m")):
            radial(parts, "Tail light", (-3.265, .737, side*z),
                   ((.055, -.031), (.062, .015)), color, 14, axis=0, capped=True)
        box(parts, "Rubber splash flap", (-3.11, .508, side*.979), (.060, .325, .284),
            "RUBBER.d", .019)
        box(parts, "Rear step plate", (-3.225, .606, side*.393), (.145, .039, .262),
            "HAZARD.l", .012)
        box(parts, "Inner rear wheel shield", (-1.81, .887, side*.781), (2.37, .064, .116),
            "HAZARD.d", .019)
        box(parts, "Tool locker / fuel tank", (-.16, .638, side*.765), (.670, .354, .54),
            "OLIVE.d", .083, 1)
        box(parts, "Locker face", (-.160, .66, side*1.013), (.52, .246, .059),
            "DECAL", .038, 1)
        for x in (-.365, .048):
            box(parts, "Tank strap", (x, .639, side*.774), (.062, .361, .518), "HAZARD.l", .019)
    box(parts, "Coupling bracket", (-3.133, .507, 0), (.233, .176, .227), "STEEL.d", .035)


def front(parts):
    hull(parts, "Rounded hood", (
        (.899, 1.335, 2.710, .611, .127), (1.267, 1.330, 2.710, .656, .125),
        (1.421, 1.342, 2.653, .584, .139), (1.517, 1.355, 2.517, .509, .115),
    ), "DECAL", .051)
    box(parts, "Grille structural surround", (2.642, 1.157, 0), (.171, .648, 1.24),
        "CAMO.d", .068, 3)
    box(parts, "Grille outer frame", (2.718, 1.163, 0), (.095, .595, 1.133),
        "CAMO.m", .053, 3)
    box(parts, "Grille recessed black radiator", (2.750, 1.159, 0), (.060, .498, 1.010),
        "HAZARD.d", .038, 3)
    for y in (.973, 1.063, 1.153, 1.243, 1.333):
        box(parts, "Grille bar", (2.781, y, 0), (.064, .045, .993), "OLIVE.m", .015, 3)
    box(parts, "Front bumper", (2.796, .621, 0), (.208, .235, 2.164),
        "STEEL.d", .052, 3)
    box(parts, "Bumper central inset", (2.888, .633, 0), (.018, .082, .40), "HAZARD.d", .016)
    for side in (-1, 1):
        box(parts, "Bumper end pad", (2.844, .626, side*.943), (.104, .143, .245),
            "STEEL.m", .031, 3)
        box(parts, "Recovery eye base", (2.777, .743, side*.58), (.128, .073, .145),
            "HAZARD.l", .023)
        radial(parts, "Forged recovery eye", (2.894, .638, side*.579),
               ((.034, -.010), (.052, -.010), (.056, -.004), (.049, .006), (.034, .006)),
               "STEEL.m", 12, axis=0)
        # True open arch, with a softened stamped edge rather than a solid box.
        angles = [math.radians(a) for a in range(8, 173, 12)] + [math.radians(172)]
        def arc(radius):
            return [(1.90+radius*math.cos(t), .45+radius*math.sin(t)) for t in angles]
        arch = arc(.566) + arc(.473)[::-1]
        prism(parts, "Painted front fender", arch, side*.875, .460, "DECAL", .024, 3)
        trim = arc(.558) + arc(.521)[::-1]
        prism(parts, "Pressed fender lip", trim, side*1.104, .034, "CAMO.l", 0)
        box(parts, "Headlamp wing", (2.550, 1.026, side*.786), (.319, .335, .566),
            "DECAL", .060, 3)
        lamp = (2.718, 1.082, side*.797)
        radial(parts, "Round headlight housing", lamp,
               ((.128, -.071), (.146, -.028), (.131, .024)),
               "HAZARD.l", 20, axis=0, capped=True)
        radial(parts, "Headlight trim ring", (2.751, 1.082, side*.797),
               ((.106, -.013), (.128, -.009), (.120, .015), (.106, .010)),
               "STEEL.m", 20, axis=0)
        radial(parts, "Headlight convex lens", (2.763, 1.082, side*.797),
               ((.107, -.011), (.103, .007), (.070, .023)),
               "GLOW.l", 20, axis=0, capped=True)
        box(parts, "Turn signal gasket", (2.708, .887, side*.827), (.063, .082, .168),
            "HAZARD.m", .027, 3)
        box(parts, "Turn signal amber lens", (2.741, .887, side*.827), (.039, .055, .130),
            "SIGNAL.m", .023, 3)


def cabin(parts):
    hull(parts, "Soft cab body", (
        (.801, .42, 1.415, .735, .13), (.920, .41, 1.53, .837, .12),
        (1.485, .40, 1.546, .846, .107), (1.616, .414, 1.531, .845, .104),
        (2.097, .445, 1.333, .839, .112), (2.230, .488, 1.291, .770, .136),
    ), "DECAL", .041)
    hull(parts, "Rounded crown visor", (
        (2.115, .419, 1.347, .848, .145), (2.199, .411, 1.354, .850, .167),
        (2.276, .484, 1.275, .758, .175),
    ), "DECAL", .046)
    for z in (-.37, 0, .37):
        box(parts, "Roof marker gasket", (1.051, 2.268, z), (.117, .025, .121),
            "HAZARD.m", .011)
        box(parts, "Roof marker lens", (1.052, 2.287, z), (.091, .026, .099),
            "SIGNAL.m", .013, 3)
    for side in (-1, 1):
        outline = ((1.575, .034), (1.564, .638), (1.625, .732),
                   (2.048, .694), (2.095, .619), (2.095, .042))
        windshield(parts, "Windshield rubber surround", [(y, side*z) for y, z in outline],
                   -.016, .054, "HAZARD.m", .022)
        pane = ((1.606, .069), (1.602, .625), (1.650, .690),
                (2.030, .660), (2.060, .605), (2.060, .070))
        windshield(parts, "Windshield blue glass", [(y, side*z) for y, z in pane],
                   .035, .018, "GLASS.m", .012)
        sheen = ((1.635, .522), (1.637, .600), (2.038, .456), (2.038, .355))
        windshield(parts, "Windshield painted soft reflection", [(y, side*z) for y, z in sheen],
                   .051, .005, "GLASS.l", .003)
        link(parts, "Wiper swing arm", (1.579, 1.598, side*.119),
             (1.564, 1.678, side*.440), .029, "HAZARD.d")
        link(parts, "Wiper blade", (1.581, 1.647, side*.279),
             (1.561, 1.678, side*.576), .027, "HAZARD.d")

        door_profile = ((.47, .988), (.52, .927), (1.12, .927), (1.414, 1.131),
                        (1.53, 1.531), (1.302, 2.108), (1.252, 2.148), (.56, 2.148), (.47, 2.060))
        prism(parts, "Door seam", door_profile, side*.843, .110, "CAMO.d", .028, 3)
        door_inset = ((.493, 1.004), (.54, .947), (1.104, .947), (1.395, 1.144),
                      (1.503, 1.529), (1.282, 2.098), (1.229, 2.128), (.576, 2.128), (.493, 2.049))
        prism(parts, "Door sheet with fleet emblem", door_inset, side*.872, .074, "DECAL", .031, 3)
        seal = ((.554, 1.616), (.599, 1.570), (1.359, 1.570), (1.391, 1.614),
                (1.237, 2.048), (1.188, 2.075), (.597, 2.075), (.554, 2.029))
        prism(parts, "Side window seal", seal, side*.915, .025, "HAZARD.m", .012)
        window = ((.582, 1.629), (.615, 1.598), (1.331, 1.598), (1.358, 1.627),
                  (1.213, 2.027), (1.175, 2.048), (.614, 2.048), (.582, 2.016))
        prism(parts, "Door window blue pane", window, side*.929, .015, "GLASS.m", .011, 3)
        prism(parts, "Side window soft reflection", ((.689, 1.614), (.768, 1.613), (1.02, 2.032),
              (.898, 2.032)), side*.938, .006, "GLASS.l", .002)
        box(parts, "Vent window divider", (1.129, 1.824, side*.934), (.031, .458, .020),
            "HAZARD.m", .007)
        box(parts, "Door handle recess", (.699, 1.497, side*.916), (.217, .051, .024),
            "CAMO.d", .016)
        box(parts, "Door grab handle", (.704, 1.505, side*.937), (.152, .033, .043),
            "STEEL.d", .013)
        for y in (1.149, 1.465):
            box(parts, "Door hinge", (1.388, y, side*.902), (.095, .076, .042), "CAMO.d", .014)
        box(parts, "Step box", (.812, .757, side*.812), (.586, .209, .275), "OLIVE.d", .038, 3)
        box(parts, "Low running board", (.815, .649, side*.903), (.702, .070, .339), "CAMO.m", .026)
        for x in (.58, .718, .856, .994, 1.096):
            box(parts, "Step grip", (x, .689, side*.94), (.066, .016, .199), "HAZARD.l", .005)
        link(parts, "Mirror support arm", (1.397, 1.600, side*.905),
             (1.224, 1.654, side*1.095), .044, "HAZARD.l")
        link(parts, "Mirror upright", (1.224, 1.65, side*1.095),
             (1.203, 1.903, side*1.095), .038, "HAZARD.l")
        box(parts, "Rearview mirror housing", (1.203, 1.890, side*1.068), (.118, .295, .146),
            "STEEL.d", .037, 1)
        box(parts, "Rearview mirror inset", (1.142, 1.890, side*1.068), (.016, .231, .103),
            "GLASS.l", .007, 3)

    box(parts, "Cab rear rubber window seal", (.407, 1.904, 0), (.074, .332, .878), "HAZARD.m", .032, 3)
    box(parts, "Cab rear glass panel", (.367, 1.904, 0), (.019, .270, .812), "GLASS.m", .008)
    box(parts, "Cab rear glass divider", (.352, 1.904, 0), (.020, .273, .036), "HAZARD.m", .007)
    radial(parts, "Exhaust lower pipe", (.378, 1.189, -.867), ((.058, -.416), (.058, .416)),
           "HAZARD.l", 16, axis=1, capped=True)
    radial(parts, "Exhaust guard", (.370, 1.627, -.872),
           ((.065, -.256), (.086, -.218), (.086, .230), (.069, .263)),
           "OLIVE.d", 20, axis=1, capped=True)
    for y in (1.398, 1.831):
        radial(parts, "Exhaust retaining band", (.370, y, -.872),
               ((.092, -.019), (.093, .019)), "STEEL.d", 16, axis=1, capped=True)
    link(parts, "Exhaust neck", (.370, 1.839, -.872), (.368, 2.150, -.872), .114, "STEEL.d")
    link(parts, "Exhaust turnover", (.368, 2.119, -.872), (.327, 2.212, -.872), .113, "STEEL.d")
    radial(parts, "Rolled exhaust tip", (.321, 2.198, -.872),
           ((.041, -.048), (.061, -.048), (.065, -.038), (.065, .041), (.041, .041)),
           "STEEL.d", 18, axis=0)


def tire(parts, center, detailed=True):
    # 0.300 m section at the sidewall and 0.900 m outside the tread.
    profile = ((.239, -.122), (.312, -.150), (.373, -.141), (.408, -.117),
               (.429, -.064), (.429, .064), (.408, .117), (.373, .141),
               (.312, .150), (.239, .122))
    if not detailed:
        profile = ((.27, -.15), (.395, -.15), (.45, -.101),
                   (.45, .101), (.395, .15), (.27, .15))
    radial(parts, "Tyre", center, profile, "RUBBER.m", 24 if detailed else 32)
    if not detailed:
        radial(parts, "Hub", center, ((.285, -.125), (.285, .125)), "CAMO.l", 24, capped=True)
        return
    for side in (-1, 1):
        verts, faces = [], []
        for block in range(16):
            angle = math.tau * block / 16
            start = len(verts)
            for inset in (0, .031):
                for axial, radius, low, high in ((.013, .45, 0, .119),
                        (.067, .45, .036, .195), (.121, .425, .105, .232)):
                    for end in (low, high):
                        t = angle + side*end
                        verts.append((center[0]+(radius-inset)*math.cos(t),
                                      center[1]+(radius-inset)*math.sin(t), center[2]+side*axial))
            for offset in (0, 6):
                faces += [(start+offset+j, start+offset+j+1, start+offset+j+3, start+offset+j+2)
                          for j in (0, 2)]
            perimeter = (0, 1, 3, 5, 4, 2)
            faces += [(start+a, start+b, start+6+b, start+6+a)
                      for a, b in zip(perimeter, perimeter[1:]+perimeter[:1])]
        parts.append(painted(mesh("Directional tread lugs", verts, faces, EXPORT), "RUBBER.m"))
    sign = 1 if center[2] > 0 else -1
    radial(parts, "Formed rim and dish", center, [(r, sign*d) for r, d in (
           (.243, .120), (.228, .143), (.209, .136), (.193, .115), (.087, .115))],
           "CAMO.m", 20, capped=True, lip="CAMO.l")
    radial(parts, "Center wheel cap", center, [(r, sign*d) for r, d in (
           (.093, .108), (.093, .132), (.073, .148))], "CAMO.l", 16, capped=True)
    radial(parts, "Inner wheel hub", center, ((.245, -sign*.117), (.234, -sign*.131),
           (.086, -sign*.142)), "CAMO.d", 16, capped=True)
    for i in range(6):
        a = i*math.tau/6
        x, y = center[0]+.168*math.cos(a), center[1]+.168*math.sin(a)
        radial(parts, "Rim recess", (x, y, center[2]+sign*.115),
                   ((.025, -.002), (.024, .002)), "HAZARD.m", 6, capped=True)
        x, y = center[0]+.108*math.cos(a), center[1]+.108*math.sin(a)
        radial(parts, "Wheel hex lug", (x, y, center[2]+sign*.132),
               ((.014, -.015), (.016, .004), (.013, .012)), "OLIVE.l", 6, capped=True)


def linear_color(hex_color):
    rgb = [int(hex_color[i:i+2], 16)/255 for i in (0, 2, 4)]
    return tuple(v/12.92 if v < .04045 else ((v+.055)/1.055)**2.4 for v in rgb)


def logo_image():
    import numpy as np

    width, height = 768, 400
    u, v = np.meshgrid((np.arange(width)+.5)/width, (np.arange(height)+.5)/height)
    pixels = np.zeros((height, width, 4), dtype=np.float32)
    cream, amber = linear_color("E4E0EE"), linear_color("F2A608")

    def ink(mask, rgb=cream):
        pixels[mask, :3] = rgb
        pixels[mask, 3] = 1

    def ellipse(x, y, rx, ry):
        return ((u-x)/rx)**2 + ((v-y)/ry)**2 <= 1

    def arm(x1, y1, x2, y2):
        dx, dy = x2-x1, (y2-y1)*.52
        px, py = u-x1, (v-y1)*.52
        t = np.clip((px*dx + py*dy)/(dx*dx + dy*dy), 0, 1)
        return (px-t*dx)**2+(py-t*dy)**2 <= .013**2

    for x in (.349, .651):
        for y in (.485, .844):
            ink(arm(.50, .665, x, y))
            ink(ellipse(x, y, .050, .061) & ~ellipse(x, y, .035, .035))
            ink(ellipse(x, y, .015, .024))
    ink(((u-.5)/.075)**4 + ((v-.663)/.097)**4 < 1)
    ink(ellipse(.50, .620, .022, .024), amber)
    word = "DRONEWORKS"
    for i, char in enumerate(word):
        for row, pattern in enumerate(WORDMARK[char]):
            for column, cell in enumerate(pattern):
                if cell == "1":
                    left = .050 + (i*6+column)*.0152
                    top = .293 - row*.0255
                    ink((left <= u) & (u < left+.0153) & (top-.0256 < v) & (v <= top),
                        cream if i < 5 else amber)
    image = bpy.data.images.new("Original DRONEWORKS fleet stencil", width, height, alpha=True, float_buffer=True)
    image.pixels.foreach_set(pixels.ravel())
    return image


def texture_node(tree, image, shader, interpolation):
    node = tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    node.interpolation = interpolation
    node.extension = "EXTEND"
    node.location = (-330, 150)
    tree.links.new(node.outputs["Color"], shader.inputs["Base Color"])
    return node


def bake_decals(body):
    paint = [obj for obj in body if obj.data.materials[0] == DECAL]
    body[:] = [obj for obj in body if obj not in paint]
    islands = join(paint, "Camo UV islands")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(77), margin_method="FRACTION",
                             island_margin=.006, correct_aspect=False)
    bpy.ops.object.mode_set(mode="OBJECT")

    tree = DECAL.node_tree
    tree.nodes.clear()
    anchor = tree.nodes.new("ShaderNodeNewGeometry")
    xyz_node = tree.nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(anchor.outputs["Position"], xyz_node.inputs[0])
    x, y, z = (xyz_node.outputs[axis] for axis in ("X", "Y", "Z"))

    def op(operation, a, b=None):
        node = tree.nodes.new("ShaderNodeMath")
        node.operation = operation
        for index, value in enumerate((a, b)):
            if isinstance(value, bpy.types.NodeSocket):
                tree.links.new(value, node.inputs[index])
            elif value is not None:
                node.inputs[index].default_value = value
        return node.outputs[0]

    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 2.7
    noise.inputs["Detail"].default_value = 1.05
    noise.inputs["Roughness"].default_value = .39
    noise.inputs["Distortion"].default_value = .20
    tree.links.new(anchor.outputs["Position"], noise.inputs["Vector"])
    color = tree.nodes.new("ShaderNodeValToRGB")
    ramp = color.color_ramp
    ramp.interpolation = "CONSTANT"
    ramp.elements[0].color = (*linear_color("4B4F2C"), 1)
    ramp.elements[1].position = .405
    ramp.elements[1].color = (*linear_color("7B8141"), 1)
    ramp.elements.new(.576).color = (*linear_color("A49B52"), 1)
    tree.links.new(noise.outputs["Fac"], color.inputs["Fac"])

    # Project the wordmark separately on each door; both sides read normally.
    door_u = op("DIVIDE", op("ADD", x, 1.272), .704)
    uv = tree.nodes.new("ShaderNodeCombineXYZ")
    mirrored_u = op("SUBTRACT", 1, door_u)
    tree.links.new(op("ADD", op("MULTIPLY", door_u, op("LESS_THAN", y, 0)),
                      op("MULTIPLY", mirrored_u, op("GREATER_THAN", y, 0))), uv.inputs["X"])
    tree.links.new(op("DIVIDE", op("SUBTRACT", z, 1.094), .370), uv.inputs["Y"])
    stencil = tree.nodes.new("ShaderNodeTexImage")
    stencil.image = logo_image()
    stencil.extension = "CLIP"
    tree.links.new(uv.outputs[0], stencil.inputs["Vector"])
    mix = tree.nodes.new("ShaderNodeMixRGB")
    is_door = op("GREATER_THAN", op("ABSOLUTE", y), .902)
    tree.links.new(op("MULTIPLY", stencil.outputs["Alpha"], is_door), mix.inputs[0])
    tree.links.new(color.outputs["Color"], mix.inputs[1])
    tree.links.new(stencil.outputs["Color"], mix.inputs[2])
    emission = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(mix.outputs[0], emission.inputs["Color"])
    tree.links.new(emission.outputs[0], tree.nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])

    atlas = bpy.data.images.new("T_Truck_Decals", 2048, 2048, alpha=False)
    sink = tree.nodes.new("ShaderNodeTexImage")
    sink.image = atlas
    tree.nodes.active = sink
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    scene.render.bake.margin = 9
    bpy.ops.object.bake(type="EMIT", save_mode="INTERNAL")
    atlas.filepath_raw = str(DECAL_FILE)
    atlas.file_format = "PNG"
    atlas.save()
    atlas.pack()
    atlas.filepath = bpy.path.relpath(str(DECAL_FILE))
    bpy.data.images.remove(stencil.image)
    tree.nodes.clear()
    shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = .48
    texture_node(tree, atlas, shader, "Linear")
    tree.links.new(shader.outputs[0], tree.nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    body.append(islands)


def ensure_collection(name):
    target = collection(name)
    if target.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(target)
    return target


def test_boxes():
    target = ensure_collection("CHECKS - 16 cargo cells")
    for level in range(2):
        for row in range(2):
            for column in range(4):
                cell = []
                obj = box(cell, f"Cell_{level*8+row*4+column:02}", (-2.70 + .80*column,
                          1.22 + .44*level, -.36 + .80*row), (.80, .44, .80), "SIGNAL.m", 0)
                target.objects.link(obj)
                EXPORT.objects.unlink(obj)
                obj.display_type = "WIRE"
                obj.show_in_front = True
    target.hide_render = True
    target.hide_viewport = True


def finish_scene(body, bed, side, wheels, blockout):
    root = assemble(body, "Body")
    assemble(bed, "CargoBed", (-1.50, 1.0, 0), root)
    assemble(side, "Board_Side", HINGE, root)
    for i, (parts, center) in enumerate(wheels):
        assemble(parts, f"Wheel_{i}", center, root, SPINDLE)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene.unit_settings.scale_length = 1.0
    activate([root])
    root.select_set(False)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                viewport = area.spaces.active
                viewport.region_3d.view_distance = 8.4
                viewport.region_3d.view_location = xyz((-.25, 1.14, 0))
                direction = xyz((4.2, 2.5, 6.9))
                viewport.region_3d.view_rotation = direction.to_track_quat("Z", "Y")
                viewport.shading.type = "MATERIAL" if not blockout else "SOLID"
                viewport.overlay.show_floor = False
                viewport.overlay.show_axis_x = False
                viewport.overlay.show_axis_y = False
    bpy.context.preferences.filepaths.save_version = 0
    path = CHECKS / "SM_Truck_Blockout.blend" if blockout else HERE / "SM_Truck.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path), relative_remap=True)


def main():
    global EXPORT, PALETTE, DECAL
    parser = argparse.ArgumentParser()
    parser.add_argument("--blockout", action="store_true")
    options = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    assert bpy.context.scene.collection.children.get("EXPORT"), "Open the DRONEWORKS template first"
    EXPORT = ensure_collection("EXPORT")
    PALETTE = bpy.data.materials["DRONEWORKS_Palette"]
    palette_image = next(n.image for n in PALETTE.node_tree.nodes if n.type == "TEX_IMAGE")
    palette_image.filepath = str(PALETTE_FILE)
    palette_image.reload()
    palette_image.pack()
    palette_image.filepath = bpy.path.relpath(str(PALETTE_FILE))
    DECAL = bpy.data.materials.new("DRONEWORKS_TruckDecals") if not options.blockout else None
    if DECAL:
        DECAL.use_nodes = True
        DECAL.diffuse_color = (*linear_color("7B8141"), 1)
    body, bed, side, wheels = [], [], [], []
    if options.blockout:
        blockout_body(body)
    else:
        PALETTE.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = .52
        chassis(body)
        front(body)
        cabin(body)
        bake_decals(body)
    cargo(bed, options.blockout)
    board(side, options.blockout)
    for x in AXLES:
        for sign in (1, -1):
            center = (x, .45, float(sign))
            parts = []
            tire(parts, center, detailed=not options.blockout)
            wheels.append((parts, center))
    test_boxes()
    finish_scene(body, bed, side, wheels, options.blockout)


if __name__ == "__main__":
    main()
