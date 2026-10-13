"""
Перевірка версії й самооновлення з GitHub: version.txt у гілці main (raw.githubusercontent.com)
і exe з останнього релізу. Схема та сама, що в ShadowSessionTool.
"""
import os
import subprocess
import sys
import tempfile
import urllib.request
import uuid

REPO_URL = "https://github.com/Pro100NeFarT/TableConverter"
VERSION_URL = "https://raw.githubusercontent.com/Pro100NeFarT/TableConverter/main/version.txt"
EXE_URL = REPO_URL + "/releases/latest/download/TableConverter.exe"
USER_AGENT = "TableConverter"


def parse_version(text):
    try:
        return tuple(int(part) for part in str(text).strip().lstrip("vV").split("."))
    except ValueError:
        return None


def _open(url, timeout):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def fetch_remote_version(timeout=8):
    with _open(VERSION_URL, timeout) as response:
        return response.read().decode("utf-8-sig").strip()


def check(local_version, fetch=None):
    """('newer', віддалена) / ('current', віддалена) / ('error', повідомлення)."""
    try:
        remote = str((fetch or fetch_remote_version)()).strip()
    except Exception as exc:
        return "error", str(exc)
    remote_v, local_v = parse_version(remote), parse_version(local_version)
    if remote_v is None or local_v is None:
        return "error", f"Невірний формат версії: {remote!r}"
    return ("newer" if remote_v > local_v else "current"), remote


def can_self_update():
    """Самооновлення має сенс лише для зібраного exe."""
    return bool(getattr(sys, "frozen", False))


def download(url, dest, timeout=120):
    with _open(url, timeout) as response, open(dest, "wb") as out:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)


def update_script(exe_path, new_path):
    """bat: дочекатись завершення застосунку (через 20 с - примусово), підмінити exe, запустити, видалити себе."""
    name = os.path.basename(exe_path)
    return "\r\n".join(
        [
            "@echo off",
            "chcp 65001 >nul",
            "set N=0",
            ":wait",
            f'tasklist /fi "IMAGENAME eq {name}" | find /I "{name}" >nul',
            "if not errorlevel 1 (",
            "  set /a N+=1",
            f"  if %N% GEQ 20 taskkill /F /IM {name} >nul 2>&1",
            "  timeout /t 1 /nobreak >nul",
            "  goto wait",
            ")",
            "set M=0",
            ":move",
            f'move /y "{new_path}" "{exe_path}" >nul 2>&1',
            "if errorlevel 1 (",
            "  set /a M+=1",
            "  if %M% LSS 10 (",
            "    timeout /t 1 /nobreak >nul",
            "    goto move",
            "  )",
            ")",
            f'start "" "{exe_path}"',
            'del "%~f0"',
            "",
        ]
    )


def launch_update(exe_path, new_path):
    """Запускає bat у фоні; після цього застосунок має завершитись."""
    bat = os.path.join(tempfile.gettempdir(), f"tableconverter_update_{uuid.uuid4().hex}.bat")
    with open(bat, "w", encoding="utf-8", newline="") as f:
        f.write(update_script(exe_path, new_path))
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")  # новий екземпляр не має успадкувати тимчасову теку старого
    subprocess.Popen(
        ["cmd.exe", "/c", bat],
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    return bat
