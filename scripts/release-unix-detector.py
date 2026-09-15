"""Build a reproducible, inspectable Python zipapp from the detector source."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'apps' / 'detector'
DEST = ROOT / 'apps' / 'web' / 'public' / 'download'
DEST.mkdir(parents=True, exist_ok=True)
archive = DEST / 'canmypcrunai-detector.pyz'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
    files = {name: (SOURCE / name).read_text(encoding='utf-8').encode('utf-8') for name in ('detector.py', 'unix_detector.py')}
    files['__main__.py'] = b'from unix_detector import main\nraise SystemExit(main())\n'
    for name, content in sorted(files.items()):
        entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
        entry.create_system = 3  # Stable ZIP metadata even when built on Windows.
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o644 << 16
        bundle.writestr(entry, content)
data = archive.read_bytes()
version = re.search(r"^VERSION = '([^']+)'", files['unix_detector.py'].decode(), re.M).group(1)
manifest = {'filename': archive.name, 'version': version, 'schemaVersion': '1.0.0',
            'sizeBytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'platforms': ['macOS', 'Linux'], 'requires': 'Python 3.9 or newer'}
(DEST / 'unix-detector-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest))
