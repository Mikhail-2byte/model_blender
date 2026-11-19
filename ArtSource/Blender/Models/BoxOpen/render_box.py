"""Render the open and sealed previews from SM_BoxOpen.blend."""

import math
from pathlib import Path

import bpy
from mathutils import Quaternion


HERE = Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(HERE/"SM_BoxOpen.blend"))
scene = bpy.data.scenes["On packing table"]
bpy.context.window.scene = scene
for view, camera in (("Open", "Open · drone fit"), ("Sealed", "Sealed · tape and print")):
    if view == "Sealed":
        for obj in scene.collection.children["BoxOpen · Posed instance"].objects:
            if obj.name.startswith("Preview_Flap_"):
                obj.rotation_quaternion @= Quaternion((1, 0, 0), math.radians(120))
        tape = scene.objects["Preview_Tape"]
        tape.hide_render = False
        tape.hide_set(False)
    scene.camera = scene.objects[camera]
    scene.render.filepath = str(HERE/f"SM_BoxOpen_{view}.png")
    bpy.ops.render.render(write_still=True)
