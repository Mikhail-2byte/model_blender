"""Check the saved model, continuous rotor envelopes, box fit, and fresh FBX import."""

import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_drone import BOX_SCALE, BOX_Y, CHECKS, HERE, MODELS, MOTORS, ROOT, SWATCH, uv

sys.path.insert(0, str(MODELS / "StationQC"))
from check_qc import bounds, distance_to_projection, halfspace

EPS = 0.000015
PARTS = {"Body": (0,0,0), "Board": (0,.035,0), "Battery": (0,-.085,0), "Camera": (0,-.1,.2)}
PARTS |= {f"Motor_{i}": (x,.085,z) for i, (x,z) in enumerate(MOTORS)}
PARTS |= {f"Propeller_{i}": (x,.155,z) for i, (x,z) in enumerate(MOTORS)}
DECALS = {f"Crack_{part}": part for part in PARTS} | {"QcStamp": "Body"}


def unity(point):
    x, y, z = point
    return (-x, z, -y)


def near(actual, expected):
    assert all(abs(a-e) < EPS for a,e in zip(actual, expected, strict=True)), (actual, expected)


def geometry(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    points = [unity(obj.matrix_world @ v.co) for v in mesh.vertices]
    triangles = [tuple(points[i] for i in tri.vertices) for tri in mesh.loop_triangles]
    assert all((Vector(b)-Vector(a)).cross(Vector(c)-Vector(a)).length > 1e-9 for a,b,c in triangles), obj.name
    return points, triangles


def fixture(name):
    source_file = MODELS / name.removeprefix("SM_") / f"{name}.blend"
    if not source_file.exists():
        return None
    with bpy.data.libraries.load(str(source_file)) as (source, dest):
        dest.collections = ["EXPORT"]
    collection = dest.collections[0]
    bpy.context.scene.collection.children.link(collection)
    bpy.context.view_layer.update()
    data = {obj.name.partition(".")[0]: geometry(obj) for obj in collection.objects}
    bpy.data.collections.remove(collection)
    return data


def check_box(all_points):
    box = fixture("SM_BoxOpen")
    floor, lid = .02, .4204
    wall = [-.34,.34,-.34,.34]
    if box:
        for index, (name, axis, side) in enumerate([("Wall_W",0,1),("Wall_E",0,0),("Wall_S",2,1),("Wall_N",2,0)]):
            wall[index] = bounds(box[name][0])[side][axis]
        floor = max(point[1] for point in box["Bottom"][0])
        lid = min(point[1] for name in box if name.startswith("Flap_") for point in box[name][0])
    low, high = bounds((x*BOX_SCALE, y*BOX_SCALE + BOX_Y, z*BOX_SCALE) for x,y,z in all_points)
    side_gaps = [low[0]-wall[0], wall[1]-high[0], low[2]-wall[2], wall[3]-high[2]]
    floor_gap = low[1]-floor
    flap_gap = lid-high[1]
    assert min(side_gaps) > 0 and abs(floor_gap) < EPS and flap_gap > 0
    return {"fixture": bool(box), "scale": BOX_SCALE, "packed_y": BOX_Y, "y_offset": BOX_Y-.1555,
            "bounds": [low,high], "wall_clearances_xmin_xmax_zmin_zmax": side_gaps,
            "floor_clearance": floor_gap, "floor_clearance_at_old_y": floor_gap+.1555-BOX_Y,
            "closed_flap_clearance": flap_gap}


def check_spin(objects, data, local_up):
    radii, heights = [], []
    propellers = [objects[f"Propeller_{i}"] for i in range(4)]
    for index, (obj, (x,z)) in enumerate(zip(propellers, MOTORS, strict=True)):
        points = data[obj.name][0]
        rad = max(math.hypot(px-x, pz-z) for px,_,pz in points)
        assert rad <= .20
        xs, _, zs = (max(c)-min(c) for c in zip(*points))
        assert (zs > 4*xs) if index % 2 == 0 else (xs > 4*zs)
        radii.append(rad)
        heights += [y for _,y,_ in points]
        tip = [v.co.copy() for v in obj.data.vertices]
        tip = max(tip,key=lambda v: (v - v.dot(local_up)*local_up).length)
        obj.rotation_mode = "QUATERNION"
        zero = obj.rotation_quaternion.copy()
        original = obj.matrix_world @ tip - obj.matrix_world.translation
        for degrees in range(0,361,5):
            angle = math.radians(degrees) * (1 if index % 2 == 0 else -1)
            obj.rotation_quaternion = zero @ Quaternion(local_up, angle)
            bpy.context.view_layer.update()
            near(unity(obj.matrix_world.translation), PARTS[obj.name])
            moved = obj.matrix_world @ tip - obj.matrix_world.translation
            expected = (math.cos(angle)*original.x-math.sin(angle)*original.y,
                        math.sin(angle)*original.x+math.cos(angle)*original.y, original.z)
            near(moved, expected)
        obj.rotation_quaternion = zero
        bpy.context.view_layer.update()
    gap = min(math.dist(MOTORS[i],MOTORS[j])-radii[i]-radii[j] for i in range(4) for j in range(i+1,4))
    assert gap > 0
    fixed_top = max(p[1] for name in PARTS if not name.startswith(("Propeller_", "Motor_")) for p in data[name][0])
    body_gap = min(heights) - fixed_top
    assert body_gap > 0
    mount_gaps = []
    for index, (x,z) in enumerate(MOTORS):
        motor_points = data[f"Motor_{index}"][0]
        prop_points = data[f"Propeller_{index}"][0]
        blade_low = min(y for px,y,pz in prop_points if math.hypot(px-x,pz-z) > .04)
        mount_gaps.append(blade_low - max(y for _,y,_ in motor_points))
    assert min(mount_gaps) > 0
    station = fixture("SM_StationQC")
    qc_y = 1.125
    legacy_shield_gap = .46 - .29 - radii[3]
    assert legacy_shield_gap > 0
    shield_gaps = None
    feet = [p for p in data["Body"][0] if abs(p[1]+.175) < EPS]
    assert feet
    if station:
        platform = station["Platform"][1]
        plane = BVHTree.FromPolygons([Vector(v) for t in platform for v in t],
                                    [tuple(range(i,i+3)) for i in range(0,len(platform)*3,3)], all_triangles=True)
        for x,y,z in feet:
            hit, _, _, _ = plane.ray_cast((x,y+qc_y+.002,z),(0,-1,0),.004)
            assert hit is not None and abs(hit.y-(y+qc_y)) < EPS, (x,y,z,hit)
        shield = [halfspace(halfspace(list(tri),1,min(heights)+qc_y,1),1,max(heights)+qc_y,-1)
                  for tri in station["Backboard"][1]]
        shield_gaps = [min(distance_to_projection(p,x,z) for p in shield if p)-r
                       for (x,z),r in zip(MOTORS,radii,strict=True)]
        assert min(shield_gaps) > 0
    return {"diameters": [2*r for r in radii], "neighbor_gap": gap, "vertical_body_gap": body_gap,
            "blade_to_motor_gaps": mount_gaps, "qc_y": qc_y, "qc_feet_vertices_tested": len(feet),
            "qc_shield_radial_gaps": shield_gaps, "legacy_flat_shield_rear_gap": legacy_shield_gap,
            "angle_step_degrees": 5}


def inspect(objects, stage):
    by_name = {obj.name: obj for obj in objects}
    expected = PARTS if stage == "blockout" else PARTS | DECALS
    assert by_name.keys() == expected.keys(), (by_name.keys() - expected.keys(), expected.keys() - by_name.keys())
    bpy.context.view_layer.update()
    data = {name: geometry(obj) for name,obj in by_name.items()}
    local_up = Vector((0,1,0) if stage == "fbx" else (0,0,1))
    for name, obj in by_name.items():
        parent = None if name == "Body" else by_name[DECALS.get(name,"Body")]
        assert obj.parent == parent, name
        near(obj.matrix_world.to_scale(), (1,1,1))
        try:
            near(unity(obj.matrix_world.translation), PARTS[DECALS.get(name,name)])
        except AssertionError as error:
            raise AssertionError(f"{name} pivot: {error}") from error
        if name in PARTS:
            near(unity(obj.matrix_world.to_quaternion() @ local_up), (0,1,0))
        expected_slot = "DRONEWORKS_DroneQuad_Decals" if name in DECALS else "DRONEWORKS_Palette"
        assert list(obj.data.materials.keys()) == [expected_slot], (name,obj.data.materials.keys())
        uvs = obj.data.uv_layers.active.data
        assert len(uvs) == len(obj.data.loops)
        if name in PARTS:
            assert set(tuple(loop.uv) for loop in uvs) <= {uv(color) for color in SWATCH}
        elif stage == "blend":
            assert obj.hide_render and obj.hide_get(), name
    count = {name: len(triangles) for name, (_,triangles) in data.items()}
    assert sum(count.values()) <= 5000, count
    all_points = [v for points,_ in data.values() for v in points]
    low, high = bounds(all_points)
    size = [b-a for a,b in zip(low,high)]
    assert all(actual <= limit+EPS for actual,limit in zip(size,(.73,.35,.73)))
    assert abs(low[1]+.175) < EPS
    camera_lens = [p for p in data["Camera"][0] if p[2] > .2599]
    assert camera_lens and max(abs(p[1]+.100) for p in camera_lens) < .008, "Lens faces Unity +Z"
    other = [t for name in PARTS if name != "Camera" for t in data[name][1]]
    obstacle = BVHTree.FromPolygons([Vector(v) for t in other for v in t],
                                   [tuple(range(i,i+3)) for i in range(0,len(other)*3,3)], all_triangles=True)
    assert obstacle.ray_cast((0,-.100,.260),(0,0,1),.50)[0] is None, "Lens should have a clear forward sightline"
    spin = check_spin(by_name,data,local_up)
    box = check_box(all_points)
    return {"part_triangles": count, "triangle_total": sum(count.values()), "bounds": [low,high],
            "part_bounds": {name: bounds(points) for name,(points,_) in data.items()},
            "size": size, "spin": spin, "box": box, "lens_faces_positive_z": True}


def main():
    stage = sys.argv[sys.argv.index("--")+1]
    if stage == "prepare-export":
        bpy.ops.wm.open_mainfile(filepath=str(HERE / "SM_DroneQuad.blend"))
        bake_basis = Matrix.Rotation(-math.pi/2,4,"X")
        for obj in bpy.context.scene.collection.children["EXPORT"].objects:
            obj.hide_set(False)
            obj.hide_render = False
            if obj.parent and obj.parent.parent:
                # With Apply Transform, the exporter applies its parent basis a second
                # time at the grandchild level. Cancel that in the staging copy only.
                obj.matrix_world = bake_basis @ obj.matrix_world
        bpy.context.preferences.filepaths.save_version = 0
        bpy.context.preferences.filepaths.file_preview_type = "NONE"
        bpy.ops.wm.save_as_mainfile(filepath=str(CHECKS / "SM_DroneQuad.export.blend"), relative_remap=True)
        return
    if stage == "fbx":
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=str(ROOT / "Exports/Unity/SM_DroneQuad.fbx"))
        objects = list(bpy.context.scene.objects)
    else:
        path = CHECKS / "SM_DroneQuad.blockout.blend" if stage == "blockout" else HERE / "SM_DroneQuad.blend"
        bpy.ops.wm.open_mainfile(filepath=str(path))
        objects = list(bpy.context.scene.collection.children["EXPORT"].objects)
    result = inspect(objects,stage)
    if stage == "fbx":
        author = json.loads((CHECKS / "blend.json").read_text(encoding="utf-8"))
        assert result["part_triangles"] == author["part_triangles"]
        for name, box in result["part_bounds"].items():
            for actual, expected in zip(box, author["part_bounds"][name], strict=True):
                near(actual, expected)
    output = CHECKS / f"{stage}.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"PASS {stage}: {result['triangle_total']} tris, size {result['size']}")


if __name__ == "__main__":
    main()
