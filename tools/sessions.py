#!/usr/bin/env python3
# Dashboard of context fill of ALL Claude sessions (reads the shared transcripts
# ~/.claude/projects/*/*.jsonl). Read-only, no hacks.
# Flags: --watch [sec] — refresh; --all — show the "empty" ones too.
import glob, json, os, sys, time

RST = "\033[0m"; DIM = "\033[2m"
def col(pct): return "\033[31m" if pct >= 85 else "\033[33m" if pct >= 70 else "\033[32m"

def window_for(model):
    m = (model or "").lower()
    if "[1m]" in m or "-1m" in m: return 1_000_000
    return 200_000

def scan(path):
    """Returns (fill_tokens, model, window) from the tail of the transcript."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 400_000))
            tail = f.read().decode("utf-8", "ignore")
    except OSError:
        return 0, None, 200_000
    fill, model, win = 0, None, 0
    for line in tail.splitlines():
        line = line.strip()
        if not line or line[0] != "{": continue
        try: ev = json.loads(line)
        except json.JSONDecodeError: continue
        msg = ev.get("message") or {}
        u = msg.get("usage")
        if isinstance(u, dict) and u.get("input_tokens") is not None:
            fill = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0))
        if msg.get("model"): model = msg["model"]
        for info in (ev.get("modelUsage") or {}).values():
            if info.get("contextWindow"): win = info["contextWindow"]
    return fill, model, (win or window_for(model))

def render(show_all):
    base = os.path.expanduser("~/.claude/projects")
    rows = []
    for path in glob.glob(os.path.join(base, "*", "*.jsonl")):
        try: mtime = os.path.getmtime(path)
        except OSError: continue
        fill, model, win = scan(path)
        if fill == 0 and not show_all: continue
        proj = os.path.basename(os.path.dirname(path)).lstrip("-").replace("-", "/")
        rows.append((mtime, proj, os.path.basename(path)[:8], fill, win))
    rows.sort(reverse=True)
    now = time.time()
    out = [f"{DIM}Claude sessions · context fill · {time.strftime('%H:%M:%S')}{RST}",
           f"{DIM}{'age':>7}  {'context':<18}  {'sid':8}  project{RST}"]
    for mtime, proj, sid, fill, win in rows[:40]:
        pct = fill * 100 // win if win else 0
        age = now - mtime
        agestr = f"{int(age)}s" if age < 60 else (f"{int(age/60)}m" if age < 3600 else f"{int(age/3600)}h")
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        out.append(f"{agestr:>7}  {col(pct)}[{bar}] {pct:>3}%{RST} {fill//1000:>4}k/{win//1000}k  {sid}  /{proj}")
    if len(rows) == 0:
        out.append(f"{DIM}(no active sessions found){RST}")
    return "\n".join(out)

def main():
    args = sys.argv[1:]
    show_all = "--all" in args
    watch = None
    if "--watch" in args:
        i = args.index("--watch")
        watch = float(args[i + 1]) if i + 1 < len(args) and args[i + 1].replace(".", "").isdigit() else 3.0
    if watch:
        try:
            while True:
                sys.stdout.write("\033[2J\033[H" + render(show_all) + "\n")
                sys.stdout.flush(); time.sleep(watch)
        except KeyboardInterrupt:
            pass
    else:
        print(render(show_all))

if __name__ == "__main__":
    main()
