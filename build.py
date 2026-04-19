#!/usr/bin/env python3
"""
Forerunner Mod - Build Script
Merges partial override XMLs into base game files using lxml.

lxml preserves attribute order, encoding, and document structure.
No regex, no text manipulation, no mangling.

Usage:
    python build.py                         # Build to build/ModData/
    python build.py --clean                 # Wipe build/ first
    python build.py --diff                  # Show what overrides will change (dry run)
    python build.py --extract path/file.xml # Extract a minimal override from a fork

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

# -- Extract ----------------------------------------------------------------

def canonical_bytes(el):
    """
    Canonical byte-string for an entry, for equivalence comparison.
    Re-parses stripping pure-whitespace text nodes so indentation differences
    between two copies of the same entry don't register as a change, then
    runs C14N to normalize attribute order.
    """
    raw = etree.tostring(el)
    stripped = etree.fromstring(raw, etree.XMLParser(remove_blank_text=True))
    return etree.tostring(stripped, method="c14n")


def extract_xml(modder_path, base_path, rule):
    """
    Compare modder's forked file against vanilla and return a new tree
    containing only entries that were added or modified.

    NOTE: entry-level granularity only. If a modder tweaked one attribute
    inside a large entry, the whole entry is emitted. Sub-entry diffing
    is out of scope.
    """
    parser = etree.XMLParser(remove_blank_text=False, strip_cdata=False)
    modder_tree = etree.parse(modder_path, parser)
    base_tree = etree.parse(base_path, parser)

    modder_root = modder_tree.getroot()
    base_root = base_tree.getroot()

    tag = rule["tag"]

    if "parent" in rule:
        modder_container = modder_root.find(rule["parent"])
        base_container = base_root.find(rule["parent"])
        if modder_container is None:
            raise ValueError(f"modder file missing <{rule['parent']}> element")
        if base_container is None:
            raise ValueError(f"base file missing <{rule['parent']}> element")
    else:
        modder_container = modder_root
        base_container = base_root

    new_names = []
    modified_names = []
    unchanged = 0
    kept = []

    for mod_el in modder_container.findall(tag):
        key_val = get_entry_key(mod_el, rule)
        if not key_val:
            print(f"  WARNING: {tag} element missing key, skipping")
            continue

        base_el = find_in_tree(base_container, tag, key_val, rule)

        if base_el is None:
            new_names.append(key_val)
            kept.append(mod_el)
        elif canonical_bytes(mod_el) != canonical_bytes(base_el):
            modified_names.append(key_val)
            kept.append(mod_el)
        else:
            unchanged += 1

    # Build the output tree: mirror the modder's root (and parent container,
    # if any), then insert only the kept entries.
    new_root = etree.Element(
        modder_root.tag, attrib=dict(modder_root.attrib), nsmap=modder_root.nsmap
    )
    if "parent" in rule:
        src_parent = modder_container
        container = etree.SubElement(
            new_root, src_parent.tag, attrib=dict(src_parent.attrib)
        )
    else:
        container = new_root

    for entry in kept:
        container.append(etree.fromstring(etree.tostring(entry)))

    out_tree = etree.ElementTree(new_root)
    summary = {
        "new": new_names,
        "modified": modified_names,
        "unchanged": unchanged,
        "encoding": modder_tree.docinfo.encoding or "utf-8",
    }
    return out_tree, summary


def write_extract(tree, path, encoding):
    """Write an extracted override file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tree.write(path, encoding=encoding, xml_declaration=True, pretty_print=True)
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

def do_extract(modder_path, out_dir):
    """
    Extract a minimal override from a full-file fork by diffing against
    base/<filename>. Use this to reduce someone else's forked XML to the
    entries they actually changed.
    """
    if not os.path.isfile(modder_path):
        print(f"ERROR: no such file: {modder_path}")
        sys.exit(1)

    fname = os.path.basename(modder_path)
    base_path = os.path.join(BASE_DIR, fname)
    out_path = os.path.join(out_dir, fname)

    print(f"\n-- Extracting {fname} --")

    if fname not in MERGE_RULES:
        # No merge rule => can't diff entry-by-entry. Fall back to copying
        # the whole file; warn the user this is a full replacement, not an
        # actual extract.
        print(f"  WARNING: no merge rule for {fname} - emitting full file")
        print(f"           as a replacement override. This is not a true")
        print(f"           extract; add a rule to MERGE_RULES for proper diffing.")
        os.makedirs(out_dir, exist_ok=True)
        shutil.copy2(modder_path, out_path)
        print(f"  wrote {out_path}")
        return

    if not os.path.isfile(base_path):
        print(f"ERROR: no vanilla base file at {base_path} to diff against")
        sys.exit(1)

    rule = MERGE_RULES[fname]
    try:
        tree, summary = extract_xml(modder_path, base_path, rule)
    except Exception as e:
        print(f"  ERROR extracting {fname}: {e}")
        sys.exit(1)

    total = len(summary["new"]) + len(summary["modified"])
    print(f"  {total} entries extracted "
          f"({len(summary['modified'])} modified, {len(summary['new'])} new, "
          f"{summary['unchanged']} unchanged and dropped)")
    for name in summary["modified"]:
        print(f"    ~ {name}")
    for name in summary["new"]:
        print(f"    + {name}")

    if total == 0:
        print(f"  (nothing to extract - modder file is identical to base)")
        return

    write_extract(tree, out_path, summary["encoding"])


# -- Main -------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Forerunner Mod build script",
        epilog=(
            "Use --extract to reduce a full-file fork (e.g. a modder's "
            "complete leaders.xml) to a minimal override containing only "
            "the entries that differ from vanilla. Diffs at entry granularity "
            "only - if one attribute inside an entry changed, the whole "
            "entry is emitted."
        ),
    )
    parser.add_argument("--clean", action="store_true", help="Wipe build/ before building")
    parser.add_argument("--diff",  action="store_true", help="Dry run - show what would change")
    parser.add_argument(
        "--extract", metavar="FILE",
        help="Extract a minimal override from a forked base file by diffing "
             "against base/<filename>. File type is inferred from the filename.",
    )
    parser.add_argument(
        "--into", metavar="DIR", default=OVERRIDES_DIR,
        help=f"Output directory for --extract (default: {OVERRIDES_DIR}/)",
    )
    args = parser.parse_args()

    if args.extract:
        do_extract(args.extract, args.into)
    elif args.diff:
        do_diff()
    else:
        do_build(clean=args.clean)