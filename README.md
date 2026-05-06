# watchdog.py

A lightweight, cross-platform process watchdog. No third-party dependencies.

Checks if a target process is running every minute via cron/schtasks, and starts it if not.

## Features

- ✅ Cross-platform: Windows & Linux
- ✅ No third-party dependencies (stdlib only)
- ✅ Multi-task support via JSON config
- ✅ Process matching by cmdline substring (not just process name)
- ✅ PID file to prevent concurrent watchdog instances
- ✅ No console window flicker on Windows (`pythonw.exe`)

## Quick Start

### 1. Config file (recommended, supports multiple tasks)

Create `watchdog.json` in the same directory as `watchdog.py`:

```json
{
    "tasks": [
        {
            "cmd":   "ssh -N -D 10081 root@myhost -p 2222 -o ServerAliveInterval=30 -o ServerAliveCountMax=3",
            "match": "-D 10081",
            "log":   "/var/log/ssh-watchdog.log"
        },
        {
            "cmd":   "frpc -c /etc/frpc.ini",
            "match": "frpc.ini"
        }
    ]
}
```

Then run:

```bash
python watchdog.py
```

`log` is optional — defaults to `watchdog.log` in the same directory.

### 2. Command line (single task)

```bash
python watchdog.py --cmd "ssh -N -D 10081 root@myhost" --match "-D 10081"
```

Priority: CLI args > config file > defaults.

## Scheduling

### Windows (schtasks)

Run in PowerShell — no console window flicker:

```powershell
# Register (every minute)
schtasks /create /tn "Watchdog" /tr '"C:\path\to\pythonw.exe" "C:\path\to\watchdog.py"' /sc minute /mo 1 /ru $env:USERNAME /f

# Run immediately
schtasks /run /tn "Watchdog"

# Query
schtasks /query /tn "Watchdog" /fo list

# Change interval (e.g. every 5 minutes)
schtasks /change /tn "Watchdog" /sc minute /mo 5

# Disable / Enable
schtasks /change /tn "Watchdog" /disable
schtasks /change /tn "Watchdog" /enable

# Delete
schtasks /delete /tn "Watchdog" /f
```

> Use `pythonw.exe` (same directory as `python.exe`) to avoid console window flicker.

### Linux (crontab)

```bash
crontab -e
```

Add:

```
* * * * * python3 /path/to/watchdog.py
```

## Log Output

```
2026-05-06 10:00:01 [OK]   '-D 10081' already running (PID: 4321)
2026-05-06 10:01:01 [WARN] '-D 10081' not found, starting: ssh -N -D 10081 ...
2026-05-06 10:01:01 [OK]   started successfully
```

## Options

```
--cmd    Launch command (single task mode)
--match  Substring to match against process cmdline
--log    Log file path (default: watchdog.log next to script)
```

## Requirements

- Python 3.6+
- No pip installs needed
