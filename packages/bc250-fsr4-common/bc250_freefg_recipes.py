# SPDX-License-Identifier: MIT
"""Translate pinned FreeFG recipes into Proton-prefix recommendations.

Identity and recipe semantics follow daniel-h-0/freefg (MIT): the matching of
its recipes.py and the layers of its compat.py, in that order. This adapter owns
no game files. Source evidence is reported as imported evidence, never upgraded
to a qualification of this different Proton/provider integration.

FreeFG's installer acts on a game its user picked; these packages apply one
default to every game. So the catalogue tempers that default per game in one
direction. What it takes away applies by itself: an FG input the OptiScaler wiki
reports broken in this game, or a package value that would switch off
OptiScaler's own fix for it. What it would add from evidence gathered on other
systems (a preferred input, a launch option, a proxy name, a wiki setting) is
advice, unless a curated BC-250 recipe or a reviewed (promoted) wiki item
carries it, as in FreeFG.
"""
import hashlib
import json
import re
import unicodedata
from pathlib import Path

QUALIFIED = {'generates', 'gameplay'}
INPUTS = {'upscaler', 'dlssg', 'fsrfg', 'fsrfg30'}
SCHEMA = 1

# From FreeFG's compat.py at the pinned commit; keep them alike when it moves.
INPUT_NAMES = {'upscaler': 'OptiFG', 'dlssg': 'DLSS FG', 'fsrfg': 'FSR 3.1 FG', 'fsrfg30': 'FSR 3.0 FG',
               'native-xefg': 'native XeSS FG', 'nukems': "Nukem's dlssg-to-fsr3", 'native-fsrfg': "the game's own FSR FG"}
INSTALLER_KEYS = {'Upscalers.Dx12Upscaler', 'FSR.UpscalerIndex', 'FSR.Fsr4ForceModel', 'FSR.Fsr4EnableWatermark',
                  'FrameGen.Enabled', 'fakenvapi.UseFakenvapi', 'FrameGen.FGInput', 'FrameGen.FGOutput',
                  'Libraries.XeFGPath', 'Libraries.XeLLPath', 'XeFG.ForceBorderless', 'Plugins.LoadAsiPlugins',
                  'XeFG.InterpolationCount', 'FrameGen.DisableHudless', 'fakenvapi.ForceReflex', 'XeFG.XeFGModel'}
NOTE_KEYS = {'reason', 'purpose', 'note', 'autoapplied_since', 'value', 'feature'}
GENERIC_EXES = {'game.exe', 'launcher.exe', 'start.exe', 'main.exe', 'app.exe', 'bin.exe', 'client.exe', 'play.exe',
                'client-win64-shipping.exe', 'medium-win64-shipping.exe', 'game-win64-shipping.exe', 'project-win64-shipping.exe'}
DX12_ARGS = ('-dx12', '-d3d12', '-force-d3d12')
TIER_NAMES = {'A': 'Verified on BC-250', 'C': 'Automatic, guided by the OptiScaler wiki', 'D': 'Automatic (no recipe)'}
# What every wiki condition is evaluated against: FreeFG's DEFAULT_CONTEXT, with
# this package's proxy.
CONTEXT = dict(gpu='amd', os='linux', api='dx12', fg_output='xefg', upscaler='fsr4', proxy='winmm.dll')

# FreeFG's installer writes its own keys whatever a quirk says (XeFG.ForceBorderless
# was measured), so they are never given back to one.
OWNED = {key.lower() for key in INSTALLER_KEYS}
# Package values kept for a reason of this package's own: where OptiScaler's fix for
# a game would change one, the fix is reported rather than applied.
PACKAGE_DECISIONS = {
    'spoofing.vulkanextensionspoofing': 'this package keeps it off (README: the "DX12 not supported" report)',
}
# The names OptiScaler loads as (docs/FSR4-PROTON.md); wiki entries also list .asi
# loaders and prose.
PROXIES = ('dxgi.dll', 'winmm.dll', 'version.dll', 'dbghelp.dll', 'd3d12.dll', 'wininet.dll', 'winhttp.dll')


def load(path, expected):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('FreeFG recipe checksum differs from its package pin')
    value = json.loads(data)
    if value.get('schema') != SCHEMA or not isinstance(value.get('verified'), list):
        raise ValueError('Unsupported FreeFG recipe schema')
    for row in value['verified']:
        if not isinstance(row.get('match'), dict) or not isinstance(row.get('title'), str):
            raise ValueError('Invalid FreeFG recipe identity')
        if row.get('route') not in ('opti', 'native') or row.get('fg_input') not in INPUTS | {None}:
            raise ValueError('Unsupported FreeFG recipe route')
    return value


# FreeFG's recipes.norm: the catalogue's titles are written in this form.
EDITION = re.compile(r'(\s+(game of the year|goty|enhanced|definitive|complete|deluxe|gold|ultimate|anniversary|remastered|'
                     r'directors cut|standard|premium)(\s+edition)?)+$')


def norm(title):
    t = re.sub(r'\([^)]*\)', '', title.lower()).replace('&', 'and').replace('’', "'").replace('‐', '-')
    t = re.sub(r"[^a-z0-9]+", ' ', t.replace("'", '')).strip()
    t = re.sub(r'\bii\b', '2', t)
    t = re.sub(r'\biii\b', '3', t)
    return EDITION.sub('', t).strip()


def titles(name):
    """A launcher's name for the game, in the catalogue's form. Accents are folded too,
    so "Ragnarök" finds "Ragnarok"; both forms are kept, because folding alone turns
    "Automata™" into "automatatm"."""
    folded = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return {norm(name), norm(folded)} - {''}


def steam_name(env, path, appid):
    """The name in Steam's appmanifest for appid, or None. Read only: the manifest sits
    in the steamapps folder above the game, its compat data, or both."""
    libraries = []
    for start in (env.get('STEAM_COMPAT_INSTALL_PATH', ''), path, env.get('STEAM_COMPAT_DATA_PATH', '')):
        for parent in Path(start).parents if start else ():
            if parent.name.lower() == 'steamapps' and parent not in libraries:
                libraries.append(parent)
    for library in libraries:
        try:
            found = re.search(r'"name"\s+"([^"]*)"', (library / f'appmanifest_{appid}.acf').read_text(errors='replace'))
        except OSError:
            continue
        if found:
            return found[1]
    return None


def identity(env, arguments):
    """A real store ID wins; shortcut/umu-0 identities need executable context.

    OptiScaler wiki entries name titles and executables, never store IDs, so the
    title comes from Steam's own record of the AppID, as in FreeFG. A launch with
    neither a store ID nor an executable keeps one identity for its prefix and the
    package defaults: a game is never refused for want of a name.
    """
    explicit = env.get('BC250_FREEFG_GAME_ID', '')
    if explicit and not re.fullmatch(r'(steam|gog|epic):[A-Za-z0-9_.-]+', explicit):
        raise ValueError('BC250_FREEFG_GAME_ID must be steam:ID, gog:ID or epic:NAME')
    store, appid = explicit.split(':', 1) if explicit else ('', '')
    if not store and not env.get('UMU_ID'):
        candidate = env.get('SteamAppId', '')
        if candidate.isdecimal() and 0 < int(candidate) < (1 << 31):
            store, appid = 'steam', candidate
    command = next((s for s in arguments if s.lower().endswith('.exe')), '')
    path = command.replace('\\', '/')
    # Used as an identity only; never opened or written by this adapter. Like
    # FreeFG, only the game's own folders count: <Game>/<Project>/Binaries/Win64.
    folders = sorted({norm(p) for p in [p for p in path.split('/')[:-1] if p][-4:]} - {''})
    exe = path.rsplit('/', 1)[-1].lower()
    name = steam_name(env, path, appid) if store == 'steam' else None
    if store:
        key = store + ':' + appid
    elif command:
        key = 'exe:' + hashlib.sha256(path.encode()).hexdigest()
    else:
        prefix = env.get('WINEPREFIX', '').strip()
        if not prefix and env.get('STEAM_COMPAT_DATA_PATH', '').strip():
            prefix = str(Path(env['STEAM_COMPAT_DATA_PATH'].strip()) / 'pfx')
        if not prefix:
            raise ValueError('Cannot identify this non-Steam game; set BC250_FREEFG_GAME_ID')
        key = 'prefix:' + hashlib.sha256(str(Path(prefix).resolve()).encode()).hexdigest()
    return dict(key=key, store=store, appid=appid, exe=exe, path=path, folders=folders,
                titles=sorted(titles(name)) if name else [])


def match(catalog, game):
    found = []
    names = set(game['folders']) | set(game.get('titles', []))
    for row in catalog['verified']:
        spec = row['match']
        if game['store']:
            hit = game['appid'] in spec.get(game['store'], [])
        else:
            hit = game['exe'] in spec.get('exe', []) and bool(({norm(row['title'])} | set(spec.get('title', []))) & names)
        if hit:
            found.append(row)
    if len(found) > 1:
        raise ValueError('Ambiguous FreeFG recipe identity; set an explicit store ID')
    return found[0] if found else None


def wiki_matches(catalog, game):
    """[(wiki entry, 'strong' | 'weak')], as FreeFG's compat.wiki_matches: strong is a
    store ID, or the executable together with the title or one of the game's folders;
    weak is the title alone, or a non-generic executable alone."""
    out = []
    ids = {game['store']: {game['appid']}} if game['store'] else {}
    names = set(game['folders']) | set(game.get('titles', []))
    for entry in catalog.get('wiki', []):
        spec = entry.get('match', {})
        by_id = any(ids.get(store, set()) & set(spec.get(store, [])) for store in ('steam', 'gog', 'epic'))
        by_exe = bool(game['exe']) and game['exe'] in spec.get('exe', [])
        if by_id or (by_exe and set(spec.get('title', [])) & names):
            out.append((entry, 'strong'))
        elif set(spec.get('title', [])) & set(game.get('titles', [])) or (by_exe and game['exe'] not in GENERIC_EXES):
            out.append((entry, 'weak'))
    return out


# FreeFG's compat.key_rule: why its RULES.md keeps a key out of automatic writes.
S1 = re.compile(r'^(fsr\.fsrnonlinear|fsr\.dlssreactivemaskbias|sharpness\.|cas\.|upscaleratio\.|outputscaling\.|mipmap\.|'
                r'anisotropy\.|qualityoverrides\.|drs\.|hdr\.|initflags\.autoexposure)')


def key_rule(key, value):
    """(class, reason) for a key FreeFG never writes automatically, or (None, None)."""
    k, v = key.lower(), str(value).strip().lower()
    if k == 'framegen.fgoutput':
        return ('redundant', 'the installer writes FGOutput=xefg') if v == 'xefg' else ('blocked', 'F0: XeFG is always the generator')
    if k == 'xefg.forceborderless' and v == 'true':
        return 'redundant', 'the installer writes ForceBorderless=true'
    if k == 'xefg.xefgmodel' and v == 'default':
        return 'redundant', 'the installer writes XeFGModel=default'
    if k in OWNED:
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


def condition(key, value, ctx):
    """FreeFG's compat._condition: True, False (with why) or None (unknown here)."""
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
        if re.search(r'dx12|d3d12|directx 12', v):
            return True, None
        if re.search(r'dx11|d3d11|vulkan|opengl|dx9', v):
            return False, f'{value} (this build runs in DirectX 12)'
        return None, None
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
    return None, None


def evaluate(when, ctx):
    """(result, reasons) as FreeFG's compat.evaluate: True when every condition holds
    here, False when one never does, None when one cannot be known before the game runs."""
    unknown, false = [], []
    for key, value in (when or {}).items():
        result, why = condition(key, value, ctx)
        if result is False:
            false.append(why or f'{key} {value}')
        elif result is None:
            unknown.append(f'{key}: {value}')
    if false:
        return False, false
    return (None, unknown) if unknown else (True, [])


def _curated(row, provider, supported, result):
    """A curated BC-250 recipe: its route, input and keys, when its evidence qualifies."""
    result['notes'].extend(row.get('manual_steps', []))
    if row.get('note'):
        result['notes'].append(row['note'])
    # Describe prerequisite game settings, but never reassert them over a player's
    # graphics/save files. Their source provenance stays visible in Status.
    result['game_settings'] = row.get('game_settings', [])
    if row['route'] != 'opti':
        result['notes'].append('This recipe needs native XeFG; the prefix OptiScaler adapter does not implement that route.')
        result['settings']['FrameGen.Enabled'] = 'false'
        return
    if row.get('evidence') not in QUALIFIED:
        result['notes'].append('Upstream evidence is ' + str(row.get('evidence')) + '; this entry is advisory only.')
        if row.get('evidence') == 'fails':
            result['settings']['FrameGen.Enabled'] = 'false'
        return
    settings = {'FrameGen.FGInput': row['fg_input'], 'FrameGen.FGOutput': 'xefg'}
    # These route mechanics live in FreeFG's installer, not its data rows.
    # DLSS FG supplies its own Reflex markers; OptiFG/FSR FG need forced Reflex.
    settings['fakenvapi.ForceReflex'] = 'auto' if row['fg_input'] == 'dlssg' else '2'
    settings['FrameGen.DisableHudless'] = 'true' if row['fg_input'] in ('fsrfg', 'fsrfg30') else 'auto'
    settings.update({k: str(v) for k, v in row.get('ini', {}).items()})
    provider = 'helixsr' if provider == 'hlx-dlss' else provider
    settings.update({k: str(v) for k, v in row.get('upscaler_ini', {}).get(provider, {}).items()})
    # Relative game-folder library paths have no equivalent in a shared prefix.
    # Keep the package's validated library wiring instead of guessing a path.
    for key in list(settings):
        if key.lower().startswith(('libraries.', 'plugins.')):
            result['notes'].append('Game-folder setting requires manual review in this layout: ' + key)
            settings.pop(key)
    missing = [key for key in settings if key.lower() not in supported]
    if missing:
        result['notes'].append('Recipe cannot be applied by this OptiScaler build: ' + ', '.join(sorted(missing)))
        return
    result['settings'] = settings
    result['arguments'] = list(row.get('launch_args', []))
    result['applicable'] = True
    result['notes'].append('Imported upstream recipe; this Proton/provider combination is not thereby gameplay-qualified.')


def _set(settings, package, key, value):
    """Set key in the spelling the package already uses, so it replaces that entry."""
    spelling = package.get(key.lower(), (key, None))[0]
    for existing in [k for k in settings if k.lower() == key.lower()]:
        settings.pop(existing)
    settings[spelling] = value


def recommendation(catalog, game, provider, supported_keys, package=None):
    """What the catalogue changes for this game, in FreeFG's layer order (compat.py).

    package is what this launch writes otherwise. A curated recipe with gameplay
    evidence decides the route, input and its keys. Below it, a key a runtime fix of
    the shipped OptiScaler sets for this executable is left to that fix; then, while
    the package's own default input is in effect, a reviewed wiki item fills its key,
    and an input the wiki reports broken here turns frame generation off. Those need
    FreeFG's strong match. Every other wiki item is advice, in notes and summary.
    """
    package = {k.lower(): (k, str(v)) for k, v in (package or {}).items() if v is not None}
    supported = {s.lower() for s in supported_keys}
    result = dict(title=None, evidence=None, settings={}, arguments=[], notes=[], summary=[], game_settings=[],
                  applicable=False, executables=[], tier='D', tier_name=TIER_NAMES['D'], wiki=[], quirks={})
    notes, settings = result['notes'], result['settings']
    try:
        row = match(catalog, game)
    except ValueError as error:
        # Never a refused launch: the defaults apply and the reason is reported.
        row = None
        notes.append(str(error) + ' (BC250_FREEFG_GAME_ID); using the selected variant’s defaults.')
    if row:
        result.update(title=row['title'], evidence=row.get('evidence'), executables=row.get('match', {}).get('exe', []))
        _curated(row, provider, supported, result)
        settings = result['settings']
    else:
        notes.append('No curated FreeFG recipe; using the selected variant’s defaults.')
    recipe_keys = {key.lower() for key in settings}
    exe, wiki = game.get('exe', ''), wiki_matches(catalog, game)
    result['wiki'] = [dict(title=w['title'], strength=s, pages=w.get('pages', [])) for w, s in wiki]
    ctx = dict(CONTEXT, store=game.get('store') or None)
    applied = []

    # OptiScaler's own fixes for this executable (FreeFG Q1, leave_auto): a fix acts
    # only while its key is auto, and the shared preset's explicit values (false,
    # which OptiScaler's auto already means) would otherwise switch it off.
    quirks = (catalog.get('quirk_keys') or {}).get(exe, {})
    for key, value in sorted(quirks.items()):
        low, theirs = key.lower(), str(value).split('@', 1)[0].lower()
        mine = package.get(low)
        if low in recipe_keys or low in OWNED or mine is None or mine[1].lower() in ('auto', theirs):
            continue
        if low in PACKAGE_DECISIONS:
            notes.append(f'OptiScaler’s own fix for this game sets {key}={value}; {PACKAGE_DECISIONS[low]}. '
                         f'To try the fix: BC250_OPTISCALER_EXTRA={key}=auto')
        elif low in supported:
            _set(settings, package, key, 'auto')
            result['quirks'][key] = value
            notes.append(f'Left {key} to OptiScaler’s own fix for this game ({key}={value}); '
                         f'the package value {mine[1]} would switch it off.')
    for item in (catalog.get('leave_auto') or {}).get(exe, []):
        low, mine = item['key'].lower(), package.get(item['key'].lower())
        if low not in recipe_keys and low in supported and mine and mine[1].lower() != 'auto':
            _set(settings, package, item['key'], 'auto')
            notes.append(f'Left {item["key"]} to OptiScaler’s own setting for this game ({item["quirk"]}).')

    current = {k.lower(): v for k, v in settings.items()}
    here = str(current.get('framegen.fginput') or package.get('framegen.fginput', ('', 'upscaler'))[1]).lower()
    fg_on = str(current.get('framegen.enabled') or package.get('framegen.enabled', ('', 'false'))[1]).lower() == 'true'
    vetoes, weak = {}, {}
    for w, strength in wiki:
        for a in w.get('fg_advice', []):
            unless = {k: v for k, v in (a.get('when') or {}).items() if k != 'fg_input'}
            if a['advice'] in ('broken', 'avoid') and evaluate(unless, ctx)[0] is True:
                (vetoes if strength == 'strong' else weak).setdefault(a['input'], w['title'])
    automatic = not result['applicable']
    if automatic and row is None:
        # Promoted wiki items (FreeFG layer 5): reviewed for automatic use, a strong
        # match whose conditions hold here, never a key a fix or the rules keep.
        for w, strength in wiki:
            for item in w.get('promoted', []) if strength == 'strong' else ():
                key, low = item['key'], item['key'].lower()
                if (evaluate(item.get('when'), ctx)[0] is True and key not in quirks and low not in current
                        and key_rule(key, item['value'])[0] is None and low in supported):
                    _set(settings, package, key, str(item['value']))
                    current[low] = str(item['value'])
                    applied.append(f'{key}={item["value"]}')
                    notes.append(f'OptiScaler wiki ({w["title"]}), reviewed for automatic use: {key}={item["value"]}.')
    if automatic and fg_on and here in vetoes:
        # The input every game gets by default is reported broken here (FreeFG V1).
        _set(settings, package, 'FrameGen.Enabled', 'false')
        applied.append('FG input veto')
        line = (f'OptiScaler wiki ({vetoes[here]}) reports {INPUT_NAMES.get(here, here)} input broken in this game: '
                'frame generation starts off; upscaling is unchanged.')
        notes.append(line + ' The menu or BC250_OPTISCALER_EXTRA=FrameGen.Enabled=true turns it on.')
        result['summary'].append(line)
    elif fg_on and here in vetoes:
        notes.append(f'OptiScaler wiki ({vetoes[here]}) reports problems with {INPUT_NAMES.get(here, here)} input; '
                     'the curated BC-250 recipe chose it regardless.')
    elif fg_on and here in weak:
        line = (f'OptiScaler wiki ({weak[here]}, matched by name only) reports problems with {INPUT_NAMES.get(here, here)} '
                'input; if frame generation misbehaves, disable it here.')
        notes.append(line)
        result['summary'].append(line)
    _advice(wiki, row, here, ctx, quirks, result)

    if result['applicable']:
        result['tier'] = 'A'
    elif applied:
        result['tier'] = 'C'
    result['tier_name'] = TIER_NAMES[result['tier']]
    if result['applicable']:
        head = f'{TIER_NAMES["A"]}: {row["title"]} ({INPUT_NAMES.get(row["fg_input"], row["fg_input"])} input; {row.get("evidence")})'
    elif row and row['route'] != 'opti':
        head = f'FreeFG recipe for {row["title"]} needs native XeSS FG, which this package lacks: frame generation starts off'
    elif row and row.get('evidence') == 'fails':
        head = f'FreeFG recipe for {row["title"]} records a failure: frame generation starts off'
    elif row:
        head = f'FreeFG recipe for {row["title"]} is advisory here ({row.get("evidence")}): package defaults'
    elif wiki:
        title, strength = max(((w['title'], s) for w, s in wiki), key=lambda t: (t[1] == 'strong', len(t[0])))
        head = ('Guided by the OptiScaler wiki: ' if applied else 'OptiScaler wiki: ') + title + (
            '' if strength == 'strong' else ' (matched by name only)') + ('' if applied else '; package defaults')
    else:
        head = 'No FreeFG recipe or OptiScaler wiki entry for this game: package defaults'
    result['summary'].insert(0, head)
    if result['quirks']:
        result['summary'].append('Left to OptiScaler’s own fix for this game: ' + ', '.join(result['quirks']))
    result['summary'] = result['summary'][:4]
    return result


def _advice(wiki, row, here, ctx, quirks, result):
    """FreeFG's shown-only wiki items (compat.wiki_advice, recipes.suggestions), as
    notes. A curated recipe outranks the wiki's preferences, as in FreeFG."""
    notes, summary = result['notes'], result['summary']
    if not wiki:
        return
    title = max((w['title'] for w, _ in wiki), key=len)
    if any(w.get('compat') == 'not-working' for w, _ in wiki):
        strong = any(w.get('compat') == 'not-working' for w, s in wiki if s == 'strong')
        line = ('The OptiScaler compatibility list says this game does not work' + ('' if strong else ' (matched by name only)')
                + '; choose No upscaling if it misbehaves.')
        notes.append(line)
        summary.append(line)
    if row is None:
        usable = ('upscaler', 'dlssg', 'fsrfg')
        prefer = sorted({a['input'] for w, _ in wiki for a in w.get('fg_advice', [])
                         if a['advice'] == 'prefer' and a['input'] in usable and a['input'] != here
                         and evaluate({k: v for k, v in (a.get('when') or {}).items() if k != 'fg_input'}, ctx)[0] is not False})
        if prefer:
            line = (f'OptiScaler wiki ({title}) prefers {" or ".join(INPUT_NAMES[i] for i in prefer)} input here: turn on the '
                    f'game’s own frame generation and launch with BC250_OPTISCALER_EXTRA=FrameGen.FGInput={prefer[0]}')
            notes.append(line)
            summary.append(f'OptiScaler wiki prefers {" or ".join(INPUT_NAMES[i] for i in prefer)} input: with the game’s '
                           f'own frame generation on, BC250_OPTISCALER_EXTRA=FrameGen.FGInput={prefer[0]}')
        args = next((a for w, _ in wiki for a in w.get('launch_args', []) if a.lower() in DX12_ARGS), None)
        if args:
            notes.append(f'XeFG needs DirectX 12; the OptiScaler wiki ({title}) starts this game with {args} '
                         '(add it to the launch options if the game starts in another API).')
        keys = []
        for w, _ in wiki:
            for item in w.get('ini', []):
                result_c, _why = evaluate(item.get('when'), ctx)
                cls = key_rule(item['key'], item['value'])[0]
                handled = str(quirks.get(item['key'], '')).split('@', 1)[0] == str(item['value'])
                text = f'{item["key"]}={item["value"]}'
                # The input is advised above; mods and preferences are the player's.
                if result_c is not False and not handled and cls not in ('redundant', 'never', 'installer', 'human') \
                        and text not in keys:
                    keys.append(text)
        if keys:
            notes.append('OptiScaler settings the wiki lists for this game (not applied): ' + '; '.join(keys[:4])
                         + ('; ...' if len(keys) > 4 else ''))
    for w, _ in wiki:
        names = [n.lower() for n in w.get('proxy', []) if n.lower() in PROXIES]
        if names and CONTEXT['proxy'] not in names:
            notes.append(f'If OptiScaler does not load (no overlay on Insert), the OptiScaler wiki ({w["title"]}) has it '
                         f'loading as {names[0]}: PROTON_OPTISCALER_NAME={names[0]} %command%')
            break
    pages = list(dict.fromkeys(p for w, _ in sorted(wiki, key=lambda t: -len(t[0]['title'])) for p in w.get('pages', [])))
    if pages:
        notes.append('Read: ' + ' '.join(pages[:2]))


def launch_arguments(arguments, recipe, game):
    """Append only to a positively matched game executable, never to a launcher."""
    if (not recipe.get('applicable') or not recipe.get('arguments')
            or game['exe'] not in recipe.get('executables', [])):
        return list(arguments)
    matches = [i for i, value in enumerate(arguments)
               if value.replace('\\', '/').rsplit('/', 1)[-1].lower() == game['exe']]
    if not matches or not game['exe']:
        return list(arguments)
    args = list(arguments)
    for option in recipe['arguments']:
        if not isinstance(option, str) or not re.fullmatch(r'-[A-Za-z0-9_-]+', option):
            raise ValueError('Unsupported recipe launch argument')
        if option not in args:
            if option in ('-dx12', '-d3d12', '-force-d3d12') and any(
                    x in args for x in ('-dx11', '-d3d11', '-force-d3d11', '-vulkan', '-opengl')):
                continue  # an explicit player API selection wins
            args.append(option)
    return args
