"""Visible model-folder names and filename ordering for OnePlus SukiSU releases.

The English model key comes from the project's existing build profile;
the public folder is localized without changing any kernel or archive bytes.
Where an official Chinese device name is unclear, preserve the model family,
chipset marker or Canary suffix instead of guessing a different device.
"""
from __future__ import annotations

import re

# Only verified build profile names; no fuzzy guessing or automatic
# substitutions of similar models.
MODEL_NAMES = {
    "OnePlus10Pro": "一加10Pro",
    "OnePlus10r": "一加10R",
    "OnePlus10t": "一加10T",
    "OnePlus11": "一加11",
    "OnePlus11r": "一加11R",
    "OnePlus12": "一加12",
    "OnePlus12r": "一加12R",
    "OnePlus13": "一加13",
    "OnePlus13r": "一加13R",
    "OnePlus13s": "一加13S",
    "OnePlus13t": "一加13T",
    "OnePlus15": "一加15",
    "OnePlus15r": "一加15R",
    "OnePlus15t": "一加15T",
    "OnePlusAce": "一加Ace",
    "OnePlusAce2": "一加Ace2",
    "OnePlusAce2Pro": "一加Ace2Pro",
    "OnePlusAce2v": "一加Ace2V",
    "OnePlusAce3": "一加Ace3",
    "OnePlusAce3Pro": "一加Ace3Pro",
    "OnePlusAce3v": "一加Ace3V",
    "OnePlusAce5": "一加Ace5",
    "OnePlusAce5Pro": "一加Ace5Pro",
    "OnePlusAce5Race": "一加Ace5竞速版",
    "OnePlusAce5Ultra": "一加Ace5至尊版",
    "OnePlusAce6": "一加Ace6",
    "OnePlusAce6Ultra": "一加Ace6至尊版",
    "OnePlusAce6UltraCanary": "一加Ace6至尊版_Canary",
    "OnePlusAce6t": "一加Ace6T",
    "OnePlusAce6tCanary": "一加Ace6T_Canary",
    "OnePlusAcePro": "一加AcePro",
    "OnePlusAceRace": "一加Ace竞速版",
    "OnePlusN6": "一加N6",
    "OnePlusNord3": "一加Nord3",
    "OnePlusNord4": "一加Nord4",
    "OnePlusNord5": "一加Nord5",
    "OnePlusNord6": "一加Nord6",
    "OnePlusNordCe4": "一加NordCE4",
    "OnePlusNordCe4Lite5g": "一加NordCE4Lite5G",
    "OnePlusNordCe6": "一加NordCE6",
    "OnePlusNordCe6Lite": "一加NordCE6Lite",
    "OnePlusNordN30Se5g": "一加NordN30SE5G",
    "OnePlusOpen": "一加Open",
    "OnePlusPad2": "一加平板2",
    "OnePlusPad2Mt6991": "一加平板2_MT6991",
    "OnePlusPad2Pro": "一加平板2Pro",
    "OnePlusPad3": "一加平板3",
    "OnePlusPad3Pro": "一加平板3Pro",
    "OnePlusPad4": "一加平板4",
    "OnePlusPadGo2": "一加平板Go2",
    "OnePlusPadLite": "一加平板Lite",
    "OnePlusPadMt6897": "一加平板_MT6897",
    "OnePlusPadMt6983": "一加平板_MT6983",
    "OnePlusPadPro": "一加平板Pro",
    "OnePlusTurbo6": "一加Turbo6",
    "OnePlusTurbo6v": "一加Turbo6V",
    "OnePlusTurbo6x": "一加Turbo6X",
}

# Former live cloud filename after the first version-first pass:
# 6.6.118_OnePlus13_Android16.0.0_SukiSU40959_KPM_ILH_HMBIRD_run123.zip
VERSION_FIRST = re.compile(
    r"(?P<kernel>\d+\.\d+\.\d+)_"
    r"(?P<model>OnePlus[A-Za-z0-9_-]{2,80})_"
    r"Android(?P<android>\d+(?:\.\d+){1,2})_"
    r"SukiSU40959_(?P<flags>[A-Za-z0-9_-]+)_"
    r"run(?P<run>\d+)\.zip"
)
# Updated visible name:
# 安卓16.0.0_风驰_内核6.6.118_OnePlus13_SukiSU40959_KPM_ILH_HMBIRD_run123.zip
DISPLAY_FIRST = re.compile(
    r"安卓(?P<android>\d+(?:\.\d+){1,2})_"
    r"(?P<variant>风驰|常规)_内核(?P<kernel>\d+\.\d+\.\d+)_"
    r"(?P<model>OnePlus[A-Za-z0-9_-]{2,80})_"
    r"SukiSU40959_(?P<flags>[A-Za-z0-9_-]+)_"
    r"run(?P<run>\d+)\.zip"
)

def folder_name(model: str) -> str:
    """Explicit mapping only: unknown model IDs are not blindly renamed."""
    try:
        result = MODEL_NAMES[model]
    except KeyError as exc:
        raise ValueError(f"Unmapped OnePlus model: {model}") from exc
    if result.startswith(".") or "/" in result or "\\" in result or len(result) > 48:
        raise ValueError("Invalid translated folder name")
    return result

def display_filename(filename: str, expected_model: str | None = None) -> str:
    """Idempotent rename; preserve entire exact kernel and Android versions."""
    if len(filename) > 240:
        raise ValueError("Filename too long")
    found = VERSION_FIRST.fullmatch(filename)
    existing = DISPLAY_FIRST.fullmatch(filename)
    match = found or existing
    if match is None:
        raise ValueError("Unrecognized AK3 filename; leave untouched")
    model = match.group("model")
    if model not in MODEL_NAMES or (expected_model and model != expected_model):
        raise ValueError("Model mismatch or not mapped")
    kernel, android = match.group("kernel"), match.group("android")
    flags = match.group("flags").strip("_")
    if not flags or len(flags) > 70:
        raise ValueError("Missing or unusual features")
    variant = "风驰" if "HMBIRD" in flags.split("_") else "常规"
    if existing and existing.group("variant") != variant:
        raise ValueError("Existing display variant conflicts with original flags")
    new_filename = (
        f"安卓{android}_{variant}_内核{kernel}_{model}_"
        f"SukiSU40959_{flags}_run{match.group('run')}.zip"
    )
    if len(new_filename) > 240:
        raise ValueError("Output filename too long")
    return new_filename
