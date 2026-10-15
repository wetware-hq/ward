"""Reads the signed wording file (read-only): found through STACK_SIBLINGS_DIR or the directory holding this checkout.
A missing file fails; it never skips. Expected values in signed-content tests come from here, not from the code under test."""
import os, pathlib, re

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent if HERE.name == "tests" else HERE
SIGNED_ROW = re.compile(r"^\| ([A-Z]{2,}-[A-Z0-9-]+) \|(.*)$", re.M)


def signed_path(name="forms_orders_lines_SIGNED.md"):
    return pathlib.Path(os.environ.get("STACK_SIBLINGS_DIR") or ROOT.parent) / "wording" / name


def signed_text(name="forms_orders_lines_SIGNED.md"):
    return signed_path(name).read_text(encoding="utf-8")


def signed_rows(name="forms_orders_lines_SIGNED.md"):
    """{id: wording} with the wording taken as the last cell, one pad space removed each side (byte-exact otherwise)."""
    out = {}
    for k, rest in SIGNED_ROW.findall(signed_text(name)):
        rest = rest.rstrip("\r")
        cell = rest.split("|")[-2] if rest.rstrip().endswith("|") else rest.split("|")[-1]
        out[k] = cell[1:-1] if cell.startswith(" ") and cell.endswith(" ") else cell.strip()
    return out
