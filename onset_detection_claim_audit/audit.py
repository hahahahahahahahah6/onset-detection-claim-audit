"""Read-only documentation and AST audit."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys

from . import __version__
from .phrases import ONSET, NOONSET

GENERIC = frozenset('''detect_onset detect_onsets onset_detect onset_detection get_onset get_onsets find_onset find_onsets extract_onset extract_onsets track_onset track_onsets onset_track onset_detect_audio detect_audio_onset detect_audio_onsets detect_note_onset detect_note_onsets estimate_onset estimate_onsets predict_onset predict_onsets identify_onset identify_onsets onset_identify onset_estimate onset_predict onset_extract onset_find analyze_onsets analyse_onsets onset_analyze onset_analyse detect_onset_times get_onset_times find_onset_times extract_onset_times detect_music_onset detect_music_onsets detect_song_onset detect_song_onsets'''.split())


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def pattern(phrases):
    return re.compile(r'\b(?:' + '|'.join(re.escape(s) for s in sorted(phrases, key=lambda s: (-len(s), s))) + r')\b')


POSITIVE = pattern(ONSET)
NEGATIVE = pattern(NOONSET)


def claims(text):
    lines = []
    fence = None
    for line in text.splitlines():
        if fence:
            if re.fullmatch(r' {0,3}' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}\s*', line):
                fence = None
            lines.append('')
            continue
        match = re.match(r' {0,3}(`{3,}|~{3,})(.*)$', line)
        if match and not (match[1][0] == '`' and '`' in match[2]):
            fence = (match[1][0], len(match[1]))
            lines.append('')
        else:
            lines.append(line)
    positive, negative = [], []
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        paragraph = normalize(paragraph)
        negative.extend(m.group() for m in NEGATIVE.finditer(paragraph))
        paragraph = NEGATIVE.sub(' ', paragraph)
        positive.extend(m.group() for m in POSITIVE.finditer(paragraph))
    return positive, negative


def has_evidence(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    imports, imported = {}, {}
    shadow = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    # Only module-level imports establish bindings, never imports in another scope.
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ('librosa', 'aubio', 'essentia'):
                    imports[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported[alias.asname or alias.name] = (node.module or '', alias.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            module, name = imported.get(func.id, ('', ''))
            if (module == 'librosa' or module.startswith('librosa.')) and name == 'onset_detect':
                return True
            if name in GENERIC and name not in shadow and func.id not in shadow:
                return True
        elif isinstance(func, ast.Attribute):
            base = func.value
            root = base
            while isinstance(root, ast.Attribute):
                root = root.value
            library = imports.get(root.id) if isinstance(root, ast.Name) else None
            if library == 'librosa' and func.attr == 'onset_detect':
                return True
            if library == 'essentia' and func.attr in ('OnsetDetection', 'OnsetDetectionGlobal'):
                return True
            if isinstance(base, ast.Name) and imports.get(base.id) == 'aubio' and func.attr == 'onset':
                return True
            if func.attr in GENERIC and func.attr not in shadow:
                return True
    return False


def audit(root, ignore=()):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise OSError('root must be a readable directory, not a symlink')
    if not root.stat().st_mode & 0o444 or not root.stat().st_mode & 0o111:
        raise OSError('root is unreadable')
    positives, negatives, production, tests = [], [], [], []
    prefixes = [Path(s).as_posix().rstrip('/') for s in ignore]

    def ignored(rel):
        return any(prefix == '.' or rel == prefix or rel.startswith(prefix + '/') for prefix in prefixes)

    def error(exc):
        raise exc

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=error):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink() and not ignored((Path(directory) / d).relative_to(root).as_posix()))
        for name in sorted(files):
            path = Path(directory) / name
            rel = path.relative_to(root)
            if path.is_symlink() or ignored(rel.as_posix()):
                continue
            doc = rel.as_posix() == 'README.md' or (path.suffix == '.md' and 'docs' in rel.parts[:-1])
            source = path.suffix == '.py' and not set(rel.parts[:-1]).intersection(('fixtures', 'docs', 'examples'))
            if not (doc or source):
                continue
            if not path.stat().st_mode & 0o444:
                raise OSError('unreadable file: ' + str(path))
            text = path.read_text(encoding='utf-8')
            if doc:
                pos, neg = claims(text)
                positives.extend(pos)
                negatives.extend(neg)
            if source and has_evidence(text):
                test = 'tests' in rel.parts[:-1] or name.startswith('test_') or name.endswith('_test.py')
                (tests if test else production).append(rel.as_posix())
    findings = []
    if positives and not production:
        findings.append({'id': 'documented-onset-detection-claim-false', 'severity': 'MEDIUM' if tests else 'HIGH', 'message': 'Documentation promise has only test evidence.' if tests else 'Documentation promise has no production evidence.'})
    if negatives and production:
        findings.append({'id': 'documented-no-onset-detection-claim-false', 'severity': 'HIGH', 'message': 'Documentation denial conflicts with production evidence.'})
    return {'verdict': 'FAIL' if findings else 'PASS', 'findings': findings, 'evidence': {'production': production, 'tests': tests}, 'claims': {'positive': positives, 'negative': negatives}}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=('HIGH', 'MEDIUM', 'LOW'), default='HIGH')
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.ignore)
    except (OSError, UnicodeError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result['verdict'])
        for finding in result['findings']:
            print('{severity} {id}: {message}'.format(**finding))
        if args.verbose:
            print(json.dumps({'claims': result['claims'], 'evidence': result['evidence']}, sort_keys=True))
    ranks = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
    return 2 if any(ranks[f['severity']] >= ranks[args.fail_on] for f in result['findings']) else 0
