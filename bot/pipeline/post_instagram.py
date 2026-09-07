# -*- coding: utf-8 -*-
"""인스타그램 게시기 — 카드 이미지를 GitHub에 올려 공개 주소를 만든 뒤,
메타 공식 API로 인스타그램에 캐러셀(여러 장 묶음)로 게시한다.

.env에 열쇠(토큰)가 없으면 안전하게 건너뛰고 안내만 남긴다 (종료 코드 2).
"""
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"


def load_env():
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def http_json(url, data=None, headers=None, method=None):
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:500]
        raise RuntimeError(f"HTTP {e.code} — {detail}") from e


def gh_upload(env, local_path, repo_path):
    """GitHub 저장소에 이미지를 올리고 공개 다운로드 주소를 돌려준다."""
    url = f"https://api.github.com/repos/{env['GITHUB_REPO']}/contents/{repo_path}"
    headers = {
        "Authorization": f"Bearer {env['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "card-news-bot",
        "Content-Type": "application/json",
    }
    branch = env.get("GITHUB_BRANCH", "main")
    content_b64 = base64.b64encode(local_path.read_bytes()).decode()

    def get_sha():
        req = urllib.request.Request(f"{url}?ref={branch}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())["sha"]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    # 항상 현재 sha를 먼저 조회해 덮어쓴다. 충돌(409)/불일치(422) 시 sha 새로 받아 재시도.
    last = None
    for _ in range(4):
        payload = {"message": f"add {repo_path}", "content": content_b64, "branch": branch}
        sha = get_sha()
        if sha:
            payload["sha"] = sha
        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body, headers=headers, method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())["content"]["download_url"]
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} — {e.read().decode('utf-8', 'ignore')[:200]}"
            if e.code in (409, 422):
                continue  # sha가 어긋남 → 다시 받아 재시도
            if e.code >= 500:   # GitHub 쪽 일시 장애(502/504 등) → 잠시 쉬고 재시도
                time.sleep(10)
                continue
            raise RuntimeError(f"GitHub 업로드 실패 {last}") from e
    raise RuntimeError(f"GitHub 업로드 실패 (반복 충돌) — {last}")


def ig_wait_ready(graph, env, container_id):
    for _ in range(40):
        res = http_json(f"{graph}/{container_id}?fields=status_code&access_token={env['IG_ACCESS_TOKEN']}")
        status = res.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"인스타그램이 이미지를 처리하지 못함 (container {container_id})")
        time.sleep(3)
    raise RuntimeError("이미지 처리 대기 시간 초과")


def main():
    env = load_env()
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "data" / "cards.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))

    # 계정 선택: 데이터 파일에 "account"가 있으면 그 계정의 열쇠를 쓴다.
    # 예) "account": "re"  → .env의 IG_USER_ID_RE / IG_ACCESS_TOKEN_RE 사용.
    # 없으면 기본 계정(IG_USER_ID / IG_ACCESS_TOKEN, AI 뉴스 @ai_podo_news).
    suffix = f"_{data['account'].upper()}" if data.get("account") else ""
    uid_key, tok_key = f"IG_USER_ID{suffix}", f"IG_ACCESS_TOKEN{suffix}"
    missing = [k for k in (uid_key, tok_key, "GITHUB_TOKEN", "GITHUB_REPO") if not env.get(k)]
    if missing:
        print(f"[건너뜀] 아직 설정되지 않은 열쇠: {', '.join(missing)}")
        print("SETUP_GUIDE.md를 따라 .env 파일을 채우면 자동 게시가 켜집니다.")
        return 2
    env["IG_USER_ID"], env["IG_ACCESS_TOKEN"] = env[uid_key], env[tok_key]

    date = data["date"]
    out_dir = BASE_DIR / "output" / date
    jpgs = sorted(out_dir.glob("card_*.jpg"))
    if not (2 <= len(jpgs) <= 10):
        print(f"[실패] 카드 이미지가 {len(jpgs)}장 — 캐러셀은 2~10장이어야 합니다")
        return 1

    graph = env.get("GRAPH_BASE", "https://graph.instagram.com/v23.0").rstrip("/")

    # 1) 이미지를 GitHub에 올려 공개 주소 확보
    image_urls = []
    for jpg in jpgs:
        url = gh_upload(env, jpg, f"cards/{date}/{jpg.name}")
        image_urls.append(url)
        print(f"[OK] 업로드: {jpg.name}")

    # 2) 캐러셀 자식 컨테이너 생성
    children = []
    for url in image_urls:
        res = http_json(f"{graph}/{env['IG_USER_ID']}/media", {
            "image_url": url, "is_carousel_item": "true",
            "access_token": env["IG_ACCESS_TOKEN"],
        })
        children.append(res["id"])
    for cid in children:
        ig_wait_ready(graph, env, cid)
    print(f"[OK] 캐러셀 자식 {len(children)}개 준비 완료")

    # 3) 캐러셀 컨테이너 생성 → 게시
    res = http_json(f"{graph}/{env['IG_USER_ID']}/media", {
        "media_type": "CAROUSEL", "children": ",".join(children),
        "caption": data.get("caption", ""),
        "access_token": env["IG_ACCESS_TOKEN"],
    })
    carousel_id = res["id"]
    ig_wait_ready(graph, env, carousel_id)

    # 게시 직후 "아직 준비 안 됨"(코드 9007) 일시 오류가 날 수 있어 몇 번 재시도한다.
    media_id = None
    for _ in range(6):
        try:
            res = http_json(f"{graph}/{env['IG_USER_ID']}/media_publish", {
                "creation_id": carousel_id, "access_token": env["IG_ACCESS_TOKEN"],
            })
            media_id = res["id"]
            break
        except RuntimeError as e:
            if any(t in str(e) for t in ("not available", "9007", "준비")):
                time.sleep(15)
                continue
            raise
    if media_id is None:
        raise RuntimeError("미디어 게시 실패 — 처리 대기 시간 초과")

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
        "cards": len(jpgs),
        "posted_at": datetime.now().isoformat(timespec="seconds"),
    }
    (BASE_DIR / "data" / "post_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[성공] 인스타그램 게시 완료! {permalink or media_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
