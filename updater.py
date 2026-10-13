"""GitHub 릴리스에서 새 exe를 받아 스스로 교체한다 (exe로 실행될 때만 동작).

흐름: 최신 릴리스 조회 -> 내 버전보다 높으면 내려받기 -> sha256 검증
      -> 실행 중인 exe를 .old 로 이름 변경 -> 새 파일을 원래 이름으로 저장 -> 새 프로세스 실행 후 종료
실패(인터넷 없음, 검증 실패 등)하면 아무것도 바꾸지 않고 현재 버전으로 계속 실행한다.
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.request

from version import ASSET_EXE, ASSET_SHA, REPO, __version__

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


def cleanup_old():
    """지난 업데이트 때 남은 .old 파일 정리."""
    if getattr(sys, "frozen", False):
        try:
            os.remove(sys.executable + ".old")
        except OSError:
            pass


def fetch_latest(timeout=6):
    req = urllib.request.Request(API, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _download(url, dest, progress=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress and total:
                progress(got, total)
    return h.hexdigest()


def check_and_update(log=print, progress=None, notify=None):
    """업데이트를 했으면 새 프로세스를 띄우고 True(= 지금 프로세스는 종료해야 함), 아니면 False."""
    if not getattr(sys, "frozen", False):
        return False  # .py 로 실행 중이면 업데이트하지 않음
    try:
        rel = fetch_latest()
        tag = rel.get("tag_name", "")
        if not is_newer(tag, __version__):
            log(f"최신 버전입니다 ({__version__})")
            return False
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        if ASSET_EXE not in assets or ASSET_SHA not in assets:
            log("새 릴리스에 필요한 파일이 없어 업데이트를 건너뜁니다")
            return False
        log(f"새 버전 {tag} 발견 (현재 {__version__}) - 내려받는 중")
        if notify:
            notify(f"새 버전 {tag}을(를) 내려받는 중입니다...")
        exe = sys.executable
        tmp = exe + ".update"
        want = _read_text(assets[ASSET_SHA]).split()[0].lower()
        got = _download(assets[ASSET_EXE], tmp, progress)
        if got != want:
            os.remove(tmp)
            log("내려받은 파일 검증 실패 - 업데이트를 건너뜁니다")
            return False
        old = exe + ".old"
        if os.path.exists(old):
            os.remove(old)
        os.rename(exe, old)       # 실행 중인 exe는 덮어쓸 수 없지만 이름 변경은 가능
        os.rename(tmp, exe)
        log("업데이트 완료 - 새 버전으로 다시 시작합니다")
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        # 이 프로세스가 끝난 뒤(약 2초) 새 exe 실행: 중복 실행 방지 뮤텍스를 피하기 위함
        subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & start "" "{exe}"', shell=True, env=env,
                         creationflags=0x00000008 | 0x08000000)  # DETACHED_PROCESS | CREATE_NO_WINDOW
        return True
    except Exception as e:
        log(f"업데이트 확인 실패(무시하고 계속): {repr(e)[:80]}")
        # 교체 도중 실패했다면 원래 이름으로 복구
        try:
            exe = sys.executable
            if not os.path.exists(exe) and os.path.exists(exe + ".old"):
                os.rename(exe + ".old", exe)
        except Exception:
            pass
        return False


def _read_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "replace")
