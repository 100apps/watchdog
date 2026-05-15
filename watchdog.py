#!/usr/bin/env python3
"""
watchdog.py - 通用进程守护，无第三方依赖，跨平台

配置文件模式（推荐，支持多任务）：
  在脚本同目录创建 watchdog.json，内容示例：
  {
      "tasks": [
          {"cmd": "ssh -N -D 10081 root@host", "match": "-D 10081"},
          {"cmd": "frpc -c /etc/frpc.ini",     "match": "frpc.ini"}
      ]
  }
  然后直接运行：
    python watchdog.py

命令行模式（单任务）：
  python watchdog.py --cmd "ssh -N -D 10081 root@host" --match "-D 10081"

schtasks (Windows，配置文件模式)：
  pythonw.exe "D:\\software\\bin\\watchdog.py"

crontab (Linux，配置文件模式)：
  * * * * * python3 /opt/watchdog.py
"""

import getpass
import json
import os
import random
import shlex
import subprocess
import sys
import argparse
import time
from datetime import datetime
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "watchdog.json"
PID_FILE    = Path(__file__).parent / "watchdog.pid"
DEFAULT_LOG = Path(__file__).parent / "watchdog.log"
SCRIPT      = Path(__file__).resolve()
TASK_NAME   = "Watchdog"


# ── PID 文件自检 ───────────────────────────────────────────

def _pid_alive(pid):
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return str(pid) in result.stdout
        else:
            os.kill(pid, 0)
            return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _is_locked():
    if not PID_FILE.exists():
        return False
    try:
        old_pid = int(PID_FILE.read_text().strip())
    except ValueError:
        return False
    return _pid_alive(old_pid)


def acquire_pid_file():
    if _is_locked():
        wait = random.randint(1, 30)
        print(f"[WARN] watchdog already running, retrying in {wait}s...", file=sys.stderr)
        time.sleep(wait)
        if _is_locked():
            print("[ERROR] watchdog still running after retry, exit.", file=sys.stderr)
            sys.exit(1)
    PID_FILE.write_text(str(os.getpid()))


def release_pid_file():
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


# ── 日志 ──────────────────────────────────────────────────

def log(path, msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} {msg}"
    with open(path, "a") as f:
        f.write(line + "\n")


# ── 进程查找 ───────────────────────────────────────────────

def find_pid(match):
    self_pid = os.getpid()

    if sys.platform == "win32":
        ps_cmd = (
            "Get-CimInstance Win32_Process "
            "| ForEach-Object { $_.ProcessId.ToString() + ' ' + $_.CommandLine }"
        )
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pid = int(line.split()[0])
            except ValueError:
                continue
            if pid == self_pid:
                continue
            if match in line:
                return pid
    elif Path("/proc").is_dir():
        # Linux: read /proc/<pid>/cmdline
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            pid = int(pid_dir.name)
            if pid == self_pid:
                continue
            try:
                cmdline = (pid_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
                if match in cmdline:
                    return pid
            except (PermissionError, FileNotFoundError):
                pass
    else:
        # macOS / other Unix: use ps
        result = subprocess.run(
            ["ps", "-eo", "pid,command"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            if pid == self_pid:
                continue
            if match in parts[1]:
                return pid
    return None


# ── 启动 ──────────────────────────────────────────────────

def start(cmd):
    args = shlex.split(cmd)
    kwargs = {
        "stdin":  subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)


# ── 执行单个任务 ───────────────────────────────────────────

def run_task(cmd, match, log_path):
    pid = find_pid(match)
    if pid:
        log(log_path, f"[OK] '{match}' already running (PID: {pid})")
    else:
        log(log_path, f"[WARN] '{match}' not found, starting: {cmd}")
        try:
            start(cmd)
            log(log_path, "[OK] started successfully")
        except Exception as e:
            log(log_path, f"[ERROR] failed to start: {e}")


# ── 配置加载 ───────────────────────────────────────────────

def load_tasks_from_config():
    if not CONFIG_FILE.exists():
        print(f"[ERROR] config file not found: {CONFIG_FILE}", file=sys.stderr)
        print("  请创建 watchdog.json 或使用 --cmd / --match 参数", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        config = json.load(f)
    tasks = config.get("tasks", [])
    if not tasks:
        print("[ERROR] watchdog.json 中 tasks 为空", file=sys.stderr)
        sys.exit(1)
    return tasks


# ── 工具函数 ───────────────────────────────────────────────

def get_pythonw():
    if sys.platform == "win32":
        pythonw = Path(sys.executable).parent / "pythonw.exe"
        if pythonw.exists():
            return str(pythonw)
    return sys.executable


# ── 帮助 epilog ────────────────────────────────────────────

def build_epilog():
    script_path = str(SCRIPT)
    username    = getpass.getuser()
    pythonw     = get_pythonw()

    if sys.platform == "win32":
        tr = f'"{pythonw}" "{script_path}"'
        schtasks_section = f"""
Windows schtasks 用法（配置文件模式，推荐）
─────────────────────────────────────────────────────────────

  注册任务（每分钟）：
    schtasks /create /tn "{TASK_NAME}" /tr '{tr}' /sc minute /mo 1 /ru {username} /f

  立即手动运行一次：
    schtasks /run /tn "{TASK_NAME}"

  查询任务状态：
    schtasks /query /tn "{TASK_NAME}" /fo list

  修改触发频率（改为每5分钟）：
    schtasks /change /tn "{TASK_NAME}" /sc minute /mo 5

  禁用任务：
    schtasks /change /tn "{TASK_NAME}" /disable

  启用任务：
    schtasks /change /tn "{TASK_NAME}" /enable

  删除任务：
    schtasks /delete /tn "{TASK_NAME}" /f
"""
    else:
        schtasks_section = ""

    return f"""
配置文件 watchdog.json 示例（与脚本同目录，支持多任务）：
─────────────────────────────────────────────────────────────
  {{
      "tasks": [
          {{
              "cmd":   "ssh -N -D 10081 root@host -p 2222 -o ServerAliveInterval=30 -o ServerAliveCountMax=3",
              "match": "-D 10081",
              "log":   "/var/log/ssh-watchdog.log"
          }},
          {{
              "cmd":   "frpc -c /etc/frpc.ini",
              "match": "frpc.ini"
          }}
      ]
  }}

  log 字段可选，默认使用脚本同目录 watchdog.log。
{schtasks_section}
Linux crontab 用法
─────────────────────────────────────────────────────────────

  编辑：
    crontab -e

  每分钟运行（添加以下行）：
    * * * * * python3 {script_path}

  查看当前 crontab：
    crontab -l

  删除所有 crontab（慎用）：
    crontab -r
"""


# ── 参数解析 ───────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="通用进程守护 - 检查目标进程是否存在，不存在则启动",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=build_epilog()
    )
    p.add_argument("--cmd",   help="启动命令（单任务模式）")
    p.add_argument("--match", help="进程匹配关键字（单任务模式）")
    p.add_argument("--log",   default=str(DEFAULT_LOG), help="日志路径（单任务模式，默认脚本同目录）")
    return p.parse_args()


# ── 入口 ──────────────────────────────────────────────────

if __name__ == "__main__":
    a = parse_args()

    # 确定任务列表
    if a.cmd or a.match:
        # 命令行模式：单任务
        if not a.cmd or not a.match:
            print("[ERROR] --cmd 和 --match 必须同时提供", file=sys.stderr)
            sys.exit(1)
        tasks = [{"cmd": a.cmd, "match": a.match, "log": a.log}]
    else:
        # 配置文件模式：多任务
        tasks = load_tasks_from_config()

    acquire_pid_file()
    try:
        for task in tasks:
            run_task(
                cmd      = task["cmd"],
                match    = task["match"],
                log_path = Path(task.get("log", DEFAULT_LOG)),
            )
    finally:
        release_pid_file()
