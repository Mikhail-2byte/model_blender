"""Build SM_StationPacking from the workshop template, in Unity metres."""

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CHECKS = ROOT / ".local/checks/station-packing"
STEM = "SM_StationPacking"
PIVOTS = {
    "Table": (0, 0, 0), "Backboard": (0, 1.50, -.48),
    "SignBoard": (0, 1.92, -.44), "Lamp": (.55, 2.20, -.45),
    "TapeRoll": (-.578, .90, .14),
}
SWATCHES = {
    "shadow": (0, 0), "steel": (1, 0), "light": (2, 0),
    "ochre": (4, 0), "yellow": (5, 0), "gold": (6, 0),
    "black": (0, 1), "dark": (1, 1), "rubber": (5, 3),
    "reflect": (0, 7), "green": (5, 4),
    "paper_dark": (4, 6), "paper": (5, 6), "paper_light": (6, 6),
    "tape": (6, 5),
}
FRAME_OPEN, FRAME_CLOSED, FRAME_SEALED = 1, 121, 141
A = math.radians(120)


def basis(point):
    # The workshop FBX profile followed by Unity's importer reflects X.
    x, y, z = point
    return Vector((-x, -z, y))


def unity(point):
    x, y, z = point
    return (-x, z, -y)


def uv(paint):
    col, row = SWATCHES[paint]
    return ((col + .5) / 8, 1 - (row + .5) / 8)


def material(name, color, roughness, emission=0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = mat.diffuse_color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Emission Color"].default_value = mat.diffuse_color
    shader.inputs["Emission Strength"].default_value = emission
    return mat


def rect(w, h, clip, u=0, v=0):
    x, y = w / 2, h / 2
    if not clip:
        return [(u-x, v-y), (u+x, v-y), (u+x, v+y), (u-x, v+y)]
    return [(u+i, v+j) for i, j in [(-x+clip, -y), (x-clip, -y), (x, -y+clip),
                                   (x, y-clip), (x-clip, y), (-x+clip, y),
                                   (-x, y-clip), (-x, -y+clip)]]


def circle(radius, sides, u=0, v=0, phase=0):
    return [(u + radius * math.cos(t), v + radius * math.sin(t))
            for t in (phase + math.tau * i / sides for i in range(sides))]


def bounds(points):
    return tuple(tuple(fn(point[i] for point in points) for i in range(3))
                 for fn in (min, max))


class Parts:
    def __init__(self):
        self.vertices, self.faces, self.colors, self.smooth = [], [], [], []
        self.islands = {}

    def append(self, name, vertices, faces, colors, smooth=()):
        start = len(self.vertices)
        self.islands[name] = range(start, start + len(vertices))
        self.vertices.extend(vertices)
        self.faces.extend(tuple(start + i for i in face) for face in faces)
        self.colors.extend(colors)
        self.smooth.extend(smooth or [False] * len(faces))

    def profile(self, name, axis, rings, bands, caps, smooth=False):
        count = len(rings[0][1])
        vertices = []
        for offset, contour in rings:
            for u, v in contour:
                point = [u, v]
                point.insert(axis, offset)
                vertices.append(point)
        faces = [tuple(range(count))]
        colors = [caps[0]]
        for layer, paint in enumerate(bands):
            start = layer * count
            for i in range(count):
                a, b = start + i, start + (i + 1) % count
                faces.append((a, b, b + count, a + count))
                colors.append(paint[i] if isinstance(paint, tuple) else paint)
        faces.append(tuple(range(len(vertices) - count, len(vertices))))
        colors.append(caps[1])
        self.append(name, vertices, faces, colors, [False]+[smooth]*(len(faces)-2)+[False])

    def block(self, name, center, size, paint, *, axis=1, bevel=.01, clip=.015,
              edge=None, cap=None):
        h = size[axis]
        w, d = [value for i, value in enumerate(size) if i != axis]
        u, v = [value for i, value in enumerate(center) if i != axis]
        c = center[axis]
        edge = edge or paint
        b = min(bevel, min(size) * .28)
        if b:
            inner = rect(w-2*b, d-2*b, max(clip-b/2, .001), u, v)
            outer = rect(w, d, clip, u, v)
            rings = [(c-h/2, inner), (c-h/2+b, outer), (c+h/2-b, outer), (c+h/2, inner)]
            bands = [paint, paint, edge]
        else:
            contour = rect(w, d, clip, u, v)
            rings = [(c-h/2, contour), (c+h/2, contour)]
            bands = [paint]
        self.profile(name, axis, rings, bands, (paint, cap or paint))

    def round(self, name, center, axis, sections, bands, caps, sides=16, direction=1):
        u, v = [value for i, value in enumerate(center) if i != axis]
        rings = [(center[axis] + direction*h, circle(r, sides, u, v, math.pi/sides))
                 for h, r in sections]
        self.profile(name, axis, rings, bands, caps, smooth=sides > 6)

    def bolt(self, name, center, axis=2, direction=1, scale=1):
        self.round(name, center, axis,
                   [(h*scale, r*scale) for h, r in [(-.002,.027),(.004,.027),(.010,.022)]],
                   ["shadow", "light"], ("shadow", "reflect"), sides=6, direction=direction)

    def object(self, name, collection, pivot, mat, *, groups=True):
        origin = basis(pivot)
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([basis(point)-origin for point in self.vertices], [], self.faces)
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        obj.location = origin
        mesh.materials.append(mat)
        texcoords = mesh.uv_layers.new(name="UVMap").data
        for face, paint, smooth in zip(mesh.polygons, self.colors, self.smooth, strict=True):
            face.use_smooth = smooth
            for loop in face.loop_indices:
                texcoords[loop].uv = uv(paint)
        if groups:
            for label, indices in self.islands.items():
                obj.vertex_groups.new(name=label).add(list(indices), 1, 'REPLACE')
        return obj


def make_table(gray):
    kit = Parts()
    kit.block("Worktop", (0,.87,0), (1.40,.06,1.00), "steel",
              bevel=.014, clip=.064, edge="light", cap="light")
    kit.block("Apron", (0,.785,0), (1.32,.129,.922), "steel",
              bevel=.023, clip=.060, edge="light")
    for x in (-1, 1):
        for z in (-1, 1):
            label = f"{x:+d} {z:+d}"
            kit.profile("Leg " + label, 1,
                        [(y, rect(w,d,.020,x*u,z*v)) for y,w,d,u,v in [
                            (.071,.138,.151,.586,.383), (.13,.142,.156,.580,.381),
                            (.637,.129,.149,.526,.350), (.760,.152,.172,.528,.350)]],
                        ["shadow", "steel", "light"], ("shadow", "steel"))
            kit.profile("Safety shoe " + label, 1,
                        [(y, rect(w,d,.036,x*.591,z*.385)) for y,w,d in [
                            (0,.169,.172),(.015,.194,.204),(.072,.194,.204),(.094,.153,.158)]],
                        ["ochre", "yellow", "gold"], ("ochre", "yellow"))
    if not gray:
        kit.block("Rear stretcher", (0,.286,-.384), (1.10,.095,.083), "shadow",
                  bevel=.012, edge="steel")
        for x in (-1, 1):
            kit.block(f"Side rung {x:+d}", (x*.565,.296,0), (.087,.081,.765), "shadow",
                      bevel=.010, edge="steel")
            kit.block(f"Apron cheek {x:+d}", (x*.664,.778,0), (.043,.101,.335), "shadow",
                      axis=0, bevel=.013, clip=.027)
            for z in (-.092,.092):
                kit.bolt(f"Cheek fastener {x:+d} {z:+.3f}", (x*.685,.778,z), 0, x, .73)
            for z in (-.454,.454):
                kit.bolt(f"Apron fastener {x:+d} {z:+.3f}", (x*.531,.775,z), 2, -1 if z<0 else 1)
    return kit


def make_backboard(gray):
    kit = Parts()
    kit.block("Recessed steel sheet", (0,1.50,-.488), (1.36,1.20,.024), "steel",
              axis=2, bevel=.005, clip=.032)
    for x in (-1, 1):
        kit.block(f"Folded edge {x:+d}", (x*.655,1.50,-.48), (.090,1.20,.040), "shadow",
                  axis=2, bevel=.010, clip=.026, edge="light", cap="steel")
    kit.block("Lower return", (0,1.000,-.482), (1.30,.140,.034), "shadow",
              axis=2, bevel=.007, clip=.022, edge="steel")
    kit.block("Header rail", (0,1.943,-.476), (1.32,.270,.034), "shadow",
              axis=2, bevel=.007, clip=.024, edge="steel")
    kit.round("Beacon socket", (.55,2.098,-.45), 1,
              [(0,.091),(.009,.097),(.028,.097),(.040,.083)],
              ["shadow", "dark", "light"], ("shadow","rubber"))
    if not gray:
        for x in (-1, 1):
            for y in (.994, 1.735, 2.075):
                kit.bolt(f"Panel fastener {x:+d} {y:.3f}", (x*.652,y,-.461), scale=.72)
    return kit


def make_sign():
    kit = Parts()
    kit.profile("Recessed display", 2,
                [(z, rect(w,h,clip,0,1.92)) for z,w,h,clip in [
                    (-.462,1.316,.286,.035),(-.455,1.350,.320,.044),
                    (-.426,1.350,.320,.044),(-.416,1.326,.296,.040),
                    (-.416,1.266,.236,.029),(-.432,1.240,.210,.026)]],
                ["shadow", "shadow", "light", "steel", "black"], ("shadow","dark"))
    return kit


def make_lamp():
    kit = Parts()
    x, y, z = PIVOTS["Lamp"]
    sides, rows, radius = 16, 10, .1
    vertices = [(x,y-radius,z)]
    for i in range(1,rows):
        angle = -math.pi/2 + math.pi*i/rows
        vertices.extend((u,y + radius*math.sin(angle),v)
                        for u,v in circle(radius*math.cos(angle),sides,x,z))
    top = len(vertices)
    vertices.append((x,y+radius,z))
    faces = []
    for j in range(sides):
        k = (j+1) % sides
        faces.extend([(0,1+j,1+k),(top,top-sides+k,top-sides+j)])
        for i in range(rows-2):
            a, b = 1+i*sides+j, 1+i*sides+k
            faces.append((a,b,b+sides,a+sides))
    kit.append("Lens", vertices, faces, ["green"]*len(faces), [True]*len(faces))
    return kit


def make_roll():
    kit = Parts()
    x, y, z = PIVOTS["TapeRoll"]
    rings = [(h,r) for h,r in [(0,.063),(0,.036),(.005,.032),(.039,.032),(.043,.036),
                               (.043,.060),(.039,.070),(.033,.073),(.006,.073)]]
    sides = 20
    vertices = [(u,y+h,v) for h,r in rings for u,v in circle(r,sides,x,z)]
    paints = ["paper_dark","paper_light","paper_dark","paper_light","tape",
              "paper_light","tape","paper","paper_dark"]
    faces, colors, smooth = [], [], []
    for layer, paint in enumerate(paints):
        for i in range(sides):
            j, following = (i+1)%sides, ((layer+1) % len(rings))*sides
            faces.append((layer*sides+i,layer*sides+j,following+j,following+i))
            colors.append(paint)
            smooth.append(layer in (2, 7))
    kit.append("Hollow tape and cardboard core", vertices, faces, colors, smooth)
    return kit


def empty(name, collection, position, display='PLAIN_AXES'):
    obj = bpy.data.objects.new(name, None)
    collection.objects.link(obj)
    obj.location = basis(position)
    obj.empty_display_type = display
    obj.empty_display_size = .035
    return obj


def make_box(collection, palette):
    pivot = (0,.90,.10)
    root = empty("BoxBottom · (0, 0.90, 0.10)", collection, pivot)
    root["Purpose"] = "Preview only. Timeline: 1 open, 121 closed, 141 sealed."
    body = Parts()
    body.block("Floor", (0,.91,.10), (.72,.02,.72), "paper_dark", clip=0, bevel=0)
    for sign in (-1, 1):
        body.block(f"Side {sign:+d}", (sign*.35,1.12,.1), (.02,.40,.68), "paper",
                   bevel=.003, clip=.004, edge="paper_light")
        body.block(f"End {sign:+d}", (0,1.12,.1+sign*.35), (.72,.40,.02), "paper",
                   bevel=.003, clip=.004, edge="paper_light")
    obj = body.object("TestBox", collection, pivot, palette)
    obj.parent, obj.location = root, Vector((0,0,0))
    flaps = []
    for name, (dx,dz) in {"Front":(0,-1),"Rear":(0,1),"Left":(1,0),"Right":(-1,0)}.items():
        hinge = (-.36*dx,1.32,.10-.36*dz)
        center = (hinge[0]+.18*dx,1.32+(.015 if dz else .005),hinge[2]+.18*dz)
        kit = Parts()
        kit.block(name, center, (.36 if dx else .72,.01,.36 if dz else .72), "paper",
                  bevel=.001, clip=.002, edge="paper_light", cap="paper_light")
        flap = kit.object("Flap_"+name, collection, hinge, palette, groups=False)
        flap.parent, flap.location = root, basis(hinge)-basis(pivot)
        inward = basis((dx,0,dz))
        axis = inward.cross(Vector((0,0,1)))
        flap.rotation_mode = 'AXIS_ANGLE'
        for frame, angle in ((FRAME_OPEN,A),(FRAME_CLOSED,0)):
            flap.rotation_axis_angle = (angle, *axis)
            flap.keyframe_insert(data_path="rotation_axis_angle", frame=frame)
        flaps.append((flap, hinge, dx, dz, kit.vertices))

    kit = Parts()
    kit.block("Applied tape", (0,1.345,.10), (.74,.008,.12), "tape",
              bevel=.001, clip=.002, cap="tape")
    tape_pivot = (-.37,1.345,.10)
    tape = kit.object("TestTape", collection, tape_pivot, palette)
    tape.parent, tape.location = root, basis(tape_pivot)-basis(pivot)
    for frame, active in ((FRAME_OPEN,False),(FRAME_CLOSED,False),
                          (FRAME_CLOSED+1,True),(FRAME_SEALED,True)):
        tape.hide_render = tape.hide_viewport = not active
        tape.scale.x = 1 if frame == FRAME_SEALED else .04
        for prop in ("hide_render", "hide_viewport", "scale"):
            tape.keyframe_insert(data_path=prop, frame=frame)
    for part in [flap[0] for flap in flaps] + [tape]:
        action = part.animation_data.action
        for channel in action.layers[0].strips[0].channelbag(part.animation_data.action_slot).fcurves:
            for key in channel.keyframe_points:
                key.interpolation = 'LINEAR'
    return flaps, tape


def extrema(c, s):
    # Extrema of c*cos(t) + s*sin(t) over the entire closed-to-open interval.
    critical = math.atan2(s,c)
    angles = [0,A] + [t for t in (critical-math.pi,critical,critical+math.pi) if 0<t<A]
    return [c*math.cos(t)+s*math.sin(t) for t in angles]


def flap_envelope(hinge, dx, dz, vertices):
    x, y, z = hinge
    heights, distances = [], []
    for vx, vy, vz in vertices:
        span = (vx-x)*dx + (vz-z)*dz
        height = vy-y
        heights.extend(y+t for t in extrema(height, span))
        distances.extend(extrema(span,-height))
    return bounds([(x+dx*t if dx else vx, h, z+dz*t if dz else vz)
                   for vx, _, vz in vertices for h in (min(heights),max(heights))
                   for t in (min(distances),max(distances))])


def separation(a, b):
    return max(max(i-l,k-j) for i,j,k,l in zip(*a,*b, strict=True))


def check_clearance(kits, flaps):
    pieces = {f"{name}/{label}": bounds([kit.vertices[i] for i in indices])
              for name, kit in kits.items() for label, indices in kit.islands.items()}
    envelopes = {flap.name: flap_envelope(hinge, dx, dz, vertices)
                 for flap, hinge, dx, dz, vertices in flaps}
    clearance = {}
    for name, swept in envelopes.items():
        gap, nearest = min((separation(swept, bb), label) for label, bb in pieces.items())
        assert gap > .005, (name, nearest, gap)
        clearance[name] = {"swept_bounds_m": swept, "separation_lower_bound_m": gap,
                           "limiting_station_part": nearest}
    # Full box footprint and all stations parts, with contact at the worktop allowed.
    for name, volume in {
        "vertical insertion and pickup": ((-.37,.90,-.26),(.37,3.0,.46)),
        "forward pickup": ((-.37,.90,-.26),(.37,1.36,1.50)),
        "progress bar": ((-.60,1.575,-.450),(.60,1.665,.50)),
    }.items():
        gap, nearest = min((separation(volume, bb), label) for label, bb in pieces.items())
        assert gap >= (-1e-7 if "pickup" in name else .005), (name, nearest, gap)
        clearance[name] = {"separation_lower_bound_m": gap, "limiting_station_part": nearest}
    return clearance


def camera(scene, collection, name, loc, focus, scale):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = basis(loc)
    obj.rotation_euler = (basis(focus)-obj.location).to_track_quat('-Z','Y').to_euler()
    data.type = 'ORTHO'
    data.ortho_scale = scale
    return obj


def studio(scene, collection, gray):
    floor = Parts()
    floor.block("Floor", (0,-.04,0), (200,.078,200), "shadow", bevel=0, clip=0)
    ground = floor.object("Studio floor", collection, (0,0,0),
                          material("Preview floor", (.052,.064,.095), .81))
    ground.hide_set(True)  # Keep the interactive modeling viewport clean.
    for name, loc, power, size, color in [
        ("Key", (-3.5,5.2,4.0), 700, 3.5, (1,.89,.74)),
        ("Fill", (4,3.4,3.0), 450, 4.0, (.69,.82,1)),
        ("Rim", (1,4,-3.7), 850, 2.7, (.76,.85,1)),
    ]:
        lamp = bpy.data.lights.new(name, 'AREA')
        lamp.energy, lamp.size, lamp.color = power, size, color
        obj = bpy.data.objects.new(name, lamp)
        collection.objects.link(obj)
        obj.location = basis(loc)
        obj.rotation_euler = (basis((0,1,0))-obj.location).to_track_quat('-Z','Y').to_euler()
        obj.hide_set(True)
    scene.world = bpy.data.worlds.new("Studio ambient")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.30,.35,.46,1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .34
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'AgX - Medium High Contrast'
    scene.render.engine = 'BLENDER_WORKBENCH' if gray else 'CYCLES'
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.resolution_percentage = 100
    scene.render.resolution_x, scene.render.resolution_y = ((550,550) if gray else (1120,1120))
    scene.display.shading.color_type = 'SINGLE'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = 'BOTH'
    front = camera(scene, collection, "Front · sealed", (0,2.47,4.45), (0,1.15,0), 2.83)
    top = camera(scene, collection, "Upper angle · open", (-2.9,3.6,3.75), (0,1.12,0), 2.88)
    front.hide_set(True)
    top.hide_set(True)
    return front, top


def check_tape(scene, front, tape):
    scene.frame_set(FRAME_SEALED)
    direction = front.rotation_euler.to_matrix() @ Vector((0,0,-1))
    dg = bpy.context.evaluated_depsgraph_get()
    hits = []
    for x in (-.32,-.24,-.16,-.08,0,.08,.16,.24,.32):
        for z in (.06,.10,.14):
            target = basis((x,1.34899,z))
            hit = scene.ray_cast(dg, target - 3*direction, direction)
            assert hit[4] == tape, (x,z,hit[4])
            hits.append((x,z))
    return len(hits)


def main():
    gray = '--blockout' in sys.argv
    CHECKS.mkdir(parents=True, exist_ok=True)
    template = ROOT / 'ArtSource/Blender/DRONEWORKS.blend'
    bpy.ops.wm.open_mainfile(filepath=str(template))
    scene = bpy.context.scene
    export = bpy.data.collections['EXPORT']
    staging = bpy.data.collections['REFERENCES']
    for obj in list(staging.all_objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    fixture = bpy.data.collections.new('TEST · Box and gameplay anchors')
    staging.children.link(fixture)
    preview = bpy.data.collections.new('PREVIEW · Lighting and cameras')
    scene.collection.children.link(preview)
    palette = bpy.data.materials['DRONEWORKS_Palette']
    palette.use_fake_user = True
    shader = palette.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Roughness'].default_value = .56
    shader.inputs['Specular IOR Level'].default_value = .33
    palette.diffuse_color = (.19,.22,.33,1)
    palette.node_tree.nodes.active = next(node for node in palette.node_tree.nodes if node.type == 'TEX_IMAGE')
    lamp_mat = material('DRONEWORKS_Packing_Lamp', (.045,.67,.10), .26, .40)
    kits = {"Table":make_table(gray),"Backboard":make_backboard(gray),
            "SignBoard":make_sign(),"Lamp":make_lamp()}
    if not gray:
        kits['TapeRoll'] = make_roll()
    objects = {name:kit.object(name, export, PIVOTS[name], lamp_mat if name=='Lamp' else palette)
               for name,kit in kits.items()}
    for name,obj in objects.items():
        if name != 'Table':
            obj.parent = objects['Table']
    flaps, tape = make_box(fixture, palette)
    empty('BoxPoint · (0, 1.12, 0.10)', fixture, (0,1.12,.10))
    empty('ProgressBar · (0, 1.62, −0.44)', fixture, (0,1.62,-.44))
    scene.frame_start, scene.frame_end = FRAME_OPEN, FRAME_SEALED
    for label, frame in [("Open · 120°",FRAME_OPEN),("Closed",FRAME_CLOSED),("Sealed",FRAME_SEALED)]:
        scene.timeline_markers.new(label, frame=frame)
    front, top = studio(scene, preview, gray)
    outset = CHECKS if gray else HERE
    report = {"clearance":check_clearance(kits, flaps),
              "visible_tape_ray_samples":check_tape(scene, front, tape),
              "profile": "blockout" if gray else "final"}
    (CHECKS / ('blockout.json' if gray else 'clearance.json')).write_text(
        json.dumps(report, indent=2), encoding='utf-8')
    scene.camera = top
    scene.frame_set(FRAME_OPEN)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = objects['Table']
    for workspace in bpy.data.workspaces:
        for screen in workspace.screens:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    view = area.spaces.active
                    view.region_3d.view_rotation = top.rotation_euler.to_quaternion()
                    view.region_3d.view_distance = 3.7
                    view.region_3d.view_location = basis((0,1.15,0))
                    view.region_3d.view_perspective = 'ORTHO'
                    view.overlay.show_extras = False
                    view.shading.color_type = 'TEXTURE'
    scene.render.filepath = '//SM_StationPacking_Open.png'
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = 'NONE'
    blend = outset / (STEM + ('.blockout.blend' if gray else '.blend'))
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), relative_remap=True)
    for current, frame, view in ((front,FRAME_SEALED,'Front'), (top,FRAME_OPEN,'Open')):
        scene.camera = current
        scene.frame_set(frame)
        scene.render.filepath = str(outset / (f'Blockout_{view}.png' if gray else f'{STEM}_{view}.png'))
        bpy.ops.render.render(write_still=True)


if __name__ == '__main__':
    main()
