"""GitHub 릴리스에 새 버전이 있는지 확인만 한다 (파일을 직접 바꾸지 않는다).

프로그램이 자기 exe를 교체하고 다시 실행하는 방식은 백신(안랩 V3 행동 기반 탐지,
DefenseEvasion/MDP.Event.M1423)이 차단하므로 쓰지 않는다.
새 버전이 있으면 호출한 쪽이 안내창을 띄우고, 브라우저로 내려받게 한다.
인터넷이 안 되거나 조회에 실패해도 현재 버전으로 그냥 계속 실행한다.
"""
import json
import os
import urllib.request

from version import ASSET_EXE, REPO, __version__

API = f"https://api.github.com/repos/{REPO}/releases/latest"
UA = {"User-Agent": "staff-training-autoplayer-updater", "Accept": "application/vnd.github+json"}


def parse_version(s):
    """'v1.2.3' -> (1, 2, 3). 해석 못 하면 None."""
    try:
        return tuple(int(x) for x in s.strip().lstrip("vV").split("."))
    except Exception:
        return None


def is_newer(remote, local):
    r, l = parse_version(remote), parse_version(local)
    return r is not None and l is not None and r > l


def check_update(log=print, timeout=6):
    """새 버전이 있으면 {'tag','url','page'}, 없거나 실패하면 None."""
    current = os.environ.get("AUTOPLAYER_FAKE_VERSION") or __version__  # 테스트용 덮어쓰기
    try:
        req = urllib.request.Request(API, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rel = json.load(r)
        tag = rel.get("tag_name", "")
        if not is_newer(tag, current):
            log(f"최신 버전입니다 ({current})")
            return None
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        url = assets.get(ASSET_EXE)
        if not url:
            log("새 릴리스에 exe 파일이 없어 안내하지 않습니다")
            return None
        log(f"새 버전 {tag} 발견 (현재 {current})")
        return {"tag": tag, "url": url, "page": rel.get("html_url", "")}
    except Exception as e:
        log(f"업데이트 확인 실패(무시하고 계속): {repr(e)[:80]}")
        return None
