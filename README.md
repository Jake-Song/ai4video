# ai4video

여러 영상 프로젝트의 대본, 장면 클립, 음성, 미리보기와 제작 코드를 관리합니다.
프로젝트마다 독립된 폴더를 사용하고, Python 3.13 가상환경은 루트의 `uv` 프로젝트로 함께 관리합니다.

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
`register`는 기존 폴더에 설정만 추가합니다. 이미 등록된 설정은 덮어쓰지 않습니다.

## 구조

```text
ai4video/
├── ai4video.py                 # 공통 관리 CLI
├── README.md
├── pyproject.toml             # 공통 Python 의존성
├── .python-version            # Python 3.13
├── .venv/                     # 공통 가상환경 (Git 제외)
└── periodic-table/             # 영상 프로젝트; 다른 프로젝트도 같은 층에 추가
    ├── project.json            # 제목, 제작 상태, 제작 스크립트·산출물 경로
    ├── README.md               # 개별 영상 설명과 재현 방법
    ├── lesson.py               # 기존 주기율표 프로젝트의 대본 원본
    ├── script.ko.md            # 대본
    ├── build.py                # 프로젝트별 제작 스크립트
    ├── timeline.json          # 장면별 번호·제목·길이
    ├── data/
    ├── audio/
    ├── clips/                  # 장면별 영상
    └── preview/
```

`project.json`의 `status`는 제작자가 `draft`, `producing`, `review`, `done` 등으로 기록합니다.
`list`는 기록된 상태와 MP4 클립 수를 보여줍니다. `clips`는 타임라인이 있으면
장면별 길이와 파일 존재 여부를, 없으면 클립 파일 목록을 보여줍니다.
`ready`는 파일이 있다는 뜻이며 영상 품질 검증 결과는 아닙니다.

## 제작 명령

기존 [주기율표 프로젝트](./periodic-table/README.md)를 공통 CLI로 실행할 수 있습니다.

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
오프라인으로 실행할 수 있습니다. 제작 코드·대본·설정·타임라인은 Git으로 관리하고,
가상환경과 생성된 음성·영상·미리보기는 `.gitignore`로 제외합니다.

## 공통 의존성 관리

루트에서 `uv add 패키지명`으로 의존성을 추가하고 `uv remove 패키지명`으로 제거합니다.
`pyproject.toml`, `.python-version`과 `uv sync`가 생성하는 `uv.lock`을 함께 관리합니다.
새 환경에서는 `uv sync`로 설치하며, 명령은 `uv run ai4video.py …`로 실행합니다.
FFmpeg/FFprobe와 글꼴은 시스템에 별도로 설치해야 합니다.

현재 설치 환경은 기존 주기율표 환경을 루트로 옮겨 보존했습니다.
네트워크 제한으로 첫 `uv sync`와 `uv.lock` 생성은 완료하지 못했습니다.
네트워크가 가능한 환경에서 `uv sync`를 실행하세요. 그 전에는 설치된 환경으로
`uv run --no-sync ai4video.py list`처럼 실행할 수 있습니다.
