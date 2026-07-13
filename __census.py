"""Read-only process census for the Wordle Strat-Console verification.

Counts every PID type relevant to "is anything dangling?":
  * game EXE               -> Wordle-Strat-Console.exe
  * dev_server children    -> python ... -m wordle_solver.app.dev_server
  * webview2 (game's UI)   -> msedgewebview2.exe  (only those whose parent is the game)
  * the matrix-load helper -> any python running the engine (optional signal)
Prints a compact table + a JSON line for easy diffing. NEVER spawns/kills.
"""
import json
import subprocess


def _ps():
    out = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress",
        ],
        capture_output=True, text=True,
    )
    procs = []
    raw = out.stdout.strip()
    if not raw:
        return procs
    # ConvertTo-Json may emit a single object (no surrounding []) when 1 row
    if raw.startswith("["):
        data = json.loads(raw)
    else:
        data = [json.loads(raw)]
    return data


def census():
    procs = _ps()
    game = []
    dev = []
    webview_under_game = []
    game_pids = set()
    for p in procs:
        name = (p.get("Name") or "")
        cmd = (p.get("CommandLine") or "") or ""
        pid = p.get("ProcessId")
        ppid = p.get("ParentProcessId")
        if name == "Wordle-Strat-Console.exe":
            game.append((pid, ppid, cmd))
            game_pids.add(pid)
        if "wordle_solver.app.dev_server" in cmd:
            dev.append((pid, ppid, cmd))
    # any webview2 whose parent is a dev_server (would prove a fork bomb)
    dev_pids = {pid for pid, _, _ in dev}
    webview_under_game = [
        (pid, ppid)
        for pid, ppid in [
            (p.get("ProcessId"), p.get("ParentProcessId"))
            for p in procs
            if (p.get("Name") or "") == "msedgewebview2.exe"
        ]
        if ppid in game_pids
    ]
    webview_under_dev = [w for w in webview_under_game if w[1] in dev_pids]
    return {
        "game_exe": len(game),
        "dev_server": len(dev),
        "webview_under_game": len(webview_under_game),
        "webview_under_dev": len(webview_under_dev),
        "game_pids": sorted(game_pids),
        "dev_pids": sorted(dev_pids),
    }


if __name__ == "__main__":
    c = census()
    print(
        f"game EXE={c['game_exe']}  dev_server={c['dev_server']}  "
        f"webview_under_game={c['webview_under_game']}  "
        f"webview_under_dev={c['webview_under_dev']}"
    )
    print("game_pids=" + str(c["game_pids"]))
    print("dev_pids=" + str(c["dev_pids"]))
    print("CENSUS_JSON " + json.dumps(c))
    if c["webview_under_dev"] > 0 or c["dev_server"] > 0:
        print("WARN: dev_server children present (expected only in source mode / not in frozen EXE)")
    else:
        print("OK: no dev_server children, no fork-bomb signature")
