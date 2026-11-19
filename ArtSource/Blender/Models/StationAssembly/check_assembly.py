"""Measure the saved station, a fresh FBX import, and the frame clearances."""

import json
from pathlib import Path
import sys

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_assembly import CHECKS, HERE, PIVOTS, ROOT, SOCKETS, STEM, SWATCH, blender, unity, uv

TOLERANCE = .0005


def near(actual, expected):
    assert all(abs(x - y) < TOLERANCE for x, y in zip(actual, expected, strict=True)), (actual, expected)


def coordinates(obj):
    return [unity(obj.matrix_world @ vert.co) for vert in obj.data.vertices]


def bounds(points):
    axes = list(zip(*points))
    return tuple(map(min, axes)), tuple(map(max, axes))


def group_coordinates(obj, group_name):
    group = obj.vertex_groups[group_name].index
    return [point for vert, point in zip(obj.data.vertices, coordinates(obj), strict=True)
            if any(entry.group == group for entry in vert.groups)]


def evaluated_geometry(objects):
    graph = bpy.context.evaluated_depsgraph_get()
    vertices, faces = [], []
    for obj in objects:
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        start = len(vertices)
        vertices.extend(evaluated.matrix_world @ vert.co for vert in mesh.vertices)
        faces.extend(tuple(start + i for i in face.vertices) for face in mesh.polygons)
        evaluated.to_mesh_clear()
    return vertices, faces


def fit(station, test, eye, frame_camera=None):
    active = bpy.context.scene
    active.render.resolution_x, active.render.resolution_y = 1400, 1170
    results = {}
    station_points, station_faces = evaluated_geometry(station.values())
    deck_y = max(point[1] for point in coordinates(station["Table"]))
    obstruction_z = max(p[2] for name in ("Backboard", "SignBoard") for p in coordinates(station[name]))
    for name, test_mesh in test.items():
        points, faces, target_y = test_mesh
        lower, upper = bounds(list(map(unity, points)))
        # All table geometry is below the flat worktop. The two back meshes
        # lie behind the proxy even at the start of an upward/forward sweep.
        assert lower[1] >= deck_y - TOLERANCE
        assert lower[2] > obstruction_z
        assert lower[2] + 1.0 > .5 and .6 > upper[1] - lower[1]
        start = len(station_points)
        tree = BVHTree.FromPolygons(station_points + points,
                                    station_faces + [tuple(i + start for i in f) for f in faces])
        sight = []
        for x, z in SOCKETS:
            target = blender((x, target_y, z))
            vector = target - eye
            hit, _, _, _ = tree.ray_cast(eye, vector.normalized())
            assert hit is not None and (hit - target).length < .003, (name, (x, z), hit)
            if frame_camera is not None:
                position = world_to_camera_view(active, frame_camera, target)
                assert 0 < position.x < 1 and 0 < position.y < 1 and position.z > 0
                sight.append(tuple(round(v, 4) for v in position[:2]))
        results[name] = {"bounds": (lower, upper), "visible_mounts": 4,
                         "screen_xy": sight, "clearance_from_worktop": round(lower[1] - deck_y, 5),
                         "clearance_from_rear_meshes": round(lower[2] - obstruction_z, 5),
                         "clear_sweeps_m": {"forward": 1.0, "up": .60, "up_then_forward": [.60, 1.0]}}
    return results


def parts(objects, authored=False):
    assert set(objects) == set(PIVOTS), list(objects)
    board, sign, table = (objects[name] for name in ("Backboard", "SignBoard", "Table"))
    assert table.parent is None and board.parent == table and sign.parent == table
    near(bounds([point for obj in objects.values() for point in coordinates(obj)])[0], (-.8, 0, -.5))
    near(bounds([point for obj in objects.values() for point in coordinates(obj)])[1], (.8, 2.1, .5))
    near(bounds(coordinates(board))[0], (-.8, .90, -.50))
    near(bounds(coordinates(board))[1], (.8, 2.10, -.46))
    near(bounds(coordinates(sign))[1], (.75, 2.08, -.43))
    near(bounds(coordinates(sign))[0][:2], (-.75, 1.76))
    deck = [p for p in coordinates(table) if p[1] >= .84 - TOLERANCE]
    near(bounds(deck)[0], (-.8, .84, -.5))
    near(bounds(deck)[1], (.8, .90, .5))
    assert any(z > .483 and .69 < x < .75 and .76 < y < .81 for x, y, z in coordinates(table))
    results = {}
    for name, obj in objects.items():
        near(unity(obj.matrix_world.translation), PIVOTS[name])
        near(tuple(obj.scale), (1, 1, 1))
        if authored:
            assert abs(obj.matrix_world.to_quaternion().angle) < TOLERANCE
        assert len(obj.material_slots) == 1 and obj.material_slots[0].name == "DRONEWORKS_Palette"
        uv_layer = obj.data.uv_layers.active
        swatches = {tuple(point.vector) for point in uv_layer.uv}
        assert swatches <= {uv(paint) for paint in SWATCH}
        assert uv("steel") in swatches or name == "SignBoard"
        if name == "Table":
            assert {uv("graphite"), uv("signal")} <= swatches
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        assert all(edge.is_manifold and edge.calc_length() > 1e-6 for edge in bm.edges), name
        assert all(face.calc_area() > 1e-8 for face in bm.faces), name
        bm.free()
        obj.data.calc_loop_triangles()
        results[name] = {"triangles": len(obj.data.loop_triangles),
                         "bounds": bounds(coordinates(obj)), "pivot": PIVOTS[name],
                         "palette_uvs": sorted(swatches)}
    assert sum(data["triangles"] for data in results.values()) <= 3000
    return results


def main():
    bpy.ops.wm.open_mainfile(filepath=str(HERE / f"{STEM}.blend"))
    scene = bpy.context.scene
    assert scene.unit_settings.system == "METRIC" and scene.unit_settings.scale_length == 1
    camera = bpy.data.objects["Player_1.65m"]
    near(unity(camera.matrix_world.translation), (.17, 1.65, 1.50))
    station = {obj.name: obj for obj in bpy.data.collections["EXPORT"].objects}
    position = camera.matrix_world.translation.copy()
    report = {"viewpoint": unity(position), "blend": parts(station, authored=True)}
    for x in (-1, 1):
        for z in (-1, 1):
            low, high = bounds(group_coordinates(station["Table"], f"Leg {x:+d}/{z:+d}"))
            near(low, (x * .72 - .04, 0, z * .42 - .04))
            near(high, (x * .72 + .04, .84, z * .42 + .04))
    test = {}
    for name, y, lower, upper in (
        ("TEST_FRAME", .925, (-.30, .90, -.30), (.30, .95, .30)),
        ("TEST_ASSEMBLY", .94, (-.365, .915, -.365), (.365, 1.105, .365)),
    ):
        layer = bpy.context.view_layer.layer_collection.children[name]
        layer.exclude = False
        bpy.context.view_layer.update()
        objects = list(bpy.data.collections[name].objects)
        root = next(obj for obj in objects if obj.parent is None)
        near(unity(root.matrix_world.translation), (0, y, 0))
        vertices, faces = evaluated_geometry(objects)
        lo, hi = bounds(list(map(unity, vertices)))
        near(lo, lower)
        near(hi, upper)
        imported = root.get("Fit Source")
        target = upper[1] if name == "TEST_ASSEMBLY" or imported else y + .0243
        test[name] = vertices, faces, target
        if imported:
            report["bare_frame_source"] = imported
        layer.exclude = True
    report["blend_fit"] = fit(station, test, position, camera)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    fbx = ROOT / "Exports/Unity" / f"{STEM}.fbx"
    assert bpy.ops.import_scene.fbx(filepath=str(fbx)) == {"FINISHED"}
    station = {obj.name: obj for obj in bpy.context.scene.objects}
    assert all(obj.type == "MESH" for obj in station.values())
    report["fbx"] = parts(station)
    assert {key: row["triangles"] for key, row in report["fbx"].items()} == {
        key: row["triangles"] for key, row in report["blend"].items()}
    report["fbx_fit"] = fit(station, test, position)
    (CHECKS / "verified.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Verified station, frame clearances, and FBX")


if __name__ == "__main__":
    main()
