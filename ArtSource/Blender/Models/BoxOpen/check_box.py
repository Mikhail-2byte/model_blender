"""Reopen the source, test the fixture, and reimport the delivery into an empty Blender."""

import itertools
import json
import math
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector
from mathutils.bvhtree import BVHTree


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CHECKS = ROOT / ".local/checks/box-open"
SIDES = {
    "N": ((0,.42,.36), (-1,0,0), (0,0,-1)),
    "S": ((0,.42,-.36), (1,0,0), (0,0,1)),
    "E": ((.36,.42,0), (0,0,1), (-1,0,0)),
    "W": ((-.36,.42,0), (0,0,-1), (1,0,0)),
}
STATION = ("Table", "Backboard", "TapeRoll", "SignBoard", "Lamp")
WALLS = {"Bottom", *("Wall_"+side for side in SIDES)}
PORTS = {"Flap_"+side for side in SIDES}
EPS = 0.00002
TRAVEL = math.radians(120)


def near(actual, expected):
    assert len(actual) == len(expected) and all(abs(x-y)<EPS for x, y in zip(actual, expected)), (
        tuple(actual), tuple(expected))


def unity(v):
    return (-v.x, v.z, -v.y)


def bounds(points):
    axes = list(zip(*points))
    return tuple(min(a) for a in axes), tuple(max(a) for a in axes)


def world_points(obj):
    return [unity(obj.matrix_world @ v.co) for v in obj.data.vertices]


def parts_bounds(objects):
    return bounds(point for obj in objects for point in world_points(obj))


def verify_asset(objects):
    assert set(objects) == WALLS | PORTS | {"Tape"}
    root = objects["Bottom"]
    assert root.parent is None
    near(unity(root.matrix_world.translation), (0,0,0))
    sizes, total = {}, 0
    for name, obj in sorted(objects.items()):
        assert obj.type == "MESH"
        assert name == "Bottom" or obj.parent == root
        near(obj.scale, (1,1,1))
        lo, hi = parts_bounds([obj])
        size = tuple(y-x for x, y in zip(lo, hi))
        obj.data.calc_loop_triangles()
        total += len(obj.data.loop_triangles)
        assert all(p.area > 1e-10 for p in obj.data.polygons), name
        assert obj.data.uv_layers.get("UVMap") is not None
        assert obj.data.materials[0].name.startswith("DRONEWORKS_Palette")
        assert len(obj.data.materials) == (2 if name == "Wall_N" else 1)
        if name == "Wall_N":
            assert obj.data.materials[1].name.startswith("DRONEWORKS_BoxDecal")
            assert sum(p.material_index == 1 for p in obj.data.polygons) == 1
        for f in obj.data.polygons:
            if f.material_index == 0:
                allowed = ((.8125,.3125),) if name == "Tape" else (
                    (.5625,.1875), (.6875,.1875), (.8125,.1875))
                assert all(any((obj.data.uv_layers[0].uv[i].vector-Vector(a)).length < EPS
                               for a in allowed) for i in f.loop_indices), name
        sizes[name] = {"size_m": size, "bounds_m": (lo,hi),
                       "triangles": len(obj.data.loop_triangles)}
    assert total <= 800
    lo, hi = parts_bounds([objects[name] for name in WALLS])
    near(lo, (-.36,0,-.36))
    # The front ink projects .18 mm off the cardboard to avoid z-fighting.
    near(hi, (.36,.42,.36018))
    near(sizes["Bottom"]["size_m"], (.72,.02,.72))
    near(sizes["Wall_N"]["size_m"], (.72,.40,.02018))
    near(sizes["Wall_S"]["size_m"], (.72,.40,.02))
    near(sizes["Wall_E"]["size_m"], (.02,.40,.68))
    near(sizes["Wall_W"]["size_m"], (.02,.40,.68))
    near((sizes["Wall_E"]["bounds_m"][0][0]-sizes["Wall_W"]["bounds_m"][1][0],
          sizes["Wall_N"]["bounds_m"][0][2]-sizes["Wall_S"]["bounds_m"][1][2]), (.68,.68))
    tips = {}
    for side, (pivot, exact_axis, inward) in SIDES.items():
        obj = objects["Flap_"+side]
        near(unity(obj.matrix_world.translation), pivot)
        # Rotation axes are axial vectors. Unity's handedness change flips the sign.
        near(unity(obj.matrix_world.to_3x3() @ Vector((-1,0,0))), exact_axis)
        lower, upper = (.4307,.441) if side in ("N","S") else (.4204,.4304)
        size = (.72,upper-lower,.36) if side in ("N","S") else (.36,upper-lower,.72)
        near(sizes[obj.name]["size_m"], size)
        near((sizes[obj.name]["bounds_m"][0][1], sizes[obj.name]["bounds_m"][1][1]),
             (lower,upper))
        tip = Vector((-(pivot[0]+.36*inward[0]), -(pivot[2]+.36*inward[2]), pivot[1]))
        local_tip = obj.matrix_world.inverted() @ tip
        rest = obj.matrix_basis.to_quaternion()
        obj.rotation_mode = "QUATERNION"
        for deg in (0,30,60,90,120):
            obj.rotation_quaternion = rest @ Quaternion((1,0,0), math.radians(-deg))
            bpy.context.view_layer.update()
            near(unity(obj.matrix_world.translation), pivot)
            p = unity(obj.matrix_world @ local_tip)
            a = math.radians(deg)
            near(p, (pivot[0]+.36*inward[0]*math.cos(a),
                     pivot[1]+.36*math.sin(a), pivot[2]+.36*inward[2]*math.cos(a)))
        tips[side] = p
        obj.rotation_quaternion = rest
    bpy.context.view_layer.update()
    tape = objects["Tape"]
    near(unity(tape.matrix_world.translation), (-.37,.445,0))
    near(sizes["Tape"]["size_m"], (.74,.008,.12))
    near((sizes["Tape"]["bounds_m"][0][1],sizes["Tape"]["bounds_m"][1][1]), (.441,.449))
    tape_samples = {}
    for progress in (0,.25,.5,.75,1):
        tape.scale.x = progress
        bpy.context.view_layer.update()
        lo, hi = parts_bounds([tape])
        near((lo[0],hi[0]), (-.37,-.37+.74*progress))
        tape_samples[progress] = (lo[0],hi[0])
    return {"triangles": total, "parts": sizes, "open_tips_m": tips, "tape_growth_m": tape_samples}


def bvh(vertices, faces):
    return BVHTree.FromPolygons(vertices, faces)


def split_bounds(obj):
    adjacency = [[] for _ in obj.data.vertices]
    for edge in obj.data.edges:
        a, b = edge.vertices
        adjacency[a].append(b)
        adjacency[b].append(a)
    unseen = set(range(len(adjacency)))
    points = world_points(obj)
    while unseen:
        todo = [unseen.pop()]
        group = []
        while todo:
            i = todo.pop()
            group.append(points[i])
            for n in adjacency[i]:
                if n in unseen:
                    unseen.remove(n)
                    todo.append(n)
        yield bounds(group)


def extrema(c, s):
    a = math.atan2(s,c)
    at = [0, TRAVEL, *(t for t in (a-math.pi,a,a+math.pi) if 0<t<TRAVEL)]
    return [c*math.cos(t)+s*math.sin(t) for t in at]


def separation(a, b):
    return max(max(i-l,k-j) for i,j,k,l in zip(*a,*b,strict=True))


def verify_fixture(scene):
    bpy.context.window.scene = scene
    bpy.context.view_layer.update()
    root = scene.objects["Preview_Bottom"]
    drone = scene.objects["TestDrone_073x035x073"]
    near(unity(root.matrix_world.translation), (0,.90,.10))
    near(drone.scale, (.9,)*3)
    drone_lo, drone_hi = parts_bounds(drone.children)
    near(tuple(y-x for x,y in zip(drone_lo,drone_hi,strict=True)), (.657,.315,.657))
    near(drone_lo, (-.3285,.92,-.2285))
    near(drone_hi, (.3285,1.235,.4285))
    station = {f"{name}/{i}": bb for name in STATION
               for i, bb in enumerate(split_bounds(scene.objects[name]))}
    legacy_shield = ((-.70,.90,-.50),(.70,2.10,-.46))
    progress_bar = ((-.60,1.575,-.450),(.60,1.665,-.430))
    panels = {}
    report = {}
    for side in SIDES:
        obj = scene.objects["Preview_Flap_"+side]
        rest = obj.matrix_world.to_quaternion() @ Quaternion((1,0,0),TRAVEL)
        pivot = obj.matrix_world.translation
        verts = [v.co.copy() for v in obj.data.vertices]
        faces = [tuple(p.vertices) for p in obj.data.polygons]
        swept = []
        for x,y,z in verts:
            a = unity(pivot + rest @ Vector((x,0,0)))
            c = unity(rest @ Vector((0,y,z)))
            s = unity(rest @ Vector((0,z,-y)))
            swept.extend(tuple(a[i]+ex[i] for i in range(3))
                         for ex in itertools.product(*(extrema(c[i],s[i]) for i in range(3))))
        envelope = bounds(swept)
        gap, limiting = min((separation(envelope, bb), name) for name, bb in station.items())
        assert gap > .005 and separation(envelope, (drone_lo,drone_hi)) > .07
        report[side] = {"swept_bounds_m": envelope, "station_minimum_gap_m": gap,
                        "limiting_part": limiting, "drone_minimum_gap_m": separation(envelope, (drone_lo,drone_hi))}
        if side == "S":
            assert separation(envelope, legacy_shield) > 0
            report[side]["prefab_backboard_minimum_gap_m"] = separation(envelope, legacy_shield)
        panels[side] = (rest, pivot, verts, faces)

    def mesh_at(side, angle):
        rest, pivot, vertices, faces = panels[side]
        q = rest @ Quaternion((1,0,0),math.radians(-angle))
        return bvh([pivot+q@v for v in vertices],faces)

    low, high = ("E","W"), ("N","S")
    pairs = list(itertools.product(low, high))
    overlap = {}
    for a,b in pairs:
        degrees = [d for d in range(121) if mesh_at(a,d).overlap(mesh_at(b,d))]
        overlap[a+b] = None if not degrees else (min(degrees),max(degrees))
        for angle in range(121):
            assert not mesh_at(a,angle).overlap(mesh_at(b,120)), (a,b,angle)
            assert not mesh_at(a,0).overlap(mesh_at(b,angle)), (a,b,angle)
    bar_lo, bar_hi = progress_bar
    corners = [Vector((-x,-z,y)) for x,y,z in itertools.product(*zip(bar_lo,bar_hi))]
    bar = bvh(corners,[(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)])
    return {"flaps": report, "drone_bounds_m": (drone_lo,drone_hi),
            "simultaneous_overlap_sampled_degrees": overlap,
            "staggered_EW_then_NS_cross_layer_clear_at_1_degree": True,
            "rear_vs_existing_progress_backdrop_sampled_degrees":
                [a for a in range(121) if mesh_at("S",a).overlap(bar)]}


def main():
    bpy.ops.wm.open_mainfile(filepath=str(HERE/"SM_BoxOpen.blend"))
    authored = verify_asset(dict(bpy.context.scene.collection.children["EXPORT"].objects.items()))
    fixture = verify_fixture(bpy.data.scenes["On packing table"])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(ROOT/"Exports/Unity/SM_BoxOpen.fbx"))
    bpy.context.view_layer.update()
    imported = verify_asset(dict(bpy.context.scene.objects.items()))
    assert authored["triangles"] == imported["triangles"]
    result = {"blend": authored, "fbx": imported, "fixture": fixture}
    dest = CHECKS/"verification.json"
    dest.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(f"PASS: source, fixture and fresh FBX import. {imported['triangles']} triangles. {dest}")


if __name__ == "__main__":
    main()
