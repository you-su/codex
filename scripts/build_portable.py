"""Build and test a Windows portable distribution on a Windows runner."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'dist'
APP = OUT / 'Fish-API-Pro'
RUNTIME = APP / 'runtime'
OUT.mkdir(exist_ok=True)
APP.mkdir(exist_ok=True)
for item in (ROOT / 'fish-api-pro').iterdir():
    if item.is_file() and not item.name.startswith('.'):
        shutil.copy2(item, APP / item.name)
RUNTIME.mkdir(exist_ok=True)
version = '3.12.10'
archive = OUT / 'python-embed.zip'
url = f'https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip'
with urllib.request.urlopen(url, timeout=90) as response:
    archive.write_bytes(response.read())
with zipfile.ZipFile(archive) as z:
    if z.testzip() is not None:
        raise RuntimeError('Python runtime archive failed integrity check')
    z.extractall(RUNTIME)
(RUNTIME / 'python312._pth').write_text('python312.zip\n.\n..\n', encoding='ascii')
python = RUNTIME / 'python.exe'
subprocess.run([str(python), '-m', 'unittest', 'discover', '-s', str(APP)], check=True, cwd=APP)
# Verify startup from a Unicode path, using only the embedded runtime.
probe = OUT / '\u4fbf\u643a\u7248 \u542f\u52a8\u6d4b\u8bd5'
shutil.copytree(APP, probe)
probe_python = probe / 'runtime' / 'python.exe'
# Exercise the actual BAT entry point as well as embedded Python's imports.
# Suppress the browser only during this automated check.
bat = probe / 'start.bat'
bat.write_bytes(bat.read_bytes().replace(b'"server.py"', b'"server.py" --no-browser'))
log_path = OUT / 'startup-test.log'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with log_path.open('wb') as log:
    process = subprocess.Popen(['cmd.exe', '/d', '/c', 'start.bat'], cwd=probe, stdout=log, stderr=log, stdin=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 25
        while True:
            try:
                html = opener.open('http://127.0.0.1:8765/', timeout=2).read().decode('utf-8')
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError('Portable startup failed: ' + log_path.read_text('utf-8', errors='replace'))
                time.sleep(.2)
        token = re.search(r"X-Local-Token':'([^']+)'", html).group(1)
        headers = {'X-Local-Token': token, 'Content-Type': 'application/json'}
        def get(path):
            return opener.open(urllib.request.Request('http://127.0.0.1:8765' + path, headers=headers), timeout=5)
        def post(path, body):
            request = urllib.request.Request('http://127.0.0.1:8765' + path, data=json.dumps(body).encode(), headers=headers)
            return json.load(opener.open(request, timeout=5))
        assert json.load(get('/api/state'))['ports'] == []
        assert get('/logo.svg').status == 200
        result = post('/api/session', {'system': 'portable smoke test'})
        assert len(result['sessions']) == 1
        assert post('/api/export', {})['ports'] == []
        # Confirm shutdown accepts local authentication and exits cleanly.
        assert post('/api/shutdown', {})['ok']
        process.wait(timeout=15)
        assert process.returncode == 0, log_path.read_text('utf-8', errors='replace')
    finally:
        if process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], check=False)

# Runtime imports must not leave cache, tests or test-generated data in the package.
for cache in APP.rglob('__pycache__'):
    shutil.rmtree(cache)
for test in APP.glob('test_*.py'):
    test.unlink()
for folder in ('logs', 'voices'):
    if (APP / folder).exists():
        shutil.rmtree(APP / folder)
(APP / 'settings.json').write_text(json.dumps({'ports': [], 'config': {'pet': False, 'qqVoice': False, 'petVoice': False}, 'activePort': None, 'autoSwitch': True, 'lastRoute': []}, indent=2), encoding='utf-8')
(APP / 'START-HERE.txt').write_text('Windows 10/11 64-bit portable edition.\nExtract ALL files, then double-click start.bat.\nPython is included in runtime/. No installation or administrator access required.\nKeep the console open while using the application.\nIf the browser does not open: http://127.0.0.1:8765\nDo not overwrite your existing settings.json when upgrading.\n', encoding='utf-8')
result = OUT / 'fish-api-pro-windows-x64.zip'
with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as z:
    for item in APP.rglob('*'):
        if item.is_file():
            z.write(item, item.relative_to(OUT))
checksum = hashlib.sha256(result.read_bytes()).hexdigest()
(OUT / 'SHA256SUMS.txt').write_text(checksum + '  ' + result.name + '\n', encoding='ascii')
print('Portable runtime, unit tests, Unicode path, BAT startup, authenticated HTTP, sessions and shutdown: PASSED')
print(result)
