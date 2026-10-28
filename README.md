# ai4video

여러 영상 프로젝트의 대본, 장면 클립, 음성, 미리보기와 제작 코드를 관리합니다.
프로젝트마다 `videos/` 아래의 독립된 폴더를 사용하고, Python 3.13 가상환경은 루트의 `uv` 프로젝트로 함께 관리합니다.
`videos/`는 대본·제작 코드·메모·영상 산출물 전체를 포함해 `.gitignore`로 제외합니다.
Git에는 공통 CLI, 리뷰어 서버·웹 UI, 테스트, 문서와 의존성 설정을 올립니다.

```bash
cd /home/jake/ai4video
uv sync
uv run ai4video.py list
uv run ai4video.py clips periodic-table

# 새 영상 프로젝트 만들기
uv run ai4video.py init atomic-bonds --title '원자는 왜 결합할까?'

# 기존 폴더를 프로젝트로 등록하기
uv run ai4video.py register my-video --title '내 영상'
```

`init`은 대본 초안과 자료·음성·클립·미리보기 폴더를 만듭니다.
`register`는 `videos/` 아래 기존 폴더에 설정만 추가합니다. 이미 등록된 설정은 덮어쓰지 않습니다.

## 구조

```text
ai4video/
├── ai4video.py                 # 공통 관리 CLI
├── review.py                   # 공통 리뷰어 서버
├── review-web/                 # 공통 리뷰어 웹 UI
├── tests/                      # 영상 파일 없이 실행하는 공통 테스트
├── README.md
├── pyproject.toml             # 공통 Python 의존성
├── .python-version            # Python 3.13
├── .venv/                     # 공통 가상환경 (Git 제외)
└── videos/                     # 영상 프로젝트 모음 (Git 제외)
    └── periodic-table/         # 다른 프로젝트도 같은 층에 추가
        ├── project.json        # 제목, 제작 상태, 제작 스크립트·산출물 경로
        ├── README.md           # 개별 영상 설명과 재현 방법
        ├── lesson.py           # 기존 주기율표 프로젝트의 대본 원본
        ├── script.ko.md        # 대본
        ├── build.py            # 프로젝트별 제작 스크립트
        ├── timeline.json       # 장면별 번호·제목·길이
        ├── data/
        ├── audio/
        ├── clips/              # 장면별 영상
        └── preview/
```

`project.json`의 `status`는 제작자가 `draft`, `producing`, `review`, `done` 등으로 기록합니다.
`list`는 기록된 상태와 MP4 클립 수를 보여줍니다. `clips`는 타임라인이 있으면
장면별 길이와 파일 존재 여부를, 없으면 클립 파일 목록을 보여줍니다.
`ready`는 파일이 있다는 뜻이며 영상 품질 검증 결과는 아닙니다.

## 브라우저에서 컷 검토와 수정 메모

공통 미리보기 도구는 저장소 최상위의 `review.py`, `review-web/`에서 관리합니다.

```bash
.venv/bin/python ai4video.py review my-video
# 또는
.venv/bin/python review.py --project my-video
```

브라우저에서 <http://127.0.0.1:8765>를 엽니다. 상단에서 프로젝트를 바꿀 수 있습니다.
컷 선택, 시간 이동, 재생·반복, 음성, 프레임 이동, 1080p PNG 저장을 지원합니다.
그림 코드 저장 시 현재 화면을 자동으로 갱신하며 MP4를 생성하지 않습니다.

수정 메모에는 컷 번호와 작성한 화면의 시간을 함께 저장합니다.
각 프로젝트의 `review-notes.json`에 저장되므로 Codex가 파일을 읽고 수정에 사용할 수 있습니다.
브라우저에도 미전송 메모를 임시 보관하며 연결이 복구되면 다시 저장합니다.

```bash
.venv/bin/python ai4video.py notes my-video
.venv/bin/python ai4video.py notes my-video --all
```

메모 입력이 **프로젝트에 저장됨**으로 표시된 뒤 채팅에서 ‘저장된 메모대로 수정해 줘’라고 요청하면 됩니다.
메모 파일은 프로젝트별로 분리됩니다. 메모가 원본 그림이나 대본을 자동으로 바꾸지는 않습니다.

영상 프로젝트는 저장소에 포함하지 않습니다. 새로 받은 저장소에서는 `videos/<프로젝트>/`에
프로젝트 파일을 별도로 배치해야 미리보기를 실행할 수 있습니다. 프로젝트가 없으면 목록은 비어 있으며,
리뷰어 실행 시 필요한 파일을 안내합니다.

기본 연결 형식은 프로젝트의 `project.json`, `timeline.json`, `visuals.py`입니다.
기존의 `frame(index, t)`와 `frame(scene, t)`를 구분해 호출합니다.
별도 타임라인 로직이 필요하면 프로젝트에 `review_adapter.py`를 두고
`timeline()`을 구현합니다. `FRAME_MODE = 'scene'` 또는 `'index'`,
`FRAME_HAS_CAPTIONS`, `CUT_LABELS`로 해당 프로젝트의 표현 방식을 지정할 수 있습니다.
프로젝트 고유의 문단·컷 연결 로직은 `videos/<프로젝트>/review_adapter.py`에서 관리합니다.

공통 도구의 회귀 검사는 실제 영상 없이 실행됩니다. 테스트가 임시 프로젝트와 WAV 음성을 생성하고,
검사 후 삭제합니다. 브라우저 검사는 별도로 설치한 Playwright와 Chromium을 사용합니다.

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node tests/review.e2e.cjs /path/to/playwright
```

## 제작 명령

로컬 프로젝트의 `build.py`를 공통 CLI로 실행할 수 있습니다. 다음은 `periodic-table` 프로젝트가 로컬에 있을 때의 예시입니다.

```bash
uv sync

uv run ai4video.py run periodic-table draft
uv run ai4video.py run periodic-table audio
uv run ai4video.py run periodic-table sync
uv run ai4video.py run periodic-table preview
uv run ai4video.py run periodic-table render --jobs 4
uv run ai4video.py run periodic-table render --scene 13 --jobs 2
uv run ai4video.py run periodic-table assemble
uv run ai4video.py run periodic-table check
```

`run`은 루트의 `.venv/bin/python`으로 해당 프로젝트의 `build.py`를 실행하고 종료 코드를 전달합니다.
새 프로젝트의 `build.py`는 사용할 제작 단계의 명령을 받아 처리하도록 작성하세요.
`init`은 영상 렌더러를 생성하지 않습니다. 주기율표의 `lesson.py`, `visuals.py`, `build.py`는
주기율표 전용이므로 다른 주제에는 별도의 장면과 제작 구현이 필요합니다.

음성 생성은 온라인 서비스를 사용합니다. 기존 음성이 있으면 주기율표의 렌더링과 검증은
오프라인으로 실행할 수 있습니다. 공통 도구와 의존성 설정은 Git으로 관리하고,
`videos/`의 프로젝트 파일 전체와 가상환경은 `.gitignore`로 제외합니다.

## 공통 의존성 관리

루트에서 `uv add 패키지명`으로 의존성을 추가하고 `uv remove 패키지명`으로 제거합니다.
`pyproject.toml`, `.python-version`과 `uv sync`가 생성하는 `uv.lock`을 함께 관리합니다.
새 환경에서는 `uv sync`로 설치하며, 명령은 `uv run ai4video.py …`로 실행합니다.
FFmpeg/FFprobe와 글꼴은 시스템에 별도로 설치해야 합니다.

현재 설치 환경은 기존 주기율표 환경을 루트로 옮겨 보존했습니다.
네트워크 제한으로 첫 `uv sync`와 `uv.lock` 생성은 완료하지 못했습니다.
네트워크가 가능한 환경에서 `uv sync`를 실행하세요. 그 전에는 설치된 환경으로
`uv run --no-sync ai4video.py list`처럼 실행할 수 있습니다.
