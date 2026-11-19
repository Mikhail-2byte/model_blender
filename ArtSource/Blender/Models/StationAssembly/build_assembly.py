"""Build and preview the DRONEWORKS assembly table from the workshop template."""

import argparse
import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CHECKS = ROOT / ".local/checks/station-assembly"
STEM = "SM_StationAssembly"
FRAME_FBX = ROOT / "Exports/Unity/SM_Frame.fbx"
PIVOTS = {"Table": (0, 0, 0), "Backboard": (0, 1.50, -.48),
          "SignBoard": (0, 1.92, -.44)}
SOCKETS = ((.29, 0), (0, .29), (-.29, 0), (0, -.29))
SWATCH = {
    "steel dark": (0, 0), "steel": (1, 0), "steel light": (2, 0),
    "ochre": (4, 0), "signal": (5, 0), "gold": (6, 0),
    "black": (0, 1), "graphite": (1, 1), "graphite light": (2, 1),
    "white dark": (0, 2), "white": (1, 2), "white light": (2, 2),
    "rubber": (5, 3), "rubber light": (6, 3), "silver": (1, 7),
}


def blender(point):
    """Unity coordinates through the workshop's rigid FBX export basis."""
    x, y, z = point
    return Vector((-x, -z, y))


def unity(point):
    x, y, z = point
    return (-x, z, -y)


def uv(paint):
    col, row = SWATCH[paint]
    return ((col + .5) / 8, 1 - (row + .5) / 8)


def contour(width, height, clip):
    x, y = width / 2, height / 2
    return [(-x + clip, -y), (x - clip, -y), (x, -y + clip), (x, y - clip),
            (x - clip, y), (-x + clip, y), (-x, y - clip), (-x, -y + clip)]


class Mesh:
    def __init__(self):
        self.points = []
        self.faces = []
        self.colors = []
        self.parts = {}

    def loft(self, name, center, axis, rings, colors, caps=True):
        start = len(self.points)
        count = len(rings[0][1])
        for depth, outline in rings:
            for u, v in outline:
                point = [u, v]
                point.insert(axis, depth)
                self.points.append(tuple(a + b for a, b in zip(point, center)))
        self.parts[name] = range(start, len(self.points))
        if caps:
            self.faces.append(tuple(range(start, start + count)))
            self.colors.append(colors[0])
        for band, paint in enumerate(colors[1:-1]):
            first = start + band * count
            for i in range(count):
                a, b = first + i, first + (i + 1) % count
                self.faces.append((a, b, b + count, a + count))
                self.colors.append(paint if isinstance(paint, str) else paint[i])
        if caps:
            self.faces.append(tuple(range(len(self.points) - count, len(self.points))))
            self.colors.append(colors[-1])

    def box(self, name, center, size, color, bevel, trim=None, axis=1):
        outer = [length for i, length in enumerate(size) if i != axis]
        half = size[axis] / 2
        outer_ring = contour(*outer, bevel * 1.7)
        inner_ring = contour(*(v - 2 * bevel for v in outer), bevel * .75)
        self.loft(name, center, axis,
                  [(-half, inner_ring), (-half + bevel, outer_ring),
                   (half - bevel, outer_ring), (half, inner_ring)],
                  [color, color, color, trim or color, color])

    def round(self, name, center, axis, profile, colors, sides=12, caps=True):
        rings = [(offset, [(radius * math.cos(i * math.tau / sides),
                            radius * math.sin(i * math.tau / sides))
                           for i in range(sides)]) for offset, radius in profile]
        self.loft(name, center, axis, rings, colors, caps)

    def bolt(self, name, center, rise, radius):
        self.round(name, center, 2, [(-.002, radius), (rise * .48, radius), (rise, radius * .77)],
                   ["steel dark", "steel dark", "silver", "steel light"], sides=6)

    def object(self, name, collection, material, pivot=(0, 0, 0), parent=None):
        origin = blender(pivot)
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([blender(point) - origin for point in self.points], [], self.faces)
        mesh.materials.append(material)
        layer = mesh.uv_layers.new(name="UVMap")
        for face, paint in zip(mesh.polygons, self.colors, strict=True):
            for index in face.loop_indices:
                layer.uv[index].vector = uv(paint)
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        obj.parent = parent
        obj.location = origin - (parent.location if parent else Vector((0, 0, 0)))
        for part, indices in self.parts.items():
            obj.vertex_groups.new(name=part).add(list(indices), 1, "REPLACE")
        return obj


def table(blockout):
    mesh = Mesh()
    mesh.loft("Worktop", (0, 0, 0), 1,
              [(y, contour(w, d, c)) for y, w, d, c in
               [(.84, 1.570, .970, .035), (.852, 1.60, 1.00, .045),
                (.881, 1.60, 1.00, .045), (.889, 1.590, .990, .041),
                (.90, 1.568, .968, .035)]],
              ["steel dark", "steel dark", "steel", "steel light", "graphite light", "graphite"])
    for x_sign in (-1, 1):
        x = x_sign * .72
        for z_sign in (-1, 1):
            z = z_sign * .42
            tag = f"{x_sign:+d}/{z_sign:+d}"
            mesh.box(f"Leg {tag}", (x, .42, z), (.08, .84, .08), "steel", .005, "steel light")
            if blockout:
                continue
            # Low levelling pad and a tapered signal-colour toe guard.
            mesh.loft(f"Shoe {tag}", (x, 0, z), 1,
                      [(h, contour(w, w, clip)) for h, w, clip in
                       [(0, .126, .019), (.012, .144, .031), (.032, .144, .031),
                        (.051, .142, .028), (.085, .102, .014)]],
                      ["black", "black", "rubber", "ochre", "signal", "gold"])
            mesh.box(f"Upper collar {tag}", (x, .803, z), (.121, .107, .121),
                     "steel dark", .011, "steel")
        if blockout:
            continue
        mesh.box(f"Side bearer {x_sign:+d}", (x, .800, 0), (.092, .101, .809),
                 "steel", .015, "steel light")
        mesh.box(f"Side tie {x_sign:+d}", (x, .266, 0), (.062, .065, .845),
                 "steel dark", .008, "steel")
        section = [(.492, .405), (.492, -.408), (.632, -.408),
                   (.783, -.265), (.783, .283), (.642, .408), (.545, .408)]
        # Use an under-table pressed cheek with a narrow chamfer around its edge.
        cy = .655
        smaller = [(cy + (y - cy) * .89, z * .96) for y, z in section]
        mesh.loft(f"Pressed cheek {x_sign:+d}", (x, 0, 0), 0,
                  [(-.053, smaller), (-.044, section), (.044, section), (.053, smaller)],
                  ["steel", "steel light", "steel dark", "steel light", "steel"])
        mesh.bolt(f"Front anchor {x_sign:+d}", (x, .785, .474), .011, .024)
    if not blockout:
        mesh.box("Rear crossbrace", (0, .266, -.42), (1.44, .081, .068),
                 "steel dark", .010, "steel")
        mesh.box("Front apron", (0, .799, .414), (1.345, .098, .102), "steel", .014, "steel light", axis=2)
        mesh.box("Apron lower fold", (0, .757, .464), (1.266, .025, .017),
                 "steel dark", .004, "steel", axis=2)
        mesh.box("Rear bearer", (0, .797, -.438), (1.49, .102, .111),
                 "steel dark", .014, "steel")
    return mesh


def backboard(blockout):
    mesh = Mesh()
    # The folded border reaches Z=-.46. The field sits inside that plane.
    mesh.loft("Folded panel", (0, 1.50, -.48), 2,
              [(z, contour(w, h, clip)) for z, w, h, clip in
               [(-.020, 1.572, 1.172, .036), (-.011, 1.600, 1.200, .041),
                (.010, 1.600, 1.200, .041), (.020, 1.562, 1.162, .038),
                (.020, 1.407, 1.068, .041), (.010, 1.366, 1.030, .037)]],
              ["steel dark", "steel dark", "steel", "steel light",
               "steel", "steel dark", "steel"])
    if blockout:
        return mesh
    mesh.box("Lower folded band", (0, 1.008, -.467), (1.365, .123, .013),
             "steel dark", .004, "steel", axis=2)
    mesh.box("Lower band inset", (0, 1.017, -.463), (1.227, .053, .006),
             "steel", .002, "steel light", axis=2)
    for side in (-1, 1):
        x = side * .644
        mesh.box(f"Vertical seam {side:+d}", (x, 1.410, -.469), (.075, .690, .008),
                 "steel dark", .0025, "steel light", axis=2)
        for y in (1.161, 1.695):
            mesh.bolt(f"Panel anchor {side:+d} {y:.3f}", (x, y, -.465), .005, .024)
    return mesh


def signboard():
    mesh = Mesh()
    mesh.loft("Formed bezel", (0, 1.92, -.44), 2,
              [(z, contour(w, h, clip)) for z, w, h, clip in
               [(-.010, 1.488, .308, .030), (-.005, 1.50, .32, .034),
                (.003, 1.50, .32, .034), (.010, 1.475, .295, .030),
                (.010, 1.408, .229, .022), (.005, 1.388, .209, .020)]],
              ["black", "steel dark", "steel dark", "steel light",
               "steel dark", "black", "graphite"])
    for side in (-1, 1):
        mesh.box(f"Header spacer {side:+d}", (side * .597, 1.92, -.456), (.149, .229, .029),
                 "steel dark", .004, "steel", axis=2)
    return mesh


def test_frame(collection, material, finished):
    pivot_y = .94 if finished else .925
    name = "Clearance_Assembly" if finished else "Clearance_Frame"
    mesh = Mesh()
    mesh.box("X arm", (0, pivot_y - .002, 0), (.60, .046, .100), "rubber", .006, "rubber light")
    mesh.box("Z arm", (0, pivot_y - .002, 0), (.100, .046, .60), "rubber", .006, "rubber light")
    mesh.box("Center plate", (0, pivot_y + .015, 0), (.171, .019, .171), "steel dark", .007, "steel light")
    # Socket shoulders stay inside the 0.60 m cross footprint.
    for index, (x, z) in enumerate(SOCKETS):
        axis, sign = (0, math.copysign(1, x)) if x else (1, math.copysign(1, z))
        outline = contour(.111, .111, .026)
        flattened = []
        for u, v in outline:
            point = [u, v]
            point[axis] = min(.01, point[axis] * sign) * sign
            flattened.append(tuple(point))
        mesh.loft(f"Socket shoulder {index}", (x, pivot_y, z), 1,
                  [(-.021, flattened), (.015, flattened), (.0237, flattened)],
                  ["steel dark", "steel dark", "steel", "rubber light"])
        # A recessed-looking fitting with a contrasting land and dark center.
        mesh.round(f"Seat {index}", (x, pivot_y, z), 1,
                   [(.024, .0098), (.025, .0098), (.025, .0072), (.0243, .0065)],
                   ["white dark", "steel", "silver", "steel dark", "black"], sides=12)
    root = mesh.object(name, collection, material, (0, pivot_y, 0))
    if not finished:
        return root
    for index, (x, z) in enumerate(SOCKETS):
        center = (x, pivot_y, z)
        motor = Mesh()
        motor.round("Flange", center, 1,
                    [(.024, .068), (.031, .075), (.047, .075), (.054, .069)],
                    ["steel dark", "steel dark", "steel", "steel light", "steel"], sides=16)
        motor.round("Can and shaft", center, 1,
                    [(.049, .064), (.062, .071), (.076, .071), (.080, .069), (.112, .069),
                     (.123, .057), (.123, .025), (.146, .019)],
                    ["steel dark", "steel dark", "signal", "gold", "white", "white light",
                     "white dark", "steel dark", "steel light"], sides=16)
        motor.object(f"Motor_{index}", collection, material, (x, pivot_y + .025, z), root)
        rotor = Mesh()
        rotor.round("Hub", center, 1,
                    [(.139, .027), (.148, .041), (.160, .040), (.165, .029)],
                    ["steel dark", "steel dark", "rubber", "steel light", "rubber light"], sides=12)
        for sign in (-1, 1):
            outline = [(.024, -.010), (.103, -.027), (.173, -.023), (.192, -.009),
                       (.174, .012), (.092, .020), (.024, .011)]
            outline = [(sign * u, sign * v) for u, v in outline]
            if x:
                outline = [(-v, u) for u, v in outline]
            rotor.loft(f"Blade {sign:+d}", center, 1,
                       [(.143, outline), (.152, outline)],
                       ["rubber", "steel dark", "rubber light"])
        rotor.object(f"Propeller_{index}", collection, material, (x, pivot_y + .146, z), root)
    return root


def import_bare_frame(destination, material):
    if not FRAME_FBX.is_file():
        return test_frame(destination, material, False)
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.fbx(filepath=str(FRAME_FBX))
    (frame,) = set(bpy.context.scene.objects) - before
    assert frame.type == "MESH" and frame.name == "Frame"
    frame.data.transform(frame.matrix_world)
    frame.matrix_world = Matrix.Translation(blender((0, .925, 0)))
    for previous in list(frame.users_collection):
        previous.objects.unlink(frame)
    destination.objects.link(frame)
    frame.data.materials[0] = material
    frame["Fit Source"] = FRAME_FBX.name
    return frame


def collection(name):
    result = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(result)
    return result


def show(col, visible):
    col.hide_render = not visible
    bpy.context.view_layer.layer_collection.children[col.name].exclude = not visible


def camera(name, stage, position, target, lens):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    stage.objects.link(obj)
    obj.location = blender(position)
    obj.rotation_euler = (blender(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
    data.lens = lens
    return obj


def area(stage, name, position, target, watts, size, color):
    data = bpy.data.lights.new(name, "AREA")
    light = bpy.data.objects.new(name, data)
    stage.objects.link(light)
    light.location = blender(position)
    light.rotation_euler = (blender(target) - light.location).to_track_quat("-Z", "Y").to_euler()
    data.energy = watts
    data.shape = "DISK"
    data.size = size
    data.color = color


def setup_preview(scene, stage):
    # Neutral cool studio floor and broad workshop-style lighting.
    floor_mesh = bpy.data.meshes.new("Studio backdrop")
    section = [(-.001, 30)]
    for i in range(17):
        angle = math.pi / 2 * i / 16
        section.append((2.8 * (1 - math.cos(angle)) - .001, -2.6 - 2.8 * math.sin(angle)))
    section.append((16, -5.4))
    floor_mesh.from_pydata(
        [blender((x, y, z)) for y, z in section for x in (-25, 25)], [],
        [(2*i, 2*i+1, 2*i+3, 2*i+2) for i in range(len(section) - 1)],
    )
    for face in floor_mesh.polygons:
        face.use_smooth = True
    floor = bpy.data.objects.new("Studio backdrop", floor_mesh)
    stage.objects.link(floor)
    matte = bpy.data.materials.new("Studio floor")
    matte.use_nodes = True
    shader = matte.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (.049, .059, .079, 1)
    shader.inputs["Roughness"].default_value = .82
    floor_mesh.materials.append(matte)
    floor.hide_set(True)
    area(stage, "Warm overhead key", (-2.8, 4.4, 2.2), (0, .9, 0), 465, 3.0, (1, .90, .77))
    area(stage, "Cool workshop fill", (3.1, 2.8, 2.5), (0, 1, 0), 250, 3.6, (.76, .86, 1))
    area(stage, "Back edge", (.8, 3.5, -2.8), (0, 1.02, 0), 400, 2.6, (.75, .82, 1))
    area(stage, "Front bounce", (-.45, 1.8, 3.7), (0, .9, 0), 56, 2.4, (1, .96, .91))
    for obj in stage.objects:
        obj.hide_set(True)
    world = bpy.data.worlds.new("Preview studio")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (.160, .183, .239, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = .32
    scene.world = world
    scene.view_settings.view_transform = "AgX"
    scene.render.engine = "CYCLES"
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    scene.cycles.samples = 20
    scene.cycles.max_bounces = 6
    scene.cycles.use_denoising = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"


def add_references():
    refs = bpy.data.collections["REFERENCES"]
    for i, (name, file) in enumerate([
        ("HUD storyboard", "storyboard_02_hud.jpg"),
        ("Stamping press style", "station_stamping_press.png"),
    ]):
        obj = bpy.data.objects.new(name, None)
        refs.objects.link(obj)
        obj.empty_display_type = "IMAGE"
        obj.empty_display_size = 2.5
        obj.data = bpy.data.images.load(str(ROOT / "References" / file), check_existing=True)
        obj.data.pack()
        obj.location = (3 * (i + 1), 0, 1.4)
        obj.rotation_euler.x = math.pi / 2
    show(refs, False)


def build(blockout):
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / "ArtSource/Blender/DRONEWORKS.blend"),
                            load_ui=False)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1
    scene.unit_settings.length_unit = "METERS"
    bpy.context.preferences.filepaths.save_version = 0
    export = bpy.data.collections["EXPORT"]
    palette = bpy.data.materials["DRONEWORKS_Palette"]
    palette.diffuse_color = (.30, .32, .46, 1)
    palette.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = .46
    image = next(node.image for node in palette.node_tree.nodes if node.type == "TEX_IMAGE")
    image.filepath = str(ROOT / "ArtSource/Textures/T_Palette_DRONEWORKS.png")
    image.reload()
    image.pack()
    root = table(blockout).object("Table", export, palette, PIVOTS["Table"])
    backboard(blockout).object("Backboard", export, palette, PIVOTS["Backboard"], root)
    signboard().object("SignBoard", export, palette, PIVOTS["SignBoard"], root)
    bare, ready = collection("TEST_FRAME"), collection("TEST_ASSEMBLY")
    import_bare_frame(bare, palette)
    test_frame(ready, palette, True)
    stage = collection("PREVIEW")
    front = camera("Empty_Front", stage, (-.38, 1.41, 3.83), (0, .955, -.06), 52)
    camera("Player_1.65m", stage, (.17, 1.65, 1.50), (0, 1.27, -.05), 25)
    scene.camera = front
    setup_preview(scene, stage)
    add_references()
    show(bare, False)
    show(ready, False)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = root
    root.select_set(True)
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1130
    scene.render.resolution_percentage = 100
    for screen in bpy.data.screens:
        for area_ in screen.areas:
            if area_.type == "VIEW_3D":
                space = area_.spaces.active
                space.region_3d.view_location = blender((0, 1.05, 0))
                space.region_3d.view_rotation = Quaternion((.8137, .4919, -.1595, -.2639)).normalized()
                space.region_3d.view_distance = 4.3
                space.overlay.show_floor = False
                space.overlay.show_axis_x = False
                space.overlay.show_axis_y = False
                space.shading.type = "MATERIAL"
    CHECKS.mkdir(parents=True, exist_ok=True)
    output = CHECKS / f"{STEM}_blockout.blend" if blockout else HERE / f"{STEM}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(output), relative_remap=True, compress=True)


def render(draft, only_view):
    scene = bpy.context.scene
    if draft:
        scene.cycles.samples = 6
    scene.render.resolution_percentage = 43 if draft else 100
    output = CHECKS if draft else HERE
    variants = [
        ("Front", "Empty_Front", None, 1024, 1130),
        ("Player", "Player_1.65m", "TEST_FRAME", 1260, 1053),
    ]
    if draft:
        variants.append(("Assembly", "Player_1.65m", "TEST_ASSEMBLY", 1400, 1170))
    for name, camera_name, test, width, height in variants:
        if only_view and name != only_view:
            continue
        for label in ("TEST_FRAME", "TEST_ASSEMBLY"):
            show(bpy.data.collections[label], test == label)
        scene.camera = bpy.data.objects[camera_name]
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.filepath = str(output / f"{STEM}_{name}.png")
        bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["blockout", "build", "draft", "render"])
    parser.add_argument("--view", choices=["Front", "Player", "Assembly"])
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.mode in {"blockout", "build"}:
        build(blockout=args.mode == "blockout")
    else:
        render(draft=args.mode == "draft", only_view=args.view)
