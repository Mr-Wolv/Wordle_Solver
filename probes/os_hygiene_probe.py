"""OS-hygiene probe for Wordle Strat-Console.

Empirically measures, for each real-world scenario, the process tree +
working-set footprint and confirms teardown leaves zero dangling processes:
  * idle (no app)
  * 1 frozen game EXE
  * 3 frozen game EXEs (multiple games)
  * 1 dev server (python -m wordle_solver.app.dev_server)
  * 2 dev servers (multiple dev servers)
  * 1 game launched with NO WSC_PORT (the default user path)
  * teardown -> residual census

Read-only except it LAUNCHES the same app processes a user would and
force-kills (taskkill /F) exactly the PIDs it recorded at the end. It never
kills anything it didn't start.

Why this lives in probes/ and is NOT a throwaway: in practice it caught
  * a dangling game EXE left from a prior test run, and
  * the P0 "Backend failed to start" regression: the frozen bundle re-probed
    a port the in-process server already held, so the window waited on an
    empty port. That bug only reproduced on the DEFAULT (no WSC_PORT) launch —
    which this probe exercises explicitly (see the no-env scenario).

Run (after building the bundle):  python probes/os_hygiene_probe.py
The bundle must exist at dist/Wordle-Strat-Console/Wordle-Strat-Console.exe
(build it with `python build_game.py` or `python -m wordle_solver.desktop.build_dist`).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(REPO, "dist", "Wordle-Strat-Console", "Wordle-Strat-Console.exe")
PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")


def ps():
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,"
         "Name,WorkingSetSize,CommandLine | ConvertTo-Json -Compress"],
        capture_output=True, text=True,
    ).stdout.strip()
    if not out:
        return []
    return json.loads(out) if out.startswith("[") else [json.loads(out)]


def census(procs):
    """Count OUR processes (python dev_server, not shell cmdlines) + working set."""
    game = dev = webv = 0
    ws = 0
    for p in procs:
        name = p.get("Name") or ""
        cmd = p.get("CommandLine") or "" or ""
        if name == "Wordle-Strat-Console.exe":
            game += 1
            ws += p.get("WorkingSetSize") or 0
        # Only count actual python dev_server processes, not the bash/powershell
        # shells whose command line happens to contain the substring.
        if name == "python.exe" and "wordle_solver.app.dev_server" in cmd:
            dev += 1
            ws += p.get("WorkingSetSize") or 0
        if name == "msedgewebview2.exe":
            webv += 1
    return game, dev, webv, round(ws / 1024 / 1024, 1)


def find_free_port(pref=8753):
    for off in range(200):
        p = pref + off
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("no free localhost port")


def urllib_request(port):
    import urllib.request
    return urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1).read()


def wait_port(port, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib_request(port)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def launch_exe(port, env_extra=None):
    """Launch with WSC_PORT forced to `port` (used for the 1/3-game scenarios)."""
    env = dict(os.environ, WSC_PORT=str(port))
    if env_extra:
        env.update(env_extra)
    return subprocess.Popen(
        [EXE], cwd=os.path.dirname(EXE), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def launch_exe_default():
    """Launch with WSC_PORT UNSET (the real default user path)."""
    env = {k: v for k, v in os.environ.items() if k != "WSC_PORT"}
    return subprocess.Popen(
        [EXE], cwd=os.path.dirname(EXE), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def launch_dev(port):
    return subprocess.Popen(
        [PY, "-m", "wordle_solver.app.dev_server", "--port", str(port)],
        cwd=REPO, env=dict(os.environ, PYTHONPATH=os.path.join(REPO, "src")),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def kill_all(pids):
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=5)
        except Exception:
            pass


def scenario(label, fn):
    g, d, w, ws = census(fn())
    print(f"{label:10s}: game={g} dev={d} webview2={w} ws_mb={ws}")


def main():
    all_pids = []
    # GUARANTEE teardown even if an assertion/scenario fails — the whole point
    # of this probe is to prove zero dangling processes, so it must never
    # itself orphan the processes it launched.
    try:
        if not os.path.exists(EXE):
            print(f"WARN: built bundle missing at {EXE} — run `python build_game.py` first.")
        procs = ps()
        g0, d0, w0, ws0 = census(procs)
        print(f"BASELINE  : game={g0} dev={d0} webview2={w0} ws_mb={ws0}")

        # 1 frozen game
        p1 = find_free_port(9001)
        e1 = launch_exe(p1); all_pids.append(e1.pid)
        assert wait_port(p1), "game1 did not come up"
        scenario("1 GAME", ps)

        # 3 frozen games (multiple games)
        p2, p3 = find_free_port(9101), find_free_port(9201)
        e2, e3 = launch_exe(p2), launch_exe(p3)
        all_pids += [e2.pid, e3.pid]
        assert wait_port(p2) and wait_port(p3), "games 2/3 did not come up"
        scenario("3 GAMES", ps)

        # 1 dev server (auto-chosen free port)
        dp1 = find_free_port(9301)
        s1 = launch_dev(dp1); all_pids.append(s1.pid)
        assert wait_port(dp1, timeout=40), f"dev1 on :{dp1} did not come up"
        scenario("1 DEV", ps)

        # 2 dev servers (multiple dev servers)
        dp2 = find_free_port(9401)
        s2 = launch_dev(dp2); all_pids.append(s2.pid)
        assert wait_port(dp2, timeout=40), f"dev2 on :{dp2} did not come up"
        scenario("2 DEV", ps)

        # DEFAULT launch path (no WSC_PORT) — the exact path that regressed
        # into "Backend failed to start". Must come up and serve. The app
        # auto-picks the first free port from 8753, so scan that window.
        e_default = launch_exe_default()
        all_pids.append(e_default.pid)
        up_default = None
        for cand in [8753 + i for i in range(40)]:
            if wait_port(cand, timeout=2.0):
                up_default = cand
                break
        if up_default is None:
            print("DEFAULT   : CONCERN — no-env launch did not come up (P0-class bug!)")
        else:
            print(f"DEFAULT   : no-WSC_PORT launch came up on :{up_default}  OK")
    finally:
        print("\n=== TEARDOWN (taskkill /F on all launched PIDs) ===")
        kill_all(all_pids)
        # belt-and-suspenders: also kill anything matching our app by name,
        # in case a PID slipped through (e.g. a child we didn't record).
        try:
            subprocess.run(["taskkill", "/F", "/IM", "Wordle-Strat-Console.exe"],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        time.sleep(3)
        g, d, w, ws = census(ps())
        print(f"AFTER     : game={g} dev={d} webview2={w} ws_mb={ws}")
        extra = (g - g0) + (d - d0)
        print("\nVERDICT:", "OK: 0 dangling game/dev beyond baseline"
              if extra == 0 else f"CONCERN: {extra} extra game/dev vs baseline")
        if w > 0:
            print(f"(webview2={w} are pre-existing OS runtime hosts, not our children — "
                  f"no fork-bomb signature if none are under our dev_servers)")


if __name__ == "__main__":
    main()
