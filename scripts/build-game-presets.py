#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build game-presets.json.gz, the per-game OptiScaler settings the launcher downloads.

Three sources, one entry per game:

- FreeFG's recipes.json (daniel-h-0/freefg, MIT): the games its maintainers
  tested on a BC-250 ("verified") with their OptiScaler.ini keys, frame-gen input
  and launch options, plus its structured reading of the OptiScaler wiki, which
  keeps every condition a page states ("only with DLSS inputs", "AMD/Intel").
- The OptiScaler wiki itself (optiscaler/OptiScaler.wiki.git), read here every
  night, so a setting added after FreeFG's last wiki refresh still arrives. Only
  what can be read mechanically is taken: `Key=value` code spans in a game page's
  Settings rows and in the compatibility list's notes, the Filename row (the
  proxy DLL names), the inputs and the compatibility verdict. A span's sentence
  decides its condition; one this cannot classify is kept with the sentence as a
  condition the launcher never meets, so only "Apply everything" applies it.
- OptiScaler.ini files (upstream's and FreeFG's build), which say which section
  a bare wiki key such as `Dxgi=false` belongs to. A key two sections define is
  ambiguous and dropped, as is a key no build defines.

Facts only: keys, values, conditions, DLL names and links, no copied prose from
the wiki. FreeFG's own notes are MIT and kept with their licence.

The launcher applies an entry (bc250-fsr4-launch.py, game_preset()), not this
script: what "matching" means depends on the variant a launch runs, which this
file cannot know. Settings FreeFG verified on a BC-250 always win over the wiki's.
"""
import argparse
import configparser
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = 1
WIKI = "https://github.com/optiscaler/OptiScaler/wiki/"

# What FreeFG's wiki conditions note beside a condition (its NOTE_KEYS): never a
# limit on where an item applies. autoapplied_since is handled on its own.
NOTE_KEYS = {"reason", "purpose", "note", "value", "feature"}
DX12_ARGS = {"-dx12", "-d3d12", "-force-d3d12"}
# The names OptiScaler can load as under Proton that the package can link
# (PROTON_OPTISCALER_NAME). d3d12.dll would replace vkd3d-proton's own and .asi
# needs an ASI loader, so neither is offered.
PROXIES = {"dxgi.dll", "winmm.dll", "version.dll", "dbghelp.dll", "winhttp.dll", "wininet.dll"}
# FreeFG's names for the variants a verified row's upscaler_ini addresses -> ours.
VARIANTS = {"hlx-fsr4": ["freefg-hlxfsr4"], "helixsr": ["helixsr"]}


def norm(title):
    """A title as every source is matched on: no marks, no punctuation, lower case."""
    title = re.sub(r"[™®©'’`]", "", title.lower()).replace("&", " and ")
    return " ".join(re.sub(r"[^0-9a-z]+", " ", title).split())


def reference_keys(paths):
    """bare option (lower) -> "Section.Option", from every reference OptiScaler.ini.
    An option two sections define maps to None: a bare key cannot say which."""
    keys = {}
    for path in paths:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str  # keep the spelling the ini uses
        parser.read_string(Path(path).read_text(encoding="utf-8-sig"))
        for section in parser.sections():
            for option in parser[section]:
                full = f"{section}.{option}"
                known = keys.get(option.lower(), full)
                keys[option.lower()] = full if known and known.lower() == full.lower() else None
    return keys


def canonical(keys, key):
    """"Section.Option" spelt as the reference ini spells it, or None if unknown."""
    section, _, option = key.partition(".")
    full = keys.get(option.lower())
    return full if full and full.split(".")[0].lower() == section.lower() else None


GPU_WORDS = (("nvidia", "nvidia"), ("geforce", "nvidia"), ("rtx", "nvidia"),
             ("amd", "amd"), ("radeon", "amd"), ("intel", "intel"), ("arc", "intel"))
INPUT_WORDS = (("dlss", "dlss"), ("fsr3.1", "fsr31"), ("fsr 3.1", "fsr31"), ("fsr31", "fsr31"),
               ("xess", "xess"), ("fsr2", "fsr2"), ("fsr 2", "fsr2"), ("fsr3", "fsr3"))
# Words that make a sentence a condition even when no GPU or input is named.
CONDITIONAL = re.compile(r"\b(if|when|unless|only|otherwise|in case|to fix|crash\w*|workaround|optional)\b")


def classify(sentence):
    """The condition a wiki sentence puts on the setting it names.

    {} for a plain instruction. A GPU or an input it names becomes FreeFG's own
    vocabulary (gpu, upscaler_input), which the launcher evaluates. Anything else
    conditional keeps the sentence under "condition", which never matches."""
    text = sentence.lower()
    when = {}
    gpus = sorted({gpu for word, gpu in GPU_WORDS if re.search(r"\b" + re.escape(word) + r"\b", text)})
    if gpus:
        when["gpu"] = "/".join(gpus)
    inputs = sorted({name for word, name in INPUT_WORDS
                     if re.search(re.escape(word) + r"\s*(input|inputs)\b", text)})
    if inputs:
        when["upscaler_input"] = ", ".join(inputs)
    if not when and CONDITIONAL.search(text):
        when["condition"] = " ".join(sentence.split())[:160]
    return when


SPAN = re.compile(r"`\**\s*([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?)\s*=\s*([^`*;\s][^`*;]*?)\s*\**`")


def spans(text, keys, auto=False):
    """(Section.Option, value, when, auto) for every `Key=value` span in text.

    Struck-out lines are history, not advice. A bullet under "Automatically
    applied ... since" is something OptiScaler already does: kept, marked auto."""
    found = []
    parent_auto = False
    for line in text.splitlines():
        if "<s>" in line:
            continue
        depth = len(line) - len(line.lstrip("*"))
        if depth <= 1:
            parent_auto = "automatically applied" in line.lower()
        for key, value in SPAN.findall(line):
            option = key.split(".")[-1]
            full = keys.get(option.lower())
            if not full:
                continue
            found.append((full, value.strip(), classify(line), auto or (parent_auto and depth > 1)))
    return found


def page_rows(text):
    """An AsciiDoc compatibility entry's |**Label** rows -> {label: value text}."""
    rows, label, lines = {}, None, []
    for line in text.splitlines():
        heading = re.match(r"^\|\*\*(.+?)\*\*\s*$", line)
        if heading or line.startswith("|==="):
            if label:
                rows[label] = "\n".join(lines).strip()
            label, lines = (heading.group(1).strip(), []) if heading else (None, [])
            continue
        if label is not None:
            lines.append(re.sub(r"^a?\|", "", line))
    return rows


def compat_list(path):
    """The compatibility list's table: {page slug or None, title, verdict, inputs, notes}."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("| ") else []
        if len(cells) < 5 or cells[0] in ("Game", "GAME NAME") or set(cells[0]) <= set("-: "):
            continue
        link = re.match(r"^\[(.+?)\]\((.+?)\)$", cells[0])
        title = link.group(1) if link else cells[0]
        slug = link.group(2).rstrip("/").split("/")[-1] if link else None
        verdict = {"✅": "working", "❌": "not-working", "➖": "partial"}.get(cells[1].strip(), None)
        if not title or title.startswith("GAME NAME"):
            continue
        rows.append(dict(title=title, slug=slug, compat=verdict, inputs=cells[2], notes=cells[4]))
    return rows


def proxies(text):
    names = []
    for name in re.findall(r"[A-Za-z0-9_]+\.(?:dll|asi)", text):
        name = name.lower()
        if name in PROXIES and name not in names:
            names.append(name)
    return names


def entry(games, title):
    key = norm(title)
    if not key:
        return None
    game = games.setdefault(key, dict(title=title, match=dict(title=[key]), settings=[], launch_args=[],
                                      proxy=[], pages=[], notes=[]))
    return game


def add_setting(game, key, value, source, when=None, auto=False, variants=None, scraped=False):
    item = dict(key=key, value=str(value), source=source)
    if scraped and any(s["key"].lower() == key.lower() and s["value"] == item["value"] for s in game["settings"]):
        # FreeFG read the same setting off the same page, with its condition
        # worked out by hand; the mechanical reading adds nothing.
        return
    if when:
        item["when"] = when
    if auto:
        item["auto"] = True
    if variants:
        item["variants"] = variants
    same = [s for s in game["settings"] if s["key"].lower() == key.lower() and s["value"] == item["value"]
            and s.get("when") == item.get("when")]
    if not same:
        game["settings"].append(item)


def add_arg(game, arg, source, when=None):
    item = dict(arg=arg, source=source, **({"when": when} if when else {}))
    if not any(a["arg"].lower() == arg.lower() for a in game["launch_args"]):
        game["launch_args"].append(item)


def from_freefg(games, recipes, keys, dropped):
    for row in recipes.get("verified", []) + recipes.get("community", []):
        game = entry(games, row["title"])
        for kind in ("steam", "exe", "gog", "epic"):
            values = [str(v).lower() if kind == "exe" else str(v) for v in row.get("match", {}).get(kind, [])]
            if values:
                game["match"].setdefault(kind, [])
                game["match"][kind] += [v for v in values if v not in game["match"][kind]]
        game["bc250"] = {k: row[k] for k in ("status", "route", "evidence", "observed", "note", "manual_steps",
                                              "pending_verification") if row.get(k) not in (None, [], "")}
        for key, value in row.get("ini", {}).items():
            full = canonical(keys, key) or key
            add_setting(game, full, value, "bc250")
        if row.get("fg_input"):
            add_setting(game, "FrameGen.FGInput", row["fg_input"], "bc250")
        for variant, settings in (row.get("upscaler_ini") or {}).items():
            for key, value in settings.items():
                add_setting(game, canonical(keys, key) or key, value, "bc250", variants=VARIANTS.get(variant, [variant]))
        for arg in row.get("launch_args", []):
            add_arg(game, arg, "bc250")
        for setting in row.get("game_settings", []):
            game["notes"].append(dict(source="bc250", game_setting=setting))
    for wiki in recipes.get("wiki", []):
        game = entry(games, wiki["title"])
        for t in wiki.get("match", {}).get("title", []):
            if t not in game["match"]["title"]:
                game["match"]["title"].append(t)
        for page in wiki.get("pages", []):
            page = WIKI + page.split("/wiki/")[-1]  # some links are doubled: .../wiki/https://.../wiki/X
            if page not in game["pages"]:
                game["pages"].append(page)
        if wiki.get("compat"):
            game.setdefault("compat", wiki["compat"])
        for name in wiki.get("proxy", []):
            if name.lower() in PROXIES and name.lower() not in game["proxy"]:
                game["proxy"].append(name.lower())
        for item in wiki.get("ini", []):
            full = canonical(keys, item["key"])
            if not full:
                dropped.append(f"{wiki['title']}: {item['key']}")
                continue
            when = {k: v for k, v in (item.get("when") or {}).items() if k not in NOTE_KEYS}
            auto = "autoapplied_since" in when
            when.pop("autoapplied_since", None)
            add_setting(game, full, item["value"], "wiki", when, auto)
        for arg in wiki.get("launch_args", []):
            add_arg(game, arg, "wiki")
        for arg in wiki.get("other_launch_args", []):
            add_arg(game, arg, "wiki", {"condition": "launch option the wiki gives with a condition"})
        for advice in wiki.get("fg_advice", []):
            game["notes"].append(dict(source="wiki", fg_advice=advice))
    # Exes where an OptiScaler quirk must keep a key at auto (FreeFG's leave_auto).
    for exe, items in recipes.get("leave_auto", {}).items():
        for game in games.values():
            if exe.lower() in game["match"].get("exe", []):
                game.setdefault("avoid", []).extend(i["key"] for i in items)


def from_wiki(games, folder, keys, dropped):
    folder = Path(folder)
    slugs = {}
    for row in compat_list(folder / "Compatibility-List.md"):
        game = entry(games, row["title"])
        if game is None:
            continue
        if row["compat"]:
            game.setdefault("compat", row["compat"])
        if row["slug"]:
            slugs[row["slug"]] = game
            page = WIKI + row["slug"]
            if page not in game["pages"]:
                game["pages"].append(page)
        for full, value, when, auto in spans(row["notes"], keys):
            add_setting(game, full, value, "wiki", when, auto, scraped=True)
        for name in proxies(row["notes"]):
            if name not in game["proxy"]:
                game["proxy"].append(name)
    for path in sorted(folder.glob("*.asciidoc")):
        rows = page_rows(path.read_text(encoding="utf-8"))
        if "Upscaler Inputs" not in rows or "Filename" not in rows:
            continue  # a template or a page about many games
        game = slugs.get(path.stem) or entry(games, path.stem.replace("-", " ").replace("‐", "-"))
        if game is None:
            continue
        page = WIKI + path.stem
        if page not in game["pages"]:
            game["pages"].append(page)
        for name in proxies(rows["Filename"]):
            if name not in game["proxy"]:
                game["proxy"].append(name)
        for label in ("Settings", "FG-Settings", "Known Issues", "Notes"):
            # Settings rows are instructions; the others mention settings as
            # workarounds, so whatever they name is conditional at best.
            for full, value, when, auto in spans(rows.get(label, ""), keys):
                if label not in ("Settings", "FG-Settings") and not when:
                    when = {"condition": f"named in the wiki's {label} row"}
                add_setting(game, full, value, "wiki", when, auto, scraped=True)


def finish(games):
    """Verified settings win: a wiki item for a key FreeFG set on a BC-250 goes."""
    out = []
    for game in sorted(games.values(), key=lambda g: g["match"]["title"][0]):
        verified = {s["key"].lower() for s in game["settings"] if s["source"] == "bc250"}
        game["settings"] = [s for s in game["settings"] if s["source"] == "bc250" or s["key"].lower() not in verified]
        for k in [k for k, v in game.items() if v in ([], {})]:
            del game[k]
        if any(k in game for k in ("settings", "launch_args", "proxy", "bc250", "compat")):
            out.append(game)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--freefg", type=Path, required=True, help="FreeFG's packaging/recipes/recipes.json")
    ap.add_argument("--freefg-commit", required=True)
    ap.add_argument("--wiki", type=Path, required=True, help="a checkout of OptiScaler.wiki.git")
    ap.add_argument("--wiki-commit", required=True)
    ap.add_argument("--ini", type=Path, action="append", required=True, help="a reference OptiScaler.ini")
    ap.add_argument("--generated", required=True, help="build time, ISO 8601")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    keys = reference_keys(args.ini)
    recipes = json.loads(args.freefg.read_text())
    if recipes.get("schema") != 1:
        raise SystemExit("unexpected FreeFG recipes schema: %r" % recipes.get("schema"))
    games, dropped = {}, []
    from_freefg(games, recipes, keys, dropped)
    from_wiki(games, args.wiki, keys, dropped)
    data = dict(schema=SCHEMA,
                sources=dict(freefg=dict(commit=args.freefg_commit, url="https://github.com/daniel-h-0/freefg",
                                         license="MIT", wiki_snapshot=recipes.get("sources", {}).get("wiki")),
                             wiki=dict(commit=args.wiki_commit, url=WIKI)),
                games=finish(games))
    # What changed, without the build time: the workflow publishes only when this differs.
    data["content_sha256"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    data["generated"] = args.generated
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    args.output.write_bytes(gzip.compress(raw, mtime=0))
    tested = sum(1 for g in data["games"] if "bc250" in g)
    print(f"{len(data['games'])} games, {tested} tested on a BC-250, "
          f"{sum(len(g.get('settings', [])) for g in data['games'])} settings, "
          f"{len(dropped)} wiki keys no build defines; {len(raw)} bytes, {args.output.stat().st_size} gzipped",
          file=sys.stderr)


if __name__ == "__main__":
    main()
