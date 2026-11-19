"""Build the packing box from DRONEWORKS.blend. -- --blockout builds the fit model."""

import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Quaternion, Vector


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CHECKS = ROOT / ".local/checks/box-open"
TEMPLATE = ROOT / "ArtSource/Blender/DRONEWORKS.blend"
STATION = HERE.parent / "StationPacking/SM_StationPacking.blend"
DECAL = HERE / "T_BoxOpen_Decal.png"
BOX_POINT = (0, .90, .10)
FLAPS = {"N": ((0, .42, .36), 180), "S": ((0, .42, -.36), 0),
         "E": ((.36, .42, 0), 90), "W": ((-.36, .42, 0), -90)}
STATION_PARTS = ("Table", "Backboard", "SignBoard", "Lamp", "TapeRoll")
PAINT = {"carton": (5, 6), "fold": (4, 6), "cut": (6, 6), "tape": (6, 5)}
BLOCKOUT = "--blockout" in sys.argv


def basis(point):
    x, up, forward = point
    return Vector((-x, -forward, up))


def mesh_object(name, vertices, faces, collection):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def block(name, collection, center, size, bevel=0, segments=1):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1)
    for vert in bm.verts:
        vert.co = tuple(a*b for a, b in zip(vert.co, size, strict=True))
    if bevel:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=segments,
                        affect="EDGES")
    data = bpy.data.meshes.new(name)
    bm.to_mesh(data)
    bm.free()
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = center
    return obj


def palette_uv(obj, palette, colors):
    obj.data.materials.append(palette)
    uv = obj.data.uv_layers.new(name="UVMap")
    for face, tone in zip(obj.data.polygons, colors, strict=True):
        col, row = PAINT[tone]
        for loop in face.loop_indices:
            uv.data[loop].uv = ((col+.5)/8, 1-(row+.5)/8)


def solid_color(name, color, roughness):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def decal_material():
    # Apply the workshop's fleet wordmark as one-color ink on kraft paper.
    sys.path.insert(0, str(HERE.parent / "Truck"))
    from build_truck import logo_image

    stencil = logo_image()
    rgba = np.empty(len(stencil.pixels), dtype=np.float32)
    stencil.pixels.foreach_get(rgba)
    rgba = rgba.reshape((-1, 4))
    rgba[:, :3] = (.048, .026, .014)
    image = bpy.data.images.new(DECAL.name, *stencil.size, alpha=True, float_buffer=True)
    image.pixels.foreach_set(rgba.ravel())
    bpy.data.images.remove(stencil)
    image.filepath_raw = str(DECAL)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    image = bpy.data.images.load(str(DECAL))
    image.pack()
    mat = solid_color("DRONEWORKS_BoxDecal", (.048, .026, .014), .85)
    tree = mat.node_tree
    node = tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    node.extension = "CLIP"
    tree.nodes.active = node
    bsdf = tree.nodes["Principled BSDF"]
    tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
    tree.links.new(node.outputs["Alpha"], bsdf.inputs["Alpha"])
    return mat


def add_logo(wall, collection, mat):
    w, h = .185, .185*400/768
    y = wall.location.y - .01018
    vertices = [(-w,y,.222-h), (w,y,.222-h), (w,y,.222+h), (-w,y,.222+h)]
    obj = mesh_object("Front print", vertices, [(0,1,2,3)], collection)
    obj.data.materials.append(mat)
    uv = obj.data.uv_layers.new(name="UVMap")
    for loop in obj.data.loops:
        uv.data[loop.index].uv = ((0,0), (1,0), (1,1), (0,1))[loop.vertex_index]
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    wall.select_set(True)
    bpy.context.view_layer.objects.active = wall
    bpy.ops.object.join()


def flap(name, collection, location, yaw, palette):
    lower, upper = (.4307-.42, .441-.42) if name in ("N", "S") else (.0004, .0104)
    stations = [
        (0, .3584, .0011), (.0015, .36, 0), (.0065, .36, 0),
        (.0086, .36, .0008), (.0107, .36, 0),
        (.3568, .36, 0), (.36, .3568, .0011),
    ]
    if BLOCKOUT:
        stations = [(0, .36, 0), (.36, .36, 0)]
    vertices = []
    for span, width, inset in stations:
        lo, hi = lower+inset, upper-inset
        k = .0007
        section = [(-width,lo+k), (-width+k,lo), (width-k,lo), (width,lo+k),
                   (width,hi-k), (width-k,hi), (-width+k,hi), (-width,hi-k)]
        vertices.extend((x, -span, up) for x, up in section)
    faces = [tuple(reversed(range(8)))]
    colors = ["fold"]
    for ring in range(len(stations)-1):
        for j in range(8):
            a, b = ring*8+j, ring*8+(j+1)%8
            faces.append((a, b, b+8, a+8))
            if ring in (2, 3) and j in (1, 5):
                colors.append("fold" if ring == 2 else "carton")
            else:
                colors.append("cut" if j in (3, 7) else "carton")
    last = (len(stations)-1)*8
    faces.append(tuple(range(last, last+8)))
    colors.append("cut")
    obj = mesh_object("Flap_"+name, vertices, faces, collection)
    obj.location = basis(location)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Quaternion((0, 0, 1), math.radians(yaw))
    palette_uv(obj, palette, colors)
    return obj


def build_box(collection, palette):
    soften = 0 if BLOCKOUT else .0017
    bottom = block("Bottom", collection, (0, 0, 0), (.72, .72, .02), soften)
    for v in bottom.data.vertices:
        v.co.z += .01
    palette_uv(bottom, palette, ["carton"]*len(bottom.data.polygons))
    for side, x, forward in [("N",0,.35), ("S",0,-.35), ("E",.35,0), ("W",-.35,0)]:
        width, depth = (.72,.02) if forward else (.02,.68)
        wall = block("Wall_"+side, collection, basis((x,.22,forward)),
                     (width,depth,.40), soften)
        wall.parent = bottom
        palette_uv(wall, palette, [
            "carton" if abs(p.normal.z) < .3 else "fold" if p.normal.z < 0 else "carton"
            for p in wall.data.polygons
        ])
        if side == "N" and not BLOCKOUT:
            add_logo(wall, collection, decal_material())
    for side, (point, angle) in FLAPS.items():
        flap(side, collection, point, angle, palette).parent = bottom
    tape = block("Tape", collection, basis((-.37,.445,0)), (.74,.12,.008), soften*.55)
    for v in tape.data.vertices:
        v.co.x -= .37
    tape.parent = bottom
    palette_uv(tape, palette, ["tape"]*len(tape.data.polygons))
    return bottom


def fixture_drone(collection):
    root = bpy.data.objects.new("TestDrone_073x035x073", None)
    collection.objects.link(root)
    root.location = basis((0, .92, .10))
    root.scale = (.9,)*3
    shell = solid_color("Fixture · pearl shell", (.40,.43,.49), .33)
    frame = solid_color("Fixture · graphite frame", (.046,.056,.079), .47)
    alloy = solid_color("Fixture · motor alloy", (.22,.26,.35), .31)
    signal = solid_color("Fixture · amber trim", (.86,.38,.024), .42)
    glass = solid_color("Fixture · camera lens", (.025,.17,.27), .19)

    def box(name, p, size, radius, material, angle=0):
        x, up, forward = size
        obj = block(name, collection, basis(p), (x,forward,up), radius, 2)
        obj.parent = root
        obj.rotation_euler.z = angle
        obj.data.materials.append(material)
        return obj

    def cylinder(name, p, radius, height, mat):
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=16,
                              radius1=radius, radius2=radius, depth=height)
        data = bpy.data.meshes.new(name)
        bm.to_mesh(data)
        bm.free()
        obj = bpy.data.objects.new(name, data)
        collection.objects.link(obj)
        obj.parent = root
        obj.location = basis(p)
        obj.data.materials.append(mat)
        return obj

    box("Drone chassis", (0,.196,0), (.182,.116,.33), .026, frame)
    box("Drone top shell", (0,.265,-.016), (.174,.083,.285), .026, shell)
    box("Drone upper spine", (0,.307,-.022), (.098,.012,.214), .005, alloy)
    box("Drone nose trim", (0,.178,.135), (.157,.024,.034), .008, signal)
    box("Drone camera housing", (0,.153,.155), (.09,.064,.065), .014, frame)
    lens = cylinder("Drone camera lens", (0,.153,.190), .022, .009, glass)
    lens.rotation_euler.x = math.pi/2
    for x in (-1, 1):
        for z in (-1, 1):
            suffix = f" {x:+d}{z:+d}"
            box("Drone motor arm"+suffix, (.145*x,.209,.145*z), (.246,.042,.049),
                .007, frame, math.pi/4*x*z)
            box("Drone foot"+suffix, (.081*x,.079,.087*z), (.035,.158,.048),
                .008, frame, math.pi/4*x*z)
            p = (.228*x, .279, .228*z)
            cylinder("Drone motor"+suffix, p, .043, .062, alloy)
            cylinder("Drone motor band"+suffix, (p[0],.252,p[2]), .044, .013, signal)
            cylinder("Drone propeller hub"+suffix, (p[0],.333,p[2]), .020, .034, frame)
            # Each pair reaches the .365 m footprint on one axis. All four share its envelope.
            horizontal = x*z > 0
            for d in (-1, 1):
                px = p[0]+.078*d if horizontal else p[0]
                pz = p[2] if horizontal else p[2]+.078*d
                dims = (.118,.009,.033) if horizontal else (.033,.009,.118)
                box("Drone propeller blade"+suffix, (px,.326,pz), dims, .004, frame)
                tx = p[0]+.129*d if horizontal else p[0]
                tz = p[2] if horizontal else p[2]+.129*d
                dims = (.016,.010,.03) if horizontal else (.03,.010,.016)
                box("Drone propeller tip"+suffix, (tx,.326,tz), dims, .002, signal)
    return root


def load_station(collection):
    with bpy.data.libraries.load(str(STATION)) as (source, target):
        target.objects = [name for name in STATION_PARTS if name in source.objects]
    if {obj.name for obj in target.objects} != set(STATION_PARTS):
        raise RuntimeError("StationPacking mesh names differ from the preview contract")
    for obj in target.objects:
        collection.objects.link(obj)


def camera(collection, name, pos, focus, scale):
    data = bpy.data.cameras.new(name)
    data.type = "ORTHO"
    data.ortho_scale = scale
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = basis(pos)
    obj.rotation_euler = (basis(focus)-obj.location).to_track_quat("-Z","Y").to_euler()
    return obj


def make_preview(asset, bottom):
    scene = bpy.data.scenes.new("On packing table")
    bpy.context.window.scene = scene
    fixtures = bpy.data.collections.new("REFERENCES · Test drone and packing table")
    posed = bpy.data.collections.new("BoxOpen · Posed instance")
    studio = bpy.data.collections.new("PREVIEW · Cameras and lights")
    for collection in (fixtures, posed, studio):
        scene.collection.children.link(collection)
    if STATION.is_file():
        load_station(fixtures)
    fixture_drone(fixtures)
    copies = {}
    for source in asset.collection.children["EXPORT"].objects:
        copy = source.copy()
        copy.name = "Preview_"+source.name
        posed.objects.link(copy)
        copies[source.name] = copy
    root = copies[bottom.name]
    root.location = basis(BOX_POINT)
    for name, obj in copies.items():
        if obj != root:
            obj.parent = root
        if name.startswith("Flap_"):
            obj.rotation_quaternion @= Quaternion((1, 0, 0), math.radians(-120))
    copies["Tape"].hide_render = True
    copies["Tape"].hide_set(True)

    floor = block("Studio floor", studio, (0,0,-.054), (200,200,.10))
    floor.data.materials.append(solid_color("Studio · blue slate", (.082,.105,.15), .82))
    for name, pos, power, size, color in [
        ("Key · warm softbox", (-2,4.0,2.3), 390, 2.4, (1,.87,.73)),
        ("Fill · cool softbox", (2.2,3.4,1.5), 310, 2.7, (.76,.87,1)),
        ("Rim · overhead", (-.5,4.2,-1.65), 490, 2.0, (.86,.91,1)),
    ]:
        data = bpy.data.lights.new(name, "AREA")
        data.energy, data.size, data.color = power, size, color
        obj = bpy.data.objects.new(name, data)
        studio.objects.link(obj)
        obj.location = basis(pos)
        obj.rotation_euler = (basis((0,1.26,.1))-obj.location).to_track_quat("-Z","Y").to_euler()
    scene.camera = camera(studio, "Open · drone fit", (1.28,3.75,1.65), (0,1.295,.075), 1.78)
    camera(studio, "Sealed · tape and print", (1.60,2.65,2.43), (0,1.15,.11), 1.32)
    scene.world = bpy.data.worlds.new("Box studio ambient")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes["Background"]
    background.inputs["Color"].default_value = (.35,.43,.55,1)
    background.inputs["Strength"].default_value = .32
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -.26
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 1280, 1080
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 6
    return scene


def main():
    bpy.ops.wm.open_mainfile(filepath=str(TEMPLATE))
    asset = bpy.context.scene
    asset.name = "SM_BoxOpen · Export"
    asset.unit_settings.system = "METRIC"
    asset.unit_settings.scale_length = 1
    for obj in list(bpy.data.collections["REFERENCES"].all_objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    palette = bpy.data.materials["DRONEWORKS_Palette"]
    palette.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = .70
    bottom = build_box(bpy.data.collections["EXPORT"], palette)
    preview = make_preview(asset, bottom)
    if BLOCKOUT:
        bpy.context.window.scene = preview
        preview.render.engine = "BLENDER_WORKBENCH"
        preview.render.resolution_percentage = 44
        preview.display.shading.light = "STUDIO"
        preview.display.shading.show_cavity = True
        preview.render.filepath = str(CHECKS / "blockout.png")
        bpy.ops.render.render(write_still=True)
        out = CHECKS / "SM_BoxOpen.blockout.blend"
    else:
        out = HERE / "SM_BoxOpen.blend"
    bpy.context.window.scene = asset
    asset_camera = preview.camera.rotation_euler.to_quaternion()
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                view = area.spaces.active
                view.region_3d.view_location = (0,0,.20)
                view.region_3d.view_rotation = asset_camera
                view.region_3d.view_distance = 1.60
                view.region_3d.view_perspective = "ORTHO"
                view.shading.color_type = "TEXTURE"
                view.overlay.show_floor = False
                view.overlay.show_axis_x = False
                view.overlay.show_axis_y = False
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = bottom
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = "NONE"
    bpy.ops.wm.save_as_mainfile(filepath=str(out), relative_remap=True)


if __name__ == "__main__":
    main()
