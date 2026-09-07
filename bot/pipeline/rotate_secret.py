# -*- coding: utf-8 -*-
"""갱신된 인스타 토큰을 깃허브 저장소 시크릿에 다시 저장한다.

토큰은 60일이면 죽는다. 워크플로가 매일 갱신해도 '저장된 시크릿'을 바꾸지 않으면
원래 만료일에 그대로 죽는다. 그래서 갱신 결과를 시크릿에 되돌려 써야 영구히 살아 있다.

GH_SECRETS_PAT(시크릿 쓰기 권한 있는 토큰)이 없으면 조용히 건너뛴다.
"""
import base64, json, os, sys, urllib.error, urllib.request

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")

PAT = os.environ.get("GH_SECRETS_PAT", "").strip()
REPO = os.environ.get("GITHUB_REPOSITORY", "").strip()
NAME = "IG_ACCESS_TOKEN"


def api(path, method="GET", body=None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": "Bearer " + PAT,
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r) if r.status not in (201, 204) else {}


def main():
    if not PAT:
        print("[건너뜀] GH_SECRETS_PAT 없음 — 시크릿은 수동으로 갱신해야 합니다")
        return 0
    token = ""
    for line in open(".env", encoding="utf-8").read().splitlines():
        if line.startswith(NAME + "="):
            token = line.split("=", 1)[1].strip()
    if not token:
        print("[실패] .env에서 토큰을 찾지 못했습니다")
        return 1
    try:
        from nacl import encoding, public
    except ImportError:
        print("[실패] pynacl이 필요합니다")
        return 1
    try:
        key = api("actions/secrets/public-key")
        sealed = public.SealedBox(
            public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
        ).encrypt(token.encode())
        api(f"actions/secrets/{NAME}", "PUT",
            {"encrypted_value": base64.b64encode(sealed).decode(),
             "key_id": key["key_id"]})
        print(f"[OK] 시크릿 {NAME} 갱신 완료 — 앞으로 60일 더 유효합니다")
    except urllib.error.HTTPError as e:
        print(f"[실패] 시크릿 갱신 — HTTP {e.code} {e.read().decode()[:150]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
