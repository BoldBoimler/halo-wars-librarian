# Librarian

A build tool for Halo Wars: Definitive Edition XML mods.

Librarian lets you keep just the parts of the game you want to change — small override fragments — under version control, and merges them against the base game files at build time to produce a working mod.

Companion to [Cartographer](https://github.com/BoldBoimler/halo-wars-cartographer), the HW:DE scenario editor.

## Why

The usual approach to HW:DE modding is to fork the whole file you want to change. You copy the game's entire `objects.xml` into your mod, make your three edits, and ship the forked copy. This works, but it has three real problems:

- **Mods step on each other.** Two mods that both fork `objects.xml` can't coexist, even if they touch unrelated things.
- **Game updates are hard to absorb.** When the base file changes, you have no way to know what drifted apart from eyeballing a 10,000-line diff.
- **Your actual changes are invisible.** What did you really change? Good luck finding out six months later.

Librarian inverts the model. You commit tiny override files — just the entries you're adding or replacing — alongside a reference copy of the base files. At build time, `build.py` merges them together into a ready-to-deploy mod.

It also makes iteration faster. HW:DE produces almost no useful crash logs, so when a change breaks the game you're stuck bisecting. Keeping your overrides tiny and separate makes "comment out one file at a time until it loads" a tractable strategy.

## How it works

Three directories, three different jobs:

**`base/`** — your extracted copy of the game's XML files. Read-only reference. Used as merge targets; never copied to the build output directly. **Not committed to the repo** (see Setup).

**`overrides/`** — your mod. Each file here is a *fragment* of the corresponding base file — same schema, but only the entries you care about. `build.py` reads both and produces a merged output.

**`static/`** — files that get copied verbatim into the build, no merging. Use this for custom triggerscripts, scenarios, `.gfx` UI files, or anything that isn't a game XML Librarian knows how to merge.

Output lands in `build/ModData/data/`, which is the structure HW:DE expects when you drop a mod in the game's `ModData/` folder.

## Worked example

Say you want to add 343 Guilty Spark as a playable leader. You don't copy the game's entire 12 KB `leaders.xml` — you just write `overrides/leaders.xml` with the new entry:

```xml
<Leaders>
  <Leader name="343GuiltySpark" ...>
    ...
  </Leader>
</Leaders>
```

Run:

```bash
python build.py --clean
```

Output:

```
-- Merging overrides --
  wrote build/ModData/data/leaders.xml
    0 replaced, 1 new
      + 343GuiltySpark
```

`build/ModData/data/leaders.xml` is now the full base game leaders file plus your new entry, ready to drop into the Deck's `ModData/`.

The merge semantic is simple: for each entry in the override, if its key matches an existing entry in the base, it replaces in place; otherwise it's appended. That's the whole thing. The key field is per-file — `name` for leaders, `_locID` for stringtables, etc., configured in `MERGE_RULES` in `build.py`.

## Setup

1. Clone the repo.
2. Extract your game's ERA files into `base/`. **Librarian does not ship base game XMLs** — you need your own copy of Halo Wars: Definitive Edition. Tools like PhxGUI can extract ERAs. `base/` is gitignored to avoid redistributing copyrighted game content.
3. Install dependencies:
   ```bash
   pip install lxml
   ```
4. Build:
   ```bash
   python build.py --clean
   ```

To preview what a build would change without writing files:

```bash
python build.py --diff
```

## Adding a new merge rule

Out of the box, `MERGE_RULES` in `build.py` covers leaders, techs, stringtables, civs, and a handful of other files. If you drop an override for a file not in the rules, Librarian will currently fall back to full-file replacement (copy the override in place of the base). For small files that's usually fine; for large files like `objects.xml` you'll want proper merging.

To add a rule, edit `MERGE_RULES`:

```python
MERGE_RULES = {
    "somefile.xml": {"tag": "Entry", "key": "name"},
    ...
}
```

That rule says: "When merging `somefile.xml`, find entries by the `<Entry>` tag and match on the `name` attribute." For nested structures (stringtables have a `<Language>` container, civs use a child element as the key), see the existing entries for examples.

## Deploying

To a Steam Deck on your LAN:

```bash
scp -r build/ModData deck@<deck-ip>:~/HaloWarsMods/<your-mod>/
```

## State of things / help wanted

Librarian builds clean and the output validates as XML, but **end-to-end game behavior testing is still the frontier**. What's known:

- ✅ Builds produce valid XML
- ✅ Adding new leader entries works — 343 Guilty Spark appears in leader select
- ✅ Removing existing entries works — Elite Honor Guard and Ghost successfully removed from the Covenant Citadel build menu
- ❌ Adding new unit entries to the roster is the current frontier — haven't gotten a new buildable unit to appear in-game yet
- ⚠️ Earlier iterations crashed on load frequently; the current committed state is stable but coverage is thin
- ❓ `static/` half of the pipeline is untested — no files currently use it
- ❓ No merge rule for `objects.xml` or `squads.xml` yet; adding one is probably the single most useful contribution and is likely related to the "new unit" problem above

If you're modding HW:DE and want to help:

- Testing the build on your own setup and reporting what breaks
- Cracking the "add a new buildable unit" problem
- Adding merge rules for commonly-modded files
- Anything you can tell me about HW:DE's mod loader's failure modes — error logs are basically nonexistent and every data point helps

## Related

- **[Cartographer](https://github.com/BoldBoimler/halo-wars-cartographer)** — desktop scenario editor for HW:DE with 2D/3D viewports, terrain rendering, and round-trip SCN/SC2 export. Edit maps visually, then use Librarian to ship the surrounding mod.
- The [HW:DE modding Discord](https://discord.gg/haloWARS) is where most of the active community lives.

---

Built by [BoldBoimler](https://github.com/BoldBoimler) with [Claude](https://claude.ai) by Anthropic. Issues and PRs welcome.
