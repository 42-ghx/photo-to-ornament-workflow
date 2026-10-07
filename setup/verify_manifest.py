"""Check downloaded project assets, detecting unhydrated LFS pointers."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
    errors = []
    for item in manifest['files']:
        path = root / item['file']
        if not path.is_file():
            errors.append({'file': item['file'], 'error': 'missing'})
            continue
        content = path.read_bytes()
        if content.startswith(b'version https://git-lfs.github.com/spec/v1'):
            errors.append({'file': item['file'], 'error': 'LFS pointer; run git lfs pull'})
        elif len(content) != item['bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
            errors.append({'file': item['file'], 'error': 'size or SHA256 mismatch'})
    print(json.dumps({'status': 'failed' if errors else 'passed', 'files': len(manifest['files']),
                      'errors': errors}, ensure_ascii=False))
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
