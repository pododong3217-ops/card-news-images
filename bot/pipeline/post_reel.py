# -*- coding: utf-8 -*-
"""릴스 게시기 — 합성된 릴스 영상을 GitHub에 올려 공개 주소를 만든 뒤 인스타그램 릴스로 게시한다.

토큰이 없거나 영상이 없으면 안전하게 건너뛴다 (종료 코드 2).
"""
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from post_instagram import gh_upload, http_json, load_env  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent


def wait_video_ready(graph, env, container_id, attempts=60, interval=10):
    """영상은 처리 시간이 길어 최대 10분까지 기다린다."""
    for _ in range(attempts):
        res = http_json(f"{graph}/{container_id}?fields=status_code&access_token={env['IG_ACCESS_TOKEN']}")
        status = res.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"인스타그램이 영상을 처리하지 못함 (container {container_id})")
        time.sleep(interval)
    raise RuntimeError("영상 처리 대기 시간 초과")


def main():
    env = load_env()
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "data" / "cards.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))

    # 계정 선택 (post_instagram과 동일 규칙): data["account"]에 따라 .env 열쇠를 고른다.
    suffix = f"_{data['account'].upper()}" if data.get("account") else ""
    uid_key, tok_key = f"IG_USER_ID{suffix}", f"IG_ACCESS_TOKEN{suffix}"
    missing = [k for k in (uid_key, tok_key, "GITHUB_TOKEN", "GITHUB_REPO") if not env.get(k)]
    if missing:
        print(f"[건너뜀] 아직 설정되지 않은 열쇠: {', '.join(missing)}")
        return 2
    env["IG_USER_ID"], env["IG_ACCESS_TOKEN"] = env[uid_key], env[tok_key]

    date = data["date"]
    reel_path = BASE_DIR / "output" / date / "reel.mp4"
    if not reel_path.exists():
        print(f"[건너뜀] 릴스 영상이 없습니다 — render_reel.py를 먼저 실행하세요")
        return 2

    graph = env.get("GRAPH_BASE", "https://graph.instagram.com/v23.0").rstrip("/")

    video_url = gh_upload(env, reel_path, f"cards/{date}/reel.mp4")
    print(f"[OK] 영상 업로드: {video_url}")

    caption = data.get("caption", "")
    meta_path = BASE_DIR / "data" / "reel_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("date") == date and meta.get("credit"):
            caption += "\n\n" + meta["credit"]

    res = http_json(f"{graph}/{env['IG_USER_ID']}/media", {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "false",  # 릴스는 릴스 탭에만 — 피드 격자는 카드뉴스로 깔끔하게
        "access_token": env["IG_ACCESS_TOKEN"],
    })
    container_id = res["id"]
    print("[OK] 릴스 컨테이너 생성 — 인스타그램이 영상을 처리하는 중 (수 분 걸릴 수 있음)")
    wait_video_ready(graph, env, container_id)

    # 게시 직후 "아직 준비 안 됨"(코드 9007) 일시 오류가 날 수 있어 몇 번 재시도한다.
    media_id = None
    for _ in range(6):
        try:
            res = http_json(f"{graph}/{env['IG_USER_ID']}/media_publish", {
                "creation_id": container_id, "access_token": env["IG_ACCESS_TOKEN"],
            })
            media_id = res["id"]
            break
        except RuntimeError as e:
            if any(t in str(e) for t in ("not available", "9007", "준비")):
                time.sleep(15)
                continue
            raise
    if media_id is None:
        raise RuntimeError("영상 게시 실패 — 처리 대기 시간 초과")

    permalink = ""
    try:
        res = http_json(f"{graph}/{media_id}?fields=permalink&access_token={env['IG_ACCESS_TOKEN']}")
        permalink = res.get("permalink", "")
    except RuntimeError:
        pass

    result = {
        "date": date,
        "media_id": media_id,
        "permalink": permalink,
        "posted_at": datetime.now().isoformat(timespec="seconds"),
    }
    (BASE_DIR / "data" / "reel_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[성공] 릴스 게시 완료! {permalink or media_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
