"""Install tools/blender_mcp_ext into Blender's user extension repository.

    blender --background --python tools/install_extension.py

Copies the extension into extensions/user_default/blender_mcp, refreshes the
repo, enables `bl_ext.user_default.blender_mcp`, and saves preferences.

Blender 5.x no longer scans the legacy user `scripts/addons` directory --
addon_utils.paths() returns only addons_core -- so a bl_info-style single-file
addon cannot be installed here. The extension repo is the only working target.
"""

import os
import shutil
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "blender_mcp_ext")
PKG = "blender_mcp"
MODULE = f"bl_ext.user_default.{PKG}"

repo_dir = os.path.join(bpy.utils.user_resource("EXTENSIONS", create=True), "user_default")
target = os.path.join(repo_dir, PKG)

os.makedirs(repo_dir, exist_ok=True)
if os.path.isdir(target):
    shutil.rmtree(target)
shutil.copytree(SOURCE, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
print(f"copied -> {target}")

try:
    bpy.ops.extensions.repo_refresh_all()
except Exception as exc:  # operator name varies across releases
    print(f"repo_refresh_all unavailable ({exc}); continuing")
bpy.ops.preferences.addon_refresh()

result = bpy.ops.preferences.addon_enable(module=MODULE)
if "FINISHED" not in result:
    print(f"FAILED to enable {MODULE}: {result}")
    sys.exit(1)

bpy.ops.wm.save_userpref()

import addon_utils
enabled = [m.__name__ for m in addon_utils.modules() if PKG in m.__name__]
print(f"enabled modules matching {PKG!r}: {enabled}")
print(f"registered panel: {hasattr(bpy.types, 'BLENDERMCP_PT_panel')}")
print("INSTALL_OK")
