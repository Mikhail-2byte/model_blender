"""Build the editable drone and its two preview scenes from the workshop template."""

import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Quaternion, Vector


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
MODELS = HERE.parent
CHECKS = ROOT / ".local/checks/drone-quad"
BLOCKOUT = "--blockout" in sys.argv
MOTORS = ((.29, 0), (0, .29), (-.29, 0), (0, -.29))
BOX_SCALE = .9
BOX_Y = .1775
SWATCH = {
    "signal": (5, 0), "lit signal": (6, 0), "shade signal": (4, 0),
    "black": (0, 1), "graphite": (1, 1), "edge": (2, 1),
    "shadow white": (0, 2), "white": (1, 2), "lit white": (2, 2),
    "rubber dark": (4, 3), "rubber": (5, 3), "rubber edge": (6, 3),
    "lens dark": (0, 4), "lens": (1, 4), "lens edge": (2, 4),
    "board": (4, 4), "metal": (1, 7), "metal dark": (0, 7),
}
ATLAS = {"stamp": (0, 0, 256, 256), "crack pale": (256, 0, 512, 128),
         "crack dark": (256, 128, 512, 256)}


def basis(x, forward, height):
    # The workshop FBX profile maps Blender -X to Unity +X.
    return Vector((-x, -forward, height))


def uv(paint):
    column, row = SWATCH[paint]
    return (column + .5) / 8, 1 - (row + .5) / 8


def chamfer(x, z, width, length, cut):
    left, right = x - width / 2, x + width / 2
    back, front = z - length / 2, z + length / 2
    return [(left + cut, back), (right - cut, back), (right, back + cut),
            (right, front - cut), (right - cut, front), (left + cut, front),
            (left, front - cut), (left, back + cut)]


class Part:
    def __init__(self):
        self.vertices = []
        self.faces = []
        self.paint = []
        self.smooth = []

    def face(self, indices, paint, smooth=False):
        self.faces.append(tuple(indices))
        self.paint.append(paint)
        self.smooth.append(smooth)

    def loft(self, rings, bands, bottom, top, smooth=False, transform=None):
        start = len(self.vertices)
        n = len(rings[0])
        for ring in rings:
            self.vertices.extend([transform(*point) for point in ring] if transform else ring)
        self.face(reversed(range(start, start + n)), bottom)
        for i, paint in enumerate(bands):
            for j in range(n):
                first = start + i * n
                a, b = first + j, first + (j + 1) % n
                self.face((a, b, b + n, a + n), paint, smooth)
        last = start + (len(rings) - 1) * n
        self.face(range(last, last + n), top)

    def rect_loft(self, sections, bands, bottom, top, transform=None):
        rings = [[(px, pz, y) for px, pz in chamfer(x, z, w, d, c)]
                 for x, z, y, w, d, c in sections]
        self.loft(rings, bands, bottom, top, transform=transform)

    def block(self, center, size, bevel, paint, edge=None):
        x, z, y = center
        width, depth, height = size
        lo, hi = y - height / 2, y + height / 2
        inset = bevel * .65
        cut = max(.0007, bevel * 1.35)
        if max(size) < .085:
            sections = [(x,z,lo,width,depth,cut), (x,z,hi,width,depth,cut)]
            self.rect_loft(sections, [paint], paint, edge or paint)
            return
        sections = [(x, z, lo, width - 2*inset, depth - 2*inset, cut*.75),
                    (x, z, lo + bevel, width, depth, cut),
                    (x, z, hi - bevel, width, depth, cut),
                    (x, z, hi, width - 2*inset, depth - 2*inset, cut*.75)]
        self.rect_loft(sections, [edge or paint, paint, edge or paint], paint, paint)

    def round(self, sections, bands, bottom, top, count=20, transform=None, smooth=True):
        ring_angles = [math.tau * i / count for i in range(count)]
        rings = [[(r * math.cos(a), r * math.sin(a), h) for a in ring_angles] for h, r in sections]
        self.loft(rings, bands, bottom, top, smooth=smooth, transform=transform)

    def object(self, name, pivot, material, collection, parent=None):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([basis(*p) for p in self.vertices], [], self.faces)
        mesh.materials.append(material)
        layer = mesh.uv_layers.new(name="UVMap")
        for face, color, smooth in zip(mesh.polygons, self.paint, self.smooth, strict=True):
            face.use_smooth = smooth
            for loop in face.loop_indices:
                layer.data[loop].uv = uv(color)
        geometry = bmesh.new()
        geometry.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(geometry, faces=list(geometry.faces))
        geometry.to_mesh(mesh)
        geometry.free()
        # Keep only the caps sharp on circular turned parts and let the side rings shade smoothly.
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        obj.parent = parent
        obj.location = basis(*pivot)
        return obj


def body_mesh():
    p = Part()
    p.block((0, -.018, -.012), (.257, .333, .074), .012, "graphite", "edge")
    for x, z in MOTORS:
        dx, dz = x / .29, z / .29
        def radial(u, span, h):
            return dx * span - dz * u, dz * span + dx * u, h
        p.rect_loft([(0, .211, -.026, .097, .201, .009), (0, .211, -.015, .109, .223, .011),
                     (0, .211, .014, .109, .223, .011), (0, .211, .025, .093, .207, .009)],
                    ["black", "graphite", "edge"], "black", "graphite", transform=radial)
        if not BLOCKOUT:
            p.rect_loft([(0, .130, .010, .125, .059, .012), (0, .130, .035, .116, .052, .010),
                         (0, .130, .044, .089, .041, .008)],
                        ["black", "edge"], "black", "rubber", transform=radial)

    # Two side shoulders are left exposed around the upper white shell.
    for side in (-1, 1):
        p.block((side * .111, -.019, .022), (.068, .310, .057), .008, "rubber", "edge")
        if not BLOCKOUT:
            for z in (-.142, .115):
                p.block((side * .107, z, -.035), (.059, .066, .081), .007, "graphite", "rubber edge")
                p.block((side * .107, z, -.012), (.063, .070, .015), .0025, "signal", "lit signal")

    shell = [
        [(-.093,-.177), (.093,-.177), (.127,-.139), (.130,.088),
         (.096,.157), (-.096,.157), (-.130,.088), (-.127,-.139)],
        [(-.097,-.184), (.097,-.184), (.133,-.143), (.137,.096),
         (.099,.164), (-.099,.164), (-.137,.096), (-.133,-.143)],
        [(-.081,-.169), (.081,-.169), (.121,-.126), (.124,.091),
         (.088,.156), (-.088,.156), (-.124,.091), (-.121,-.126)],
        [(-.064,-.151), (.064,-.151), (.087,-.117), (.095,.077),
         (.070,.137), (-.070,.137), (-.095,.077), (-.087,-.117)],
        [(-.061,-.143), (.061,-.143), (.079,-.115), (.087,.075),
         (.066,.129), (-.066,.129), (-.087,.075), (-.079,-.115)],
    ]
    heights = [.042, .056, .074, .116, .126]
    p.loft([[(x, z, h) for x, z in outline] for h, outline in zip(heights, shell, strict=True)],
           ["shadow white", "white", "shadow white", "lit white"], "shadow white", "white")
    for side in (-1, 1):
        for end in (-1, 1):
            x, z = side*.103, end*.097
            p.rect_loft([(x, z, -.042, .051, .048, .008),
                         (x + side*.013, z + end*.015, -.096, .046, .046, .007),
                         (x + side*.034, z + end*.037, -.164, .039, .040, .006)],
                        ["graphite", "rubber"], "edge", "black")
            p.block((x + side*.034, z + end*.037, -.165), (.046, .049, .020), .003,
                    "rubber dark", "rubber edge")
    if not BLOCKOUT:
        for x in (-.053, .053):
            p.block((x, -.097, .1262), (.031, .008, .003), .00055, "metal dark", "white")
        p.block((0, .130, -.052), (.120, .062, .040), .005, "graphite", "edge")
        p.block((0, -.193, .037), (.096, .030, .026), .0035, "rubber", "edge")
        for x in (-.024, 0, .024):
            p.block((x, -.205, .052), (.012, .014, .005), .001, "black", "metal dark")
    return p


def motor_mesh():
    p = Part()
    p.round([(-.060,.063), (-.048,.074), (-.044,.0748),
             (-.031,.0748), (-.027,.072), (.031,.071), (.044,.066),
             (.047,.054), (.051,.044), (.060,.034)],
            ["black", "shade signal", "signal", "lit signal", "white", "white",
             "lit white", "graphite", "edge"], "black", "black", count=16 if not BLOCKOUT else 12)
    if not BLOCKOUT:
        for i in range(4):
            a = math.pi / 4 + math.tau * i / 4
            p.round([(.045,.0046), (.0484,.0038)], ["metal dark"],
                    "metal dark", "metal", count=6,
                    transform=lambda u, v, h: (u + .051*math.cos(a), v + .051*math.sin(a), h))
    return p


def blade_point(index, span, cross, h):
    if index % 2 == 0:
        return cross, span, h
    return span, cross, h


def prop_mesh(index):
    p = Part()
    p.round([(-.010,.027), (-.006,.035), (.014,.032), (.019,.027), (.020,.020)],
            ["black", "graphite", "edge", "graphite"], "black", "rubber", count=12 if not BLOCKOUT else 8)
    profile = [(.020,-.011,.011), (.040,-.012,.015), (.070,-.026,.021),
               (.096,-.027,.022), (.136,-.019,.016), (.154,-.012,.012), (.167,-.0045,.0045)]
    for side in (-1, 1):
        rings = []
        for j, (span, left, right) in enumerate(profile):
            inset = min(.0035, (right-left)*.21)
            depth = .0052 - .00029*j
            center = .0024 - .00024*j
            section = [(left,center-depth*.50), (left+inset,center-depth),
                       (right-inset,center-depth), (right,center-depth*.48),
                       (right-inset,center+depth*.57), (left+inset,center+depth)]
            rings.append([blade_point(index, side*span, side*cross, h) for cross, h in section])
        start = len(p.faces)
        p.loft(rings, ["rubber"]*5 + ["signal"], "graphite", "lit signal")
        for j in range(len(profile)-1):
            row = start + 1 + j*6
            p.paint[row+1] = "shade signal" if j >= 5 else "rubber dark"
            p.paint[row+5] = "lit signal" if j >= 5 else "rubber edge"
    return p


def electronics():
    board, battery, camera = Part(), Part(), Part()
    board.block((0, -.015, -.001), (.226, .161, .018), .0025, "board", "metal dark")
    battery.block((0, -.016, 0), (.273, .164, .112), .008, "graphite", "edge")
    battery.block((0, -.014, -.055), (.233, .137, .010), .0025, "rubber", "rubber edge")
    camera.block((0, -.017, 0), (.128, .101, .113), .009, "graphite", "edge")
    if not BLOCKOUT:
        board.block((0, -.021, .013), (.069, .061, .018), .002, "graphite", "edge")
        for x in (-.078, .078):
            for z in (-.073, .047):
                board.block((x, z, .010), (.026, .018, .009), .0016, "metal", "metal dark")
        for x in (-.090, .090):
            battery.rect_loft([(x,-.016,-.048,.020,.170,.006), (x,-.016,.051,.020,.170,.006)],
                              ["rubber"], "edge", "edge")
        for x in (-.022, .022):
            battery.block((x, -.104, -.010), (.024, .013, .027), .002, "signal", "shade signal")
    # A hood with a recessed lens surface, pointing through the front face.
    camera.rect_loft([(0, 0, .028, .113, .094, .009),
                      (0, 0, .042, .123, .104, .011),
                      (0, 0, .053, .115, .098, .010)],
                     ["edge", "graphite"], "black", "graphite", transform=lambda x,z,y: (x,y,z))
    camera.round([(.051,.039), (.057,.037), (.059,.032), (.0595,.027),
                  (.0555,.026), (.0567,.022), (.059,.015), (.060,.006)],
                 ["black", "edge", "black", "black", "lens dark", "lens", "lens edge"],
                 "black", "lens edge", count=16 if not BLOCKOUT else 12, transform=lambda x,z,y: (x,y,z))
    return board, battery, camera


def decal(parent, suffix, points, tile, collection, material, faces=((0, 1, 2, 3),), coordinates=None):
    name = suffix if suffix == "QcStamp" else f"Crack_{parent.name}"
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([basis(*point) for point in points], [], faces)
    mesh.materials.append(material)
    layer = mesh.uv_layers.new(name="UVMap")
    l, t, r, b = ATLAS[tile]
    coordinates = coordinates or [(0,0),(1,0),(1,1),(0,1)]
    for loop in mesh.loops:
        u, v = coordinates[loop.vertex_index]
        layer.data[loop.index].uv = ((l + u*(r-l)) / 512, 1 - (b - v*(b-t)) / 256)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.parent = parent
    obj.hide_render = True
    obj["Prefab default"] = "Disabled"
    return obj


def patch(x, z, width, length, height):
    return [(x-width/2,z-length/2,height), (x+width/2,z-length/2,height),
            (x+width/2,z+length/2,height), (x-width/2,z+length/2,height)]


def materials():
    palette = bpy.data.materials["DRONEWORKS_Palette"]
    tree = palette.node_tree
    image = next(n.image for n in tree.nodes if n.type == "TEX_IMAGE")
    image.pack()
    tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = .43
    layered = bpy.data.materials.new("DRONEWORKS_DroneQuad_Decals")
    layered.use_nodes = True
    tree = layered.node_tree
    sampler = tree.nodes.new("ShaderNodeTexImage")
    sampler.image = bpy.data.images.load(str(HERE / "T_DroneQuad_Decals.png"), check_existing=True)
    sampler.image.pack()
    sampler.extension = "EXTEND"
    shader = tree.nodes.get("Principled BSDF")
    shader.inputs["Roughness"].default_value = .65
    tree.links.new(sampler.outputs["Color"], shader.inputs["Base Color"])
    tree.links.new(sampler.outputs["Alpha"], shader.inputs["Alpha"])
    return palette, layered


def model(collection, palette, layered):
    def add(name, mesh, origin, parent=None):
        return mesh.object(name, origin, palette, collection, parent)

    root = add("Body", body_mesh(), (0,0,0))
    for i, (x, z) in enumerate(MOTORS):
        motor = add(f"Motor_{i}", motor_mesh(), (x,z,.085), root)
        prop = add(f"Propeller_{i}", prop_mesh(i), (x,z,.155), root)
        if not BLOCKOUT:
            direction = [0, 4, 8, 12][i]
            angles = [math.tau*j/16 for j in range(direction-1, direction+2)]
            points = [(r*math.cos(a), r*math.sin(a), h) for h,r in [(-.024,.07255), (.025,.07175)]
                      for a in angles]
            decal(motor, "Crack", points, "crack pale", collection, layered,
                  faces=[(j,j+1,j+4,j+3) for j in range(2)],
                  coordinates=[(j/2,v) for v in (0,1) for j in range(3)])
            points = [blade_point(i, s, c, h) for s,c,h in
                      [(.074,-.011,.0066), (.136,-.011,.0057), (.136,.010,.0045), (.074,.010,.0049)]]
            if i % 2 == 0:
                points = [points[j] for j in (3,2,1,0)]
            decal(prop, "Crack", points, "crack dark", collection, layered)
    board, battery, camera = electronics()
    board = add("Board", board, (0,0,.035), root)
    battery = add("Battery", battery, (0,0,-.085), root)
    camera = add("Camera", camera, (0,.20,-.100), root)
    if not BLOCKOUT:
        decal(root, "QcStamp", patch(.021,.052,.093,.093,.12645), "stamp", collection, layered,
              coordinates=[(1,1),(0,1),(0,0),(1,0)])
        decal(root, "Crack", patch(-.013,-.058,.117,.050,.1265), "crack pale", collection, layered)
        decal(board, "Crack", patch(.066,-.012,.054,.025,.0096), "crack dark", collection, layered)
        decal(battery, "Crack", [(x,z,-.0606) for x,z,_ in patch(0,-.003,.111,.050,0)],
              "crack dark", collection, layered, faces=((3,2,1,0),))
        # Right shoulder of the camera hood, clear of the optical aperture.
        decal(camera, "Crack", [(.042,.0535,-.037), (.054,.0535,-.031),
                                (.054,.0535,.031), (.042,.0535,.037)],
              "crack dark", collection, layered, faces=((3,2,1,0),))
    return root


def camera(collection, name, position, focus, width):
    data = bpy.data.cameras.new(name)
    data.type = "ORTHO"
    data.ortho_scale = width
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = basis(*position)
    obj.rotation_euler = (basis(*focus) - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def copy_drone(source, scene, packed=False):
    collection = bpy.data.collections.new("Preview drone")
    scene.collection.children.link(collection)
    copies = {obj: obj.copy() for obj in source.objects}
    for old, new in copies.items():
        collection.objects.link(new)
        new.parent = copies.get(old.parent)
        if packed and old.name == "QcStamp":
            new.hide_render = False
    root = copies[bpy.data.objects["Body"]]
    if packed:
        root.scale = (BOX_SCALE,) * 3
        root.location.z = BOX_Y


def append_box(scene):
    path = MODELS / "BoxOpen/SM_BoxOpen.blend"
    with bpy.data.libraries.load(str(path)) as (source, dest):
        dest.collections = ["EXPORT"]
    box = dest.collections[0]
    box.name = "SM_BoxOpen · Fit fixture"
    scene.collection.children.link(box)
    for obj in box.objects:
        if obj.name.startswith("Flap_"):
            obj.rotation_quaternion @= Quaternion((1,0,0), math.radians(-120))
        if obj.name == "Tape":
            obj.hide_render = True


def studio(scene, packed):
    lighting = bpy.data.collections.new("Studio")
    scene.collection.children.link(lighting)
    floor = bpy.data.meshes.new("Studio floor")
    level = -.1751 if not packed else -.002
    floor.from_pydata([(-30,-30,level),(30,-30,level),(30,30,level),(-30,30,level)],[],[(0,1,2,3)])
    mat = bpy.data.materials.new("Studio slate")
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (.024,.034,.057,1)
    shader.inputs["Roughness"].default_value = .68
    floor.materials.append(mat)
    lighting.objects.link(bpy.data.objects.new("Studio floor", floor))
    for name, loc, power, size, color in [
        ("Warm key", (-1.0,1.2,1.55), 100, 1.1, (1,.89,.78)),
        ("Cool fill", (1.22,1.05,.65), 50, 1.15, (.73,.85,1)),
        ("Rim", (.38,-1.08,1.37), 135, .73, (.77,.88,1)),
    ]:
        data = bpy.data.lights.new(name, "AREA")
        data.energy, data.size, data.color = power, size, color
        obj = bpy.data.objects.new(name, data)
        lighting.objects.link(obj)
        obj.location = basis(*loc)
        obj.rotation_euler = (-obj.location).to_track_quat("-Z", "Y").to_euler()
    scene.world = bpy.data.worlds.new("Studio ambient")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (.26,.32,.43,1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = .28
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 5
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.render.resolution_x, scene.render.resolution_y = (1440,1440) if packed else (1440,1040)
    scene.render.image_settings.file_format = "PNG"
    if packed:
        box_camera = camera(lighting, "Open carton", (.88,.75,2.37), (0,0,.21), 1.60)
        box_camera.data.shift_y = .085
        return box_camera
    return camera(lighting, "Drone hero", (1.07,1.84,1.06), (0,0,.003), .96)


def main():
    bpy.ops.wm.open_mainfile(filepath=str(MODELS.parent / "DRONEWORKS.blend"))
    scene = bpy.context.scene
    scene.name = "SM_DroneQuad"
    collection = scene.collection.children["EXPORT"]
    references = scene.collection.children["REFERENCES"]
    for obj in list(references.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    reference_path = ROOT / "References/drone_quadcopter.png"
    if reference_path.is_file():
        ref = bpy.data.objects.new("drone_quadcopter.png", None)
        ref.empty_display_type = "IMAGE"
        ref.data = bpy.data.images.load(str(reference_path))
        ref.data.pack()
        ref.empty_display_size = .76
        ref.location = (0, .72, .20)
        ref.rotation_euler.x = math.pi / 2
        references.objects.link(ref)
        ref.hide_set(True)
    model(collection, *materials())
    hero = bpy.data.scenes.new("Preview · Drone")
    copy_drone(collection, hero)
    hero.camera = studio(hero, False)
    reference_camera = camera(references, "Reference · three quarter", (1.05,1.83,1.21), (0,0,.015), .95)
    scene.camera = reference_camera
    if not BLOCKOUT:
        packed = bpy.data.scenes.new("Preview · Packed")
        copy_drone(collection, packed, packed=True)
        if (MODELS / "BoxOpen/SM_BoxOpen.blend").exists():
            append_box(packed)
        packed.camera = studio(packed, True)
    bpy.context.window.scene = scene
    for obj in collection.objects:
        if obj.hide_render:
            obj.hide_set(True)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                view = area.spaces.active
                view.region_3d.view_location = (0,0,.005)
                view.region_3d.view_rotation = hero.camera.rotation_euler.to_quaternion()
                view.region_3d.view_distance = 1.14
                view.region_3d.view_perspective = "ORTHO"
                view.shading.type = "MATERIAL"
                view.overlay.show_overlays = False
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = "NONE"
    bpy.ops.file.pack_all()
    output = CHECKS / "SM_DroneQuad.blockout.blend" if BLOCKOUT else HERE / "SM_DroneQuad.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(output), relative_remap=True)


if __name__ == "__main__":
    main()
