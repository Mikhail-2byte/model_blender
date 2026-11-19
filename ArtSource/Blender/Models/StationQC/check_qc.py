"""Verify both the saved scene and the independently reimported rigid FBX."""

import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_qc import CHECKS, PALETTE, PIVOTS, ROTOR_AXES, STEM, SWATCH, unity, uv


EPS = 1e-5
DRONE_MIN = (-.365, .95, -.365)
DRONE_MAX = (.365, 1.30, .365)


def near(actual, expected):
    assert all(abs(x - y) <= EPS for x, y in zip(actual, expected, strict=True)), (actual, expected)


def bounds(points):
    coordinates = list(zip(*points))
    return tuple(map(min, coordinates)), tuple(map(max, coordinates))


def geometry(objects):
    result = {}
    for obj in objects:
        assert obj.type == "MESH", obj.name
        mesh = obj.data
        mesh.calc_loop_triangles()
        points = [unity(obj.matrix_world @ vertex.co) for vertex in mesh.vertices]
        triangles = [tuple(points[i] for i in face.vertices) for face in mesh.loop_triangles]
        for tri in triangles:
            a, b, c = map(Vector, tri)
            assert (b - a).cross(c - a).length > 1e-8, (obj.name, tri)
        result[obj.name] = (points, triangles)
    return result


def halfspace(polygon, axis, limit, sign):
    if not polygon:
        return []
    result = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        da, db = (a[axis] - limit) * sign, (b[axis] - limit) * sign
        if da >= 0:
            result.append(a)
        if (da >= 0) != (db >= 0):
            t = da / (da - db)
            result.append(tuple(x + t * (y - x) for x, y in zip(a, b)))
    return result


def box_is_empty(low, high, triangles):
    for tri in triangles:
        polygon = list(tri)
        for axis in range(3):
            polygon = halfspace(polygon, axis, low[axis], 1)
            polygon = halfspace(polygon, axis, high[axis], -1)
        if polygon:
            return False
    return True


def distance_to_projection(polygon, x, z):
    points = [Vector((px - x, pz - z)) for px, _, pz in polygon]
    signed_edges = []
    distances = []
    for a, b in zip(points, points[1:] + points[:1]):
        delta = b - a
        signed_edges.append(a.cross(b))
        t = min(1, max(0, -a.dot(delta) / delta.length_squared)) if delta.length_squared else 0
        distances.append((a + t * delta).length)
    # Clipping a triangle preserves convexity. Nonzero area distinguishes a collapsed projection.
    if abs(sum(signed_edges)) > 1e-9 and (min(signed_edges) >= 0 or max(signed_edges) <= 0):
        return 0.0
    return min(distances)


def check_fit(triangles):
    # Use the entire continuous sweep of the prefab's .50 x .06 m blade rectangle.
    # This radius also conservatively contains the stylized blades' silhouette.
    radius = math.hypot(.25, .03)
    slab = [halfspace(halfspace(list(tri), 1, 1.257, 1), 1, 1.300, -1) for tri in triangles]
    margins = [min(distance_to_projection(p, x, z) for p in slab if p) - radius
               for x, _, z in ROTOR_AXES]
    assert min(margins) > 0, margins

    # The parked AABB includes the feet. Exclude only the intentional bottom contact.
    # The lift and front extraction boxes represent continuous translations, including every intermediate pose.
    bottom = DRONE_MIN[1] + EPS
    assert box_is_empty((-.365, bottom, -.365), DRONE_MAX, triangles), "parked drone"
    assert box_is_empty((-.365, bottom, -.365), (.365, 1.30, 1.365), triangles), "forward by 1 m"
    assert box_is_empty((-.365, bottom, -.365), (.365, 1.90, .365), triangles), "lift by .60 m"
    assert box_is_empty((-.365, bottom + .60, -.365), (.365, 1.90, 1.365), triangles), "lift then forward"
    assert box_is_empty((-.60, 1.575, -.45), (.60, 1.665, -.417), triangles), "prefab progress background and fill"
    assert box_is_empty((-.655, 1.765, -.425), (.655, 2.075, -.40), triangles), "sign text plane"
    return {"rotor_sweep_radius_m": radius, "radial_clearance_m": margins,
            "pickup_forward_m": 1.0, "pickup_vertical_m": .60, "progress_and_text_clear": True}


def check_drone(objects, deck_triangles):
    drone = geometry(objects)
    near(bounds(v for points, _ in drone.values() for v in points)[0], DRONE_MIN)
    near(bounds(v for points, _ in drone.values() for v in points)[1], DRONE_MAX)
    assert len(drone) == 5, drone.keys()
    by_name = {obj.name: obj for obj in objects}
    near(unity(by_name["Test_Drone"].matrix_world.translation), (0, 1.125, 0))
    for i, position in enumerate(ROTOR_AXES):
        rotor = by_name[f"Test_Propeller_{i}"]
        near(unity(rotor.matrix_world.translation), position)
        x, _, z = position
        assert max(math.hypot(v[0] - x, v[2] - z) for v in drone[rotor.name][0]) <= math.hypot(.25, .03) + EPS
    feet = [point for point in drone["Test_Drone"][0] if abs(point[1] - .95) < EPS]
    assert len(feet) == 32, len(feet)
    # A 2 mm vertical probe at every foot footprint vertex hits the actual platform.
    for x, y, z in feet:
        assert not box_is_empty((x - EPS, y - .001, z - EPS), (x + EPS, y + .001, z + EPS),
                                deck_triangles), (x, y, z)


def inspect(objects, stage):
    bpy.context.view_layer.update()
    station = geometry(objects)
    assert station.keys() == PIVOTS.keys(), station.keys()
    by_name = {obj.name: obj for obj in objects}
    all_points = [v for points, _ in station.values() for v in points]
    all_triangles = [t for _, triangles in station.values() for t in triangles]
    low, high = bounds(all_points)
    near(low, (-.70, 0, -.55))
    near(high, (.70, 2.30, .50))
    assert len(all_triangles) <= 3000, len(all_triangles)
    for name, pivot in PIVOTS.items():
        obj = by_name[name]
        near(unity(obj.matrix_world.translation), pivot)
        near(obj.matrix_world.to_scale(), (1, 1, 1))
        assert obj.parent == (None if name == "Table" else by_name["Table"])
        material = "DRONEWORKS_QC_Lamp" if name == "Lamp" else "DRONEWORKS_Palette"
        assert [mat.name for mat in obj.data.materials] == [material], (name, obj.data.materials[:])
        layer = obj.data.uv_layers.active
        assert layer and len(layer.data) == len(obj.data.loops), name
        if name != "Lamp":
            for corner in layer.data:
                assert tuple(corner.uv) in {uv(paint) for paint in SWATCH}, (name, tuple(corner.uv))
    expected = {
        "Platform": ((-.425, .90, -.425), (.425, .95, .425)),
        "SignBoard": ((-.675, 1.76, -.45), (.675, 2.08, -.43)),
        "Lamp": ((.45, 2.10, -.55), (.65, 2.30, -.35)),
    }
    for name, target in expected.items():
        for actual, point in zip(bounds(station[name][0]), target):
            near(actual, point)
    near(bounds(station["Table"][0])[0], (-.70, 0, -.50))
    near(bounds(station["Table"][0])[1], (.70, .90, .50))
    near(bounds(v for v in station["Table"][0] if v[1] >= .84 - EPS)[0], (-.70, .84, -.50))
    # The raised fascia with bolt heads is on the +Z side. The board and lamp are behind the deck.
    assert high[2] == bounds(station["Table"][0])[1][2]
    assert bounds(station["SignBoard"][0])[1][2] < 0
    if stage != "blockout":
        assert not box_is_empty((.48, .74, .443), (.55, .79, .447), station["Table"][1]), "front +Z bolt"
    fit = check_fit(all_triangles)
    if stage != "fbx":
        check_drone(bpy.data.collections["TEST_DRONE"].objects, station["Platform"][1])
        for asset in (PALETTE.name, "drone_quadcopter.png"):
            image = bpy.data.images[asset]
            assert image.size[0] > 0 and Path(bpy.path.abspath(image.filepath)).is_file(), asset
    counts = {key: len(value[1]) for key, value in station.items()}
    report = {"stage": stage, "blender": bpy.app.version_string, "bounds_xyz": (low, high),
              "dimensions_xyz": tuple(b - a for a, b in zip(low, high)), "triangles": len(all_triangles),
              "meshes": {name: {"bounds_xyz": bounds(points), "triangles": counts[name], "pivot_xyz": PIVOTS[name]}
                         for name, (points, _) in station.items()}, "fit": fit}
    (CHECKS / f"{stage}.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps({"stage": stage, "dimensions": report["dimensions_xyz"], "triangles": counts, "fit": fit}))


if __name__ == "__main__":
    mode, *args = sys.argv[sys.argv.index("--") + 1:]
    if mode == "fbx":
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = Path(args[0]).resolve()
        assert bpy.ops.import_scene.fbx(filepath=str(path)) == {"FINISHED"}
        inspect(bpy.context.scene.objects, "fbx")
    else:
        scene = bpy.context.scene
        assert scene.unit_settings.system == "METRIC" and scene.unit_settings.scale_length == 1.0
        inspect(bpy.data.collections["EXPORT"].objects, mode)
