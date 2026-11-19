"""Measure the saved asset or a clean FBX import and optionally render previews."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Euler, Vector, Quaternion
from mathutils.bvhtree import BVHTree

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_truck import AXLES, CHECKS, DECAL_FILE, HERE, HINGE, PALETTE_FILE, xyz


EXPECTED = {"Body", "CargoBed", "Board_Side", *(f"Wheel_{i}" for i in range(6))}
TOL = .0008


def unity(vector):
    return Vector((-vector.x, vector.z, -vector.y))


def bounds(points):
    return tuple(tuple(minmax(point[axis] for point in points) for axis in range(3))
                 for minmax in (min, max))


def close(actual, expected):
    return all(abs(a-b) < TOL for a, b in zip(actual, expected))


def geometry(obj):
    data = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    data.calc_loop_triangles()
    vertices = [obj.matrix_world @ vertex.co for vertex in data.vertices]
    return vertices, [tuple(face.vertices) for face in data.loop_triangles]


def inspect_fbx_file(path):
    from io_scene_fbx import parse_fbx

    document, version = parse_fbx.parse(str(path))

    def child(element, name):
        return next(item for item in element.elems if item.id == name)

    def properties(element):
        return {prop.props[0].decode(): prop.props[4:]
                for prop in child(element, b"Properties70").elems}

    settings = properties(child(document, b"GlobalSettings"))
    expected = {"UpAxis": 1, "UpAxisSign": 1, "FrontAxis": 2, "FrontAxisSign": 1,
                "CoordAxis": 0, "CoordAxisSign": 1, "UnitScaleFactor": 100}
    assert all(settings[key] == [value] for key, value in expected.items()), settings
    models = {item.props[1].split(b"\x00")[0].decode(): properties(item)
              for item in child(document, b"Objects").elems if item.id == b"Model"}
    assert set(models) == EXPECTED
    assert close(models["Body"].get("Lcl Rotation", [0]*3), (0, 0, 0))
    axes = {}
    for i, (x, side) in enumerate((x, s) for x in AXLES for s in (1, -1)):
        name = f"Wheel_{i}"
        model = models[name]
        assert close(model["Lcl Translation"], (-x, .45, side)), model
        assert close(model.get("Lcl Scaling", [1]*3), (1, 1, 1)), model
        rotation = Euler([math.radians(v) for v in model["Lcl Rotation"]], "XYZ")
        axes[name] = list(rotation.to_matrix() @ Vector((0, 1, 0)))
        assert close(axes[name], (0, 0, -1)), axes
    return {"version": version, "settings": expected, "axle_vectors_in_y_up_fbx": axes}


def intersects_box(points, lo, hi):
    # Clip the triangle by all six planes. Empty output means no overlap.
    for axis in range(3):
        for plane, sign in ((lo[axis], 1), (hi[axis], -1)):
            output = []
            for p, q in zip(points, points[1:] + points[:1]):
                a, b = sign*(p[axis]-plane), sign*(q[axis]-plane)
                if a >= 0:
                    output.append(p)
                if (a < 0) != (b < 0):
                    output.append(p.lerp(q, a/(a-b)))
            if not output:
                return False
            points = output
    return True


def inspect(meshes, mode, path, raw_fbx=None):
    assert set(meshes) == EXPECTED, set(meshes)
    assert meshes["Body"].parent is None
    assert close(unity(meshes["Body"].matrix_world.translation), (0, 0, 0))
    assert all(obj.parent == meshes["Body"] for name, obj in meshes.items() if name != "Body")
    assert close(unity(meshes["Board_Side"].matrix_world.translation), HINGE)
    data = {name: geometry(obj) for name, obj in meshes.items()}
    vertices = {name: [unity(v) for v in points] for name, (points, _) in data.items()}
    overall = bounds([v for values in vertices.values() for v in values])
    assert close(overall[0], (-3.30, 0.0, -1.15)) and close(overall[1], (2.90, 2.30, 1.15)), overall
    deck = [v for v in vertices["CargoBed"] if .88 < v.y < 1.003]
    bed_bounds = bounds(deck)
    assert close(bed_bounds[0][::2], (-3.30, -1)), bed_bounds
    assert close(bed_bounds[1], (.30, 1, 1)), bed_bounds
    bed_points = vertices["CargoBed"]
    rail_tops = {
        "tail": max(v.y for v in bed_points if v.x < -3.18),
        "far_side": max(v.y for v in bed_points if v.z < -.975),
        "bulkhead": max(v.y for v in bed_points if v.x > .17),
    }
    assert close(list(rail_tops.values()), (2, 2, 2.30)), rail_tops
    assert max(v.y for v in vertices["Board_Side"]) < 1, "Loading edge sticks above deck"
    assert min(v.z for v in vertices["Board_Side"]) > .95, "Board on wrong side"
    for name, points in vertices.items():
        for indices in data[name][1]:
            tri = [points[i] for i in indices]
            assert not intersects_box(tri, (-3.10+TOL, 1+TOL, -.76+TOL),
                                      (.10-TOL, 1.88-TOL, .84-TOL)), (name, tri)

    board_bvh = BVHTree.FromPolygons(*data["Board_Side"], all_triangles=True)
    wheels = {}
    for i, (x, side) in enumerate((x, s) for x in AXLES for s in (1, -1)):
        name = f"Wheel_{i}"
        obj = meshes[name]
        pivot = unity(obj.matrix_world.translation)
        local_axis = Vector((0, 1, 0)) if mode == "fbx" else Vector((0, 0, 1))
        axis = unity(obj.matrix_world.to_3x3() @ local_axis).normalized()
        assert close(pivot, (x, .45, side)), (name, pivot)
        assert close(axis, (0, 0, -1)), (name, axis)
        assert close(obj.scale, (1, 1, 1)), (name, obj.scale)
        dims = bounds(vertices[name])
        assert close([b-a for a, b in zip(*dims)], (.9, .9, .3)), (name, dims)
        assert not board_bvh.overlap(BVHTree.FromPolygons(*data[name], all_triangles=True)), name
        tread_bottom = Vector((0, -.45, 0))
        rolled = Quaternion(axis, math.pi/2) @ tread_bottom
        assert close(rolled, (-.45, 0, 0)), rolled
        wheels[name] = {
            "pivot_xyz": list(pivot), "intended_unity_local_y": list(axis),
            "bottom_tread_after_positive_90_relative_to_pivot": list(rolled),
        }
    if mode != "fbx":
        checks = bpy.data.collections["CHECKS - 16 cargo cells"]
        assert len(checks.objects) == 16
        cell_bounds = bounds([unity(v) for obj in checks.objects for v in geometry(obj)[0]])
        assert close(cell_bounds[0], (-3.10, 1, -.76)) and close(cell_bounds[1], (.10, 1.88, .84))
        assert all(close([b-a for a, b in zip(*bounds([unity(v) for v in geometry(obj)[0]]))],
                         (.80, .44, .80)) for obj in checks.objects)
    assert all(obj.data.uv_layers.get("UVMap") for obj in meshes.values())
    totals = {name: len(tris) for name, (_, tris) in data.items()}
    assert 0 < sum(totals.values()) <= 25000, totals
    for name, obj in meshes.items():
        expected_slots = ["DRONEWORKS_Palette"]
        if mode != "blockout" and name == "Body":
            expected_slots.append("DRONEWORKS_TruckDecals")
        assert [m.name for m in obj.data.materials] == expected_slots, name
        uv = obj.data.uv_layers["UVMap"].data
        assert all(0 <= d.uv.x <= 1 and 0 <= d.uv.y <= 1 for d in uv), name
        assert all(face.area > 1e-12 for face in obj.data.polygons), f"{name} has a collapsed face"
        assert all((obj.data.vertices[a].co-obj.data.vertices[b].co).length > 1e-9
                   for a, b in (edge.vertices for edge in obj.data.edges)), f"{name} has a collapsed edge"
    report = {
        "mode": mode, "blender": bpy.app.version_string,
        "coordinates": "workshop -> MayaYUp FBX -> DirectX axes (-x, z, -y); not measured in Unity",
        "bounds_xyz_m": overall, "dimensions_xyz_m": [b-a for a, b in zip(*overall)],
        "deck_height_m": bed_bounds[1][1], "deck_xz_m": [3.6, 2.0],
        "rail_top_heights_m": rail_tops,
        "board_top_m": max(v.y for v in vertices["Board_Side"]),
        "cargo_cells": 16, "cargo_volume_clear": True, "board_tire_intersection": False,
        "triangles": sum(totals.values()), "triangles_by_mesh": totals,
        "wheels": wheels, "materials": {
            name: [m.name for m in obj.data.materials] for name, obj in meshes.items()
        },
    }
    if raw_fbx is not None:
        report["raw_fbx"] = raw_fbx
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"PASS {mode}: {report['dimensions_xyz_m']} m, {report['triangles']} triangles")


def plain(name, color, roughness=.65):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    material.diffuse_color = (*color, 1)
    return material


def aim(obj, point):
    obj.rotation_euler = (xyz(point) - obj.location).to_track_quat("-Z", "Y").to_euler()


def camera_at(scene, name, position, target, focal=52, ortho=None):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.location = xyz(position)
    aim(obj, target)
    data.lens = focal
    if ortho:
        data.type = "ORTHO"
        data.ortho_scale = ortho
    scene.camera = obj


def area_light(scene, name, position, target, power, size, color):
    data = bpy.data.lights.new(name, "AREA")
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.location = xyz(position)
    aim(obj, target)
    data.energy, data.shape, data.size, data.color = power, "DISK", size, color


def studio(scene):
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -.011))
    floor = bpy.context.object
    floor.name = "Preview studio floor"
    floor.data.materials.append(plain("Studio • slate", (.080, .114, .151), .78))
    scene.world = bpy.data.worlds.new("Studio • ambient")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (.45, .54, .69, 1)
    background.inputs["Strength"].default_value = .26
    area_light(scene, "Softbox • ramp side", (1.5, 6.5, 4.5), (-.35, .9, 0), 1670, 5, (1, .94, .82))
    area_light(scene, "Softbox • front fill", (6, 2.5, 1.3), (.4, 1, 0), 435, 4, (.81, .89, 1))
    area_light(scene, "Softbox • overhead rim", (-3.0, 5.2, -3.1), (-.4, .8, 0), 1640, 4, (.76, .87, 1))
    area_light(scene, "Softbox • tail", (-6.0, 2.4, 2.5), (-2.0, 1, 0), 430, 4, (1, .96, .90))
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.use_denoising = True
    scene.cycles.samples = 32
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -.14


def render(scene, path, size):
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def restore_materials():
    # The project exports stripped paths so moving the FBX does not embed PNG copies.
    for material in bpy.data.materials:
        if material.name not in ("DRONEWORKS_Palette", "DRONEWORKS_TruckDecals"):
            continue
        path = PALETTE_FILE if material.name == "DRONEWORKS_Palette" else DECAL_FILE
        image = bpy.data.images.load(str(path), check_existing=True)
        material.use_nodes = True
        tree = material.node_tree
        bsdf = next(node for node in tree.nodes if node.type == "BSDF_PRINCIPLED")
        node = next((node for node in tree.nodes if node.type == "TEX_IMAGE"), None)
        if node is None:
            node = tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        node.interpolation = "Closest" if path == PALETTE_FILE else "Linear"
        tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])


def contact_sheet(paths):
    import numpy as np

    strips = []
    for row in range(2):
        tiles = []
        for path in paths[row*3:(row+1)*3]:
            frame = bpy.data.images.load(str(path), check_existing=False)
            pixels = np.empty(len(frame.pixels), dtype=np.float32)
            frame.pixels.foreach_get(pixels)
            tiles.append(pixels.reshape((frame.size[1], frame.size[0], 4)))
            bpy.data.images.remove(frame)
        strips.append(np.concatenate(tiles, axis=1))
    result = np.concatenate(strips[::-1], axis=0)
    output = bpy.data.images.new("FBX contact sheet", result.shape[1], result.shape[0], alpha=True)
    output.pixels.foreach_set(result.ravel())
    output.filepath_raw = str(CHECKS / "FBX_Contact.png")
    output.file_format = "PNG"
    output.save()


def views(mode, quality):
    scene = bpy.context.scene
    studio(scene)
    if mode == "blockout":
        cells = bpy.data.collections["CHECKS - 16 cargo cells"]
        cells.hide_viewport = cells.hide_render = False
        fill = [plain("Cargo test • lower", (.43, .22, .055)),
                plain("Cargo test • upper", (.059, .33, .37))]
        for i, obj in enumerate(sorted(cells.objects, key=lambda obj: obj.name)):
            center = sum((p.co for p in obj.data.vertices), Vector()) / len(obj.data.vertices)
            for vert in obj.data.vertices:
                vert.co = center.lerp(vert.co, .965)
            obj.data.materials.clear()
            obj.data.materials.append(fill[i // 8])
        scene.cycles.samples = 12
        camera_at(scene, "Blockout • fit", (-4.8, 4.5, 7.2), (-.45, 1, 0), ortho=7.6)
        render(scene, CHECKS / "Blockout_Fit.png", (760, 535))
    elif mode == "fbx":
        restore_materials()
        scene.cycles.samples = 8
        paths = []
        specs = (
            ("Perspective", (5.6, 4, 7.7), 7.25), ("Front", (10, 1.15, 0), 4.0),
            ("Tail", (-10, 1.15, 0), 4.0), ("Ramp side", (-.2, 1.15, 10), 7.05),
            ("Far side", (-.2, 1.15, -10), 7.05), ("Top", (-.2, 12, .001), 7.05),
        )
        for name, position, width in specs:
            target = (-.2, 1.15, 0)
            camera_at(scene, name, position, target, ortho=width)
            path = CHECKS / f"FBX_{name.replace(' ', '_')}.png"
            render(scene, path, (468, 310))
            paths.append(path)
        contact_sheet(paths)
    else:
        scene.cycles.samples = 24 if quality == "final" else 12
        size = (1600, 1050) if quality == "final" else (810, 535)
        directory = HERE if quality == "final" else CHECKS
        camera_at(scene, "General • front three quarters", (5.85, 4.08, 8.30), (-.24, 1.11, .02), 49)
        render(scene, directory / "SM_Truck_Overview.png", size)
        camera_at(scene, "Cargo • ramp side", (-4.85, 3.81, 7.68), (-.48, 1.10, .02), 47)
        render(scene, directory / "SM_Truck_RampSide.png", size)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("blockout", "source", "fbx"))
    parser.add_argument("--fbx", type=Path)
    parser.add_argument("--render", choices=("preview", "final"))
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    raw_fbx = None
    if args.mode == "fbx":
        raw_fbx = inspect_fbx_file(args.fbx)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=str(args.fbx), use_custom_normals=True)
        objects = bpy.context.scene.objects
        assert all(obj.type == "MESH" for obj in objects), list(objects)
    else:
        objects = bpy.data.collections["EXPORT"].all_objects
    bpy.context.view_layer.update()
    inspect({obj.name: obj for obj in objects}, args.mode, CHECKS / f"{args.mode}_report.json", raw_fbx)
    if args.render:
        views(args.mode, args.render)


if __name__ == "__main__":
    main()
