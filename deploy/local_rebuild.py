from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
LOG_DIR = REPO_ROOT / "deploy" / "logs"
BACKEND_LOG = LOG_DIR / "backend.log"
FRONTEND_LOG = LOG_DIR / "frontend.log"
MIN_PYTHON = (3, 10)
MIN_NODE = (18, 0, 0)


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def backend_venv_python() -> Path:
    if os.name == "nt":
        return BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
    return BACKEND_DIR / ".venv" / "bin" / "python"


def is_transient_python(candidate: Path) -> bool:
    value = str(candidate)
    transient_markers = [
        "uv-cache",
        "/private/tmp/",
        "/tmp/",
        "/var/folders/",
        "\\Temp\\",
    ]
    return any(marker in value for marker in transient_markers)


def resolve_bootstrap_python() -> str:
    candidates: list[Path] = []
    for command in ("python3.13", "python3.12", "python3.11", "python3.10", "python3", "python"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
    if sys.executable:
        candidates.append(Path(sys.executable))

    for candidate in candidates:
        if candidate.exists() and not is_transient_python(candidate) and python_version_supported(str(candidate)):
            return str(candidate)
    for candidate in candidates:
        if candidate.exists() and python_version_supported(str(candidate)):
            log(f"警告：回退使用临时 Python 解释器 {candidate}")
            return str(candidate)
    raise RuntimeError("未找到 Python 3.10+ 解释器。请先安装 Python 3.10、3.11 或 3.12。")


def read_python_version(python_bin: str) -> tuple[int, int] | None:
    completed = subprocess.run(
        [python_bin, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    raw = completed.stdout.strip()
    try:
        major, minor = raw.split(".", 1)
        return int(major), int(minor)
    except Exception:
        return None


def python_version_supported(python_bin: str) -> bool:
    version = read_python_version(python_bin)
    return bool(version and version >= MIN_PYTHON)


def parse_semver(raw: str) -> tuple[int, ...] | None:
    value = raw.strip().lstrip("v")
    if not value:
        return None
    parts = value.split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def read_node_version(node_bin: Path) -> tuple[int, ...] | None:
    completed = subprocess.run(
        [str(node_bin), "-p", "process.versions.node"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return parse_semver(completed.stdout)


def node_bin_candidates() -> list[Path]:
    candidates: list[Path] = []
    direct = shutil.which("node")
    if direct:
        candidates.append(Path(direct))

    nvm_root = Path.home() / ".nvm" / "versions" / "node"
    if nvm_root.exists():
        discovered = sorted(
            nvm_root.glob("v*/bin/node"),
            key=lambda path: parse_semver(path.parents[1].name) or (0, 0, 0),
            reverse=True,
        )
        candidates.extend(discovered)

    for extra in (
        Path("/opt/homebrew/bin/node"),
        Path("/usr/local/bin/node"),
    ):
        if extra.exists():
            candidates.append(extra)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen and candidate.exists():
            seen.add(key)
            unique.append(candidate)
    return unique


def resolve_node_runtime() -> tuple[str, dict[str, str]]:
    for node_bin in node_bin_candidates():
        npm_bin = node_bin.with_name("npm")
        if not npm_bin.exists():
            continue
        version = read_node_version(node_bin)
        if version and version >= MIN_NODE:
            env = os.environ.copy()
            bin_dir = str(node_bin.parent)
            env["PATH"] = bin_dir if not env.get("PATH") else f"{bin_dir}{os.pathsep}{env['PATH']}"
            return str(npm_bin), env
    raise RuntimeError("未找到 Node 18+ / npm 环境。请先安装 Node.js 18、20 或 24，或确保 ~/.nvm/versions/node 可用。")


def resolve_npm_binary() -> str:
    npm_bin, _ = resolve_node_runtime()
    return npm_bin


def ensure_backend_python() -> str:
    venv_python = backend_venv_python()
    if venv_python.exists() and python_version_supported(str(venv_python)):
        return str(venv_python)
    if venv_python.exists():
        log(f"检测到旧版 backend/.venv（{venv_python}），准备删除并按 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ 重建。")
        shutil.rmtree(BACKEND_DIR / ".venv", ignore_errors=True)

    bootstrap_python = resolve_bootstrap_python()
    log(f"未检测到 backend/.venv，正在使用 {bootstrap_python} 创建虚拟环境。")
    run_command([bootstrap_python, "-m", "venv", str(BACKEND_DIR / ".venv")], REPO_ROOT)
    if not venv_python.exists():
        raise RuntimeError(f"虚拟环境创建成功但未找到解释器：{venv_python}")
    run_command([str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], BACKEND_DIR)
    return str(venv_python)


def run_command(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    log(f"执行：{' '.join(command)}")
    completed = subprocess.run(command, cwd=str(cwd), check=False, env=env)
    if completed.returncode != 0:
        raise RuntimeError(f"命令执行失败（exit={completed.returncode}）：{' '.join(command)}")


def _kill_pid(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        return


def kill_port(port: int) -> None:
    log(f"尝试释放端口 {port}")
    if os.name == "nt":
        script = (
            f"$connections = Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue; "
            "if ($connections) { "
            "$connections | Select-Object -ExpandProperty OwningProcess -Unique | "
            "ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } "
            "}"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=False)
        return

    lsof = shutil.which("lsof")
    if lsof:
        result = subprocess.run([lsof, "-ti", f":{port}"], capture_output=True, text=True, check=False)
        pids = [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]
        for pid in pids:
            _kill_pid(pid)
        return

    fuser = shutil.which("fuser")
    if fuser:
        subprocess.run([fuser, "-k", f"{port}/tcp"], check=False)


def start_detached(command: list[str], cwd: Path, log_path: Path, env: dict[str, str] | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8")
    try:
        popen_kwargs: dict[str, object] = {
            "cwd": str(cwd),
            "stdin": subprocess.DEVNULL,
            "stdout": handle,
            "stderr": subprocess.STDOUT,
            "env": env,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            popen_kwargs["start_new_session"] = True
        subprocess.Popen(command, **popen_kwargs)
    finally:
        handle.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键重建并重启本地 Forecast Lab。")
    parser.add_argument("--delay-seconds", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if args.delay_seconds > 0:
        log(f"等待 {args.delay_seconds} 秒后开始重建，以便当前请求先返回。")
        time.sleep(args.delay_seconds)

    backend_python = ensure_backend_python()
    npm_binary, frontend_env = resolve_node_runtime()

    run_command([backend_python, "-m", "pip", "install", "-r", "requirements.txt"], BACKEND_DIR)
    run_command([npm_binary, "install"], FRONTEND_DIR, env=frontend_env)
    run_command([npm_binary, "run", "build"], FRONTEND_DIR, env=frontend_env)

    kill_port(8100)
    kill_port(5173)
    if os.name != "nt":
        time.sleep(1)

    start_detached([backend_python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8100"], BACKEND_DIR, BACKEND_LOG)
    start_detached([npm_binary, "run", "dev", "--", "--host", "127.0.0.1"], FRONTEND_DIR, FRONTEND_LOG, env=frontend_env)

    log("已启动后台服务：后端 http://127.0.0.1:8100 ，前端 http://127.0.0.1:5173")
    log(f"日志目录：{LOG_DIR}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log(f"重建失败：{exc}")
        raise
