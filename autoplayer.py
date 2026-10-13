"""서울시 평생학습포털 인권교육 자동 수강

실행 -> 디버그 크롬 + 진행 상황 창이 뜬다.
크롬에서 로그인하고, 창에 공지를 붙여넣고 [시작]:
  1) 공지에서 URL만 뽑아 강좌 주소 확인
  2) 모든 강좌 수강신청(재수강신청)
  3) 강좌별로 미진행 차시를 끝까지 재생, 끝나면 다음 강의/다음 강좌로
  4) 모든 강좌가 끝나면 큰 팝업
진행 상황은 창에 계속 표시되고, 창은 직접 닫기 전까지 유지된다.

테스트용:  --notice 공지.txt  (입력 생략)   --retake  (이미 완료된 강좌도 다시 수강)
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request

import websocket

import updater
from version import __version__

PORT = 9222
HOST = "sll.seoul.go.kr"
START_URL = f"https://{HOST}"
APPDIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "LectureAutoNext")
PROFILE = os.path.join(APPDIR, "profile")
LOGFILE = os.path.join(APPDIR, "log.txt")
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
]
DETAIL = f"https://{HOST}/lms/requestCourse/doDetailInfo.do?main_se=lie&course_id={{cid}}&class_no=01&course_gubun=1&asp_id=ASP00001&simin_yn=N"
DONE_POLL_MIN = 12   # 마지막 차시 후 수료 반영 대기(분)
MAX_ATTEMPTS = 2     # 강좌당 시도 횟수

# 화면(진행 상황 창)과 작업 스레드가 공유하는 상태
ST = {"headline": "", "courses": [], "results": None, "lines": [], "popup_shown": False}


def log(*a):
    line = time.strftime("%H:%M:%S") + " " + " ".join(str(x) for x in a)
    ST["lines"].append(line)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        os.makedirs(APPDIR, exist_ok=True)
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


NOTICE_FILE = os.path.join(APPDIR, "last_notice.json")


def load_saved():
    try:
        with open(NOTICE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if re.search(r"https?://", d.get("text", "")):
            return d
    except Exception:
        pass
    return None


def save_notice(text):
    try:
        os.makedirs(APPDIR, exist_ok=True)
        with open(NOTICE_FILE, "w", encoding="utf-8") as f:
            json.dump({"text": text, "saved": time.strftime("%m/%d %H:%M")}, f, ensure_ascii=False)
    except Exception:
        pass


_mutex = None


def already_running_peek():
    """뮤텍스를 잡지 않고 이미 실행 중인지만 확인 (업데이트 도중 중복 방지용)."""
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenMutexW(0x00100000, False, "Local\\LectureAutoNext_SingleInstance")
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


def already_running():
    """같은 프로그램이 이미 떠 있으면 True (윈도우 이름있는 뮤텍스)."""
    global _mutex
    try:
        import ctypes
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\LectureAutoNext_SingleInstance")
        return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return False


def keep_awake():
    """수강 중 PC 절전/화면보호로 멈추지 않게 한다."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)
    except Exception:
        pass


# ───────────────────────── 크롬 / CDP ─────────────────────────
def targets():
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=3))


def chrome_alive():
    try:
        targets()
        return True
    except Exception:
        return False


def find_chrome():
    return next((p for p in CHROME_PATHS if os.path.exists(p)), None)


def ensure_chrome():
    if chrome_alive():
        log("이미 떠 있는 디버그 크롬에 연결합니다.")
        return
    exe = find_chrome()
    if not exe:
        raise RuntimeError("크롬을 찾을 수 없습니다. 크롬을 설치해 주세요.")
    log("디버그 크롬을 실행합니다.")
    os.makedirs(PROFILE, exist_ok=True)
    subprocess.Popen([exe, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}", START_URL])
    for _ in range(20):
        time.sleep(1)
        if chrome_alive():
            return
    raise RuntimeError("디버그 크롬 연결 실패")


class ChromeClosed(Exception):
    pass


class CDP:
    """한 탭에 계속 붙어 있는 세션. 알림창(alert/confirm)은 자동으로 확인 처리."""

    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, suppress_origin=True, timeout=30)
        self.n = 0
        self.send("Page.enable")

    def send(self, method, params=None):
        self.n += 1
        i = self.n
        self.ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get("method") == "Page.javascriptDialogOpening":
                log("알림창 자동 확인:", r["params"]["message"].replace("\n", " ")[:60])
                self.n += 1
                self.ws.send(json.dumps({"id": self.n, "method": "Page.handleJavaScriptDialog",
                                         "params": {"accept": True}}))
            if r.get("id") == i:
                return r

    def ev(self, expr, gesture=False):
        """JS 실행. 실패(페이지 이동 중 등)하면 None."""
        try:
            r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "userGesture": gesture})
            return r.get("result", {}).get("result", {}).get("value")
        except Exception:
            if not chrome_alive():
                raise ChromeClosed()
            return None

    def goto(self, url, timeout=40):
        self.send("Page.navigate", {"url": url})
        t0 = time.time()
        time.sleep(1.5)
        while time.time() - t0 < timeout:
            if self.ev("document.readyState") == "complete":
                break
            time.sleep(1)
        time.sleep(1.5)


def sll_login_state(ws_url):
    """이 탭이 sll 사이트이고 로그인되어 있으면 True."""
    try:
        ws = websocket.create_connection(ws_url, suppress_origin=True, timeout=5)
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": "location.host.includes('%s') && [...document.querySelectorAll('a,button')].some(e=>/로그아웃/.test(e.innerText)&&e.offsetParent)" % HOST,
            "returnByValue": True}}))
        v = json.loads(ws.recv())["result"]["result"].get("value")
        ws.close()
        return bool(v)
    except Exception:
        return False


def wait_login(home_url):
    ST["headline"] = "크롬에서 로그인해 주세요 (로그인되면 자동으로 시작합니다)"
    log("로그인을 기다리는 중... (크롬에서 로그인해 주세요)")
    while True:
        for t in targets():
            if t["type"] != "page":
                continue
            if sll_login_state(t["webSocketDebuggerUrl"]):
                log("★ 로그인 확인됨")
                return t["webSocketDebuggerUrl"]
            if HOST in t["url"] and "doViewOnlineLecture" in t["url"]:
                # 재생 화면에는 로그아웃 버튼이 없어 판별 불가 -> 상세 페이지로 이동
                try:
                    ws = websocket.create_connection(t["webSocketDebuggerUrl"], suppress_origin=True, timeout=5)
                    ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": home_url}}))
                    ws.recv()
                    ws.close()
                except Exception:
                    pass
        time.sleep(3)


# ───────────────────────── URL 해석 ─────────────────────────
def resolve_courses(text):
    urls = []
    for u in re.findall(r"https?://[^\s<>\"')]+", text):
        u = u.rstrip(".,;")
        if u not in urls:
            urls.append(u)
    courses = []
    for u in urls:
        final = u
        if HOST not in u:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                final = urllib.request.urlopen(req, timeout=15).geturl()
            except Exception as e:
                log("주소 확인 실패:", u, repr(e)[:60])
                continue
        q = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
        cid = (q.get("course_id") or [None])[0]
        if HOST not in final or not cid:
            log("강좌 주소가 아니라 건너뜀:", u, "->", final[:70])
            continue
        if cid not in [c["cid"] for c in courses]:
            courses.append({"cid": cid, "url": DETAIL.format(cid=cid), "src": u, "name": cid,
                            "status": "대기", "detail": "", "enrolled": False})
    return courses


# ───────────────────────── 강좌 상세 페이지 ─────────────────────────
STATE_JS = """(()=>{const vis=e=>!!e.offsetParent;
const reg=[...document.querySelectorAll('.btn-course-regist,.re_apply_y')].filter(vis).map(e=>e.innerText.replace(/\\s+/g,''))[0]||null;
const items=[...document.querySelectorAll('.info-bar-list')].map(e=>e.innerText.replace(/\\s+/g,' ').trim());
const m=(document.querySelector('#apply-modal-box')||{}).textContent||'';
const nm=(m.match(/(\\S[^\\n]*?)\\s*강의를\\s*수강신청/)||[])[1]||null;
return JSON.stringify({reg,items,name:nm,ready:document.readyState})})()"""


def read_state(cdp):
    for _ in range(5):
        v = cdp.ev(STATE_JS)
        if v:
            s = json.loads(v)
            if s["items"] or s["reg"]:
                return s
        time.sleep(2)
    return {"reg": None, "items": [], "name": None}


def is_done(item):
    return "완료" in item and "미" not in item.split("완료")[0][-2:]


def all_done(state):
    return bool(state["items"]) and all(is_done(i) for i in state["items"])


def open_course(cdp, c):
    cdp.goto(c["url"])
    s = read_state(cdp)
    if s.get("name"):
        c["name"] = s["name"]
    return s


# ───────────────────────── 1단계: 수강신청 ─────────────────────────
def enroll(cdp, c, retake):
    c["status"] = "수강신청 중"
    s = open_course(cdp, c)
    if all_done(s) and not retake:
        log(f"[{c['name']}] 이미 전부 완료 -> 신청 생략")
        c["enrolled"] = True
        c["status"] = "이미 완료"
        return
    if s["reg"] == "신청완료":
        log(f"[{c['name']}] 이미 신청완료")
        c["enrolled"] = True
        c["status"] = "신청완료"
        return
    if s["reg"] not in ("수강신청", "재수강신청"):
        log(f"[{c['name']}] 신청 버튼을 찾지 못함: {s['reg']}")
        c["status"] = "신청 확인 필요"
        return
    log(f"[{c['name']}] '{s['reg']}' 진행")
    cdp.ev("[...document.querySelectorAll('.btn-course-regist')].find(e=>e.offsetParent).click()")
    time.sleep(2)
    cdp.ev("document.querySelector('#course-add-btn').click()")
    for _ in range(20):
        time.sleep(2)
        s = read_state(cdp)
        if s["reg"] == "신청완료":
            log(f"[{c['name']}] 신청완료 확인")
            c["enrolled"] = True
            c["status"] = "신청완료"
            return
    log(f"[{c['name']}] 신청 결과 확인 실패 - 이후 단계에서 다시 확인")
    c["status"] = "신청 확인 필요"


# ───────────────────────── 2단계: 학습 ─────────────────────────
WATCH_JS = """(()=>{try{
const units=[...document.querySelectorAll('.unit-el')];
const idx=units.findIndex(u=>u.classList.contains('is-current'));
const v=document.querySelector('iframe').contentDocument.querySelector('video');
if(!v||!v.duration)return JSON.stringify({s:'novideo'});
const last=idx===units.length-1;
if(v.ended||v.currentTime>=v.duration-1.5){fncComplete();return JSON.stringify({s:'complete',idx,n:units.length,last});}
const wasPaused=v.paused;if(wasPaused)v.play();
return JSON.stringify({s:'play',idx,n:units.length,t:v.currentTime,d:v.duration,paused:wasPaused,rs:v.readyState,ns:v.networkState,err:v.error?v.error.message:null});
}catch(e){return JSON.stringify({s:'err',e:String(e)})}})()"""


def mmss(x):
    x = int(x)
    return f"{x//60}:{x%60:02d}"


def watch(cdp, c):
    """강의 재생 페이지에서 끝까지 재생. 마지막 차시까지 끝나면 'last', 페이지를 벗어나면 'left'."""
    novideo = 0
    tick = 0
    last_t, last_move, nudged, reloads = -1.0, time.time(), 0.0, 0
    while True:
        href = cdp.ev("location.href") or ""
        if "doViewOnlineLecture" not in href:
            return "left"
        raw = cdp.ev(WATCH_JS, gesture=True)
        if not raw:
            time.sleep(5)
            continue
        v = json.loads(raw)
        if v["s"] == "play":
            novideo = 0
            c["detail"] = f"{v['idx']+1}/{v['n']}차시  {mmss(v['t'])} / {mmss(v['d'])}"
            tick += 1
            if tick % 4 == 1:
                log(f"  [{c['name']}] {c['detail']}")
            # 멈춤 감시: 재생 시간이 안 흐르면 단계별로 복구
            now = time.time()
            if abs(v["t"] - last_t) > 0.5:
                last_t, last_move, nudged = v["t"], now, 0.0
            stalled = now - last_move
            if stalled >= 60 and now - nudged >= 60:
                nudged = now
                log(f"  ⚠ 재생 멈춤 {int(stalled)}초: 일시정지={v['paused']} 준비상태={v['rs']} 네트워크={v['ns']} 오류={v['err']}")
                cdp.ev("(()=>{const v=document.querySelector('iframe').contentDocument.querySelector('video');"
                       "v.currentTime=Math.min(v.currentTime+0.5,v.duration-2);v.play();})()", gesture=True)
            if stalled >= 180:
                reloads += 1
                if reloads > 3:
                    log("  ⚠ 새로고침 3번에도 재생이 안 되어 이 시도를 포기합니다")
                    return "stalled"
                log(f"  ⚠ 3분 이상 멈춰 있어 페이지를 새로고침합니다 ({reloads}/3)")
                c["detail"] = f"재생 멈춤 → 새로고침 {reloads}/3"
                cdp.send("Page.reload")
                time.sleep(8)
                last_t, last_move, nudged = -1.0, time.time(), 0.0
                continue
        elif v["s"] == "complete":
            c["detail"] = f"{v['idx']+1}/{v['n']}차시 끝 - 다음으로 이동 중"
            log(f"  [{c['name']}] {v['idx']+1}/{v['n']}차시 끝 -> 다음 강의 버튼")
            time.sleep(20)
            if v["last"]:
                return "last"
            continue
        elif v["s"] == "novideo":
            c["detail"] = "영상 불러오는 중"
            novideo += 1
            if novideo > 24:
                log("  영상을 찾지 못해 중단")
                return "stuck"
        else:
            log("  ", v)
        time.sleep(15)


def start_first_todo(cdp):
    ok = cdp.ev("""(()=>{const items=[...document.querySelectorAll('.info-bar-list')];
const t=items.find(e=>!(/완료/.test(e.innerText)&&!/미/.test(e.innerText.split('완료')[0].slice(-2))));
if(!t)return false;const b=t.querySelector('button');if(!b)return false;b.click();return true})()""", gesture=True)
    if not ok:
        return False
    for _ in range(30):
        time.sleep(1)
        if "doViewOnlineLecture" in (cdp.ev("location.href") or ""):
            time.sleep(3)
            return True
    return False


def wait_done(cdp, c):
    log(f"[{c['name']}] 수료 반영 확인 중 (최대 {DONE_POLL_MIN}분)")
    t0 = time.time()
    while time.time() - t0 < DONE_POLL_MIN * 60:
        c["detail"] = f"수료 반영 확인 중 ({int((time.time()-t0)//60)}분 경과, 최대 {DONE_POLL_MIN}분)"
        s = open_course(cdp, c)
        if all_done(s):
            return True
        log(f"  아직 반영 전: {s['items']}")
        for _ in range(60):
            time.sleep(1)
    return False


def study(cdp, c, retake):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        c["status"] = "학습 중"
        c["detail"] = "준비 중"
        s = open_course(cdp, c)
        if all_done(s):
            return "완료"
        if s["reg"] in ("수강신청", "재수강신청"):
            enroll(cdp, c, retake)
            c["status"] = "학습 중"
            s = open_course(cdp, c)
        log(f"[{c['name']}] 학습 시작 (시도 {attempt}) {s['items']}")
        if not start_first_todo(cdp):
            log(f"[{c['name']}] 학습하기를 누르지 못함")
            continue
        r = watch(cdp, c)
        log(f"[{c['name']}] 재생 종료: {r}")
        if r in ("stalled", "stuck"):
            log(f"[{c['name']}] 재생이 진행되지 않아 처음부터 다시 시도합니다")
            continue
        if wait_done(cdp, c):
            return "완료"
    return "확인 필요"


def run_all(notice, retake, chrome_ready):
    try:
        keep_awake()
        chrome_ready.wait()
        courses = resolve_courses(notice)
        if not courses:
            ST["headline"] = "공지에서 강좌 주소를 찾지 못했습니다. 창을 닫고 다시 실행해 주세요."
            log(ST["headline"])
            return
        ST["courses"] = courses
        log(f"강좌 {len(courses)}개 확인:")
        for i, c in enumerate(courses, 1):
            log(f"  {i}. {c['src']} -> {c['cid']}")

        cdp = CDP(wait_login(courses[0]["url"]))

        ST["headline"] = "1단계: 수강신청"
        log("──── 1단계: 수강신청 ────")
        for c in courses:
            enroll(cdp, c, retake)

        ST["headline"] = "2단계: 학습"
        log("──── 2단계: 학습 ────")
        results = []
        for c in courses:
            res = study(cdp, c, retake)
            c["status"] = res
            c["detail"] = ""
            log(f"[{c['name']}] 결과: {res}")
            results.append((c["name"], res))

        ST["headline"] = "모든 강좌 처리 끝"
        log("──── 전체 종료 ────")
        for n, v in results:
            log(f"  {n}: {v}")
        ST["results"] = results
    except Exception as e:
        if isinstance(e, ChromeClosed) or not chrome_alive():
            ST["headline"] = "크롬이 닫혀서 중단되었습니다. 프로그램을 다시 실행하고 '이어서 하기'를 선택해 주세요."
            log(ST["headline"])
        else:
            log(traceback.format_exc())
            ST["headline"] = "오류로 중단됨: " + repr(e)[:100]


# ───────────────────────── 화면 ─────────────────────────
def summary_text():
    cs = ST["courses"]
    if not cs:
        return ST["headline"]
    n = len(cs)
    enrolled = sum(1 for c in cs if c["enrolled"])
    done = sum(1 for c in cs if c["status"] == "완료" or c["status"] == "이미 완료")
    cur = next((i for i, c in enumerate(cs) if c["status"] == "학습 중"), None)
    head = f"총 {n}개 강좌  ·  수강신청 {enrolled}/{n} 완료  ·  수강 완료 {done}/{n}"
    if cur is not None:
        c = cs[cur]
        head += f"\n▶ {cur+1}번째 강좌 진행 중: {c['name']}\n    {c['detail']}"
    else:
        head += "\n" + ST["headline"]
    return head


def show_final_popup(root):
    import tkinter as tk
    results = ST["results"]
    ok = all(v in ("완료",) or v == "이미 완료" for _, v in results)
    color = "#1a7f37" if ok else "#b45309"
    p = tk.Toplevel(root)
    p.title("강의 완료")
    p.attributes("-topmost", True)
    w, h = p.winfo_screenwidth(), p.winfo_screenheight()
    p.geometry(f"{int(w*0.6)}x{int(h*0.55)}+{int(w*0.2)}+{int(h*0.22)}")
    p.configure(bg=color)
    head = "모든 강좌 수강이 끝났습니다!" if ok else "수강이 끝났지만 확인이 필요한 강좌가 있습니다"
    body = "\n".join(f"{'✔' if v == '완료' else '⚠'} {n} - {v}" for n, v in results)
    tk.Label(p, text=head, font=("맑은 고딕", 30, "bold"), fg="white", bg=color).pack(pady=(40, 10))
    tk.Label(p, text=body, font=("맑은 고딕", 18), fg="white", bg=color, justify="left").pack(expand=True)
    tk.Button(p, text="확인", font=("맑은 고딕", 22), command=p.destroy).pack(pady=24)


def build_ui(auto_notice, auto_retake):
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(f"인권교육 자동 수강  v{__version__}")
    root.geometry("820x700")
    chrome_ready = threading.Event()

    def boot():
        try:
            ensure_chrome()
        except Exception as e:
            log("크롬 실행 오류:", e)
            ST["headline"] = str(e)
        chrome_ready.set()

    threading.Thread(target=boot, daemon=True).start()

    # --- 입력 화면 ---
    inp = tk.Frame(root)
    help_text = (
        "사용법\n"
        "  1. 방금 열린 크롬 창에서 서울시 평생학습포털에 로그인하세요.\n"
        "  2. URL이 들어 있는 공지사항 글을 대충 긁어서 아래에 붙여넣고 [시작]을 누르세요.\n"
        "     (공지에서 URL만 자동으로 찾아 수강신청 → 수강을 진행합니다.)\n"
        "  3. 그 뒤로는 손댈 필요 없습니다. 모든 강좌가 끝나면 '완료' 창이 뜹니다.\n"
        "주의: 크롬 창과 이 창을 닫지 마세요. 컴퓨터를 켜 둔 채로 두면 됩니다(절전은 자동으로 막습니다).\n"
        "      중간에 껐다면 다음에 '이어서 하기'를 고르면 완료한 건 건너뛰고 이어서 합니다.")
    tk.Label(inp, text=help_text, font=("맑은 고딕", 10), justify="left", anchor="w",
             bg="#f2f6ff", relief="groove", padx=10, pady=8).pack(fill="x", padx=10, pady=(10, 6))

    saved = load_saved()
    mode = tk.StringVar(value="resume" if saved else "new")
    if saved:
        n_saved = len(set(re.findall(r"https?://[^\s<>\"')]+", saved["text"])))
        tk.Radiobutton(inp, variable=mode, value="resume", font=("맑은 고딕", 11, "bold"),
                       text=f"이어서 하기  (저장된 공지 사용 · URL {n_saved}개 · 저장 {saved.get('saved', '')})",
                       command=lambda: set_mode()).pack(anchor="w", padx=14)
        tk.Radiobutton(inp, variable=mode, value="new", font=("맑은 고딕", 11, "bold"),
                       text="새 공지 붙여넣기", command=lambda: set_mode()).pack(anchor="w", padx=14)
    box = tk.Text(inp, font=("맑은 고딕", 10), height=12)
    box.pack(fill="both", expand=True, padx=10, pady=4)
    var = tk.IntVar(value=0)
    tk.Checkbutton(inp, text="이미 완료된 강좌도 다시 수강 (테스트용)", variable=var,
                   font=("맑은 고딕", 10)).pack(pady=2)

    def set_mode():
        box.config(state="disabled" if mode.get() == "resume" else "normal",
                   bg="#eeeeee" if mode.get() == "resume" else "white")

    if saved:
        set_mode()

    # --- 진행 화면 ---
    run = tk.Frame(root)
    big = tk.Label(run, text="", font=("맑은 고딕", 15, "bold"), justify="left", anchor="w", wraplength=780)
    big.pack(fill="x", padx=14, pady=(12, 6))
    tree = ttk.Treeview(run, columns=("name", "status", "detail"), show="headings", height=4)
    for k, t, w in (("name", "강좌", 330), ("status", "상태", 110), ("detail", "진행", 320)):
        tree.heading(k, text=t)
        tree.column(k, width=w)
    tree.pack(fill="x", padx=14)
    logbox = tk.Text(run, font=("Consolas", 9), height=14, state="disabled", bg="#f6f6f6")
    logbox.pack(fill="both", expand=True, padx=14, pady=10)
    shown = {"n": 0}

    def refresh():
        big.config(text=summary_text())
        tree.delete(*tree.get_children())
        for i, c in enumerate(ST["courses"], 1):
            tree.insert("", "end", values=(f"{i}. {c['name']}", c["status"], c["detail"]))
        if shown["n"] < len(ST["lines"]):
            logbox.config(state="normal")
            for line in ST["lines"][shown["n"]:]:
                logbox.insert("end", line + "\n")
            shown["n"] = len(ST["lines"])
            logbox.see("end")
            logbox.config(state="disabled")
        if ST["results"] and not ST["popup_shown"]:
            ST["popup_shown"] = True
            show_final_popup(root)
        root.after(1000, refresh)

    def start(notice, retake):
        inp.pack_forget()
        run.pack(fill="both", expand=True)
        ST["headline"] = "시작하는 중..."
        threading.Thread(target=run_all, args=(notice, retake, chrome_ready), daemon=True).start()
        refresh()

    def on_click():
        if saved and mode.get() == "resume":
            start(saved["text"], bool(var.get()))
            return
        text = box.get("1.0", "end")
        if not re.search(r"https?://", text):
            from tkinter import messagebox
            messagebox.showwarning("안내", "붙여넣은 내용에 URL이 없습니다.")
            return
        save_notice(text)
        start(text, bool(var.get()))

    tk.Button(inp, text="시작", font=("맑은 고딕", 16, "bold"), command=on_click).pack(pady=8)

    if auto_notice is not None:
        start(auto_notice, auto_retake)
    else:
        inp.pack(fill="both", expand=True)

    def on_close():
        root.destroy()
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def main():
    args = sys.argv[1:]
    retake = "--retake" in args
    notice = None
    if "--notice" in args:
        notice = open(args[args.index("--notice") + 1], encoding="utf-8").read()
    if "--no-update" not in args and not already_running_peek():
        if run_update():
            return  # 새 버전이 설치되어 다시 시작됨
    if already_running():
        warn("이미 실행 중", "이 프로그램이 이미 실행 중입니다.\n열려 있는 '인권교육 자동 수강' 창을 확인해 주세요.\n(두 개를 동시에 켜면 서로 방해합니다)")
        return
    if not chrome_alive() and not find_chrome():
        warn("크롬이 필요합니다",
             "이 PC에 구글 크롬이 설치되어 있지 않습니다.\n\n"
             "확인을 누르면 크롬 다운로드 페이지가 열립니다.\n"
             "크롬을 설치한 뒤 이 프로그램을 다시 실행해 주세요.")
        try:
            import webbrowser
            webbrowser.open("https://www.google.com/chrome/")
        except Exception:
            pass
        return
    log(f"인권교육 자동 수강 시작 (v{__version__})")
    build_ui(notice, retake)


def warn(title, msg):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        r.attributes("-topmost", True)
        messagebox.showwarning(title, msg, parent=r)
        r.destroy()
    except Exception:
        pass


def run_update():
    """새 버전이 있으면 안내창을 띄운다. '예'면 브라우저로 내려받게 하고 True(= 이 프로그램은 종료)."""
    info = updater.check_update(log=log)
    if not info:
        return False
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        r.attributes("-topmost", True)
        ok = messagebox.askyesno(
            "새 버전이 있습니다",
            f"새 버전 {info['tag']}이(가) 있습니다. (현재 v{__version__})\n\n"
            "[예]  브라우저로 새 파일을 내려받고, 이 프로그램은 종료합니다.\n"
            "        (내려받은 파일을 실행하세요. 이전 파일은 지워도 됩니다)\n\n"
            "[아니오]  이번에는 현재 버전으로 계속합니다.",
            parent=r)
        r.destroy()
    except Exception:
        return False
    if ok:
        try:
            import webbrowser
            webbrowser.open(info["url"])
        except Exception:
            pass
        return True
    return False


if __name__ == "__main__":
    main()
