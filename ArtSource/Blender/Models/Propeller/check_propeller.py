"""Check the saved source, fresh FBX import, and continuous rotor clearances."""

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Quaternion, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_propeller import CHECKS, HERE, ROOT, uv

sys.path.insert(0, str(HERE.parent / "StationQC"))
from check_qc import bounds, distance_to_projection, halfspace

EPS = 1e-5
CENTERS = ((.29, .155, 0), (0, .155, .29), (-.29, .155, 0), (0, .155, -.29))
GEOMETRY = ROOT / "Exports/Unity"
QC_HEIGHT = 1.125  # Station_QC.prefab / DroneVisual, feet on exported platform
LEGACY_SHIELD_FACE = -.460  # Station_QC.prefab / Backboard, -.48 + .04 / 2


def unity(point):
    x, y, z = point
    return (-x, z, -y)


def close(actual, expected):
    assert math.dist(actual, expected) <= EPS, (actual, expected)


def geometry(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    vertices = [unity(obj.matrix_world @ v.co) for v in mesh.vertices]
    triangles = [tuple(vertices[i] for i in t.vertices) for t in mesh.loop_triangles]
    for a, b, c in triangles:
        assert (Vector(b) - Vector(a)).cross(Vector(c) - Vector(a)).length > 1e-9, obj.name
    return vertices, triangles


def fbx_fixture(name):
    previous = bpy.context.window.scene
    scene = bpy.data.scenes.new("Fixture " + name)
    bpy.context.window.scene = scene
    bpy.ops.import_scene.fbx(filepath=str(GEOMETRY / f"SM_{name}.fbx"), use_image_search=False)
    bpy.context.view_layer.update()
    data = {obj.name.partition(".")[0]: geometry(obj) for obj in scene.objects if obj.type == "MESH"}
    bpy.context.window.scene = previous
    bpy.data.scenes.remove(scene)
    return data


def topology(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    assert all(e.is_manifold and e.is_contiguous for e in bm.edges)
    assert bm.calc_volume(signed=True) > 0
    visited = {next(iter(bm.verts))}
    pending = list(visited)
    while pending:
        current = pending.pop()
        for edge in current.link_edges:
            vertex = edge.other_vert(current)
            if vertex not in visited:
                visited.add(vertex)
                pending.append(vertex)
    assert len(visited) == len(bm.verts), "Propeller has disconnected geometry"
    bm.free()


def spin(prop, crack):
    scene = bpy.context.scene
    copies = []
    base = prop.matrix_world.to_quaternion()
    marker = max((v.co.copy() for v in prop.data.vertices),
                 key=lambda v: abs((base @ v).x))
    for i, (x, y, z) in enumerate(CENTERS):
        rotor = prop.copy()
        scene.collection.objects.link(rotor)
        rotor.location = (-x, -z, y)
        rotor.rotation_mode = "QUATERNION"
        rotor.rotation_quaternion = Quaternion((0, 0, 1),
                                               math.pi / 2 if i % 2 == 0 else 0) @ base
        damage = crack.copy()
        scene.collection.objects.link(damage)
        damage.parent = rotor
        copies.append((rotor, damage, rotor.rotation_quaternion.copy()))
    bpy.context.view_layer.update()
    initial = [rotor.matrix_world @ marker - rotor.location for rotor, _, _ in copies]
    for i, v in enumerate(initial):
        assert (abs(v.y) > .16 if i % 2 == 0 else abs(v.x) > .16), v

    for degree in range(361):
        rotations = [Quaternion((0, 0, 1), math.radians(degree * (1 if i % 2 == 0 else -1)))
                     for i in range(4)]
        for (rotor, _, rest), rotation in zip(copies, rotations, strict=True):
            rotor.rotation_quaternion = rotation @ rest
        bpy.context.view_layer.update()
        for i, (rotor, damage, _) in enumerate(copies):
            close(unity(rotor.matrix_world.translation), CENTERS[i])
            close(rotor.matrix_world @ marker - rotor.location, rotations[i] @ initial[i])
            local_damage = crack.data.vertices[0].co
            close(damage.matrix_world @ local_damage,
                  rotor.matrix_world @ crack.matrix_local @ local_damage)
    for rotor, damage, _ in copies:
        bpy.data.objects.remove(damage, do_unlink=True)
        bpy.data.objects.remove(rotor, do_unlink=True)


def check_clearance(prop, all_vertices, radius):
    frame = fbx_fixture("Frame")
    drone = fbx_fixture("DroneQuad")
    station = fbx_fixture("StationQC")
    low, high = bounds(all_vertices)
    lowest = low[1] + .155
    neighbors = min(math.hypot(x - xx, z - zz) - 2 * radius
                    for i, (x, _, z) in enumerate(CENTERS)
                    for xx, _, zz in CENTERS[i+1:])
    body_top = max(y for name in ("Body", "Board", "Battery", "Camera")
                   for _, y, _ in drone[name][0])
    frame_top = max(y for name, (vertices, _) in frame.items()
                    if not name.startswith("Crack") for _, y, _ in vertices)
    motors = []
    for i, (x, _, z) in enumerate(CENTERS):
        points = drone[f"Motor_{i}"][0]
        motor_top = max(y for _, y, _ in points)
        face = [(px, pz) for px, y, pz in points if abs(y - motor_top) < EPS]
        f_min, f_max = bounds(face)
        close(((f_min[0] + f_max[0]) / 2, (f_min[1] + f_max[1]) / 2), (x, z))
        assert abs(motor_top - lowest) < EPS
        motors.append(motor_top)
    blade_min = min(y for x, y, _ in prop if abs(x) > .038 + EPS)
    blade_gap = blade_min + .155 - max(motors)
    assert abs(low[1] + .070 - .060) < EPS
    assert all(math.hypot(x, z) <= .038 + EPS for x, y, z in prop if y <= -.010 + EPS)

    slab = [halfspace(halfspace(list(t), 1, lowest + QC_HEIGHT, 1),
                      1, high[1] + .155 + QC_HEIGHT, -1)
            for _, (_, triangles) in station.items() for t in triangles]
    openings = [min(distance_to_projection(p, x, z) for p in slab if p) - radius
                for x, _, z in CENTERS]
    shield_legacy = CENTERS[3][2] - LEGACY_SHIELD_FACE - radius
    assert min(neighbors, lowest - body_top, lowest - frame_top, blade_gap,
               shield_legacy, *openings) > 0
    return {
        "motor_hub_contact_y_above_motor_center_m": .060,
        "motor_centered_on_all_four_axes": True,
        "blade_gap_over_motor_m": blade_gap,
        "control_cylinder_diameter_height_m": [.150, .120],
        "gap_between_continuous_rotor_envelopes_m": neighbors,
        "gap_over_drone_m": lowest - body_top,
        "gap_over_frame_m": lowest - frame_top,
        "qc_radial_gaps_by_rotor_in_height_slab_m": openings,
        "legacy_qc_solid_shield_gap_m": shield_legacy,
        "rotation_test": "0–360 degrees at 1 degree; 0/2 and 1/3 counter-rotating",
    }


def check(mode):
    if mode == "fbx":
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=str(GEOMETRY / "SM_Propeller.fbx"), use_image_search=False)
        assert {obj.name for obj in bpy.context.scene.objects} == {"Propeller", "Crack"}
    else:
        bpy.ops.wm.open_mainfile(filepath=str(HERE / "SM_Propeller.blend"), use_scripts=False)
        assert bpy.context.scene.unit_settings.scale_length == 1
        assert {obj.name for obj in bpy.data.collections["EXPORT"].all_objects} == {"Propeller", "Crack"}
        assert bpy.data.objects["Crack"].hide_get()
    bpy.context.view_layer.update()
    prop, crack = (bpy.context.scene.objects[name] for name in ("Propeller", "Crack"))
    assert prop.parent is None and crack.parent == prop
    close(prop.matrix_world.translation, (0, 0, 0))
    close(crack.matrix_world.translation, (0, 0, 0))
    close(prop.matrix_world.to_scale(), (1, 1, 1))
    local_up = Vector((0, 1, 0) if mode == "fbx" else (0, 0, 1))
    close(prop.matrix_world.to_quaternion() @ local_up, (0, 0, 1))
    topology(prop)
    for obj, palette_names in [
        (prop, ("rubber dark", "rubber", "rubber light", "signal dark", "signal", "signal light")),
        (crack, ("crack", "crack edge")),
    ]:
        assert [m.name for m in obj.data.materials] == ["DRONEWORKS_Palette"]
        coordinates = {tuple(loop.uv) for loop in obj.data.uv_layers.active.data}
        assert coordinates == {uv(name) for name in palette_names}, (obj.name, coordinates)
        assert not obj.animation_data
    p_vertices, p_triangles = geometry(prop)
    c_vertices, c_triangles = geometry(crack)
    p_low, p_high = bounds(p_vertices)
    all_vertices = p_vertices + c_vertices
    all_low, all_high = bounds(all_vertices)
    close(all_low, p_low)
    close(all_high, p_high)
    assert p_high[0] - p_low[0] > .32
    blade_positive_plan = [point for point in p_vertices if point[0] > .038 + EPS]
    blade_low, blade_high = bounds(blade_positive_plan)
    width = blade_high[2] - blade_low[2]
    assert width <= .060 + EPS  # Across the entire swept planform of one blade.
    close((p_low[1], p_high[1]), (-.01, .01))
    radius = max(math.hypot(x, z) for x, _, z in all_vertices)
    assert radius <= .2
    assert len(p_triangles) + len(c_triangles) <= 300
    tree = BVHTree.FromPolygons([prop.matrix_world @ v.co for v in prop.data.vertices],
                                [t.vertices for t in prop.data.loop_triangles], all_triangles=True)
    decal_offset = []
    for tri in c_triangles:
        for w in ((1/3, 1/3, 1/3), (.6, .2, .2), (.2, .6, .2), (.2, .2, .6)):
            px, py, pz = (sum(v[i] * k for v, k in zip(tri, w, strict=True)) for i in range(3))
            hit, *_ = tree.ray_cast((-px, -pz, .02), (0, 0, -1), .02)
            assert hit is not None and 0 < py - hit.z < .001, (py, hit)
            decal_offset.append(py - hit.z)
    spin(prop, crack)
    result = check_clearance(p_vertices, all_vertices, radius)
    result.update(
        radius_m=radius, diameter_m=2*radius, pivot_unity_m=unity(prop.matrix_world.translation),
        axis_unity=(0, 1, 0), bounds_unity_m=[all_low, all_high],
        blade_plan_width_m=width,
        triangles={"Propeller": len(p_triangles), "Crack": len(c_triangles)},
        crack_offset_m=[min(decal_offset), max(decal_offset)],
        blender=bpy.app.version_string,
    )
    (CHECKS / f"{mode}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(result, flush=True)


if __name__ == "__main__":
    check(sys.argv[-1])
