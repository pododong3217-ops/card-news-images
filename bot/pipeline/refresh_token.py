# -*- coding: utf-8 -*-
"""인스타 토큰 자동 갱신 — 60일마다 만료되는 열쇠를 미리 새 것으로 바꿔 끼운다.

인스타 장기 토큰은 발급 후 60일이면 죽는다. 죽은 뒤에는 갱신이 안 되고
사람이 직접 로그인해 다시 받아야 하므로, 살아 있는 동안 주기적으로 갱신해야 한다.
(발급 후 24시간이 지나면 언제든 갱신 가능하고, 갱신하면 다시 60일이 된다)

사용법: python pipeline/refresh_token.py        (모든 .env의 토큰 갱신)
        python pipeline/refresh_token.py --check (갱신하지 않고 남은 기간만 확인)
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
API = "https://graph.instagram.com"
# 갱신 대상 (.env 경로, 토큰 키 이름)
TARGETS = [
    (BASE_DIR / ".env", "IG_ACCESS_TOKEN"),
    (BASE_DIR / ".env", "IG_ACCESS_TOKEN_MONEY"),
    (BASE_DIR.parent / "card-news-game" / ".env", "IG_ACCESS_TOKEN"),
]
LOG_PATH = BASE_DIR / "data" / "token_log.txt"


def read_value(env_path, key):
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def write_value(env_path, key, value):
    """주석과 다른 줄은 그대로 두고 해당 키의 값만 바꿔 쓴다."""
    text = env_path.read_text(encoding="utf-8")
    new = re.sub(rf"(?m)^{re.escape(key)}=.*$", f"{key}={value}", text, count=1)
    env_path.write_text(new, encoding="utf-8")


def log(msg):
    stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    print(msg)
    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {msg}\n")


def api(path, **params):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, json.loads(e.read().decode()).get("error", {}).get("message", "")


def main():
    check_only = "--check" in sys.argv
    failed = []

    for env_path, key in TARGETS:
        label = f"{env_path.parent.name}/{key}"
        if not env_path.exists():
            print(f"[건너뜀] {label} — .env 없음")
            continue
        token = read_value(env_path, key)
        if not token:
            print(f"[건너뜀] {label} — 키 없음")
            continue

        me, err = api("v23.0/me", fields="username", access_token=token)
        if err:
            log(f"[위험] {label} — 토큰이 죽었습니다. 사람이 직접 재발급해야 합니다: {err[:90]}")
            failed.append(label)
            continue

        who = me["username"]
        if check_only:
            print(f"[확인] {label} — @{who} 살아있음")
            continue

        out, err = api("refresh_access_token",
                       grant_type="ig_refresh_token", access_token=token)
        if err:
            log(f"[실패] {label} (@{who}) 갱신 실패: {err[:90]}")
            failed.append(label)
            continue

        new_token, secs = out["access_token"], out.get("expires_in", 0)
        write_value(env_path, key, new_token)
        until = (datetime.now(KST) + timedelta(seconds=secs)).strftime("%Y-%m-%d")
        log(f"[OK] {label} (@{who}) 갱신 완료 — {until}까지 ({secs // 86400}일)")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
