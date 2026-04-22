import subprocess
from datetime import datetime
from pathlib import Path

from config import LOG_FILE


def _log(action: str, **kwargs):
    parts = " ".join(f"{k}={v}" for k, v in kwargs.items())
    msg = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [{action}] {parts}\n"
    try:
        with LOG_FILE.open("a") as f:
            f.write(msg)
    except PermissionError:
        pass


def run(cmd: list, input: str = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, input=input)


def run_capture(cmd: list) -> str:
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return result.stdout


def sudo_mkdir(path: Path):
    run(["sudo", "mkdir", "-p", str(path)])


def sudo_write(path: Path, content: str, owner: str = None):
    subprocess.run(
        ["sudo", "tee", str(path)],
        input=content,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    if owner:
        run(["sudo", "chown", f"{owner}:{owner}", str(path)])


def sudo_chown_r(path: Path, owner: str):
    run(["sudo", "chown", "-R", f"{owner}:{owner}", str(path)])
