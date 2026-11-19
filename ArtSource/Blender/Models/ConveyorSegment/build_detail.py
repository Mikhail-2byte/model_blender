"""Detail the accepted conveyor blockout and check the saved scene."""

import argparse
import json
import math
import struct
import sys
import zlib
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_blockout import END, HERE, LENGTH, MODEL, PARTS, ROOT, camera, check, require

BASELINE = HERE / "SM_ConveyorSegment.blockout.blend"
ARROWS = ROOT / "ArtSource/Textures/ConveyorArrow.png"
HAZARD_TILE = HERE / "Conveyor_HazardTile.png"
TILE_LENGTH = 1.0
PALETTE_UVS = {
    "olive": (0.6875, 0.6875),
    "dark_olive": (0.5625, 0.6875),
    "steel": (0.1875, 0.9375),
    "light_steel": (0.3125, 0.9375),
    "signal": (0.6875, 0.9375),
}


def linear_srgb(rgb):
    return tuple((channel / 255 + 0.055) ** 2.4 / 1.055 ** 2.4 for channel in rgb)


def stripe_image():
    """Generate one repeating diagonal decal tile and pack it into the blend."""
    size = 128
    yellow, dark = bytes((242, 166, 8)), bytes((43, 42, 53))
    rows = []
    for y in range(size):
        rows.append(b"\x00" + b"".join(
            yellow if (x + y * 0.48) % size < size * 0.52 else dark for x in range(size)
        ))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))
    if not HAZARD_TILE.exists():
        HAZARD_TILE.write_bytes(png)
    image = bpy.data.images.load(str(HAZARD_TILE))
    image.filepath = bpy.path.relpath(str(HAZARD_TILE))
    image.pack()
    return image


def node_material(name, roughness, metallic=0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    shader = mat.node_tree.nodes["Principled BSDF"]
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    return mat, shader


def conveyor_materials():
    palette = bpy.data.materials["DRONEWORKS_Palette"]
    palette.diffuse_color = (*linear_srgb((128, 128, 96)), 1)
    shader = palette.node_tree.nodes["Principled BSDF"]
    shader.inputs["Roughness"].default_value = 0.38
    shader.inputs["Metallic"].default_value = 0.24

    hazard, shader = node_material("Conveyor_Hazard", 0.54, 0.1)
    decal = hazard.node_tree.nodes.new("ShaderNodeTexImage")
    decal.image = stripe_image()
    decal.extension = "REPEAT"
    hazard.node_tree.links.new(decal.outputs["Color"], shader.inputs["Base Color"])

    belt, shader = node_material("Conveyor_Belt", 0.77)
    shader.inputs["Specular IOR Level"].default_value = 0.16
    rubber = (*linear_srgb((52, 50, 61)), 1)
    glow = (*linear_srgb((255, 194, 61)), 1)
    belt.diffuse_color = rubber
    nodes, links = belt.node_tree.nodes, belt.node_tree.links
    uv = nodes.new("ShaderNodeTexCoord")
    repeat = nodes.new("ShaderNodeVectorMath")
    repeat.operation = "MULTIPLY"
    repeat.inputs[1].default_value = (1, LENGTH / TILE_LENGTH, 1)
    repeat.label = "Blender preview / runtime repeats from arrowTileLength"
    links.new(uv.outputs["UV"], repeat.inputs[0])
    image = nodes.new("ShaderNodeTexImage")
    image.image = bpy.data.images.load(str(ARROWS), check_existing=True)
    image.image.filepath = bpy.path.relpath(str(ARROWS))
    image.extension = "REPEAT"
    links.new(repeat.outputs["Vector"], image.inputs["Vector"])
    color = nodes.new("ShaderNodeSeparateColor")
    links.new(image.outputs["Color"], color.inputs[0])

    def math_node(operation, input_socket, constant):
        node = nodes.new("ShaderNodeMath")
        node.operation = operation
        links.new(input_socket, node.inputs[0])
        node.inputs[1].default_value = constant
        return node.outputs[0]

    arrow = math_node("GREATER_THAN", color.outputs["Red"], 0.32)
    axes = nodes.new("ShaderNodeSeparateXYZ")
    links.new(uv.outputs["UV"], axes.inputs[0])
    treads = math_node("MULTIPLY", axes.outputs["Y"], 6)
    treads = math_node("FRACT", treads, 0)
    grooves = math_node("LESS_THAN", treads, 0.025)
    tread_color = nodes.new("ShaderNodeMixRGB")
    tread_color.inputs[1].default_value = rubber
    tread_color.inputs[2].default_value = (*linear_srgb((34, 33, 43)), 1)
    links.new(grooves, tread_color.inputs[0])
    base = nodes.new("ShaderNodeMixRGB")
    links.new(arrow, base.inputs[0])
    links.new(tread_color.outputs[0], base.inputs[1])
    base.inputs[2].default_value = glow
    links.new(base.outputs[0], shader.inputs["Base Color"])
    shader.inputs["Emission Color"].default_value = glow
    links.new(math_node("MULTIPLY", arrow, 0.38), shader.inputs["Emission Strength"])
    return palette, hazard, belt


class Part:
    def __init__(self):
        self.points, self.faces, self.finishes = [], [], []

    def add(self, points, faces, finishes):
        offset = len(self.points)
        self.points.extend(points)
        self.faces.extend(tuple(offset + index for index in face) for face in faces)
        self.finishes.extend(finishes)

    def prism_y(self, section, finish):
        # A counterclockwise X/Z section has a normal pointing in -Y.
        count = len(section)
        points = [(x, y, z) for y in (-END, END) for x, z in section]
        faces = [tuple(range(count)), tuple(reversed(range(count, 2 * count)))]
        finishes = [finish, finish]
        for i, a in enumerate(section):
            j = (i + 1) % count
            b = section[j]
            faces.append((i, count + i, count + j, j))
            if abs(a[0]) == abs(b[0]) == 0.572 and {a[1], b[1]} == {0.451, 0.569}:
                finishes.append("hazard")
            elif finish == "belt" and a[1] == b[1] == 0.60:
                finishes.append("belt_top")
            else:
                finishes.append(finish)
        self.add(points, faces, finishes)

    def bevel_box(self, x, y, z, bevel, finish):
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1)
        for vert in bm.verts:
            vert.co = [(hi - lo) * (p + 0.5) + lo for p, (lo, hi) in zip(vert.co, (x, y, z))]
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=1,
                        affect="EDGES", clamp_overlap=True)
        bm.verts.index_update()
        points = [tuple(vert.co) for vert in bm.verts]
        faces = [tuple(vert.index for vert in face.verts) for face in bm.faces]
        self.add(points, faces, [finish] * len(faces))
        bm.free()

    def bolt(self, side, x, y, z, radius, depth):
        angles = [math.tau * index / 6 for index in range(6)]
        points = [(side * (x + t * depth), y + r * math.cos(angle), z + r * math.sin(angle))
                  for t, r in ((0, radius), (1, radius * 0.77)) for angle in angles]
        faces = [tuple(range(5, -1, -1)), tuple(range(6, 12))]
        for i in range(6):
            j = (i + 1) % 6
            faces.append((i, j, j + 6, i + 6))
        if side < 0:
            faces = [tuple(reversed(face)) for face in faces]
        self.add(points, faces, ["steel", "light_steel", *["steel"] * 6])

    def apply(self, obj, materials):
        mesh = bpy.data.meshes.new(obj.name + "_Detailed")
        mesh.from_pydata([Vector(point) - obj.location for point in self.points], [], self.faces)
        mesh.update()
        for mat in materials:
            mesh.materials.append(mat)
        uv = mesh.uv_layers.new(name="UVMap")
        for face, finish in zip(mesh.polygons, self.finishes):
            face.material_index = int(finish == "hazard")
            for index in face.loop_indices:
                x, y, z = self.points[mesh.loops[index].vertex_index]
                if finish == "hazard":
                    value = (math.copysign(1, x) * (y + END) * 4, (z - 0.451) / 0.118)
                elif finish in ("belt", "belt_top"):
                    value = ((x + 0.55) / 1.10 if finish == "belt_top" else 0, (END - y) / LENGTH)
                else:
                    value = PALETTE_UVS[finish]
                uv.uv[index].vector = value
        obj.data = mesh


def chamfered(x0, x1, z0, z1, chamfer):
    c = chamfer
    return [(x0 + c, z0), (x1 - c, z0), (x1, z0 + c), (x1, z1 - c),
            (x1 - c, z1), (x0 + c, z1), (x0, z1 - c), (x0, z0 + c)]


def details(scene):
    palette, hazard, belt_material = conveyor_materials()
    frame = Part()
    frame.prism_y(chamfered(-0.55, 0.55, 0.47, 0.53, 0.004), "dark_olive")
    side_profile = [(0.550, 0.428), (0.557, 0.420), (0.594, 0.420), (0.600, 0.426),
                    (0.600, 0.444), (0.594, 0.451), (0.572, 0.451), (0.572, 0.569),
                    (0.594, 0.569), (0.600, 0.575), (0.600, 0.593), (0.594, 0.600),
                    (0.557, 0.600), (0.550, 0.593)]
    for side in (1, -1):
        section = side_profile if side == 1 else [(-x, z) for x, z in reversed(side_profile)]
        frame.prism_y(section, "olive")
        for y in (-0.68, 0.68):
            frame.bevel_box(sorted((side * 0.572, side * 0.590)), (y - 0.055, y + 0.055),
                            (0.448, 0.572), 0.005, "steel")
            for z in (0.477, 0.544):
                frame.bolt(side, 0.589, y, z, 0.020, 0.010)
            x = side * 0.44
            frame.bevel_box((x - 0.07, x + 0.07), (y - 0.09, y + 0.09),
                            (0.055, 0.47), 0.010, "olive")
            frame.bevel_box((x - 0.105, x + 0.105), (y - 0.115, y + 0.115),
                            (0, 0.035), 0.009, "signal")
            frame.bevel_box((x - 0.09, x + 0.09), (y - 0.10, y + 0.10),
                            (0.031, 0.059), 0.006, "steel")
            for z in (0.155, 0.403):
                frame.bolt(side, 0.509, y, z, 0.023, 0.014)
    for y in (-0.68, 0.68):
        frame.bevel_box((-0.38, 0.38), (y - 0.07, y + 0.07), (0.22, 0.31), 0.008, "dark_olive")
    frame.apply(scene.objects["Frame"], (palette, hazard))

    belt = Part()
    belt.prism_y(chamfered(-0.55, 0.55, 0.53, 0.60, 0.005), "belt")
    belt.apply(scene.objects["Belt"], (belt_material,))
    for name, x0, x1 in (("Rail_L", -0.60, -0.55), ("Rail_R", 0.55, 0.60)):
        rail = Part()
        rail.prism_y(chamfered(x0, x1, 0.60, 0.75, 0.008), "olive")
        rail.apply(scene.objects[name], (palette,))

    for name in PARTS:
        obj = scene.objects[name + ".Joint"]
        obj.data = scene.objects[name].data
        for slot in obj.material_slots:
            slot.link = "DATA"


def studio(scene):
    stage = bpy.data.collections.new("PREVIEW_STAGE")
    scene.collection.children.link(stage)
    mesh = bpy.data.meshes.new("Preview Floor")
    mesh.from_pydata([(-100, -100, -0.001), (100, -100, -0.001),
                      (100, 100, -0.001), (-100, 100, -0.001)], [], [(0, 1, 2, 3)])
    floor = bpy.data.objects.new("Preview Floor", mesh)
    stage.objects.link(floor)
    floor.hide_set(True)
    mat, shader = node_material("Preview Floor", 0.78)
    shader.inputs["Base Color"].default_value = (0.018, 0.024, 0.034, 1)
    mesh.materials.append(mat)

    for name, pos, power, size, rgb in (
        ("Key", (-4.3, 0.4, 5.2), 790, 5.0, (1, 0.91, 0.77)),
        ("Fill", (-2.1, -4.4, 3.1), 260, 4.0, (0.75, 0.86, 1)),
        ("Rim", (3.0, 0.9, 4.6), 860, 3.8, (0.78, 0.85, 1)),
    ):
        light = bpy.data.lights.new(name, "AREA")
        light.energy, light.shape, light.size, light.color = power, "DISK", size, rgb
        obj = bpy.data.objects.new(name, light)
        stage.objects.link(obj)
        obj.location = pos
        obj.rotation_euler = (Vector((0, -1, 0.25)) - obj.location).to_track_quat("-Z", "Y").to_euler()
        obj.hide_set(True)
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes["Background"]
    background.inputs["Color"].default_value = (0.14, 0.18, 0.25, 1)
    background.inputs["Strength"].default_value = 0.28
    scene.render.engine = "BLENDER_EEVEE"
    scene.view_settings.view_transform = "AgX"
    scene.camera = camera(scene.collection.children["PREVIEW_CAMERAS"], "Detail_ThreeQuarter",
                          (-6, 1.55, 3.3), (0, -1, 0.37), 4.62)
    scene.render.resolution_x, scene.render.resolution_y = 1400, 680
    scene.render.image_settings.file_format = "PNG"
    scene["Stage"] = "Detail / two segments at a 2 m step"
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.type = "MATERIAL"


def build(output):
    if output.exists():
        raise FileExistsError(output)
    bpy.ops.wm.open_mainfile(filepath=str(BASELINE), load_ui=True)
    scene = bpy.context.scene
    details(scene)
    studio(scene)
    bpy.context.preferences.filepaths.file_preview_type = "NONE"
    bpy.ops.wm.save_as_mainfile(filepath=str(output), relative_remap=True)


def export_for_unity(source, output):
    sys.path.insert(0, str(ROOT / "Tools/Blender"))
    from workflow import export_rigid

    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    belt = bpy.context.scene.collection.children["EXPORT"].objects["Belt"]
    # Unity 6000.3.28f1 with Bake Axis Conversion keeps the rails on their
    # specified sides, but imports authored -Y along -Z for this asset.
    # Orient the belt UV along Unity +Z while leaving the authoring file intact.
    for datum in belt.data.uv_layers.active.uv:
        datum.vector.y = 1.0 - datum.vector.y
    export_rigid(output, apply_transform=False)


def finish_check(source, output):
    report = check(source, output, stage="detail", render=False)
    scene = bpy.context.scene
    belt = scene.objects["Belt"]
    top = next(face for face in belt.data.polygons if face.normal.z > 0.999)
    uv = belt.data.uv_layers.active
    for index in top.loop_indices:
        point = belt.matrix_world @ belt.data.vertices[belt.data.loops[index].vertex_index].co
        u, v = uv.uv[index].vector
        require(round(u, 6), round((point.x + 0.55) / 1.10, 6), "arrow U")
        require(round(v, 6), round((END - point.y) / LENGTH, 6), "arrow V")
    frame = scene.objects["Frame"]
    require([slot.material.name for slot in frame.material_slots],
            ["DRONEWORKS_Palette", "Conveyor_Hazard"], "frame materials")
    require(sum(face.material_index == 1 for face in frame.data.polygons), 2, "hazard side faces")
    arrow_image = bpy.data.images[ARROWS.name]
    require(Path(bpy.path.abspath(arrow_image.filepath)).resolve(), ARROWS.resolve(), "arrow image path")
    hazard_image = bpy.data.images[HAZARD_TILE.name]
    require(Path(bpy.path.abspath(hazard_image.filepath)).resolve(), HAZARD_TILE.resolve(), "hazard tile path")
    if not hazard_image.packed_file:
        raise RuntimeError("Hazard decal was not embedded")
    for name in PARTS:
        require(scene.objects[name].data, scene.objects[name + ".Joint"].data, f"{name} linked geometry")
    report["appearance"] = {"arrow_uv_axis": "V along -Y", "arrows_per_segment": int(LENGTH / TILE_LENGTH),
                            "hazard_faces_per_segment": 2, "bolts_per_segment": 16}
    (output / "dimensions.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name, width, height in (
        ("Detail_ThreeQuarter", 1400, 680), ("Reference_ThreeQuarter", 960, 440),
        ("Top", 1120, 425), ("Right", 1120, 320),
        ("Left", 1120, 320), ("Front", 760, 510), ("Back", 760, 510),
    ):
        scene.camera = scene.objects[name]
        scene.render.resolution_x, scene.render.resolution_y = width, height
        scene.render.filepath = str(output / f"{name}.png")
        bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "check", "export-unity"))
    parser.add_argument("--blend", type=Path, default=MODEL)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.mode == "build":
        build(args.blend.resolve())
    elif args.mode == "export-unity" and args.output:
        export_for_unity(args.blend.resolve(), args.output.resolve())
    elif args.output:
        finish_check(args.blend.resolve(), args.output.resolve())
    else:
        parser.error(f"{args.mode} requires --output")


if __name__ == "__main__":
    main()
