#!/usr/bin/env python3
"""Deterministic tests without LanZouCloud login, network or device access."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace as N

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lanzou_display_names import MODEL_NAMES, display_filename, folder_name
import lanzou_migrate_display_20261009 as migrate

assert len(MODEL_NAMES) == 57
assert len(set(MODEL_NAMES.values())) == 57
assert folder_name("OnePlusAce5Race") == "一加Ace5竞速版"

samples = [
    ("6.1.157_OnePlusAce5Race_Android16.0.0_SukiSU40959_KPM_ILH_run37884290075.zip",
     "Android16.0.0_Kernel6.1.157_OnePlusAce5Race_SukiSU40959_KPM_ILH_run37884290075.zip"),
    ("6.6.118_OnePlus13_Android16.0.0_SukiSU40959_KPM_ILH_HMBIRD_run37615216318.zip",
     "Android16.0.0_HMBIRD_Kernel6.6.118_OnePlus13_SukiSU40959_KPM_ILH_HMBIRD_run37615216318.zip"),
    ("6.6.118_OnePlus13_Android16.0.0_SukiSU40959_KPM_ILH_run37888241390.zip",
     "Android16.0.0_Kernel6.6.118_OnePlus13_SukiSU40959_KPM_ILH_run37888241390.zip"),
    ("6.1.118_OnePlusPadPro_Android15.0.0_SukiSU40959_KPM_ILH_run37630818892.zip",
     "Android15.0.0_Kernel6.1.118_OnePlusPadPro_SukiSU40959_KPM_ILH_run37630818892.zip"),
    ("6.1.118_OnePlusPadPro_Android16.0.0_SukiSU40959_KPM_ILH_run37888245161.zip",
     "Android16.0.0_Kernel6.1.118_OnePlusPadPro_SukiSU40959_KPM_ILH_run37888245161.zip"),
    ("6.6.118_OnePlusAce5Pro_Android16.0.0_SukiSU40959_KPM_ILH_HMBIRD_run37630854781.zip",
     "Android16.0.0_HMBIRD_Kernel6.6.118_OnePlusAce5Pro_SukiSU40959_KPM_ILH_HMBIRD_run37630854781.zip"),
]
for old, expected in samples:
    assert display_filename(old) == expected
    assert display_filename(expected) == expected
for wrong in ["random.zip", "6.1.118_OnePlusUnmapped_Android16.0.0_SukiSU40959_KPM_ILH_run1.zip",
              "Android16.0.0_HMBIRD_Kernel6.6.118_OnePlus13_SukiSU40959_KPM_ILH_run11.zip"]:
    try:
        display_filename(wrong)
        raise AssertionError("Unverifiable filename accepted")
    except ValueError:
        pass
print("PASS: 57 unique folder labels and 6 representative exact filename transformations", flush=True)

# Recovery of filenames modified by the earlier Chinese ZIP migration.
for old, expected in [
    ("安卓16.0.0_常规_内核6.1.157_OnePlusAce5Race_SukiSU40959_KPM_ILH_run37884290075.zip",samples[0][1]),
    ("安卓16.0.0_风驰_内核6.6.118_OnePlus13_SukiSU40959_KPM_ILH_HMBIRD_run37615216318.zip",samples[1][1]),
    ("安卓16.0.0_常规_内核6.6.118_OnePlus13_SukiSU40959_KPM_ILH_run37888241390.zip",samples[2][1]),
]:
    assert display_filename(old) == expected
    assert expected.isascii()
print("PASS: already-renamed Chinese ZIP names convert back to ASCII safely", flush=True)


lanzou = types.ModuleType("lanzou")
api = types.ModuleType("lanzou.api")
class SDK:
    SUCCESS=0
    FAILED=-1
api.LanZouCloud=SDK
sys.modules["lanzou"]=lanzou
sys.modules["lanzou.api"]=api

class Cloud:
    def __init__(self, deny_file=False, deny_folder=False, folder_conflict=False):
        self.deny_file=deny_file
        self.deny_folder=deny_folder
        self.folders = {-1:[N(id=10,name="一加suki")],10:[N(id=11,name="suki-40959")],
                        11:[N(id=12,name="OnePlusAce5Race"),N(id=13,name="OnePlus13"),N(id=14,name="OnePlusPadPro")]}
        if folder_conflict:
            self.folders[11].append(N(id=20,name="一加Ace5竞速版"))
        self.files = {
            12:[N(id=101,name=samples[0][0],size="18MB"),N(id=999,name="private.txt",size="1K")],
            13:[N(id=102,name=samples[1][0],size="18MB"),N(id=103,name=samples[2][0],size="18MB")],
            14:[N(id=104,name=samples[3][0],size="18MB"),N(id=105,name=samples[4][0],size="18MB")],
        }
        self.actions=[]
    def get_dir_list(self,parent): return self.folders.get(parent,[])
    def get_file_list(self,parent): return self.files.get(parent,[])
    def login_by_cookie(self,cookie): return 0
    def rename_file(self,file_id,stem):
        self.actions.append(("file",file_id,stem))
        if self.deny_file:return -1
        for f in [x for group in self.files.values() for x in group]:
            if f.id==file_id:
                f.name=stem+".zip"
                return 0
        return -1
    def rename_dir(self,folder_id,target):
        self.actions.append(("folder",folder_id,target))
        if self.deny_folder:return -1
        for entry in self.folders[11]:
            if entry.id==folder_id:
                entry.name=target
                return 0
        return -1

client=Cloud()
files,folders,skipped=migrate.plan(client,"all")
assert len(files)==5,files
assert len(folders)==3,folders
assert not skipped
assert client.actions==[]
assert len(migrate.plan(client,"OnePlusAce5Race")[0])==1
assert len(migrate.plan(client,"OnePlusAce5Race")[1])==1

with tempfile.TemporaryDirectory() as td:
    migrate.REPORT=Path(td)/"receipt.json"
    migrate.make_secure_client=lambda:client
    migrate.auth_cookies=lambda:{"ylogin":"123456","phpdisk_info":"unit-test"}
    sys.argv=["script","--dry-run"]
    assert migrate.main()==0
    assert not client.actions
    assert json.loads(migrate.REPORT.read_text())["status"]=="preview_ok"

    sys.argv=["script"]
    assert migrate.main()==0
    rec=json.loads(migrate.REPORT.read_text())
    assert rec["status"]=="completed" and len(rec["files"])==5 and len(rec["folders"])==3
    assert client.files[12][0].name==samples[0][1] and client.files[12][1].name=="private.txt"
    assert client.folders[11][0].name=="一加Ace5竞速版"
    assert all(k["readback"]=="same_id_and_children" for k in rec["folders"])
    assert migrate.plan(client,"all")[0]==[] and migrate.plan(client,"all")[1]==[]
    print("PASS: dry-run, per-file renames, Chinese model folders, same IDs and child inventory",flush=True)

    denied=Cloud(deny_file=True)
    migrate.make_secure_client=lambda:denied
    assert migrate.main()==1
    assert len(denied.actions)==1 and denied.actions[0][0]=="file"
    assert denied.folders[11][0].name=="OnePlusAce5Race"
    print("PASS: file rename rejected, no attempted folder rename",flush=True)

    denied=Cloud(deny_folder=True)
    migrate.make_secure_client=lambda:denied
    assert migrate.main()==1
    assert denied.folders[11][0].name=="OnePlusAce5Race"
    assert json.loads(migrate.REPORT.read_text())["status"]=="stopped_folder_rename"
    print("PASS: folder rename rejected; exact failure receipt, no folder deletion",flush=True)

    collide=Cloud(folder_conflict=True)
    migrate.make_secure_client=lambda:collide
    assert migrate.main()==1 and not collide.actions
    print("PASS: duplicate target folder causes zero mutations",flush=True)
