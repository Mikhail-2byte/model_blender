"""Build the metric source from the workshop template and render both previews."""

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Quaternion, Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CHECKS = ROOT / ".local/checks/propeller"
TEMPLATE = ROOT / "ArtSource/Blender/DRONEWORKS.blend"
DRONE = ROOT / "Exports/Unity/SM_DroneQuad.fbx"
PALETTE = ROOT / "ArtSource/Textures/T_Palette_DRONEWORKS.png"
REFERENCE = ROOT / "References/drone_quadcopter.png"
SWATCH = {
    "rubber dark": (4, 3), "rubber": (5, 3), "rubber light": (6, 3),
    "signal dark": (4, 0), "signal": (5, 0), "signal light": (6, 0),
    "white dark": (0, 2), "white": (1, 2), "white light": (2, 2),
    "crack": (0, 1), "crack edge": (0, 7),
}


def uv(color):
    col, row = SWATCH[color]
    return (col + .5) / 8, 1 - (row + .5) / 8


class Surface:
    def __init__(self):
        self.points, self.faces, self.paint = [], [], []

    def ring(self, points):
        first = len(self.points)
        self.points.extend(points)
        return list(range(first, len(self.points)))

    def face(self, indices, paint):
        self.faces.append(indices)
        self.paint.append(paint)

    def join(self, lower, upper, colors, skip=()):
        for i, color in enumerate(colors):
            if i not in skip:
                j = (i + 1) % len(lower)
                self.face((lower[i], lower[j], upper[j], upper[i]), color)

    def object(self, name, collection, material):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.points, [], self.faces)
        mesh.update()
        layer = mesh.uv_layers.new(name="Palette")
        for poly, color in zip(mesh.polygons, self.paint, strict=True):
            for i in poly.loop_indices:
                layer.data[i].uv = uv(color)
        bm = bmesh.new()
        bm.from_mesh(mesh)
        if name == "Crack":
            bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-7)
        else:
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        mesh.materials.append(material)
        return obj


def circle(radius, height):
    angles = [math.pi * (i - .5) / 6 for i in range(12)]
    return [(radius * math.cos(a), radius * math.sin(a), height) for a in angles]


def blade_plan(span, chord):
    # Leave clearance at the current QC prefab's solid shield as well as the FBX opening.
    return .0367 + (span - .0367) * .802, chord * .94


def propeller():
    part = Surface()
    hub = [part.ring(circle(r, h)) for r, h in
           ((.032, -.010), (.038, -.004), (.038, .001),
            (.038, .006), (.033, .010), (.015, .0082))]
    part.face(hub[0], "rubber dark")
    part.face(hub[-1], "rubber dark")
    for i, color in enumerate(("rubber dark", "rubber", "rubber",
                               "rubber light", "rubber")):
        part.join(hub[i], hub[i + 1], [color] * 12, (0, 6) if i in (1, 2) else ())

    # Longitudinal sections with a swept leading edge and a pitched top face.
    # x, outer left/right edges, width of the bevel, half-thickness, pitch.
    stations = [
        (.055, -.0115, .0120, .0030, .0040, .0006),
        (.081, -.0250, .0135, .0040, .0041, .0015),
        (.124, -.0315, .0250, .0045, .0038, .0016),
        (.176, -.0235, .0230, .0042, .0030, .0012),
        (.193, -.0155, .0160, .0035, .0024, .0009),
        (.199, -.0075, .0090, .0026, .0017, .0005),
    ]
    for a, sign in ((0, 1), (6, -1)):
        b = a + 1
        previous = [hub[2][a], hub[3][a], hub[3][b],
                    hub[2][b], hub[1][b], hub[1][a]]
        for i, (x, left, right, bevel, thick, pitch) in enumerate(stations):
            section = [(left, .001 - pitch), (left + bevel, .001 + thick - pitch),
                       (right - bevel, .001 + thick + pitch), (right, .001 + pitch),
                       (right - bevel, .001 - thick + pitch),
                       (left + bevel, .001 - thick - pitch)]
            plan = [(*blade_plan(x, y), z) for y, z in section]
            ring = part.ring((sign * u, sign * v, z) for u, v, z in plan)
            color = "signal" if i >= 4 else "rubber"
            part.join(previous, ring, [color + " light", color, color + " light",
                                       color + " dark", color + " dark", color + " dark"])
            previous = ring
        part.face(previous, "signal dark")
    return part


def crack_surface(prop):
    mesh = prop.data
    mesh.calc_loop_triangles()
    tree = BVHTree.FromPolygons([v.co for v in mesh.vertices],
                                [t.vertices for t in mesh.loop_triangles], all_triangles=True)
    part = Surface()

    def decal(points, color):
        lifted = []
        for span, chord in points:
            x, y = blade_plan(span, chord)
            hit, *_ = tree.ray_cast((x, y, .02), (0, 0, -1), .02)
            assert hit is not None, (x, y)
            lifted.append((x, y, hit.z + .00018))
        part.face(part.ring(lifted), color)

    spine = [(.142, -.014, .0002), (.146, -.006, .0012),
             (.143, .001, .0010), (.151, .006, .0009), (.154, .015, .0002)]
    for (x, y, w), (xx, yy, ww) in zip(spine[:-1], spine[1:], strict=True):
        decal([(x + w, y), (xx + ww, yy), (xx - ww, yy), (x - w, y)], "crack")
    for (x, y, w), (xx, yy, ww) in zip(spine[:3], spine[1:4], strict=True):
        decal([(x + w + .00065, y), (xx + ww + .00065, yy),
               (xx + ww, yy), (x + w, y)], "crack edge")
    decal([(.1448, -.006), (.1436, -.003), (.136, -.002), (.134, -.003)], "crack")
    return part


def palette():
    material = bpy.data.materials["DRONEWORKS_Palette"]
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = .52
    bsdf.inputs["Specular IOR Level"].default_value = .18
    image = next(n.image for n in material.node_tree.nodes if n.type == "TEX_IMAGE")
    image.filepath = bpy.path.relpath(str(PALETTE))
    image.pack()
    return material


def camera(scene, name, location, target, scale):
    data = bpy.data.cameras.new(name)
    data.type = "ORTHO"
    data.ortho_scale = scale
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    aim(obj, location, target)
    return obj


def aim(obj, location, target):
    obj.location = location
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def stage(name, resolution, ortho_scale, location, focus, floor_z):
    scene = bpy.data.scenes.new(name)
    scene.unit_settings.system = "METRIC"
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 48
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Khronos PBR Neutral"
    scene.world = bpy.data.worlds.new(name)
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = (.48, .58, .75, 1)
    scene.world.node_tree.nodes["Background"].inputs[1].default_value = .22
    scene.camera = camera(scene, name, location, focus, ortho_scale)
    for label, pos, energy, size, color in (
        ("Key", (-.29, -.28, .60), 5, .36, (1, .96, .91)),
        ("Fill", (.34, -.15, .28), 1.4, .24, (.82, .89, 1)),
        ("Rim", (.10, .40, .41), 3, .28, (.89, .93, 1)),
    ):
        data = bpy.data.lights.new(label, "AREA")
        data.energy, data.shape, data.size, data.color = energy, "DISK", size, color
        obj = bpy.data.objects.new(label, data)
        scene.collection.objects.link(obj)
        aim(obj, pos, focus)
    floor_material = bpy.data.materials.new(name + " / studio")
    floor_material.use_nodes = True
    bsdf = floor_material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (.36, .43, .54, 1)
    bsdf.inputs["Roughness"].default_value = .79
    floor = Surface()
    floor.face(floor.ring([(-2, -2, floor_z), (2, -2, floor_z),
                           (2, 2, floor_z), (-2, 2, floor_z)]), "rubber")
    floor.object("Studio floor", scene.collection, floor_material)
    return scene


def fitted_motor(scene, material):
    # The FBX contains an actual game motor. Only this display copy is staged.
    original_scene = bpy.context.window.scene
    bpy.context.window.scene = scene
    before = set(scene.objects)
    bpy.ops.import_scene.fbx(filepath=str(DRONE), use_image_search=False)
    imported = set(scene.objects) - before
    motor = next(obj for obj in imported if obj.name.startswith("Motor_0"))
    bpy.context.view_layer.update()
    transform = motor.matrix_world.copy()
    transform.translation = Vector((0, 0, 0))
    motor.data.transform(transform)
    motor.parent = None
    motor.matrix_world.identity()
    motor.data.materials.clear()
    motor.data.materials.append(material)
    for poly in motor.data.polygons:
        poly.material_index = 0
    for obj in imported - {motor}:
        bpy.data.objects.remove(obj, do_unlink=True)
    motor.name = "Motor / DroneQuad fit reference"
    bpy.context.window.scene = original_scene


def duplicate(prop, scene, height):
    copy = prop.copy()
    copy.name = scene.name + " / Propeller"
    scene.collection.objects.link(copy)
    copy.location.z = height
    return copy


def main():
    CHECKS.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(TEMPLATE), use_scripts=False)
    scene = bpy.context.scene
    scene.name = "SM_Propeller"
    material = palette()
    export = bpy.data.collections["EXPORT"]
    references = bpy.data.collections["REFERENCES"]
    prop = propeller().object("Propeller", export, material)
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            view = area.spaces.active
            view.region_3d.view_distance = .51
            view.region_3d.view_location = (0, 0, 0)
            view.region_3d.view_rotation = Quaternion((1, 0, 0), math.radians(23))
            view.shading.color_type = "TEXTURE"
    bpy.context.view_layer.objects.active = prop
    prop.select_set(True)
    image = bpy.data.images.load(str(REFERENCE), check_existing=True)
    image.pack()
    guide = bpy.data.objects.new("Reference / drone_quadcopter.png", None)
    guide.empty_display_type = "IMAGE"
    guide.data = image
    guide.empty_display_size = .60
    guide.location = (0, .31, -.015)
    references.objects.link(guide)
    guide.hide_set(True)
    reference_camera = camera(scene, "Reference / front-right propeller", (-.29, -.63, .43),
                              (0, 0, -.006), .350)
    references.objects.link(reference_camera)
    scene.collection.objects.unlink(reference_camera)
    reference_camera.hide_set(True)

    if "--blockout" in sys.argv:
        for polygon in prop.data.polygons:
            for index in polygon.loop_indices:
                prop.data.uv_layers.active.data[index].uv = uv("rubber light")
        out = CHECKS / "blockout.blend"
    else:
        crack = crack_surface(prop).object("Crack", export, material)
        crack.parent = prop
        crack.hide_set(True)
        crack.hide_render = True
        crack["Usage"] = "Enable only for the damaged item"
        top = stage("Top", (1320, 700), .425, (0, 0, .75), (0, 0, 0), -.024)
        top.camera.rotation_euler = (0, 0, 0)
        duplicate(prop, top, 0)
        mounted = stage("Motor Fit", (1320, 980), .420, (.25, -.60, .38),
                        (0, 0, .012), -.061)
        fitted_motor(mounted, material)
        duplicate(prop, mounted, .070)
        out = HERE / "SM_Propeller.blend"
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = "NONE"
    bpy.ops.wm.save_as_mainfile(filepath=str(out), relative_remap=True)


def prepare_export():
    bpy.ops.wm.open_mainfile(filepath=str(HERE / "SM_Propeller.blend"), use_scripts=False)
    crack = bpy.context.scene.objects["Crack"]
    crack.hide_set(False)
    crack.hide_render = False
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = "NONE"
    bpy.ops.wm.save_as_mainfile(filepath=str(CHECKS / "SM_Propeller.export.blend"),
                              relative_remap=True)


if __name__ == "__main__":
    if "--prepare-export" in sys.argv:
        prepare_export()
    else:
        main()
