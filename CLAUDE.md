# 직원교육(온라인)자동넘기기 (staff-training-autoplayer)

GitHub: lovslave-netizen/staff-training-autoplayer (**공개**, 2026-10-16 GitHub 에서 확인) — 계정 lovslave-netizen (개인)
서울시 평생학습포털(sll.seoul.go.kr)의 직원 인권교육을 자동으로 수강신청하고 끝까지 재생하는 도구. 상세 사용법은 `README.md`.

## 이어서 작업하는 법 (PC 가 바뀌어도, 기준은 이 GitHub 저장소)
- 시작: `python -I E:\파이썬\JYDashBoard\tools\jyup.py start` (다른 PC 는 `W:\JYDashBoard\tools\jyup.py`). 같음 / GitHub 가 더 최신(자동으로 받음) / 이 PC 가 더 최신 / 갈라짐(멈추고 사용자에게 묻기) 중 하나로 알려 준다.
- 그다음 이 파일과 `README.md` 를 읽고 이어서 한다.
- 올리기: `jyup.py up "한 일 요약"`. **이 저장소는 공개라서 올리기 전에 사용자에게 먼저 묻는다.** 작업 단위가 끝날 때, 끝낼 낌새가 보일 때 올리자고 제안한다.
- 비밀번호·개인키·토큰은 절대 커밋하지 않는다. 크롬 프로필/로그 폴더(`%LOCALAPPDATA%\LectureAutoNext`)도 저장소에 넣지 않는다.

## 실행 방법 (README.md · release.yml 을 읽어 확인한 것)
- 배포판: GitHub Releases 의 `staff-training-autoplayer.exe` 를 내려받아 실행 (설치 없음, 이 PC 에 **구글 크롬** 필요).
- 소스로 실행: `pip install -r requirements.txt` 후 `python autoplayer.py` (업데이트 확인 끄기: `--no-update`).
- 이 폴더에는 옛 이름의 복사본 `직원교육(온라인)자동넘기기.exe` / `.zip` 이 있다 (저장소에는 올라가지 않음, 옛 빌드일 수 있음).
- 로그: `%LOCALAPPDATA%\LectureAutoNext\log.txt`. 테스트: `python test_updater.py`.

## 배포 방법 (README.md · `.github/workflows/release.yml` 을 읽어 확인한 것)
- 배포는 업로드와 **별개**다. 사용자가 분명히 시킬 때만 하고, 하기 전에 **버전 번호와 올라갈 내용을 보여 주고 확인**받는다. 저장소가 공개이고 사용자의 프로그램이 이 릴리스로 업데이트 안내를 받기 때문이다.
1. `version.py` 의 `__version__` 을 올리고 커밋한다. (현재 1.0.2, 최신 릴리스 v1.0.2 — 2026-10-16 확인)
2. 같은 번호의 태그를 만들어 push 한다: `git tag vX.Y.Z` → `git push origin main` → `git push origin vX.Y.Z`.
3. GitHub Actions(windows-latest)가 태그와 `version.py` 가 같은지 확인하고 `python test_updater.py` 를 돌린 뒤, PyInstaller 로 exe 를 만들고 체크섬(.sha256)과 함께 Releases 에 올린다. **이 PC 에 빌드 도구가 없어도 push 만 하면 된다.**
4. 사용자의 프로그램은 다음 실행 때 새 버전을 확인해 안내창을 띄운다.

## 주의 (겪은 것)
- exe 가 자기 파일을 교체하고 재실행하는 자동 업데이트는 안랩 V3 행동 탐지에 걸려 쓰지 않는다 (새 버전이 있으면 브라우저로 내려받게 안내).
- push 때 출력을 숨기면(`| Out-Null`) 거절(non-fast-forward)을 못 본다. 푸시 결과는 꼭 확인한다.
- 이 저장소는 로컬 폴더가 그대로 git 저장소다. 동료에게 줄 때는 exe 만 전달한다 (SmartScreen 경고가 뜰 수 있음).
