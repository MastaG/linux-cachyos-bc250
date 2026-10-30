# SPDX-License-Identifier: MIT
"""Game compatibility: one verdict per game, from local evidence only, before anything is written.

Layers, highest first (research/recipes/RULES.md "Recipe precedence"; a lower layer only fills what every higher one
left open):
  1 the user           an OptiScaler.ini value that is not auto, an explicit route or input, their own API switch
  2 verified recipe    verified-bc250 (recipes.json "verified"): route, input, keys, game settings, launch argument
  3 OptiScaler quirks  keys a runtime quirk of the shipped build sets for the exe stay auto (Q1; Q3 for every key)
  4 community recipe   community-bc250 (recipes.json "community"), reviewed reports from other BC-250 owners
  5 promoted wiki      the OptiScaler wiki items wiki_promote.json promotes (agent-reviewed, awaiting a maintainer's
                       confirmation), for a strong match where every condition holds here (P1)
  6 wiki vetoes        an FG input the wiki reports broken leaves the automatic candidates (V1)
  7 detection          gamescan.py: executable, route, FG input, DX12 switch, DLSS helper, refusals
  8 installer defaults install.py CHANGES and route keys
  9 wiki, shown only   every other wiki item, with its condition evaluated as true, false or unknown

Tiers: A verified on BC-250, B community-reported on BC-250, C automatic guided by the wiki, D automatic from
detection, R refused; M marks a step the user has to take (a flag on A to D). Every function here is pure: it reads the
scan (gamescan.scan_*), the recipe file (recipes.load) and the identity (recipes.identity) it is given, writes nothing
and uses no network. install.py check prints the verdict; install.py install applies it.
"""
import json
import hashlib
import os
import re
from pathlib import Path

# OptiScaler keys the installer writes itself (research/recipes/build_recipes.py INSTALLER_KEYS; a test keeps them alike).
INSTALLER_KEYS = {'Upscalers.Dx12Upscaler', 'FSR.UpscalerIndex', 'FSR.Fsr4ForceModel', 'FSR.Fsr4EnableWatermark',
                  'FrameGen.Enabled', 'fakenvapi.UseFakenvapi', 'FrameGen.FGInput', 'FrameGen.FGOutput',
                  'Libraries.XeFGPath', 'Libraries.XeLLPath', 'XeFG.ForceBorderless', 'Plugins.LoadAsiPlugins',
                  'XeFG.InterpolationCount', 'FrameGen.DisableHudless', 'fakenvapi.ForceReflex', 'XeFG.XeFGModel'}
# What the wiki drafts record beside a condition: explanations, never limits on where an item applies.
NOTE_KEYS = {'reason', 'purpose', 'note', 'autoapplied_since', 'value', 'feature'}
INPUT_NAMES = {'upscaler': 'OptiFG', 'dlssg': 'DLSS FG', 'fsrfg': 'FSR 3.1 FG', 'fsrfg30': 'FSR 3.0 FG',
               'native-xefg': 'native XeSS FG', 'nukems': "Nukem's dlssg-to-fsr3", 'native-fsrfg': "the game's own FSR FG"}
UPSCALER_NAMES = {'dlss': 'DLSS', 'fsr2': 'FSR 2', 'fsr3': 'FSR 3.0', 'fsr31': 'FSR 3.1', 'xess': 'XeSS'}
DX12_ARGS = ('-dx12', '-d3d12', '-force-d3d12')
OFF_DX12_ARGS = ('-dx11', '-d3d11', '-force-d3d11', '-vulkan', '-force-vulkan', '-opengl', '-force-glcore')
# Executable names many games share: an exe-name match alone never identifies a game.
GENERIC_EXES = {'game.exe', 'launcher.exe', 'start.exe', 'main.exe', 'app.exe', 'bin.exe', 'client.exe', 'play.exe',
                'client-win64-shipping.exe', 'medium-win64-shipping.exe', 'game-win64-shipping.exe', 'project-win64-shipping.exe'}
TIER_NAMES = {'A': 'Verified on BC-250', 'B': 'Community-reported on BC-250', 'C': 'Automatic, guided by the OptiScaler wiki',
              'D': 'Automatic (no recipe)', 'R': 'Not supported'}
EVIDENCE = {'gameplay': 'generates in gameplay', 'generates': '2.0 observed', 'startup': 'generates at start-up',
            'installed': 'installed; generation not checked yet', 'fails': 'known problem'}
# This install: the GPU, OS, frame-generation output and output upscaler every wiki condition is evaluated against.
DEFAULT_CONTEXT = dict(gpu='amd', os='linux', api='dx12', fg_output='xefg', upscaler='fsr4', proxy='dxgi.dll')


class Refused(ValueError):
    """A refusal before anything is downloaded or written: str() is the line Setup and the command line print."""

    def __init__(self, refusal):
        self.refusal = refusal
        super().__init__(f'Not supported: {refusal["text"]} {refusal["way"]} [{refusal["code"]}]'.replace('  ', ' ').strip())


# ---------------------------------------------------------------------------------------------- RULES.md per INI key
S1 = re.compile(r'^(fsr\.fsrnonlinear|fsr\.dlssreactivemaskbias|sharpness\.|cas\.|upscaleratio\.|outputscaling\.|mipmap\.|'
                r'anisotropy\.|qualityoverrides\.|drs\.|hdr\.|initflags\.autoexposure)')


def key_rule(key, value):
    """Why RULES.md keeps an OptiScaler key out of automatic writes: (class, reason) with class installer / blocked /
    policy / never / human / redundant, or (None, None) for a key a recipe or a promoted wiki item may write."""
    k, v = key.lower(), str(value).strip().lower()
    if k == 'framegen.fgoutput':
        return ('redundant', 'the installer writes FGOutput=xefg') if v == 'xefg' else ('blocked', 'F0: XeFG is always the generator')
    if k == 'xefg.forceborderless' and v == 'true':
        return 'redundant', 'the installer writes ForceBorderless=true'
    if k == 'xefg.xefgmodel' and v == 'default':
        return 'redundant', 'the installer writes XeFGModel=default'
    if k in {x.lower() for x in INSTALLER_KEYS}:
        return 'installer', 'the installer and verified recipes choose this key'
    if k.startswith('optifg.hudfix') or k == 'optifg.hudlimit':
        return 'blocked', 'H1: HUDFix is never switched on automatically'
    if k == 'spoofing.dxgi':
        return 'blocked', 'D1: OptiScaler\'s own per-game fixes cover the confirmed cases'
    if k.startswith('fakenvapi.') or 'reflex' in k or k.startswith('nvapi.'):
        return 'blocked', 'R1: the installer\'s Reflex policy stands'
    if S1.match(k):
        return 'blocked', 'S1: quality and colour settings are suggestions'
    if k.startswith('upscalers.') or k.startswith('fsr.fsr4') or k == 'fsr.upscalerindex':
        return 'installer', 'the output upscaler is the installer\'s choice'
    if k in ('spoofing.spoofedvendorid', 'spoofing.spoofeddeviceid', 'spoofing.spoofedgpuname'):
        return 'policy', 'spoofing another GPU turns off this build\'s BC-250 path'
    if k.startswith('v-sync.') or k.startswith('framerate.'):
        return 'policy', 'V-Sync and frame-rate overrides interact with the pacing layer'
    if k.startswith(('fsrfg.', 'dlssg.', 'nvngxfg.')):
        return 'never', 'settings of a frame-generation output this build never uses (F0)'
    if k.startswith('menu.shortcutkey'):
        return 'human', 'a personal preference'
    if k.startswith('plugins.loadreshade') or 'luma' in k:
        return 'human', 'needs another mod (ReShade or Luma)'
    if k.startswith('log.'):
        return 'never', 'logging'
    return None, None


# --------------------------------------------------------------------------------------- wiki conditions, evaluated
def _condition(key, value, ctx):
    """True, False or None (unknown here) for one wiki condition, with the reason for False."""
    v = str(value).strip().lower()
    if key in NOTE_KEYS:
        return True, None
    if key == 'gpu':
        if re.search(r'rdna ?[34]|9070|7900|7800|7600|\brx 9|\brx 7', v):
            return False, 'other AMD GPUs (RDNA 3/4)'
        if re.search(r'not nvidia|non-nvidia|\bamd\b|radeon|dp4a|steam deck|\brdna\b', v):
            return True, None
        if re.search(r'nvidia|gtx|rtx', v):
            return False, 'NVIDIA GPUs only'
        if re.search(r'intel|\barc\b', v):
            return False, 'Intel GPUs only'
        return None, None
    if key == 'os':
        if re.search(r'linux|proton|steam ?os|steam deck', v):
            return True, None
        if re.search(r'windows|\bw1[01]\b|win1[01]', v):
            return False, 'Windows only'
        return None, None
    if key == 'fg_output':
        return (True, None) if v == ctx.get('fg_output', 'xefg') else (False, 'another frame-generation output (F0)')
    if key == 'fg':
        return False, 'another frame generation (F0)'
    if key == 'fg_input':
        chosen = ctx.get('fg_input')
        parts = {p.strip() for p in re.split(r'[/,]| or ', v.removeprefix('not ')) if p.strip()}
        parts = {'upscaler' if p in ('optifg', 'opti') else p for p in parts}
        if parts & {'nukems', 'native-fsrfg'} and not parts & {'upscaler', 'dlssg', 'fsrfg', 'fsrfg30', 'native-xefg'}:
            return False, 'an FG input this build never uses (F0)'
        if chosen is None or not parts & {'upscaler', 'dlssg', 'fsrfg', 'fsrfg30', 'native-xefg'}:
            return None, None
        hit = chosen in parts
        if v.startswith('not '):
            return (not hit), (None if not hit else f'not with {INPUT_NAMES.get(chosen, chosen)}')
        return hit, (None if hit else f'only with {", ".join(sorted(INPUT_NAMES.get(p, p) for p in parts))}')
    if key == 'required_file':
        files = ctx.get('files')
        return (None, None) if files is None else (v in {str(path).lower() for path in files}, 'required file: ' + str(value))
    if key == 'upscaler_input':
        chosen = ctx.get('upscaler_input')
        if not chosen:
            return None, None
        return (str(chosen).lower() == v, 'requires ' + str(value) + ' game input')
    if key in ('upscaler', 'upscaler_output'):
        mine = ctx.get('upscaler', 'fsr4')
        if mine in v:
            return True, None
        if re.search(r'fsr ?4|helix|dlss|xess|fsr ?3|fsr ?2', v):
            return False, f'another output upscaler ({value})'
        return None, None
    if key == 'optiscaler':
        if re.fullmatch(r'0\.[0-8](\.\d+)*|before 0\.9|0\.7\.\d+', v):
            return False, f'OptiScaler {value} (older than the shipped build)'
        return True, None
    if key == 'api':
        mine = str(ctx.get('api') or '').lower()
        aliases = {'dx12': ('dx12', 'd3d12', 'directx 12'), 'dx11': ('dx11', 'd3d11', 'directx 11'),
                   'vulkan': ('vulkan',), 'opengl': ('opengl',), 'dx9': ('dx9', 'd3d9')}
        expected = {name for name, names in aliases.items() if any(alias in v for alias in names)}
        actual = next((name for name, names in aliases.items() if mine in names), None)
        if actual and expected:
            return actual in expected, f'requires {value}; current API is {mine}'
        return None, None
    if key == 'proxy':
        mine = ctx.get('proxy')
        return (None, None) if not mine else (str(mine).lower() == v, 'requires proxy ' + str(value))
    if key in ('platform', 'store', 'launcher'):
        if re.search(r'xbox|game ?pass|ms store|microsoft store', v):
            return False, 'the Xbox / Game Pass build'
        store = (ctx.get('store') or '').lower()
        if store and store in v:
            return True, None
        return None, None
    if key == 'engine':
        engine = (ctx.get('engine') or '').lower()
        if engine and (engine in v or (engine == 'unreal' and re.search(r'\bue\d?\b|unreal', v))):
            return True, None
        return (False, f'the {value} engine') if engine and engine != 'unknown' else (None, None)
    if key == 'condition' and re.fullmatch(r'xefg( output)?', v):
        return True, None
    return None, None  # upscaler_input (the user's pick in the game), symptoms, game versions, other mods: unknown here


def evaluate(when, ctx):
    """(result, reasons): result True when every condition holds for this install, False when one never does (reasons
    says which), None when one cannot be known before the game runs (reasons lists the unknown ones)."""
    unknown, false = [], []
    for key, value in (when or {}).items():
        result, why = _condition(key, value, ctx)
        if result is False:
            false.append(why or f'{key} {value}')
        elif result is None:
            unknown.append(f'{key}: {value}')
    if false:
        return False, false
    return (None, unknown) if unknown else (True, [])


# ---------------------------------------------------------------------------------------------- matching the wiki
def wiki_matches(data, ids):
    """[(wiki entry, 'strong' | 'weak')]: strong = a launcher ID, or the exe name together with the game's title or one
    of its folders; weak = the title alone, or a (non-generic) exe name alone."""
    out = []
    exe = ids.get('exe', '')
    names = set(ids.get('titles') or ()) | set(ids.get('folders') or ())
    for w in (data or {}).get('wiki', []):
        m = w.get('match', {})
        by_id = any(set(ids.get(k) or ()) & set(m.get(k, [])) for k in ('steam', 'gog', 'epic'))
        by_exe = exe in m.get('exe', [])
        by_title = bool(set(m.get('title', [])) & set(ids.get('titles') or ()))
        named = bool(set(m.get('title', [])) & names)
        if by_id or (by_exe and named):
            out.append((w, 'strong'))
        elif by_title or (by_exe and exe not in GENERIC_EXES):
            out.append((w, 'weak'))
    return out


def community_match(data, ids):
    """The community recipe for the game (same matching as verified recipes), or None."""
    for entry in (data or {}).get('community', []):
        m = entry['match']
        by_id = any(set(ids.get(k) or ()) & set(m.get(k, [])) for k in ('steam', 'gog', 'epic'))
        known = any(ids.get(k) for k in ('steam', 'gog', 'epic'))
        title = re.sub(r'[^a-z0-9]+', ' ', entry.get('title', '').lower()).strip()
        named = (({title} | set(m.get('title', []))) - {''}) & (set(ids.get('titles') or ()) | set(ids.get('folders') or ()))
        if by_id or (ids.get('exe') in m.get('exe', []) and not known and named):
            return entry
    return None


# Catalog-only API used by both the installer and Proton integrations. No scan,
# filesystem, GUI or dependency fetch is performed by these functions.
WIKI_PLAN_FORMAT = 1


def wiki_plan(data, ids, ctx=None, *, supported_keys=None, current=None, recipe_ini=None,
              quirk_exe=None, optiscaler_commit=None):
    """Return source-backed INI proposals, automatic writes and negative evidence.

    Automatic writes require a reviewed item, a strong identity, true conditions,
    and no higher-priority owner. Other usable INI values are explicit prefills;
    unknown conditions and title-only matches require confirmation of that row.
    Known-inapplicable, unsupported, runtime-owned and policy keys are never
    selectable. Merely constructing or displaying this plan changes nothing.
    """
    ctx = dict(DEFAULT_CONTEXT, **(ctx or {}))
    for key in ('fg_input', 'fg_output', 'upscaler', 'api'):
        if ctx.get(key) is not None:ctx[key] = str(ctx[key]).lower()
    ctx.setdefault('store', next((store for store in ('steam', 'gog', 'epic') if ids.get(store)), None))
    supported = None if supported_keys is None else {key.lower() for key in supported_keys}
    current = {key.lower(): str(value) for key, value in (current or {}).items()}
    recipe_ini = {key.lower(): str(value) for key, value in (recipe_ini or {}).items()}
    source_commit = (data.get('sources') or {}).get('optiscaler_pinned')
    compatible = set((data.get('sources') or {}).get('optiscaler_compatible_commits', [])) | {source_commit}
    quirk_current = not optiscaler_commit or not source_commit or optiscaler_commit in compatible
    quirks = (data.get('quirk_keys') or {}).get(quirk_exe or ids.get('exe', ''), {}) if quirk_current else {}
    quirks = {key.lower(): value for key, value in quirks.items()}
    matches = wiki_matches(data, ids)
    rows, vetoes, weak_vetoes, requirements = [], {}, {}, []
    for entry, strength in matches:
        requirements.extend(dict(title=entry['title'], text=text, pages=entry.get('pages', [])) for text in entry.get('requirements', []))
        for advice in entry.get('fg_advice', []):
            when = {k: v for k, v in (advice.get('when') or {}).items() if k != 'fg_input'}
            if advice.get('advice') in ('broken', 'avoid') and evaluate(when, ctx)[0] is True:
                (vetoes if strength == 'strong' else weak_vetoes).setdefault(advice['input'], entry['title'])
        promoted = {(item['key'].lower(), str(item['value']), json.dumps(item.get('when') or {}, sort_keys=True))
                    for item in entry.get('promoted', [])}
        items = list(entry.get('ini', []))
        for item in entry.get('promoted', []):
            if item not in items and not any(old['key'].lower() == item['key'].lower() and str(old['value']) == str(item['value'])
                                             and (old.get('when') or {}) == (item.get('when') or {}) for old in items):
                items.append(item)
        for item in items:
            key, value = item['key'], str(item['value'])
            if not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_]+', key) or any(c in value for c in '\r\n\0'):
                raise ValueError('Malformed wiki INI proposal')
            low, when = key.lower(), item.get('when') or {}
            condition, reasons = evaluate(when, ctx)
            rule, rule_reason = key_rule(key, value)
            reviewed = (low, value, json.dumps(when, sort_keys=True)) in promoted
            source = dict(title=entry['title'], pages=list(entry.get('pages', [])),
                          wiki=(data.get('sources') or {}).get('wiki'), reviewed=reviewed, tested=entry.get('tested', {}))
            identity = dict(source=source, key=key, value=value, when=when)
            token = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
            confirmations = ([] if strength == 'strong' else ['Confirm this is the game named by the wiki'])
            if condition is None:
                confirmations.extend(reasons)
            action, reason = 'prefill', 'Apply only when explicitly selected'
            if condition is False:
                action, reason = 'inapplicable', '; '.join(reasons)
            elif supported is not None and low not in supported:
                action, reason = 'unsupported', 'This OptiScaler build does not define the key'
            elif low in recipe_ini:
                action, reason = 'handled', 'The curated/community recipe owns this key'
            elif low in quirks:
                action, reason = 'handled', 'Leave the key automatic for the shipped OptiScaler runtime fix'
            elif 'autoapplied_since' in when:
                action, reason = 'advice', 'Check the shipped runtime fix before setting an older workaround explicitly'
            elif rule in ('installer', 'policy', 'never', 'redundant') or low.startswith(('libraries.', 'plugins.')) or low == 'framegen.fgoutput':
                action, reason = 'advice', rule_reason or 'Library/plugin wiring belongs to the integration'
            elif reviewed and rule is None and strength == 'strong' and condition is True and current.get(low, 'auto').lower() in ('', 'auto'):
                action, reason = 'automatic', 'Reviewed fix; matching identity and conditions'
            elif confirmations:
                action, reason = 'conditional', '; '.join(confirmations)
            elif rule_reason:
                reason = ('Changes GPU-spoofing behavior; this game has no recipe/runtime owner for the key; explicit selection only'
                          if low == 'spoofing.dxgi' else rule_reason + '; explicit selection only')
            rows.append(dict(id=token, key=key, value=value, current=current.get(low), when=when,
                             condition=condition, strength=strength, action=action, reason=reason,
                             confirmations=confirmations, source=source))
    # Two simultaneously applicable sources cannot silently pick different values.
    by_key = {}
    for row in rows:
        if row['action'] in ('automatic', 'prefill'):
            by_key.setdefault(row['key'].lower(), set()).add(row['value'])
    for row in rows:
        if len(by_key.get(row['key'].lower(), ())) > 1 and row['action'] in ('automatic', 'prefill'):
            row.update(action='conflict', reason='Applicable wiki sources disagree on this value')
    rows = list({row['id']: row for row in rows}.values())
    automatic = {row['key']: row['value'] for row in rows if row['action'] == 'automatic'}
    plan = dict(format=WIKI_PLAN_FORMAT, context=ctx, rows=rows, automatic=automatic,
                vetoes=vetoes, weak_vetoes=weak_vetoes, quirks_current=quirk_current, requirements=requirements)
    plan['digest'] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan


def select_wiki_settings(plan, selected, confirmed=()):
    """Validate explicit prefill selections; no write is performed.

    confirmed contains row IDs whose displayed identity/unknown conditions the
    player confirmed. It cannot override a known false condition or a key owned
    by a recipe, runtime quirk, unsupported build, or another output generator.
    """
    if plan.get('format') != WIKI_PLAN_FORMAT:
        raise ValueError('Unsupported wiki settings plan')
    rows = {row['id']: row for row in plan['rows']}
    selected, confirmed = set(selected), set(confirmed)
    if not selected or not selected <= rows.keys() or not confirmed <= selected:
        raise ValueError('Select current wiki settings IDs; refresh the preview if it changed')
    changes, sources = {}, []
    for token in sorted(selected):
        row = rows[token]
        if row['action'] not in ('automatic', 'prefill', 'conditional'):
            raise ValueError(row['key'] + ': ' + row['reason'])
        if row['confirmations'] and token not in confirmed:
            raise ValueError(row['key'] + ': confirm the displayed game/conditions first')
        low = row['key'].lower()
        if low in changes and changes[low][1] != row['value']:
            raise ValueError('Conflicting wiki selections for ' + row['key'])
        changes[low] = (row['key'], row['value'])
        sources.append(row)
    return dict(settings={key: value for key, value in changes.values()}, selected=sources,
                plan_digest=plan['digest'])


# ---------------------------------------------------------------------------------------------- the decision
def _engine_text(scan):
    e = scan.get('engine') or {}
    if e.get('name') in (None, 'unknown'):
        return None
    return {'unreal': 'Unreal Engine', 'unity': 'Unity', 'godot': 'Godot'}.get(e['name'], e['name']) + (
        ' ' + e['version'] if e.get('version') not in (None, 'unknown') and e['name'] in ('unreal', 'unity') else '')


def _refusal(code, kind, text, way):
    return dict(code=code, kind=kind, text=text, way=way)


def names_text(names):
    """'A', 'A and B', 'A, B and C'."""
    names = list(names)
    return ' and '.join(names) if len(names) < 3 else ', '.join(names[:-1]) + ' and ' + names[-1]


def refusals(scan, verified=None, community=None, launcher_conflicts=(), launchers=None, wiki=(), explicit=False, setup=()):
    """Every refusal the evidence calls for (gamescan scan, the recipe in effect, launcher_config.conflicts, and setup:
    what install.preconditions finds in the game folder): hard ones cannot be overridden, soft ones need an explicit
    accept (Setup's Install anyway, --accept CODE), and risk ones (anti-cheat) are lifted only by the user's override for
    that one game (decide's accept_risk), never by an accept. explicit: the user chose the route and input, so a refusal
    that rests on detection alone (no DirectX 12, no input) is soft: detection can miss what the user knows."""
    out = []
    kind = 'soft' if explicit else 'hard'
    anyway = ' Install anyway (you chose the input) only if you know the game has what this check missed.' if explicit else ''
    exe = scan.get('exe') or {}
    api = scan.get('api') or {}
    recipe = verified or community
    found = scan.get('anticheat') or []
    if found:
        # A risk refusal: no accept lifts it (--accept, Install anyway); only the user's own override for this one game,
        # confirmed with the typed sentence (install.py --accept-anticheat-risk, Setup's Override anti-cheat refusal).
        names = [ac['name'] for ac in found]
        out.append(dict(_refusal('anticheat', 'risk', f'This game ships anti-cheat: {names_text(names)} ({found[0]["evidence"][0]}). This '
                                 'build loads DLLs into the game process, which anti-cheat software can treat as tampering and may ban the '
                                 'account.', 'None by default. An override for one game risks a ban: --accept-anticheat-risk '
                                 '(COMPATIBILITY.md#anti-cheat).'),
                        names=names))
    if not exe.get('selected') and exe.get('native_linux'):
        out.append(_refusal('native-linux', 'hard', 'Steam installed the Linux version of this game.',
                            'Steam: Properties, Compatibility, force a Proton version, let Steam download the Windows version, then Check again.'))
    elif not exe.get('selected'):
        out.append(_refusal('no-exe', 'hard', 'No Windows game executable was found.', 'Choose the game\'s .exe.'))
    elif exe.get('bits') == 32:
        out.append(_refusal('32bit', 'hard', 'This is a 32-bit game; XeFG and this build are 64-bit only.', 'None.'))
    confident = scan.get('complete') and exe.get('imports')
    if exe.get('selected') and exe.get('bits') == 64 and not recipe and confident:
        if not api.get('dx12') and api.get('default') in ('vulkan', 'opengl', 'd3d11', 'd3d9'):
            code = {'vulkan': 'api-vulkan', 'opengl': 'api-opengl', 'd3d9': 'api-dx9'}.get(api['default'], 'api-dx11')
            name = {'vulkan': 'Vulkan', 'opengl': 'OpenGL', 'd3d11': 'DirectX 11', 'd3d9': 'DirectX 9'}[api['default']]
            way = ('None until a DirectX 11 game is qualified (OptiScaler\'s DX11-to-DX12 bridge read shared textures as zero '
                   'under this Proton stack; expect a black screen).' if code == 'api-dx11' else 'None (a DirectX 12 mode in a game update).')
            out.append(_refusal(code, kind, f'This game renders with {name} only; XeFG works in DirectX 12 only.', way + anyway))
        elif not api.get('dx12') and not scan.get('upscalers') and not scan.get('native_xefg') and not any((scan.get('game_fg') or {}).values()):
            out.append(_refusal('no-dx12', kind, 'No DirectX 12 path and no upscaler input were found in this game' +
                                (f' (it imports {", ".join(a for a in api.get("apis", []) if not a.endswith("?"))})' if any(
                                    not a.endswith('?') for a in api.get('apis', [])) else ' (its renderer is not one this check can read)') + '.',
                                'None: frame generation needs DirectX 12 and the game\'s upscaler inputs.' + anyway))
        elif api.get('dx12') and not scan.get('upscalers') and not scan.get('native_xefg') and not any((scan.get('game_fg') or {}).values()) \
                and not scan.get('dlss_unconfirmed'):
            out.append(_refusal('no-input', kind, 'This game has no upscaler or frame-generation SDK that OptiScaler hooks (DLSS, FSR 2/3, '
                                'XeSS, DLSS FG, FSR 3.1 FG, XeSS FG), so there are no motion vectors for frame generation' +
                                (f' ({_engine_text(scan)})' if _engine_text(scan) else '') + '.',
                                'None inside this build: frame generation needs the game\'s own upscaler inputs.' + anyway))
    if exe.get('selected') and not recipe and scan.get('dlss_unconfirmed') and not scan.get('upscalers') and not scan.get('native_xefg') \
            and not any((scan.get('game_fg') or {}).values()):
        # Unity's NVIDIA module bundles the DLL whether or not the game uses DLSS: never installed automatically.
        out.append(_refusal('input-unconfirmed', 'soft', 'The only DLSS evidence is the DLL Unity bundles: ' + scan['dlss_unconfirmed'] +
                            ', so the game most likely offers no DLSS and has no input for frame generation.',
                            'Install anyway only if the game\'s graphics menu offers DLSS (then choose it there).'))
    stub = exe.get('stub')
    if stub and exe.get('best') == stub and exe.get('confidence') == 'high' and not verified:
        out.append(_refusal('wrong-exe', 'hard', f'{exe["selected"]} is the launcher stub; the game renders from {stub}.', f'Choose {stub} instead.'))
    for c in launcher_conflicts:
        out.append(dict(c))
    if launchers is not None and not launchers:
        out.append(_refusal('no-launcher', 'hard', 'No launcher entry found for this executable: no Steam, Heroic or Lutris entry starts it, '
                            'and the settings go into the game\'s launcher entry.', 'Add the game to Steam (as a non-Steam game), Heroic or '
                            'Lutris first, then Check again.'))
    fix = scan.get('protonfix')
    if fix:
        others = fix.get('others') or []
        out.append(_refusal('protonfix-api', 'soft', f'{fix["tool"]}\'s fix for this game switches it off DirectX 12 ({fix["change"]}).',
                            'Install anyway adds PROTONFIXES_DISABLE=1 to the game\'s launch options, which turns off all of GE-Proton\'s '
                            'fixes for this game' + (f' (here also: {", ".join(others)})' if others else ' (here only that switch)') +
                            '; Restore removes it.'))
    # Only a strong match (launcher ID, or exe name with title or folder): a title-only match warns (decide).
    if any(w.get('compat') == 'not-working' for w, s in wiki if s == 'strong') and not recipe:
        out.append(_refusal('wiki-not-working', 'soft', 'The OptiScaler wiki\'s compatibility list says this game does not work.',
                            'Install anyway if you want to try.'))
    for r in setup:
        out.append(dict(r, setup=True))
    return out


MATCH = object()


def decide(scan, data=None, ids=None, choice=None, ctx=None, accept=(), launcher_conflicts=(), launchers=None, quirk_exe=None,
           verified=MATCH, setup=(), accept_risk=()):
    """The verdict for one game. choice: dict(route, fg_input) chosen by the user (None: Automatic). accept: soft
    refusal codes the user accepted. accept_risk: risk refusal codes (anticheat) the user overrode for this game after
    the typed confirmation; accept never lifts one. Returns dict(tier, name, line, route, fg_input, reason, launch_args,
    launch_source, ini, ini_sources, dlss_helper, extra_env, manual_steps, warnings, refusals, blocking, accepted,
    risk_accepted, confidence, wiki, recipe, recipe_entry). verified: the verified recipe recipes.match found (None for
    none), so that the installer and the verdict use one matcher; by default it is matched here the same way. setup:
    refusals of the game folder's current state (install.preconditions): they block Install but do not change the tier."""
    ids = ids or dict(exe=Path((scan.get('exe') or {}).get('selected') or '').name.lower(), steam=set(), gog=set(), epic=set(),
                      titles=set(), folders=set())
    data = data or {}
    exe_name = ids.get('exe', '')
    found = None
    for entry in data.get('verified', []) if verified is MATCH else []:
        m = entry['match']
        by_id = any(set(ids.get(k) or ()) & set(m.get(k, [])) for k in ('steam', 'gog', 'epic'))
        known = any(ids.get(k) for k in ('steam', 'gog', 'epic'))
        title = re.sub(r'[^a-z0-9]+', ' ', entry.get('title', '').lower()).strip()
        named = (({title} | set(m.get('title', []))) - {''}) & (set(ids.get('titles') or ()) | set(ids.get('folders') or ()))
        if by_id or (exe_name in m.get('exe', []) and not known and named):
            found = entry
            break
    verified = found if verified is MATCH else verified
    community = None if verified else community_match(data, ids)
    wiki = wiki_matches(data, ids)
    strong = [w for w, s in wiki if s == 'strong']
    api = scan.get('api') or {}
    exe = scan.get('exe') or {}
    ctx = dict(DEFAULT_CONTEXT, **(ctx or {}), store=scan.get('store'), engine=(scan.get('engine') or {}).get('name'))
    quirks = (data.get('quirk_keys') or {}).get(quirk_exe or exe_name, {})
    warnings, manual, sources = [], [], {}
    recipe = verified or community
    # Vetoes (V1): strong matches whose conditions hold remove an input from the automatic candidates; weak ones warn.
    vetoes, weak_vetoes = {}, {}
    for w, strength in wiki:
        for a in w.get('fg_advice', []):
            if a['advice'] not in ('broken', 'avoid'):
                continue
            result, _ = evaluate({k: v for k, v in (a.get('when') or {}).items() if k != 'fg_input'}, ctx)
            if result is True:
                (vetoes if strength == 'strong' else weak_vetoes).setdefault(a['input'], w['title'])
    for problem in (community or {}).get('known_problems', []):
        if problem.get('input'):
            vetoes.setdefault(problem['input'], 'BC-250 reports')
    # Route and FG input.
    route = fg_input = None
    reason, choice_source = '', 'detection'
    native_ok = bool(scan.get('native_xefg'))
    if choice and choice.get('route'):
        route, fg_input, choice_source = choice['route'], choice.get('fg_input') or 'upscaler', 'user'
        reason = 'chosen by you'
    # A verified native recipe needs only the game's libxess_fg.dll beside the executable (0.9.0's main()); an XeSSMFG
    # folder there changes the automatic choice of games without a recipe, not a verified recipe's route.
    elif recipe and (recipe['route'] == 'opti' or native_ok or (verified and scan.get('xefg_beside'))):
        route, fg_input = recipe['route'], recipe.get('fg_input') or 'upscaler'
        choice_source = 'verified' if verified else 'community'
        reason = ('the recipe verified on BC-250' if verified else 'the community recipe')
    else:
        game_fg = scan.get('game_fg') or {}
        if native_ok and 'native-xefg' not in vetoes:
            route, fg_input, reason = 'native', 'upscaler', 'the game ships XeSS FG beside its executable'
        elif scan.get('upscalers') and 'upscaler' not in vetoes:
            route, fg_input = 'opti', 'upscaler'
            reason = 'OptiFG from the game\'s ' + ', '.join(UPSCALER_NAMES.get(u, u) for u in scan['upscalers'])
            if native_ok:
                reason += ' (the OptiScaler wiki reports native XeSS FG broken here: ' + vetoes['native-xefg'] + ')'
        else:
            for key, flag in (('fsrfg', 'fsrfg_sdk2'), ('dlssg', 'dlssg'), ('fsrfg', 'fsrfg_combined')):
                if game_fg.get(flag) and key not in vetoes:
                    route, fg_input = 'opti', key
                    reason = f'{INPUT_NAMES[key]} input from the game\'s own frame generation' + (
                        ' (the OptiScaler wiki reports OptiFG broken here: ' + vetoes['upscaler'] + ')' if 'upscaler' in vetoes else '')
                    hint = ', '.join(scan.get('fg_toggle_hints') or [])
                    manual.append('Turn on the game\'s own frame generation' + (f' ({hint})' if hint else '') +
                                  f'; {INPUT_NAMES[key]} input generates only while it is on.')
                    break
        if route is None:
            route, fg_input, reason = 'opti', 'upscaler', 'no input was found; OptiFG is the default'
            if scan.get('dlss_unconfirmed'):
                reason = 'OptiFG from the DLSS DLL Unity bundles (the game\'s use of it was not found)'
            if not ((scan.get('complete') and exe.get('imports') and api.get('dx12'))):
                warnings.append('Detection found no upscaler input, but it could not read enough of the game to be sure.')
    if choice_source == 'user':
        here = 'native-xefg' if route == 'native' else fg_input
        if here in vetoes:
            warnings.append(f'The OptiScaler wiki reports {INPUT_NAMES.get(here, here)} broken in this game ({vetoes[here]}); installed as you chose.')
    here = 'native-xefg' if route == 'native' else fg_input
    if here in weak_vetoes and here not in vetoes:
        warnings.append(f'The OptiScaler wiki ({weak_vetoes[here]}) reports problems with {INPUT_NAMES.get(here, here)}; '
                        'it is matched by title only, so this is not applied.')
    if any(w.get('compat') == 'not-working' for w, s in wiki if s == 'weak') and not recipe:
        warnings.append('The OptiScaler wiki\'s compatibility list says a game of this title does not work; it is matched by title '
                        'only, so this is not applied.')
    if fg_input == 'fsrfg30' and choice_source != 'user':
        fg_input = 'upscaler'
    ctx['fg_input'] = here
    # Launch argument: one API switch. launcher_config.with_args adds none where the user's options already choose an API.
    current = [a.lower() for a in api.get('current_switch') or []]
    if any(a in OFF_DX12_ARGS for a in current):
        warnings.append('Your launch options select ' + ' '.join(a for a in current if a in OFF_DX12_ARGS) +
                        ': XeFG works in DirectX 12 only; remove it.')
    launch_args, launch_source, wiki_applied = [], None, []
    if verified:
        # 0.9.0's rule, unchanged: the verified recipe's own argument (recipes.launch_args).
        launch_args = list(verified.get('launch_args', []))[:1]
        launch_source = 'verified recipe' if launch_args else None
    elif community and community.get('launch_args'):
        launch_args, launch_source = list(community['launch_args'])[:1], 'community recipe'
    else:
        for w, strength in wiki:
            args = [a for a in w.get('launch_args', []) if a.lower() in DX12_ARGS]
            # L1: a strong match, or a title match where detection confirms the game's DX12 path.
            if args and (strength == 'strong' or api.get('dx12')):
                launch_args, launch_source = args[:1], f'OptiScaler wiki ({w["title"]})'
                if strength == 'strong':
                    wiki_applied.append('launch option')
                break
        if not launch_args and api.get('dx12') and api.get('switch'):
            launch_args = api['switch'].split()
            launch_source = 'detection (' + (api.get('switch_kind') or 'DX12 switch') + ')'
    if not launch_args and not current and not recipe and api.get('dx12') and api.get('default') not in ('d3d12', None):
        manual.append('Select DirectX 12 in the game\'s own settings.')
    if choice_source == 'detection' and any(i in vetoes for i in ('native-xefg', 'upscaler', 'dlssg', 'fsrfg')):
        wiki_applied.append('FG input veto')
    # OptiScaler keys: community recipe (layer 4), promoted wiki items (layer 5); never a key a quirk sets (Q1/Q3).
    ini = {}
    if community:
        for key, value in community.get('ini', {}).items():
            if key not in quirks:
                ini[tuple(key.split('.', 1))] = str(value)
                sources[key] = 'community recipe'
    # The same pure planner is consumed by Proton integrations and explicit INI
    # prefills. A curated recipe, community recipe or runtime quirk stays above it.
    wiki_settings = wiki_plan(data or {}, ids, ctx, recipe_ini={
        **((verified or {}).get('ini') or {}), **{'.'.join(key): value for key, value in ini.items()}},
        quirk_exe=quirk_exe)
    if not verified:
        for key, value in wiki_settings['automatic'].items():
            ini[tuple(key.split('.', 1))] = value
            source = next(row['source']['title'] for row in wiki_settings['rows'] if row['key'] == key and row['action'] == 'automatic')
            sources[key] = f'OptiScaler wiki ({source}), promoted'
            wiki_applied.append(key)
    # DLSS helper: DLSS is the game's only hookable upscaler and the game ships no copy (OptiFG needs DLSS to show).
    dlss_helper = 'auto'
    if not verified and route == 'opti' and fg_input == 'upscaler' and scan.get('upscalers') == ['dlss'] and not scan.get('dlss_copy'):
        dlss_helper = 'yes'
    # Proxy name, OptiPatcher, wiki tests: shown.
    for w, strength in wiki:
        names = [n for n in w.get('proxy', []) if n.lower().endswith(('.dll', '.asi'))]
        if names and not any(n.lower() == 'dxgi.dll' for n in names):
            warnings.append(f'The OptiScaler wiki reports this game needs OptiScaler as {" or ".join(names)}; this installer uses dxgi.dll, '
                            'which may not load.')
            manual.append('If OptiScaler does not load (no overlay with Insert), this game needs another proxy name (see the OptiScaler wiki).')
            break
    if route == 'native':
        manual.insert(0, 'Turn on the game\'s XeSS frame generation in its graphics settings.')
    elif any(s.get('values', {}).get('ResolutionScaling') == 'DLSS'
             for s in (verified or {}).get('game_settings', [])):
        step = 'Select DLSS upscaling in the game\'s graphics settings; your chosen upscaler takes its place.'
        if fg_input == 'dlssg':
            step += ' Enable DLSS frame generation for XeFG.'
        manual.insert(0, step)
    else:
        manual.insert(0, 'In the game\'s graphics settings choose its upscaler (DLSS, FSR or XeSS: your chosen upscaler takes its place).')
    if verified and verified.get('note'):
        warnings.append('Known on BC-250: ' + verified['note'])
    manual += list((verified or {}).get('manual_steps', []))
    manual += list((community or {}).get('manual_steps', []))
    # Refusals.
    found = refusals(scan, verified, community, launcher_conflicts, launchers, wiki, explicit=choice_source == 'user', setup=setup)
    if choice_source == 'user' and route == 'native' and not scan.get('xefg_beside') and exe.get('selected'):
        found.insert(0, _refusal('no-native-xefg', 'hard', 'Native XeSS FG needs the game\'s own libxess_fg.dll beside its executable, '
                                 'and there is none.', 'Choose an OptiScaler input (OptiFG) instead.'))
    def lifted(r):
        # A hard refusal never; a soft one by an accept; a risk one only by accept_risk (an accept of its code does nothing).
        return (r['kind'] == 'soft' and r['code'] in accept) or (r['kind'] == 'risk' and r['code'] in accept_risk)
    accepted = [r['code'] for r in found if r['kind'] == 'soft' and lifted(r)]
    risk_accepted = [r['code'] for r in found if r['kind'] == 'risk' and lifted(r)]
    blocking = [r for r in found if not lifted(r)]
    refused = [r for r in blocking if not r.get('setup')]
    extra_env = {'PROTONFIXES_DISABLE': '1'} if 'protonfix-api' in accepted else {}
    # Confidence for the two things detection can get wrong.
    confidence = dict(exe=exe.get('confidence', 'low') if exe.get('selected') == exe.get('best') else 'low',
                      api=api.get('confidence', 'low'))
    if recipe:
        confidence = dict(exe='high', api='high')
    if refused:
        tier = 'R'
    elif verified:
        tier = 'A'
    elif community:
        tier = 'B'
    elif wiki_applied:
        tier = 'C'
    else:
        tier = 'D'
    standard = 1
    verdict = dict(tier=tier, name=TIER_NAMES[tier], route=route, fg_input=fg_input, reason=reason, choice=choice_source,
                   launch_args=launch_args, launch_source=launch_source, ini=ini, ini_sources=sources, dlss_helper=dlss_helper,
                   extra_env=extra_env, manual_steps=manual, needs_step=len(manual) > standard, warnings=warnings,
                   refusals=found, blocking=blocking, accepted=accepted, risk_accepted=risk_accepted, confidence=confidence, vetoes=vetoes,
                   recipe=dict(title=recipe['title'], status='verified-bc250' if verified else 'community-bc250',
                               evidence=(verified or {}).get('evidence'), observed=(verified or {}).get('observed'),
                               reports=(community or {}).get('reports')) if recipe else None,
                   wiki=[dict(title=w['title'], strength=s, pages=w.get('pages', [])) for w, s in wiki], wiki_applied=wiki_applied,
                   recipe_entry=recipe, wiki_settings=wiki_settings)
    verdict['line'] = verdict_line(verdict, scan)
    return verdict


def verdict_line(v, scan):
    """One sentence for Setup and the command line."""
    refused = [r for r in v['blocking'] if not r.get('setup')]
    if refused:
        return f'{TIER_NAMES["R"]}: {refused[0]["text"]} {refused[0]["way"]}'
    first = [r for r in v['blocking'] if r.get('setup')]
    return _plan_line(v, scan) + (f'. Before Install: {first[0]["text"]} {first[0]["way"]}' if first else '')


def _plan_line(v, scan):
    route = 'native XeSS FG' if v['route'] == 'native' else INPUT_NAMES.get(v['fg_input'], v['fg_input']) + ' input'
    args = (', launch option ' + ' '.join(v['launch_args'])) if v['launch_args'] else ''
    if v['tier'] == 'A':
        r = v['recipe']
        level = EVIDENCE.get(r.get('evidence') or '', '')
        return f'{TIER_NAMES["A"]}: {r["title"]}' + (f' ({r["observed"] or level})' if (r.get('observed') or level) else '') + f'; {route}{args}'
    if v['tier'] == 'B':
        n = v['recipe'].get('reports') or 0
        return f'Reported working on BC-250 by {n} report{"s" if n != 1 else ""} (not reproduced by the maintainers): {v["recipe"]["title"]}; {route}{args}'
    engine = _engine_text(scan)
    inputs = ', '.join(UPSCALER_NAMES.get(u, u) for u in scan.get('upscalers') or [])
    detail = ', '.join(x for x in (engine, inputs) if x)
    head = TIER_NAMES[v['tier']] + (f': detected {detail}' if detail else '')
    step = ' (needs one step from you)' if v['needs_step'] else ''
    return f'{head} → {route}{args}{step}'


def preflight(verdict):
    """Raise Refused for the first refusal that blocks an install (hard, soft and not accepted, or risk and not
    overridden)."""
    if verdict['blocking']:
        raise Refused(verdict['blocking'][0])


# -------------------------------------------------------------------------------------- what the wiki says, evaluated
def wiki_advice(data, ids, verdict, ctx=None, quirk_exe=None):
    """What Check lists from the matched wiki entries: dict(applied, shown, hidden, links, tested). Every item's
    condition is evaluated for this install; hidden counts what does not apply here or is handled already."""
    ctx = dict(DEFAULT_CONTEXT, **(ctx or {}))
    ctx['fg_input'] = 'native-xefg' if verdict['route'] == 'native' else verdict['fg_input']
    quirks = ((data or {}).get('quirk_keys') or {}).get(quirk_exe or ids.get('exe', ''), {})
    applied, shown, hidden, links, tested = [], [], {}, [], []
    # What the recipe in effect sets itself (its keys and game settings), and who chose the input.
    entry = verdict.get('recipe_entry') or {}
    kind = 'verified recipe' if (verdict.get('recipe') or {}).get('status') == 'verified-bc250' else 'community recipe'
    recipe_ini = {k.lower(): str(v) for k, v in (entry.get('ini') or {}).items()}
    recipe_settings = {str(k).lower(): str(v) for s in entry.get('game_settings') or [] for k, v in (s.get('values') or {}).items()}
    chooser = {'user': 'your choice', 'verified': 'the verified recipe', 'community': 'the community recipe'}.get(verdict.get('choice'))
    for w, strength in wiki_matches(data, ids):
        shown.extend(w.get('requirements', []))
        links += [p for p in w.get('pages', []) if p not in links]
        t = w.get('tested') or {}
        if t:
            tested.append(f'{w["title"]}: tested on ' + ', '.join(filter(None, ['/'.join(t.get('os', [])[:2]), '/'.join(t.get('gpu', [])[:2]),
                                                                                  'OptiScaler ' + '/'.join(t['optiscaler'][:2]) if t.get('optiscaler') else '']))
                          + ('; Linux reported' if t.get('linux') else ''))
        if w.get('optipatcher'):
            shown.append('OptiPatcher unlocks the upscalers for this game (placed by a fresh setup).')
        for item in w.get('ini', []):
            key, value = item['key'], item['value']
            result, why = evaluate(item.get('when'), ctx)
            text = f'{key}={value}'
            if result is False:
                hidden[why[0]] = hidden.get(why[0], 0) + 1
                continue
            if 'autoapplied_since' in (item.get('when') or {}) or quirks.get(key, '').split('@')[0] == value:
                hidden['already handled by OptiScaler'] = hidden.get('already handled by OptiScaler', 0) + 1
                continue
            if tuple(key.split('.', 1)) in verdict['ini'] and verdict['ini'][tuple(key.split('.', 1))] == value:
                applied.append(f'{text} ({verdict["ini_sources"].get(key, "applied")})')
                continue
            if key.lower() in recipe_ini:
                (applied if recipe_ini[key.lower()] == str(value) else shown).append(
                    f'{text} (the {kind} sets it)' if recipe_ini[key.lower()] == str(value) else
                    f'{text}: not applied; the {kind} sets {key}={recipe_ini[key.lower()]}')
                continue
            if key in quirks:
                shown.append(f'{text}: not applied; OptiScaler\'s own fix for this game sets {key} (Q1)')
                continue
            cls, reason = key_rule(key, value)
            if cls in ('redundant',):
                hidden['already handled by the installer'] = hidden.get('already handled by the installer', 0) + 1
            elif cls == 'never':
                hidden[reason] = hidden.get(reason, 0) + 1
            elif cls == 'policy':
                shown.append(f'{text}: not applied (warning: {reason})')
            elif cls:
                shown.append(f'{text}: not applied automatically ({reason})')
            elif result is None:
                shown.append(f'{text}: a known fix when {"; ".join(why)} (set it in OptiScaler\'s menu if that applies)')
            else:
                shown.append(f'{text}: suggested (not reviewed for automatic use)' + ('' if strength == 'strong' else '; matched by title'))
        for a in w.get('fg_advice', []):
            result, why = evaluate({k: v for k, v in (a.get('when') or {}).items() if k != 'fg_input'}, ctx)
            if result is False:
                hidden[why[0]] = hidden.get(why[0], 0) + 1
                continue
            name = INPUT_NAMES.get(a['input'], a['input'])
            if a['input'] in ('nukems', 'native-fsrfg'):
                hidden['an FG input this build never uses (F0)'] = hidden.get('an FG input this build never uses (F0)', 0) + 1
            elif a['advice'] == 'prefer':
                shown.append(f'Prefers {name} input (a suggestion; F3)')
            elif a['advice'] not in ('broken', 'avoid'):
                shown.append(f'Reports {name} input working')
            elif a['input'] in verdict['vetoes'] and verdict.get('choice') == 'detection':
                applied.append(f'{name} input left out of the automatic choice (reported broken)')
            elif a['input'] in verdict['vetoes']:
                shown.append(f'Reports problems with {name} input (not used here: {chooser} decides the input)')
            else:
                shown.append(f'Reports problems with {name} input' + (f' when {"; ".join(why)}' if result is None else '') +
                             ('' if strength == 'strong' else ' (matched by title)'))
        for s in w.get('game_settings', []):
            text = f'Game setting {s["key"]}={s["value"]}' + (f' in {s["file"]}' if s.get('file') else '')
            mine = recipe_settings.get(str(s['key']).lower())
            if mine is not None and mine == str(s['value']):
                applied.append(f'{text} (the {kind} sets it)')
            elif mine is not None:
                shown.append(f'{text}: not applied; the {kind} sets {s["key"]}={mine}')
            else:
                shown.append(f'{text} (a recipe candidate; not applied)')
        for arg in w.get('other_launch_args', []):
            if arg.lower() in OFF_DX12_ARGS:
                hidden['launch options that leave DirectX 12'] = hidden.get('launch options that leave DirectX 12', 0) + 1
            else:
                shown.append(f'Launch option {arg} (not applied)')
        if verdict['launch_source'] and verdict['launch_source'].startswith('OptiScaler wiki') and w['title'] in verdict['launch_source']:
            applied.append('Launch option ' + ' '.join(verdict['launch_args']))
        if w.get('compat') == 'not-working':
            shown.append('The compatibility list says this game does not work' + ('.' if strength == 'strong' else ' (matched by title).'))
    return dict(applied=list(dict.fromkeys(applied)), shown=list(dict.fromkeys(shown)), hidden=hidden, links=links, tested=tested)


# ------------------------------------------------------------------------------------------------- after a run
# Programs this build replaces in a fully accelerated session: BC250-XeFG-fast.log has one "REPLACE <hash> <bytes>" line
# per program, 13 in every full session measured (2x/3x/4x, SDR and HDR10, native and OptiScaler routes; Cyberpunk 2077,
# 2026-10-21). With MFG Unlocker's own model (OptiScaler.ini [XeFG] XeFGModel not default) 7 of them ran.
# BC250-MFG.log is written afresh at every start; BC250-XeFG-fast.log only in a session with FAST_OWNER, so without that
# line the fast log is an earlier session's.
FULL_PROGRAMS = 13
MFG_UNLOCKER_PROGRAMS = 7
MFG_UNLOCKER_CHECKED = 'v1.6.0'
XEFG_MODEL_FIX = 'set XeFGModel=default under [XeFG] in OptiScaler.ini (a new Install writes it where it is unset)'
# The game folder's logs are read up to this size (a long session's log is larger; its beginning names the case).
LOG_LIMIT = 8 << 20


def _read(root, *names, since=None):
    """The first of names in root that is a regular file (not a symlink), decoded leniently; None when there is none.
    since: a POSIX time; a file last written before it is treated as absent."""
    for name in names:
        p = Path(root) / name
        try:
            if p.is_file() and not p.is_symlink() and (since is None or p.stat().st_mtime >= since):
                with open(p, 'rb') as f:
                    return f.read(LOG_LIMIT).decode('utf-8-sig', 'replace')  # a BOM, as install.read_ini accepts
        except OSError:
            continue
    return None


def xefg_model(root):
    """OptiScaler.ini [XeFG] XeFGModel in the game folder, stripped ('' when the line is empty), or None when the file or
    the key is missing. Read line by line like OptiScaler (sections and keys in any case), so an INI configparser
    refuses still answers; the last value wins."""
    text = _read(root, 'OptiScaler.ini')
    if text is None:
        return None
    section, value = '', None
    for line in text.splitlines():
        header = re.match(r'\s*\[([^]]+)\]\s*$', line)
        if header:
            section = header[1].strip().lower()
            continue
        key, eq, rest = line.partition('=')
        if eq and section == 'xefg' and key.strip().lower() == 'xefgmodel':
            value = rest.strip()
    return value


def mfg_unlocker_file(root):
    """MFG Unlocker's plugin in the game folder (OptiScaler/plugins/ or plugins/: an .asi whose name contains 'mfg',
    other than this build's BC250-MFG.asi), as a relative path, or None."""
    for folder in ('OptiScaler/plugins', 'plugins'):
        try:
            names = sorted(p.name for p in (Path(root) / folder).iterdir())
        except OSError:
            continue
        for name in names:
            low = name.lower()
            if low.endswith('.asi') and 'mfg' in low and low != 'bc250-mfg.asi':
                return f'{folder}/{name}'
    return None


def _mfg_unlocker_files(root):
    """The RTXMFG-* files MFG Unlocker writes beside the executable (its status and log), or []."""
    try:
        return sorted(p.name for p in Path(root).iterdir() if p.name.startswith('RTXMFG-'))
    except OSError:
        return []


def last_run(root, route=None, beside_exe=False, since=None):
    """What the logs in the game folder say about the last session: dict(found, optiscaler, xefg, fg_input, upscaler,
    proxy, accelerated, problems, cause, own_programs, f4q, owner, coexist_accelerated, skipped_game_context,
    context_caller, other_module, aside, mfg_unlocker, mfg_unlocker_files, xefg_model, route, fast_stale, acceleration,
    acceleration_reason, output, output_fallbacks). output: the FP16 forms' state of the last session (dict(mode, source,
    forms) from its FP16_CONFIG line; None when the log has none: builds before 1.1.2). output_fallbacks: the shaders of its
    F4Q_FALLBACK and FP16_FALLBACK lines (pipelines that ran an exact form instead; an FP16 pipeline that could not be
    created logs FP16_REPLACE first, then F4Q_FALLBACK). route: the installation's route ('native' or 'opti', None when unknown); the logs alone tell
    the game's own XeSS FG beside MFG Unlocker (FAST_SKIP, no CONTEXT_CALLER) from OptiScaler's FG with
    BC250_XEFG_DISABLE (FAST_SKIP and a CONTEXT_CALLER line), the route breaks a tie. fast_stale: BC250-XeFG-fast.log is
    from an earlier session (BC250-MFG.log, written at every start, has no FAST_OWNER) and is not counted.
    acceleration: 'full', 'partial', 'not-running', 'idle' (no frame-generation context) or None (the logs do not say).
    beside_exe: read only the logs beside the executable, where this build writes them (an installation of this build;
    logs under OptiScaler/ come from private test builds before 0.9.0). since: the installation's time; logs last
    written before it are from before the installation and are not read.
    Reads only; nothing is sent anywhere."""
    root = Path(root)
    opti = _read(root, 'OptiScaler.log', *(() if beside_exe else ('OptiScaler/OptiScaler.log',)), since=since)
    proxy = _read(root, 'BC250-MFG.log', *(() if beside_exe else ('OptiScaler/plugins/BC250-MFG.log',)), since=since)
    fast = _read(root, 'BC250-XeFG-fast.log', *(() if beside_exe else ('OptiScaler/BC250-XeFG-fast.log',
                                                                     'OptiScaler/plugins/BC250-XeFG-fast.log')), since=since)
    out = dict(found=bool(opti or proxy or fast), optiscaler=opti is not None, xefg=False, fg_input=None, upscaler=None,
               proxy=None, accelerated=0, problems=[], cause=None, own_programs=0, f4q=0, owner=False, coexist_accelerated=False,
               skipped_game_context=False, context_caller=False, other_module=False, aside=None, mfg_unlocker=None,
               mfg_unlocker_files=_mfg_unlocker_files(root), xefg_model=xefg_model(root), route=route, fast_stale=False,
               acceleration=None, acceleration_reason=None, output=None, output_fallbacks=[])
    if opti:
        out['xefg'] = 'XeFG swapchain created' in opti or 'XeFG context created' in opti
        m = re.findall(r'FrameGen\.FGInput:\s*(\S+)', opti)
        out['fg_input'] = m[-1] if m else None
        if re.search(r'TryCreateOptiFeature Creating|CreateFeature', opti):
            out['upscaler'] = 'DLSS' if 'NVSDK_NGX' in opti else 'FSR' if re.search(r'ffx|FSR', opti) else 'XeSS' if 'xess' in opti.lower() else 'yes'
        out['problems'] += [line.split('] ', 2)[-1][:160] for line in opti.splitlines() if '[E]' in line and 'streamline' not in line.lower()][:3]
    if proxy:
        out['proxy'] = 'ready' if 'MFG proxy ready' in proxy else 'failed' if 'MFG proxy:' in proxy else 'loaded'
        out['xefg'] = out['xefg'] or 'MFG proxy ready' in proxy or 'MFG addon ready' in proxy
        out['problems'] += [line[:160] for line in proxy.splitlines() if line.startswith('MFG proxy:')][:3]
        out['owner'] = bool(re.search(r'^FAST_OWNER ', proxy, re.M))
        out['coexist_accelerated'] = bool(re.search(r'^FAST_COEXIST this context is accelerated', proxy, re.M))
        out['skipped_game_context'] = bool(re.search(r'^FAST_SKIP beside another module', proxy, re.M))
        out['context_caller'] = bool(re.search(r'^CONTEXT_CALLER ', proxy, re.M))
        out['other_module'] = bool(re.search(r'^FAST_COEXIST another module hooks', proxy, re.M))
        module = re.search(r'^FAST_COEXIST .*?jumps to ([^)\r\n]+)\)', proxy, re.M)
        if module:
            out['mfg_unlocker'] = re.split(r'[\\/]', module[1].strip())[-1] or None
    # BC250-MFG.log is new at every start (also when a session ends before its first line); the fast log only in a
    # session that selected a context, so without FAST_OWNER here it is an earlier session's.
    if proxy is not None and fast is not None and not out['owner'] and not out['coexist_accelerated']:
        out['fast_stale'], fast = True, None
    aside = re.search(r'^FAST_ASIDE (.+?)(?:, with another module|$)', proxy or fast or '', re.M)
    if aside:
        out['aside'] = aside[1].strip()[:120]
    if fast:
        out['accelerated'] = len(set(re.findall(r'WINOGRAD_EXECUTE shader=([0-9a-f]+)', fast)))
        out['own_programs'] = len(set(re.findall(r'^REPLACE ([0-9A-Fa-f]+)\b', fast, re.M)))
        out['f4q'] = len(re.findall(r'^F4Q_REPLACE ', fast, re.M))
        forms = re.findall(r'^FP16_CONFIG mode=(on|off) source=(\S+) forms=(\d+)', fast, re.M)
        if forms:
            out['output'] = dict(mode=forms[-1][0], source=forms[-1][1], forms=int(forms[-1][2]))
        out['output_fallbacks'] = sorted(set(re.findall(r'^(?:F4Q|FP16)_FALLBACK ([0-9a-f]{16})\b', fast, re.M)))
        if 'FAIL' in fast:
            out['problems'].append('a FAIL marker in BC250-XeFG-fast.log')
    if out['mfg_unlocker'] is None:
        out['mfg_unlocker'] = mfg_unlocker_file(root) or next(iter(out['mfg_unlocker_files']), None)
    if out['found'] and not out['xefg']:
        if not opti:
            out['cause'] = 'OptiScaler did not log anything: it may not have loaded (check the launch options and that the game started from its launcher).'
        elif out['upscaler'] is None:
            out['cause'] = 'The game never created an upscaler: choose DLSS, FSR or XeSS in its graphics settings, then play past the menus.'
        else:
            out['cause'] = 'The upscaler ran but XeFG never started: check FG Input / XeFG Output in OptiScaler\'s menu (Insert), or reinstall with another input.'
    out['acceleration'], out['acceleration_reason'] = _acceleration(out, proxy, fast)
    return out


def _is_mfg_unlocker(summary):
    """MFG Unlocker by its plugin's or the hooking module's name, or by the RTXMFG-* files it writes."""
    return 'mfg' in (summary.get('mfg_unlocker') or '').lower() or bool(summary.get('mfg_unlocker_files'))


def _acceleration(out, proxy, fast):
    """(acceleration, reason) for last_run; reason: 'aside' (not running: a FAST_ASIDE line, this build stepped aside
    beside another module), 'mfg-unlocker-model' (partial beside MFG Unlocker or another module hooking Intel's runtime,
    XeFGModel not default) or 'native-beside-mfg-unlocker' (not running: the game's own XeSS FG context, skipped beside
    another module hooking Intel's runtime, on either route), else None."""
    if out['aside']:
        return 'not-running', 'aside'
    n = out['own_programs']
    if n:
        if n >= FULL_PROGRAMS:
            return 'full', None
        model = (out['xefg_model'] or '').strip().lower()
        beside = out['other_module'] or _is_mfg_unlocker(out)
        return 'partial', ('mfg-unlocker-model' if beside and model != 'default' else None)
    if fast is not None or out['owner'] or out['coexist_accelerated'] or proxy is None or not re.search(r'^(MFG|FAST_)', proxy, re.M):
        return None, None  # a log of another format, or a context selected that replaced nothing: the logs do not say
    # The game's own context skipped and none of OptiScaler's reached the choice (no CONTEXT_CALLER line; with
    # BC250_XEFG_DISABLE an OptiScaler context logs one). On the native route there is no OptiScaler context at all.
    if out['skipped_game_context'] and (not out['context_caller'] or out['route'] == 'native'):
        return 'not-running', 'native-beside-mfg-unlocker'
    generated = re.search(r'^MFG_FACTOR |^MFG_STATUS XeFG generates|^MFG_PRESENT enabled=1', proxy, re.M)
    if not generated and re.search(r'^MFG_(SETTINGS|PRESENT) ', proxy, re.M):
        return 'idle', None
    return 'not-running', None


def acceleration_lines(summary):
    """The lines that name the last session's acceleration (last_run's acceleration), [] when the logs do not say."""
    kind, why = summary.get('acceleration'), summary.get('acceleration_reason')
    n = summary.get('own_programs') or 0
    name = summary.get('mfg_unlocker')
    unlocker = _is_mfg_unlocker(summary)
    if kind == 'full':
        return [f'Acceleration: full (this build\'s shaders ran on {n} of {FULL_PROGRAMS} programs).' if n == FULL_PROGRAMS
                else f'Acceleration: full (this build\'s shaders ran on {n} programs).']
    if kind == 'partial' and why == 'mfg-unlocker-model':
        model = 'MFG Unlocker\'s own model' if unlocker else f'the own model of the module hooking Intel\'s runtime ({name or "unnamed"})'
        return [f'Acceleration: partial (this build\'s shaders ran on {n} of {FULL_PROGRAMS} programs): {model} '
                'replaced the rest.', 'Fix: ' + XEFG_MODEL_FIX + '.']
    if kind == 'partial':
        return [f'Acceleration: partial (this build\'s shaders ran on {n} of {FULL_PROGRAMS} programs).']
    if kind == 'not-running' and why == 'aside':
        return [f'Acceleration: stepped aside during the session ({summary.get("aside")}): Intel\'s or the other module\'s shaders '
                'ran from then on.',
                f'Fix: use MFG Unlocker {MFG_UNLOCKER_CHECKED} (the version this build was checked with) with XeFGModel=default, '
                'or remove the other module.']
    if kind == 'not-running' and why == 'native-beside-mfg-unlocker':
        opti = summary.get('route') == 'opti'
        if not name or unlocker:
            return ['Acceleration: none. MFG Unlocker is loaded and the game\'s own XeSS frame generation was used: this build '
                    'accelerates only OptiScaler\'s frame generation beside MFG Unlocker.',
                    'Fix: in the game, use the frame generation of the installation\'s OptiScaler input instead of XeSS frame '
                    'generation, or remove MFG Unlocker for 2×.' if opti else
                    'Fix: remove MFG Unlocker for 2×, or install on the OptiScaler route for 3×/4×.']
        return [f'Acceleration: none. Another module ({name}) hooks Intel\'s XeFG runtime and the game\'s own XeSS frame generation '
                'was used: this build accelerates only OptiScaler\'s frame generation beside it.',
                'Fix: remove that module, or use OptiScaler\'s frame generation.' if opti else
                'Fix: remove that module, or install on the OptiScaler route.']
    if kind == 'not-running' and not summary.get('cause') and summary.get('proxy') != 'failed':
        return ['Acceleration: none (no acceleration log' + (' from this session' if summary.get('fast_stale') else '') + ').',
                'Check: the launch options for BC250_XEFG_DISABLE, and BC250-MFG.log for FAST_FALLBACK, FAST_SKIP or FAST_ASIDE lines.']
    if kind == 'idle':
        return ['Acceleration: not used (no XeFG frame-generation context in the last session).']
    return []


def setup_notes(root, route=None, installed=True, run=None):
    """Lines about MFG Unlocker from the game folder's files alone (no logs): on the native route this build does not
    accelerate the game's own context beside it; on the OptiScaler route of an installation (installed) it needs XeFGModel=default. A line that the last
    run's acceleration lines (run: last_run) already give is left out."""
    found = mfg_unlocker_file(root)
    if not found:
        return []
    run = run or {}
    if route == 'native':
        if run.get('acceleration_reason') == 'native-beside-mfg-unlocker':
            return []
        return [f'MFG Unlocker ({found}) is in this game folder: on the native route this build does not accelerate the '
                'game\'s own XeSS frame generation beside it, which then runs without this build\'s shaders. Remove it for 2×, '
                'or install on the OptiScaler route for 3×/4×.']
    model = xefg_model(root)
    if installed and (model or '').lower() != 'default' and run.get('acceleration_reason') != 'mfg-unlocker-model':
        state = 'not set' if not model else model
        return [f'MFG Unlocker ({found}) is in this game folder and XeFGModel is {state}: on MFG Unlocker\'s own model this '
                f'build\'s shaders run on {MFG_UNLOCKER_PROGRAMS} of their {FULL_PROGRAMS} programs. Fix: {XEFG_MODEL_FIX}.']
    return []


EXACT_HOW = 'BC250_XEFG_EXACT=1 in the launch options or Exact=1 in BC250-XeFG/settings.ini'


def output_lines(summary):
    """The line that names the last session's output form (last_run's output, 1.1.2 and later), [] when the log does not
    say."""
    form = summary.get('output')
    if not form:
        return []
    if form['mode'] == 'on':
        fallbacks = summary.get('output_fallbacks') or []
        if fallbacks:
            return [f'Output: the FP16 forms ran (the default), but {len(fallbacks)} shader(s) ran an exact form instead (fallback '
                    'lines in BC250-XeFG-fast.log): generated frames differ slightly from Intel\'s. For output identical to '
                    f'Intel\'s in every test: {EXACT_HOW}.']
        return ['Output: the FP16 forms ran (the default): generated frames differ slightly from Intel\'s. For output '
                f'identical to Intel\'s in every test: {EXACT_HOW}.']
    if form['source'] in ('BC250_XEFG_EXACT', 'settings.ini'):
        return [f'Output: exact (set by {form["source"]}): identical to Intel\'s in every test.']
    if form['source'] == 'F4Q':
        return ['Output: exact (F4Q was off or in its diagnostic, so the FP16 forms were off).']
    return ['Output: exact (the model layout did not fit the FP16 forms).']


def last_run_lines(summary):
    if not summary['found']:
        return ['No logs yet: start the game once with frame generation on.']
    acceleration = acceleration_lines(summary)
    lines = ['XeFG ' + ('started (swap chain created)' if summary['xefg'] else 'did not start') +
             (f'; FG input {summary["fg_input"]}' if summary['fg_input'] else '') +
             (f'; upscaler input {summary["upscaler"]}' if summary['upscaler'] else '' if summary['xefg'] else '; no upscaler input seen') +
             (f'; accelerated stages {summary["accelerated"]}/4' if summary['accelerated'] and not acceleration else '')]
    lines += acceleration
    lines += output_lines(summary)
    lines += ['Log: ' + p for p in summary['problems']]
    if summary['cause']:
        lines.append('Likely cause: ' + summary['cause'])
    return lines


# --------------------------------------------------------------------------------------------- Check and the report
def check_lines(verdict, scan, advice=None, run=None, installed=None, installed_notes=()):
    """The text of install.py check / Setup's Check for one game. installed_notes: lines about the installation (an
    anti-cheat override, install.risk_lines)."""
    exe = scan.get('exe') or {}
    api = scan.get('api') or {}
    out = [verdict['line'], '']
    out.append('Game: ' + (scan.get('name') or Path(scan.get('root', '')).name) +
               (f' ({scan["store"].capitalize()} {scan["id"]})' if scan.get('store') else ''))
    if exe.get('selected'):
        out.append(f'Executable: {exe["selected"]} ({exe.get("bits") or "?"}-bit; confidence {verdict["confidence"]["exe"]})' +
                   (f'; the best candidate is {exe["best"]}' if exe.get('best') and exe['best'] != exe['selected'] else ''))
    engine = _engine_text(scan)
    if engine:
        out.append('Engine: ' + engine)
    if api:
        names = [a for a in api.get('apis', []) if not a.endswith('?')]
        names += [a[:-1] + ' (named in its code)' for a in api.get('apis', []) if a.endswith('?') and a[:-1] not in names]
        out.append('Graphics: ' + (', '.join(names) or 'not read') +
                   ('; DirectX 12 path' if api.get('dx12') else '; no DirectX 12 path') +
                   (f'; starts with {api["default"]}' if api.get('default') else '') + f' (confidence {verdict["confidence"]["api"]})')
    inputs = scan.get('upscalers') or []
    fg = [INPUT_NAMES[k] for k, flag in (('fsrfg', 'fsrfg_sdk2'), ('dlssg', 'dlssg'), ('fsrfg', 'fsrfg_combined'), ('fsrfg30', 'fsrfg30'))
          if (scan.get('game_fg') or {}).get(flag)]
    out.append('Inputs found: ' + (', '.join([UPSCALER_NAMES.get(i, i) for i in inputs] + list(dict.fromkeys(fg)) +
                                             (['XeSS FG beside the executable'] if scan.get('native_xefg') else []) +
                                             ([f'XeSS FG in {scan["native_xefg_elsewhere"]} (not usable by the native route)']
                                              if scan.get('native_xefg_elsewhere') else []) +
                                             (['XeSS FG beside the executable (the native route, not chosen automatically: an XeSSMFG '
                                               'folder is there)'] if scan.get('xefg_beside') and not scan.get('native_xefg') else []) +
                                             (['a DLSS DLL Unity bundles (the game\'s use of it was not found)']
                                              if scan.get('dlss_unconfirmed') else [])) or 'none'))
    if scan.get('mods'):
        out.append('Other tools\' files: ' + ', '.join(sorted({m['what'] for m in scan['mods']}))[:200])
    if installed:
        out.append('Installed: ' + installed)
    out += list(installed_notes)
    out.append('')
    if not [r for r in verdict['blocking'] if not r.get('setup')]:
        out.append('Plan: ' + ('native XeSS FG' if verdict['route'] == 'native' else INPUT_NAMES.get(verdict['fg_input'], verdict['fg_input']) + ' input')
                   + f' ({verdict["reason"]})')
        if verdict['launch_args']:
            out.append(f'Launch option: {" ".join(verdict["launch_args"])} ({verdict["launch_source"]})')
        for (section, key), value in verdict['ini'].items():
            out.append(f'OptiScaler.ini {section}.{key}={value} ({verdict["ini_sources"].get(section + "." + key, "")})')
        if verdict['dlss_helper'] == 'yes':
            out.append('DLSS helper: NVIDIA\'s nvngx_dlss.dll beside the executable (DLSS is the game\'s only upscaler and it ships no copy).')
        if verdict['extra_env']:
            out.append('Launch environment: ' + ' '.join(f'{k}={v}' for k, v in verdict['extra_env'].items()))
        out.append('')
        out.append('Your steps:')
        out += [f'  {n}. {s}' for n, s in enumerate(verdict['manual_steps'], 1)]
    for r in verdict['refusals']:
        mark = 'accepted' if r['code'] in verdict['accepted'] else 'risk accepted' if r['code'] in verdict.get('risk_accepted', ()) \
            else 'refused' if r in verdict['blocking'] else 'note'
        out.append(f'[{r["code"]}, {r["kind"]}{", before Install" if r.get("setup") else ""}, {mark}] {r["text"]} {r["way"]}')
    for w in verdict['warnings']:
        out.append('Note: ' + w)
    if advice and (advice['applied'] or advice['shown'] or advice['links']):
        out += ['', 'OptiScaler wiki (community reports): ' + ', '.join(f'{w["title"]} ({w["strength"]} match)' for w in verdict['wiki'])]
        out += ['  ' + t for t in advice['tested'][:2]]
        out += ['  Applied: ' + a for a in advice['applied']]
        out += ['  ' + s for s in advice['shown'][:12]] + (['  ...'] if len(advice['shown']) > 12 else [])
        hidden = sum(advice['hidden'].values())
        if hidden:
            out.append(f'  {hidden} note{"s" if hidden != 1 else ""} for other setups or already handled, hidden')
        out += ['  Read: ' + ' '.join(advice['links'][:3])]
    if run:
        out += ['', 'After the last run:'] + ['  ' + line for line in last_run_lines(run)]
    return out


def redact(text, home=None, libraries=()):
    """text without the home folder, the user name and library roots (for a report someone will post)."""
    home = str(home or Path.home())

    def replace(text, path, by):
        # The POSIX path, and the same path as Wine shows it to the game (Z:\\run\\media\\..., any case, either slash).
        for sep in ('\\', '/'):
            text = re.sub(re.escape('z:' + path.replace('/', sep)), lambda m: 'Z:' + by.replace('/', sep), text, flags=re.I)
        return text.replace(path, by)
    for root in sorted({str(r) for r in libraries if r}, key=len, reverse=True):
        text = replace(text, root, '<library>')
    text = replace(text, home, '~')
    user = Path(home).name
    if user and len(user) > 2:
        text = re.sub(r'(?<![\w])' + re.escape(user) + r'(?![\w])', '<user>', text)
    return text


def report(verdict, scan, versions=None, run=None, package=None, home=None, installed_notes=()):
    """The redacted text Check's Copy report gives for a GitHub issue: no paths, no user name, no file contents.
    installed_notes: lines about the installation (an anti-cheat override), listed with the package."""
    v = {k: verdict[k] for k in ('tier', 'route', 'fg_input', 'reason', 'launch_args', 'launch_source', 'dlss_helper', 'accepted')}
    v['ini'] = {f'{s}.{k}': value for (s, k), value in verdict['ini'].items()}
    v['refusals'] = [r['code'] for r in verdict['refusals']]
    exe = scan.get('exe') or {}
    detected = dict(engine=scan.get('engine'), apis=(scan.get('api') or {}).get('apis'), dx12=(scan.get('api') or {}).get('dx12'),
                    upscalers=scan.get('upscalers'), game_fg=scan.get('game_fg'), native_xefg=scan.get('native_xefg'),
                    anticheat=[a['name'] for a in scan.get('anticheat') or []], exe=Path(exe.get('selected') or '').name,
                    exe_bits=exe.get('bits'))
    lines = ['### Game report', '', f'- Package: {package or "unknown"}',
             '- Game: ' + (scan.get('name') or '?') + (f' ({scan["store"]} {scan["id"]})' if scan.get('store') else '')]
    lines += [f'- {k}: {val}' for k, val in (versions or {}).items()]
    lines += [f'- {note}' for note in installed_notes]
    lines += ['', '```json', json.dumps(dict(verdict=v, detected=detected), indent=1, sort_keys=True, default=str), '```']
    if run:
        lines += ['', 'After the last run:'] + ['- ' + line for line in last_run_lines(run)]
    lines += ['', 'Your answers: did frames generate (2.0 in the log or the overlay)? HUD, crashes, HDR, VRR, resolution, upscaler '
              'mode, minutes played. Check this text before you post it.']
    return redact('\n'.join(lines), home, [Path(scan.get('root') or '/nonexistent').parent])
