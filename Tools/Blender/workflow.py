"""DRONEWORKS Blender template, rigid FBX export and environment check."""

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path("ArtSource/Blender/DRONEWORKS.blend")
PALETTE = Path("ArtSource/Textures/T_Palette_DRONEWORKS.png")
REFERENCE = Path("References/conveyor.png")
COLORS = {"Frame": (0.1875, 0.9375), "Belt": (0.6875, 0.9375)}
BELT_PIVOT = (0.30, -0.65, 0.60)


def save(path):
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = "NONE"
    bpy.ops.wm.save_as_mainfile(filepath=str(path), relative_remap=True)


def make_template(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "METERS"
    scene["Art direction"] = "DRONEWORKS / 1 unit = 1 m / front = -Y"
    for name in ("EXPORT", "REFERENCES"):
        scene.collection.children.link(bpy.data.collections.new(name))

    image = bpy.data.images.load(str(ROOT / PALETTE))
    material = bpy.data.materials.new("DRONEWORKS_Palette")
    material.use_fake_user = True
    material.use_nodes = True
    nodes = material.node_tree.nodes
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Closest"
    texture.extension = "EXTEND"
    texture.location = (-340, 120)
    material.node_tree.links.new(texture.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
    if path.exists():
        raise FileExistsError(path)
    save(path)
    image.filepath = bpy.path.relpath(str(ROOT / PALETTE))
    save(path)


def export_rigid(path, apply_transform):
    if path.suffix.lower() != ".fbx":
        raise ValueError("Output must end in .fbx")
    scene = bpy.context.scene
    collection = scene.collection.children.get("EXPORT")
    if collection is None:
        raise ValueError("Scene needs an EXPORT collection")
    meshes = {obj for obj in collection.all_objects if obj.type == "MESH"}
    if not meshes:
        raise ValueError("EXPORT contains no meshes")
    for obj in meshes:
        if obj.parent and obj.parent not in meshes:
            raise ValueError(f"{obj.name}: parent must be a mesh in EXPORT")
        if obj.name not in bpy.context.view_layer.objects:
            raise ValueError(f"{obj.name}: EXPORT object is excluded from the active view layer")
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj in meshes)
    path.parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.export_scene.fbx(
        filepath=str(path), use_selection=True, object_types={"MESH"},
        axis_forward="-Z", axis_up="Y", apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS", bake_space_transform=apply_transform,
        use_mesh_modifiers=True, bake_anim=False, path_mode="STRIP",
    )
    if result != {"FINISHED"} or not path.is_file():
        raise RuntimeError(f"FBX export failed: {result}")


def probe_mesh(name, collection, origin, boxes, uv):
    parts = []
    for center, dimensions in boxes:
        bpy.ops.mesh.primitive_cube_add(size=1)
        obj = bpy.context.object
        parts.append(obj)
        transform = Matrix.Translation(Vector(center) - Vector(origin))
        obj.data.transform(transform @ Matrix.Diagonal((*dimensions, 1.0)))
        for i in range(len(obj.data.uv_layers.active.data)):
            obj.data.uv_layers.active.data[i].uv = uv
    for obj in parts:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    if len(parts) > 1:
        bpy.ops.object.join()
    obj = parts[0]
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)
    obj.name = name
    obj.location = origin
    obj.data.materials.append(bpy.data.materials["DRONEWORKS_Palette"])
    return obj


def close(actual, expected):
    return len(actual) == len(expected) and all(
        math.isclose(a, b, abs_tol=0.001) for a, b in zip(actual, expected)
    )


def verify_geometry(objects):
    if set(objects) != {"Frame", "Belt"}:
        raise RuntimeError(f"Unexpected mesh names: {sorted(objects)}")
    frame, belt = objects["Frame"], objects["Belt"]
    bpy.context.view_layer.update()
    if belt.parent != frame or not close(frame.matrix_world.translation, (0, 0, 0)):
        raise RuntimeError("Expected Frame at the origin with Belt as a child")
    if not close(belt.matrix_world.translation, BELT_PIVOT):
        raise RuntimeError(f"Belt pivot moved: {tuple(belt.matrix_world.translation)}")
    points = [obj.matrix_world @ vertex.co for obj in objects.values() for vertex in obj.data.vertices]
    bounds_min = tuple(min(v[i] for v in points) for i in range(3))
    bounds_max = tuple(max(v[i] for v in points) for i in range(3))
    if not close(bounds_min, (-0.60, -1.00, 0.00)) or not close(bounds_max, (0.60, 1.00, 0.75)):
        raise RuntimeError(f"Bounds differ: {bounds_min} to {bounds_max}")
    for name, obj in objects.items():
        uv = obj.data.uv_layers.active
        if not uv or not all(close(item.uv, COLORS[name]) for item in uv.data):
            raise RuntimeError(f"Palette UV changed: {name}")
    top = [belt.matrix_world @ v.co for v in belt.data.vertices]
    top = [v for v in top if abs(v.z - 0.75) < 0.001]
    if not top or not all(v.x > 0 and v.y < -0.65 for v in top):
        raise RuntimeError("Orientation marker moved from +X / -Y")
    return {"bounds_min": bounds_min, "bounds_max": bounds_max, "belt_pivot": tuple(belt.matrix_world.translation)}


def render_probe(path):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 12
    scene.cycles.use_denoising = True
    scene.view_settings.view_transform = "Standard"
    bpy.ops.object.camera_add(location=(3.0, -4.4, 3.0))
    camera = bpy.context.object
    camera.rotation_euler = (Vector((0, 0, 0.30)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 3.05
    scene.camera = camera
    bpy.ops.object.light_add(type="AREA", location=(1.2, -2.0, 4.0))
    light = bpy.context.object
    light.rotation_euler = (-light.location).to_track_quat("-Z", "Y").to_euler()
    light.data.energy = 520
    light.data.shape = "DISK"
    light.data.size = 4
    scene.world = bpy.data.worlds.new("Probe World")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.115, 0.135, 0.19, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.55
    scene.render.resolution_x = 560
    scene.render.resolution_y = 430
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def check(output, apply_transform):
    output.mkdir(parents=True, exist_ok=False)
    replica = output / "чистая копия"
    for relative in (TEMPLATE, PALETTE, REFERENCE):
        (replica / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, replica / relative)
    bpy.ops.wm.open_mainfile(filepath=str(replica / TEMPLATE), load_ui=False)
    scene = bpy.context.scene
    if (scene.unit_settings.system, scene.unit_settings.scale_length, scene.unit_settings.length_unit) != (
        "METRIC", 1, "METERS",
    ):
        raise RuntimeError("Template unit mismatch")
    collection = scene.collection.children["EXPORT"]
    references = scene.collection.children["REFERENCES"]
    if list(collection.all_objects) or list(references.all_objects):
        raise RuntimeError("Expected an empty template")
    ref_image = bpy.data.images.load(str(replica / REFERENCE))
    ref = bpy.data.objects.new("Reference_2m_Probe", None)
    ref.empty_display_type = "IMAGE"
    ref.data = ref_image
    ref.empty_display_size = 2.0
    ref.location = (0, 2, 0.5)
    ref.rotation_euler.x = math.pi / 2
    references.objects.link(ref)
    ref_image.filepath = bpy.path.relpath(str(replica / REFERENCE))
    frame = probe_mesh("Frame", collection, (0, 0, 0), [((0, 0, 0.25), (1.2, 2, 0.50))], COLORS["Frame"])
    belt = probe_mesh("Belt", collection, BELT_PIVOT, [
        ((0, 0, 0.55), (1.1, 1.9, 0.1)),
        ((0.30, -0.80, 0.675), (0.2, 0.2, 0.15)),
    ], COLORS["Belt"])
    belt.parent = frame
    outside = probe_mesh("OutsideExport", references, (8, 0, 0), [((8, 0, 0), (1, 1, 1))], COLORS["Frame"])
    outside.hide_render = True
    probe = replica / TEMPLATE.parent / "Models/Probe/Probe.blend"
    probe.parent.mkdir(parents=True)
    save(probe)
    bpy.ops.wm.open_mainfile(filepath=str(probe), load_ui=False)
    for image_name, relative in ((PALETTE.name, PALETTE), (REFERENCE.name, REFERENCE)):
        image = bpy.data.images[image_name]
        if not image.filepath.startswith("//") or Path(bpy.path.abspath(image.filepath)).resolve() != (replica / relative).resolve():
            raise RuntimeError(f"Relative path failed after Save As: {image_name} {image.filepath}")
        if not image.has_data and not image.size[0]:
            raise RuntimeError(f"Image failed to load: {image_name}")
    ref = bpy.data.objects["Reference_2m_Probe"]
    if ref.data != bpy.data.images[REFERENCE.name] or ref.empty_display_size != 2.0:
        raise RuntimeError("Reference image or calibration changed")
    palette = bpy.data.materials["DRONEWORKS_Palette"]
    texture = next(node for node in palette.node_tree.nodes if node.type == "TEX_IMAGE")
    if texture.interpolation != "Closest" or texture.image != bpy.data.images[PALETTE.name]:
        raise RuntimeError("Palette image or filter changed")
    measurements = verify_geometry({obj.name: obj for obj in bpy.data.collections["EXPORT"].all_objects})
    render_probe(output / "preview.png")
    fbx = output / "SM_BlenderProbe.fbx"
    export_rigid(fbx, apply_transform)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if bpy.ops.import_scene.fbx(filepath=str(fbx)) != {"FINISHED"}:
        raise RuntimeError("FBX import failed")
    imported = verify_geometry({obj.name: obj for obj in bpy.context.scene.objects})
    report = {"blender": bpy.app.version_string, "source": str(probe), "fbx": str(fbx),
              "apply_transform": apply_transform, "blend": measurements, "fbx_round_trip": imported}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("DRONEWORKS_CHECK_OK", output, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("template", "check", "export"))
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--no-apply-transform", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    apply_transform = not args.no_apply_transform
    if args.mode == "template":
        make_template(args.output or ROOT / TEMPLATE)
    elif args.mode == "check":
        check(args.output, apply_transform)
    else:
        export_rigid(args.output, apply_transform)


if __name__ == "__main__":
    main()
