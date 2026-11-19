"""Build or inspect the DRONEWORKS conveyor blockout in Blender 5.2."""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
TEMPLATE = ROOT / "ArtSource/Blender/DRONEWORKS.blend"
REFERENCE = ROOT / "References/conveyor.png"
MODEL = HERE / "SM_ConveyorSegment.blend"
LENGTH = 2.0
WIDTH = 1.20
BELT_WIDTH = 1.10
BELT_TOP = 0.60
RAIL_TOP = 0.75
HALF_WIDTH = WIDTH / 2
HALF_BELT = BELT_WIDTH / 2
END = LENGTH / 2
PARTS = ("Frame", "Belt", "Rail_L", "Rail_R")


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    return mat


def box_parts(name, collection, boxes, origin, mat):
    vertices, faces = [], []
    cube_faces = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                  (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    for (x0, y0, z0), (x1, y1, z1) in boxes:
        offset = len(vertices)
        corners = ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))
        vertices.extend(Vector(point) - Vector(origin) for point in corners)
        faces.extend(tuple(index + offset for index in face) for face in cube_faces)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = origin
    return obj


def camera(collection, name, from_point, to_point, scale, top=False):
    data = bpy.data.cameras.new(name)
    data.type = "ORTHO"
    data.ortho_scale = scale
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = from_point
    if top:
        obj.rotation_euler.z = math.pi / 2
    else:
        obj.rotation_euler = (Vector(to_point) - obj.location).to_track_quat("-Z", "Y").to_euler()
    obj.hide_set(True)
    return obj


def build(output):
    if output.exists():
        raise FileExistsError(output)
    bpy.ops.wm.open_mainfile(filepath=str(TEMPLATE), load_ui=True)
    scene = bpy.context.scene
    export = scene.collection.children["EXPORT"]
    references = scene.collection.children["REFERENCES"]
    joint = bpy.data.collections.new("JOINT_CHECK")
    preview = bpy.data.collections.new("PREVIEW_CAMERAS")
    scene.collection.children.link(joint)
    scene.collection.children.link(preview)

    ref = bpy.data.objects.new("Reference_Conveyor", None)
    ref.empty_display_type = "IMAGE"
    ref.data = bpy.data.images.load(str(REFERENCE))
    ref.data.filepath = bpy.path.relpath(str(REFERENCE))
    references.objects.link(ref)
    ref.hide_render = True
    ref.hide_set(True)

    frame_color = material("Blockout_Frame", (0.27, 0.30, 0.32))
    rail_color = material("Blockout_Rail", (0.40, 0.44, 0.46))
    belt_color = material("Blockout_Belt", (0.10, 0.13, 0.17))
    deck_bottom, deck_top = 0.47, 0.53
    frame_boxes = [
        ((-HALF_BELT, -END, deck_bottom), (HALF_BELT, END, deck_top)),
        ((-HALF_WIDTH, -END, 0.42), (-HALF_BELT, END, BELT_TOP)),
        ((HALF_BELT, -END, 0.42), (HALF_WIDTH, END, BELT_TOP)),
    ]
    for y in (-0.68, 0.68):
        for x in (-0.44, 0.44):
            frame_boxes.extend([
                ((x - 0.07, y - 0.09, 0.055), (x + 0.07, y + 0.09, deck_bottom)),
                ((x - 0.105, y - 0.115, 0.0), (x + 0.105, y + 0.115, 0.055)),
            ])
        frame_boxes.append(((-0.37, y - 0.07, 0.22), (0.37, y + 0.07, 0.31)))
    frame = box_parts("Frame", export, frame_boxes, (0, 0, 0), frame_color)
    belt = box_parts("Belt", export,
                     [((-HALF_BELT, -END, deck_top), (HALF_BELT, END, BELT_TOP))],
                     (0, 0, deck_top), belt_color)
    left = box_parts("Rail_L", export,
                     [((-HALF_WIDTH, -END, BELT_TOP), (-HALF_BELT, END, RAIL_TOP))],
                     (-(HALF_WIDTH + HALF_BELT) / 2, 0, BELT_TOP), rail_color)
    right = box_parts("Rail_R", export,
                      [((HALF_BELT, -END, BELT_TOP), (HALF_WIDTH, END, RAIL_TOP))],
                      ((HALF_WIDTH + HALF_BELT) / 2, 0, BELT_TOP), rail_color)
    for obj in (belt, left, right):
        obj.parent = frame

    second = {}
    joint_colors = {
        frame_color: material("Blockout_Frame_02", (0.36, 0.40, 0.43)),
        belt_color: material("Blockout_Belt_02", (0.16, 0.20, 0.25)),
        rail_color: material("Blockout_Rail_02", (0.51, 0.55, 0.57)),
    }
    for obj in (frame, belt, left, right):
        copy = obj.copy()
        copy.name = f"{obj.name}.Joint"
        joint.objects.link(copy)
        copy.material_slots[0].link = "OBJECT"
        copy.material_slots[0].material = joint_colors[obj.data.materials[0]]
        second[obj.name] = copy
    second["Frame"].location.y = -LENGTH
    for name in PARTS[1:]:
        second[name].parent = second["Frame"]

    center = (0, -END, 0.37)
    scene.camera = camera(preview, "Reference_ThreeQuarter", (6, -3.55, 3.15), center, 4.68)
    camera(preview, "Top", (0, -END, 5), center, 4.48, top=True)
    camera(preview, "Right", (5, -END, 0.375), (0, -END, 0.375), 4.48)
    camera(preview, "Left", (-5, -END, 0.375), (0, -END, 0.375), 4.48)
    camera(preview, "Front", (0, -6, 0.375), (0, -END, 0.375), 1.65)
    camera(preview, "Back", (0, 4, 0.375), (0, -END, 0.375), 1.65)
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.view_settings.view_transform = "Standard"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "MATERIAL"
    shading.background_type = "WORLD"
    shading.show_shadows = True
    shading.show_cavity = True
    shading.cavity_type = "BOTH"
    scene.world = bpy.data.worlds.new("Blockout Background")
    scene.world.color = (0.035, 0.044, 0.054)
    scene.render.resolution_x = 960
    scene.render.resolution_y = 440
    scene.render.resolution_percentage = 100
    scene["Stage"] = "Blockout / two segments at a 2 m step"
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.shading.color_type = "MATERIAL"
                space.region_3d.view_distance = 6.0
                space.region_3d.view_location = center
                space.region_3d.view_rotation = scene.camera.rotation_euler.to_quaternion()
    bpy.context.view_layer.objects.active = frame
    bpy.context.preferences.filepaths.file_preview_type = "NONE"
    bpy.ops.wm.save_as_mainfile(filepath=str(output), relative_remap=True)


def evaluated(obj, depsgraph):
    obj = obj.evaluated_get(depsgraph)
    mesh = obj.data
    mesh.calc_loop_triangles()
    points = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    return points, mesh.polygons, len(mesh.loop_triangles)


def bounds(points):
    return [[round(fn(point[i] for point in points), 6) for i in range(3)] for fn in (min, max)]


def require(actual, expected, label):
    if actual != expected:
        raise RuntimeError(f"{label}: {actual} != {expected}")


def end_faces(points, polygons, y, direction):
    return {
        tuple(sorted((round(points[index].x, 6), round(points[index].z, 6)) for index in face.vertices))
        for face in polygons
        if face.normal.y * direction > 0.999
        and all(abs(points[index].y - y) < 1e-6 for index in face.vertices)
    }


def check(source, output, *, stage="blockout", render=True):
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    scene = bpy.context.scene
    require(scene.unit_settings.system, "METRIC", "units")
    require(scene.unit_settings.scale_length, 1.0, "unit scale")
    require(Path(bpy.path.abspath(scene.objects["Reference_Conveyor"].data.filepath)).resolve(),
            REFERENCE.resolve(), "reference path after Save As")
    first = {obj.name: obj for obj in scene.collection.children["EXPORT"].objects}
    second = {obj.name.removesuffix(".Joint"): obj for obj in scene.collection.children["JOINT_CHECK"].objects}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    assembly = []
    report = {"blender": bpy.app.version_string, "stage": stage, "segments": [], "seam": {}}
    for segment, y in ((first, 0), (second, -2)):
        require(set(segment), set(PARTS), "part names")
        require(tuple(segment["Frame"].matrix_world.translation), (0, y, 0), "frame origin")
        parts = {}
        total = 0
        for name, obj in segment.items():
            require(obj.parent, segment["Frame"] if name != "Frame" else None, f"{name} parent")
            points, _, triangles = evaluated(obj, depsgraph)
            parts[name] = bounds(points)
            total += triangles
            assembly.extend(points)
        expected_belt = [[-0.55, y - 1, 0.53], [0.55, y + 1, 0.60]]
        require(parts["Belt"], expected_belt, "belt bounds")
        require(parts["Rail_L"], [[-0.60, y - 1, 0.60], [-0.55, y + 1, 0.75]], "left rail")
        require(parts["Rail_R"], [[0.55, y - 1, 0.60], [0.60, y + 1, 0.75]], "right rail")
        current_bounds = bounds([coord for pair in parts.values() for coord in pair])
        require(current_bounds, [[-0.60, y - 1, 0], [0.60, y + 1, 0.75]], "segment bounds")
        if total > 1500:
            raise RuntimeError(f"Triangle budget exceeded: {total}")
        report["segments"].append({"origin_y_m": y, "bounds_xyz_m": current_bounds,
                                   "triangles": total, "parts_bounds_xyz_m": parts})
    for name in PARTS:
        a, a_polys, _ = evaluated(first[name], depsgraph)
        b, b_polys, _ = evaluated(second[name], depsgraph)
        cap_a = end_faces(a, a_polys, -1, -1)
        cap_b = end_faces(b, b_polys, -1, 1)
        if not cap_a:
            raise RuntimeError(f"{name} has no planar seam face")
        require(cap_a, cap_b, f"{name} seam cross section")
        gap = min(point.y for point in a) - max(point.y for point in b)
        require(round(gap, 6), 0.0, f"{name} gap or overlap")
        report["seam"][name] = {"matched_faces": len(cap_a), "gap_m": round(gap, 6)}
    report["assembly_bounds_xyz_m"] = bounds(assembly)
    require(report["assembly_bounds_xyz_m"], [[-0.60, -3, 0], [0.60, 1, 0.75]], "assembly bounds")
    output.mkdir(parents=True, exist_ok=True)
    (output / "dimensions.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("CONVEYOR_GEOMETRY_OK", output, flush=True)

    if not render:
        return report
    for name, height in (("Reference_ThreeQuarter", 440), ("Top", 310), ("Right", 235),
                         ("Left", 235), ("Front", 510), ("Back", 510)):
        scene.camera = scene.objects[name]
        scene.render.resolution_x = 960 if name not in ("Front", "Back") else 760
        scene.render.resolution_y = height
        scene.render.filepath = str(output / f"{name}.png")
        bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "check"))
    parser.add_argument("--blend", type=Path, default=MODEL)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.mode == "build":
        build(args.blend.resolve())
    elif args.output:
        check(args.blend.resolve(), args.output.resolve())
    else:
        parser.error("check requires --output")


if __name__ == "__main__":
    main()
