#!/usr/bin/env python3
"""
Forerunner Mod - Build Script
Merges partial override XMLs into base game files using lxml.

lxml preserves attribute order, encoding, and document structure.
No regex, no text manipulation, no mangling.

Usage:
    python build.py              # Build to build/ModData/
    python build.py --clean      # Wipe build/ first
    python build.py --diff       # Show what overrides will change (dry run)

Requirements:
    pip install lxml
"""

from lxml import etree
import argparse
import shutil
import os
import sys

# -- Configuration ----------------------------------------------------------

BASE_DIR      = "base"
OVERRIDES_DIR = "overrides"
STATIC_DIR    = "static"
BUILD_DIR     = os.path.join("build", "ModData", "data")

# How to merge each file.
#   tag:       the XML element name for each entry
#   key:       attribute name to match on
#   child_key: if set, match on a child element's text instead of an attribute
#   parent:    if entries are nested inside a container element (e.g. Language > String)
MERGE_RULES = {
    "objects.xml":        {"tag": "Object", "key": "name"},
    "squads.xml":         {"tag": "Squad",  "key": "name"},
    "techs.xml":          {"tag": "Tech",   "key": "name"},
    "powers.xml":         {"tag": "Power",  "key": "name"},
    "leaders.xml":        {"tag": "Leader", "key": "Name"},
    "stringtable-en.xml": {"tag": "String", "key": "_locID", "parent": "Language"},
    "civs.xml":           {"tag": "Civ",    "child_key": "Name"},
    "hpbars.xml":         {"tag": "HPBar",  "key": "name"},
}

# -- Merge ------------------------------------------------------------------

def get_entry_key(el, rule):
    """Get the key value for an entry element."""
    if "child_key" in rule:
        child = el.find(rule["child_key"])
        return child.text.strip() if child is not None and child.text else None
    else:
        return el.get(rule["key"])


def find_in_tree(parent, tag, key_val, rule):
    """Find an existing entry in the base tree by key."""
    if "child_key" in rule:
        child_key = rule["child_key"]
        results = parent.xpath(f'{tag}[{child_key}="{key_val}"]')
        return results[0] if results else None
    else:
        key = rule["key"]
        results = parent.xpath(f'{tag}[@{key}="{key_val}"]')
        return results[0] if results else None


def merge_xml(base_path, override_path, rule):
    """
    Merge override entries into base XML using lxml.
    Returns (tree, summary).
    """
    parser = etree.XMLParser(remove_blank_text=False, strip_cdata=False)
    base_tree = etree.parse(base_path, parser)
    override_tree = etree.parse(override_path, parser)

    base_root = base_tree.getroot()
    override_root = override_tree.getroot()

    tag = rule["tag"]

    # Find the container (root, or a parent element like <Language>)
    if "parent" in rule:
        base_container = base_root.find(rule["parent"])
        override_container = override_root.find(rule["parent"])
        if base_container is None:
            print(f"  WARNING: base file missing <{rule['parent']}> element")
            return base_tree, {"replaced": [], "appended": []}
        if override_container is None:
            print(f"  WARNING: override file missing <{rule['parent']}> element")
            return base_tree, {"replaced": [], "appended": []}
    else:
        base_container = base_root
        override_container = override_root

    replaced = []
    appended = []

    for override_el in override_container.findall(tag):
        key_val = get_entry_key(override_el, rule)
        if not key_val:
            print(f"  WARNING: {tag} element missing key, skipping")
            continue

        existing = find_in_tree(base_container, tag, key_val, rule)

        if existing is not None:
            # Replace in-place
            idx = list(base_container).index(existing)
            override_el.tail = existing.tail
            base_container.remove(existing)
            base_container.insert(idx, override_el)
            replaced.append(key_val)
        else:
            # Append
            override_el.tail = "\n"
            base_container.append(override_el)
            appended.append(key_val)

    return base_tree, {"replaced": replaced, "appended": appended}


def write_xml(tree, path):
    """Write XML preserving the original encoding."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    encoding = tree.docinfo.encoding or "utf-8"
    tree.write(path, encoding=encoding, xml_declaration=True, pretty_print=False)
    print(f"  wrote {path}")

# -- Commands ---------------------------------------------------------------

def do_build(clean=False):
    if clean and os.path.exists("build"):
        shutil.rmtree("build")
        print("Cleaned build/")

    os.makedirs(BUILD_DIR, exist_ok=True)

    # 1. Merge overrides into base files
    if os.path.isdir(OVERRIDES_DIR):
        print("\n-- Merging overrides --")
        for fname in sorted(os.listdir(OVERRIDES_DIR)):
            if not fname.endswith(".xml"):
                continue
            override_path = os.path.join(OVERRIDES_DIR, fname)
            base_path     = os.path.join(BASE_DIR, fname)
            out_path      = os.path.join(BUILD_DIR, fname)

            if fname in MERGE_RULES:
                if not os.path.isfile(base_path):
                    print(f"  SKIP {fname}: no base file at {base_path}")
                    continue
                rule = MERGE_RULES[fname]

                try:
                    tree, summary = merge_xml(base_path, override_path, rule)
                    write_xml(tree, out_path)
                    print(f"    {len(summary['replaced'])} replaced, {len(summary['appended'])} new")
                    for name in summary["replaced"]:
                        print(f"      ~ {name}")
                    for name in summary["appended"]:
                        print(f"      + {name}")
                except Exception as e:
                    print(f"  ERROR merging {fname}: {e}")
                    sys.exit(1)
            else:
                # No merge rule - full replacement
                print(f"  copy (full replacement) {fname}")
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                shutil.copy2(override_path, out_path)

    # 2. Copy static files (preserving subdirectory structure)
    if os.path.isdir(STATIC_DIR):
        print("\n-- Copying static files --")
        for dirpath, _, filenames in os.walk(STATIC_DIR):
            for fname in sorted(filenames):
                if fname == '.gitkeep':
                    continue
                src = os.path.join(dirpath, fname)
                rel = os.path.relpath(src, STATIC_DIR)
                dst = os.path.join(BUILD_DIR, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                print(f"  {rel}")

    print(f"\nDone -> {BUILD_DIR}/")


def do_diff():
    """Show what the overrides would change without building."""
    if not os.path.isdir(OVERRIDES_DIR):
        print("No overrides/ directory found.")
        return

    print("\n-- Override summary (dry run) --\n")
    for fname in sorted(os.listdir(OVERRIDES_DIR)):
        if not fname.endswith(".xml"):
            continue
        override_path = os.path.join(OVERRIDES_DIR, fname)
        base_path     = os.path.join(BASE_DIR, fname)

        if fname in MERGE_RULES:
            if not os.path.isfile(base_path):
                print(f"  {fname}: SKIP (no base file)")
                continue
            rule = MERGE_RULES[fname]

            try:
                _, summary = merge_xml(base_path, override_path, rule)
                total = len(summary["replaced"]) + len(summary["appended"])
                print(f"  {fname}: {total} entries ({len(summary['replaced'])} modified, {len(summary['appended'])} new)")
                for name in summary["replaced"]:
                    print(f"    ~ {name}")
                for name in summary["appended"]:
                    print(f"    + {name}")
            except Exception as e:
                print(f"  {fname}: ERROR - {e}")
        else:
            print(f"  {fname}: full replacement (no merge rule)")

    if os.path.isdir(STATIC_DIR):
        statics = []
        for dirpath, _, filenames in os.walk(STATIC_DIR):
            for f in filenames:
                if f == '.gitkeep':
                    continue
                statics.append(os.path.relpath(os.path.join(dirpath, f), STATIC_DIR))
        if statics:
            print(f"\n  static/ ({len(statics)} files copied as-is):")
            for s in sorted(statics):
                print(f"    {s}")

# -- Main -------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Forerunner Mod build script")
    parser.add_argument("--clean", action="store_true", help="Wipe build/ before building")
    parser.add_argument("--diff",  action="store_true", help="Dry run - show what would change")
    args = parser.parse_args()

    if args.diff:
        do_diff()
    else:
        do_build(clean=args.clean)