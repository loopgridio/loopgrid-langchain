"""Conservative wheel and source-archive integrity audit."""
from pathlib import Path
from zipfile import ZipFile
from tarfile import open as taropen
from typing import Iterable

root=Path(__file__).resolve().parents[1]
files=sorted((root/'dist').glob('*'))
assert len(files)==2 and any(x.suffix=='.whl' for x in files) and any(str(x).endswith('.tar.gz') for x in files),files
banned=('.env', '.pem', '.key', '.sqlite', '.sqlite3', '__pycache__', '.coverage', 'secrets.json')
for item in files:
    if item.suffix=='.whl':
        with ZipFile(item) as z:
            names=z.namelist();assert z.testzip() is None
    else:
        with taropen(item,'r:gz') as tar:
            names=tar.getnames()
    for name in names:
        assert not name.startswith('/') and '..' not in Path(name).parts,name
        assert not any(name.endswith(s) for s in banned),name
    if item.suffix=='.whl':
        assert any(name.endswith('/bridge.py') for name in names),names
        assert any(name.endswith('/middleware.py') for name in names),names
        assert not any(name.startswith('tests/') for name in names),names
    else:
        assert any(name.endswith('/README.md') for name in names),names
        assert any(name.endswith('/SECURITY.md') for name in names),names
print('PASS: wheel and source distribution contents verified')
