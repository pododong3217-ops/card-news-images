# -*- coding: utf-8 -*-
"""밀린 배치 게시기 — 아직 안 올린 배치를 오래된 것부터 한 번에 하나씩 올린다.

토큰이 막혀 있는 동안 쌓인 배치를 한꺼번에 쏟으면 스팸으로 보여 도달이 깎인다.
이 스크립트는 한 번 실행에 딱 한 배치만 올리고 기록해 둔다. 예약으로 하루 한 번
돌리면 밀린 것이 하루 한 편씩 빠져나간다.

사용법: python pipeline/post_queue.py          (가장 오래된 미게시 배치 1편 게시)
        python pipeline/post_queue.py --list   (대기 목록만 보기)
        python pipeline/post_queue.py --all    (전부 게시 — 스팸 위험, 확인 후 사용)
        python pipeline/post_queue.py --skip 2026-08-14   (그 배치를 게시하지 않고 지나감)
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "output"
STATE_PATH = BASE_DIR / "data" / "posted.json"
TMP_JSON = BASE_DIR / "data" / "_queue.json"
KST = timezone(timedelta(hours=9))
# AI 채널 배치만 다룬다 (머니·게임은 각자 폴더/파이프라인이 따로 있다)
PREFIX = "2026-"
SKIP_SUFFIX = ("-money", "-realestate", "-realestate2", "-taxreform", "-taxguide",
               "-jeonse", "-evergreen", "-roadmap", "-cheongyak")


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"posted": [], "skipped": []}


def save_state(state):
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def batch_data(folder):
    """배치 폴더에서 게시에 필요한 데이터를 되살린다."""
    saved = folder / "data.json"
    if saved.exists():
        return json.loads(saved.read_text(encoding="utf-8"))
    # 예전 배치에는 사본이 없다 — 폴더 이름과 caption.txt로 최소한만 되살린다
    caption = (folder / "caption.txt").read_text(encoding="utf-8") if (folder / "caption.txt").exists() else ""
    return {"date": folder.name, "caption": caption}


def pending(state):
    done = set(state["posted"]) | set(state["skipped"])
    rows = []
    for d in sorted(OUT_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith(PREFIX) or d.name in done:
            continue
        if any(d.name.endswith(s) for s in SKIP_SUFFIX):
            continue
        if not (d / "reel.mp4").exists() or not list(d.glob("card_*.jpg")):
            continue
        rows.append(d)
    return rows


def post_one(folder):
    data = batch_data(folder)
    TMP_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for script in ("post_reel.py", "post_instagram.py"):
        print(f"  → {script}")
        r = subprocess.run([sys.executable, str(BASE_DIR / "pipeline" / script), str(TMP_JSON)],
                           capture_output=True, timeout=900)
        out = r.stdout.decode("utf-8", "ignore").strip()
        if out:
            print("    " + out.replace("\n", "\n    "))
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", "ignore")[-400:]
            print(f"[실패] {script} — {err}")
            return False
    return True


def main():
    state = load_state()

    if "--skip" in sys.argv:
        name = sys.argv[sys.argv.index("--skip") + 1]
        state["skipped"].append(name)
        save_state(state)
        print(f"[건너뜀] {name} — 앞으로 대기 목록에 나오지 않습니다")
        return 0

    rows = pending(state)
    if not rows:
        print("[대기] 올릴 배치가 없습니다")
        return 0

    print(f"■ 대기 중인 배치 {len(rows)}편")
    for d in rows:
        first = ((d / "caption.txt").read_text(encoding="utf-8").split("\n")[0][:44]
                 if (d / "caption.txt").exists() else "")
        print(f"   · {d.name}  {first}")

    if "--list" in sys.argv:
        return 0

    targets = rows if "--all" in sys.argv else rows[:1]
    print()
    for d in targets:
        print(f"[게시] {d.name}")
        if not post_one(d):
            return 1
        state["posted"].append(d.name)
        save_state(state)
        print(f"[완료] {d.name} — {datetime.now(KST):%Y-%m-%d %H:%M}\n")

    left = len(pending(state))
    print(f"남은 대기: {left}편" + ("  (하루 한 편씩 빠집니다)" if left else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
