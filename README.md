# Documentation claim auditor

An offline static auditor that compares documentation promises with Python
call patterns. It reads the root README and Markdown under any docs directory,
ignores fenced examples, and parses source without executing it.

```sh
python3 -m pip install .
onset-detection-claim-audit /path/to/project
python3 -m onset_detection_claim_audit /path/to/project --json
onset-detection-claim-audit /path/to/project --fail-on MEDIUM --ignore vendor
onset-detection-claim-audit --version
```

Use repeatable `--ignore` path prefixes to omit subtrees. `--verbose` includes
matched phrases and evidence paths. JSON provides a verdict, findings with
messages, and evidence paths. HIGH findings fail by default; MEDIUM findings
fail when the threshold is MEDIUM. Exit status is 0 for success, 2 for findings
at the threshold, and 1 for usage or filesystem errors.

Finding identifiers:

```text
documented-onset-detection-claim-false
documented-no-onset-detection-claim-false
```

Test evidence is reported separately. Files in fixtures, docs, and examples
are excluded from evidence, as are symlinks. Invalid Python provides no
evidence. Import bindings are resolved within individual modules; generic
calls shadowed by local definitions are excluded. Static patterns establish
only the presence of a call, not runtime correctness or audio quality.

Requires Python 3.9 or later. No runtime dependencies.

```sh
python3 -m unittest discover
python3 -m build
```
