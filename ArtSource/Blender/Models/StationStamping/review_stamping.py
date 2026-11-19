"""Reopen the source or a clean FBX import, then verify the station contract."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_stamping import (
    CHECKS, COLORS, DIMENSIONS, HERE, PARTS, ROOT, TOL,
    evaluated_points, fit_review, intersects_box, limits, near,
    render, require, rounded, samples, stage, swatch, unity,
)


BOXES = {
    "IntakeTray": ((-.65, .85, .60), (.65, .98, 1.50)),
    "OutputTray": ((-1.7, 0, -.50), (-.80, .98, .50)),
    "Lamp": ((.45, 2.35, .05), (.65, 2.55, .25)),
    "PressHead": ((-.50, 1.725, -.40), (.50, 1.975, .40)),
    "Base": ((-.80, 0, -.60), (.80, .90, 1.50)),
}
PALETTE = "DRONEWORKS_Palette"
HAZARD = "DRONEWORKS_StampingHazard"
LAMP = "DRONEWORKS_StampingLamp"


def raw_fbx(path):
    from io_scene_fbx import parse_fbx

    document, version = parse_fbx.parse(str(path))

    def child(element, name):
        return next(item for item in element.elems if item.id == name)

    def properties(element):
        return {p.props[0].decode(): p.props[4:] for p in child(element, b"Properties70").elems}

    settings = properties(child(document, b"GlobalSettings"))
    expected = {"UpAxis": 1, "UpAxisSign": 1, "FrontAxis": 2, "FrontAxisSign": 1,
                "CoordAxis": 0, "CoordAxisSign": 1, "UnitScaleFactor": 100}
    require(all(settings[key] == [value] for key, value in expected.items()), str(settings))
    models = {}
    for item in child(document, b"Objects").elems:
        element_type = item.id
        require(element_type not in (b"AnimationStack", b"AnimationLayer", b"Deformer", b"NodeAttribute"),
                f"Unexpected FBX payload {element_type}")
        if element_type == b"Model":
            require(item.props[2] == b"Mesh", str(item.props))
            name = item.props[1].split(b"\x00")[0].decode()
            models[name] = properties(item)
    require(models.keys() == PARTS.keys(), f"Raw FBX model set: {list(models)}")
    # The FBX stores Y-up, before the Unity importer's X reflection.
    for name, (x, y, z) in PARTS.items():
        props = models[name]
        require(near(props.get("Lcl Translation", (0, 0, 0)), (-x, y, z)), str(props))
        require(near(props.get("Lcl Scaling", (1, 1, 1)), (1, 1, 1)), str(props))
        require(near(props.get("Lcl Rotation", (0, 0, 0)), (0, 0, 0)), str(props))
    return {"version": version, "settings": expected}


def surfaces_in_box(objects, lo, hi):
    graph = bpy.context.evaluated_depsgraph_get()
    for obj in objects:
        data = obj.evaluated_get(graph).data
        data.calc_loop_triangles()
        points = evaluated_points(obj)
        for triangle in data.loop_triangles:
            contour = [points[index] for index in triangle.vertices]
            if intersects_box(contour, lo, hi):
                yield obj.name


def check_spaces(parts):
    for name, (lo, hi) in {
        "intake": ((-.619, .901, .631), (.619, .979, 1.469)),
        "output": ((-1.669, .901, -.469), (-.831, .979, .469)),
        "progress": ((-.60, 2.575, .230), (.60, 2.665, .263)),
        "heat": ((-.60, 3.175, .230), (.60, 3.265, .263)),
        "label plane": ((-.85, 2.823, .254), (.85, 3.017, .259)),
    }.items():
        impacted = set(surfaces_in_box(parts.values(), lo, hi))
        require(not impacted, f"Geometry in clear volume for {name}: {sorted(impacted)}")


def check_mesh(obj):
    data = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    data.calc_loop_triangles()
    require(not any(tri.area < 1e-10 for tri in data.loop_triangles), f"{obj.name}: degenerate triangle")
    require(not any((data.vertices[a].co - data.vertices[b].co).length < 1e-7
                    for a, b in (edge.vertices for edge in data.edges)), f"{obj.name}: zero-length edge")
    require(all(math.isfinite(v) for vert in data.vertices for v in vert.co), obj.name)
    slots = [m.name for m in data.materials]
    expected = [LAMP] if obj.name == "Lamp" else [PALETTE, HAZARD] if obj.name == "PressHead" else [PALETTE]
    require(slots == expected, f"{obj.name}: materials {slots}")
    uv = data.uv_layers.active
    require(uv is not None, f"{obj.name}: missing UV")
    palette_uvs = []
    stripe_uvs = []
    counts = Counter()
    for triangle in data.loop_triangles:
        counts[slots[triangle.material_index]] += 1
    for face in data.polygons:
        role = slots[face.material_index]
        if role == PALETTE:
            palette_uvs.extend(tuple(uv.data[loop].uv) for loop in face.loop_indices)
        elif role == HAZARD:
            stripe_uvs.extend(tuple(uv.data[loop].uv) for loop in face.loop_indices)
    centers = [swatch(name) for name in COLORS]
    require(all(any(near(pair, center) for center in centers) for pair in palette_uvs),
            f"{obj.name}: palette UV outside used swatches")
    if obj.name == "PressHead":
        require(len(stripe_uvs) == 32 and abs(min(u for u, _ in stripe_uvs)) < TOL and
                abs(max(u for u, _ in stripe_uvs) - 20) < TOL, "Hazard tile UV envelope")
        require(all(abs(v) < TOL or abs(v - 1) < TOL for _, v in stripe_uvs), "Hazard tile UV rows")
    lo, hi = limits((obj,))
    return {"triangles": len(data.loop_triangles), "materials": dict(counts),
            "pivot": rounded(unity(obj.matrix_world.translation)),
            "bounds": [rounded(lo), rounded(hi)],
            "palette_uvs": [list(pair) for pair in sorted(
                {tuple(round(v, 5) for v in uv) for uv in palette_uvs})]}


def restore_textures(parts):
    # FBX uses the workshop STRIP profile. Bind the delivered tile and the
    # project's existing palette for the independent appearance renders.
    for material_name, path, wrap, filtering in (
        (PALETTE, ROOT / "ArtSource/Textures/T_Palette_DRONEWORKS.png", "EXTEND", "Closest"),
        (HAZARD, ROOT / "Exports/Unity/Conveyor_HazardTile.png", "REPEAT", "Linear"),
    ):
        material = bpy.data.materials[material_name]
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        tex = material.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(path), check_existing=True)
        tex.extension = wrap
        tex.interpolation = filtering
        material.node_tree.links.new(tex.outputs["Color"], shader.inputs["Base Color"])
        shader.inputs["Roughness"].default_value = .42
    lamp = parts["Lamp"].data.materials[0].node_tree.nodes.get("Principled BSDF")
    lamp.inputs["Roughness"].default_value = .23
    lamp.inputs["Emission Color"].default_value = lamp.inputs["Base Color"].default_value
    lamp.inputs["Emission Strength"].default_value = .32


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("source", "fbx"))
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    report = {}
    if args.mode == "fbx":
        fbx = ROOT / "Exports/Unity/SM_StationStamping.fbx"
        bpy.ops.wm.read_factory_settings(use_empty=True)
        require(not bpy.data.objects, "FBX review must start in a clean scene")
        report["raw_fbx"] = raw_fbx(fbx)
        require(bpy.ops.import_scene.fbx(filepath=str(fbx), use_custom_normals=True) == {"FINISHED"},
                "FBX import failed")
        parts = {obj.name: obj for obj in bpy.data.objects}
    else:
        scene = bpy.context.scene
        require(scene.unit_settings.system == "METRIC" and scene.unit_settings.scale_length == 1,
                "Source unit mismatch")
        parts = {obj.name: obj for obj in bpy.data.collections["EXPORT"].all_objects}
        palette = bpy.data.images["T_Palette_DRONEWORKS.png"]
        hazard = bpy.data.images["Conveyor_HazardTile.png"]
        require(palette.packed_file and palette.size[:] == (256, 256), "Unpacked palette")
        require(hazard.packed_file and hazard.size[:] == (128, 128), "Unpacked stripe tile")
    bpy.context.view_layer.update()
    require(parts.keys() == PARTS.keys(), f"Part set: {list(parts)}")
    require(not bpy.data.actions, "Unexpected animation")
    require(not parts["Base"].parent, "Base is not at the root")
    for name, obj in parts.items():
        require(obj.type == "MESH", name)
        require(obj.parent == parts["Base"] or name == "Base", f"{name}: parent")
        require(near(unity(obj.matrix_world.translation), PARTS[name]), f"{name}: pivot")
        # Blender keeps the Y-up to Z-up conversion as a root rotation.
        x_rotation = math.pi / 2 if name == "Base" and args.mode == "fbx" else 0
        require(near(obj.scale, (1, 1, 1)) and near(obj.rotation_euler, (x_rotation, 0, 0)),
                f"{name}: transforms")
    for name, (lo, hi) in BOXES.items():
        actual_lo, actual_hi = limits((parts[name],))
        require(near(actual_lo, lo) and near(actual_hi, hi), f"{name}: {actual_lo} to {actual_hi}")
    lo, hi = limits(parts.values())
    require(near(lo, (-1.70, 0, -.60)) and near(hi, (.95, 3.08, 1.50)) and near(hi - lo, DIMENSIONS),
            f"Overall bounds {lo} to {hi}")
    report["dimensions_xyz_m"] = rounded(hi - lo)
    report["parts"] = {name: check_mesh(parts[name]) for name in PARTS}
    report["triangles"] = sum(info["triangles"] for info in report["parts"].values())
    require(report["triangles"] <= 6000, f"Budget exceeded: {report['triangles']}")
    check_spaces(parts)
    report["clear_volumes"] = ["intake", "output", "progress", "heat", "label plane"]
    if args.mode == "source":
        markers = [bpy.data.objects[name] for name in ("Fit_Sheet_0800x0500", "Fit_Frame_0600x0600")]
        for obj in markers:
            obj.hide_set(False)
    else:
        prior = json.loads((CHECKS / "source_report.json").read_text(encoding="utf-8"))
        require(report["parts"] == prior["parts"], "FBX part metrics differ from reopened source")
        markers = samples(bpy.data.materials[PALETTE])
    bpy.context.view_layer.update()
    report["functional_checks"] = fit_review(parts, *markers)
    for obj in markers:
        obj.hide_render = True
        obj.hide_set(True)
    (CHECKS / f"{args.mode}_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"PASS {args.mode}: {report['dimensions_xyz_m']} m, {report['triangles']} triangles")
    if args.render:
        if args.mode == "fbx":
            restore_textures(parts)
            stage()
            for name in ("Front", "OutputSide"):
                render(f"Preview_{name}", CHECKS / f"FBX_{name}.png", (680, 650), 9)
        else:
            for name in ("Front", "OutputSide"):
                render(f"Preview_{name}", HERE / f"SM_StationStamping_{name}.png", (1080, 1040), 24)


if __name__ == "__main__":
    main()
