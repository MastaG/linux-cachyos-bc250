# SPDX-License-Identifier: MIT
"""Translate pinned FreeFG recipes into Proton-prefix recommendations.

Identity and recipe semantics follow daniel-h-0/freefg (MIT). This adapter owns
no game files. Source evidence is reported as imported evidence, never upgraded
to a qualification of this different Proton/provider integration.
"""
import hashlib
import json
import re
from pathlib import Path

QUALIFIED = {'generates', 'gameplay'}
INPUTS = {'upscaler', 'dlssg', 'fsrfg', 'fsrfg30'}
SCHEMA = 1


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


def normalized(text):
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def identity(env, arguments):
    """A real store ID wins; shortcut/umu-0 identities need executable context."""
    explicit = env.get('BC250_FREEFG_GAME_ID', '')
    if explicit and not re.fullmatch(r'(steam|gog|epic):[A-Za-z0-9_.-]+', explicit):
        raise ValueError('BC250_FREEFG_GAME_ID must be steam:ID, gog:ID or epic:NAME')
    store, appid = explicit.split(':', 1) if explicit else ('', '')
    if not store and not env.get('UMU_ID'):
        candidate = env.get('SteamAppId', '')
        if candidate.isdecimal() and 0 < int(candidate) < (1 << 31):
            store, appid = 'steam', candidate
    command = next((s for s in arguments if s.lower().endswith('.exe')), '')
    if not store and not command:
        raise ValueError('Cannot identify this non-Steam game; set BC250_FREEFG_GAME_ID')
    path = command.replace('\\', '/')
    # Used as an identity only; never opened or written by this adapter.
    folders = [normalized(p) for p in path.split('/')[:-1] if p]
    exe = path.rsplit('/', 1)[-1].lower()
    key = store + ':' + appid if store else 'exe:' + hashlib.sha256(path.encode()).hexdigest()
    return dict(key=key, store=store, appid=appid, exe=exe, path=path, folders=folders)


def match(catalog, game):
    found = []
    for row in catalog['verified']:
        spec = row['match']
        if game['store']:
            hit = game['appid'] in spec.get(game['store'], [])
        else:
            names = {normalized(row['title']), *[normalized(s) for s in spec.get('title', [])]}
            hit = game['exe'] in spec.get('exe', []) and bool(names & set(game['folders']))
        if hit:
            found.append(row)
    if len(found) > 1:
        raise ValueError('Ambiguous FreeFG recipe identity; set an explicit store ID')
    return found[0] if found else None


def recommendation(catalog, game, provider, supported_keys):
    row = match(catalog, game)
    result = dict(title=row['title'] if row else None, evidence=row.get('evidence') if row else None,
                  settings={}, arguments=[], notes=[], game_settings=[], applicable=False,
                  executables=(row or {}).get('match', {}).get('exe', []))
    if row is None:
        result['notes'].append('No curated FreeFG recipe; using the selected variant’s defaults.')
        return result
    result['notes'].extend(row.get('manual_steps', []))
    if row.get('note'):
        result['notes'].append(row['note'])
    # Describe prerequisite game settings, but never reassert them over a player's
    # graphics/save files. Their source provenance stays visible in Status.
    result['game_settings'] = row.get('game_settings', [])
    if row['route'] != 'opti':
        result['notes'].append('This recipe needs native XeFG; the prefix OptiScaler adapter does not implement that route.')
        result['settings']['FrameGen.Enabled'] = 'false'
        return result
    if row.get('evidence') not in QUALIFIED:
        result['notes'].append('Upstream evidence is ' + str(row.get('evidence')) + '; this entry is advisory only.')
        if row.get('evidence') == 'fails':
            result['settings']['FrameGen.Enabled'] = 'false'
        return result
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
    supported = {s.lower() for s in supported_keys}
    missing = [key for key in settings if key.lower() not in supported]
    if missing:
        result['notes'].append('Recipe cannot be applied by this OptiScaler build: ' + ', '.join(sorted(missing)))
        return result
    result['settings'] = settings
    result['arguments'] = list(row.get('launch_args', []))
    result['applicable'] = True
    result['notes'].append('Imported upstream recipe; this Proton/provider combination is not thereby gameplay-qualified.')
    return result


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
