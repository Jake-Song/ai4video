# Triton tiled matmul

전체 대본은 [script.md](script.md)입니다. 1번부터 9번까지 66개 컷으로 구성하며, 최신 길이는 `timeline.json`의 실제 음성 기준을 따릅니다. 수정 중에는 브라우저 미리보기와 내레이션만 갱신하며, MP4는 사용자가 수정 완료를 알린 뒤 출력합니다. 현재 MP4는 이전 출력본입니다.

## 영상

- `triton-tiled-matmul.ko.mp4`: 전체 9장면 영상, 장면별 챕터 포함
- `triton-tiled-matmul.ko.srt`: 전체 영상의 시간에 맞춘 한국어 자막
- `clips/01.mp4`부터 `clips/09.mp4`: 장면별 개별 영상
- `preview/01-storyboard.jpg`부터 `preview/09-storyboard.jpg`: 장면별 미리보기
- `preview/scenes01-09-storyboard.jpg`: 전체 컷 미리보기
- `timeline.json`: 실제 음성에 맞춘 장면·문단·자막 시간
- `triton-scenes01-02-preview.ko.mp4`: 이전 1·2번 시험 출력 보관본

1920×1080, 30fps, 한국어 내레이션과 화면 자막을 사용합니다. 어두운 남색 배경, 밝은 글자, 점선 격자와 사선 강조로 사용자가 제공한 참고 이미지의 구성을 반영했습니다. A는 파랑, B는 청록, C는 보라로 표시합니다. 왼쪽 상단의 수식은 모든 컷에서 `A(M × K) × B(K × N) = C(M × N)`입니다.

1·2번의 기존 격자는 M=N=9, K=12에 해당하는 설명용 축척입니다. 강조한 입력 타일의 크기는 3×4와 4×3, 출력 타일은 3×3입니다. 첫 컷 뒤에는 숫자 없이 같은 A 행과 B 열의 중복 전송, 대역폭·대기 비용, 입력 재사용을 격자 애니메이션으로 보여줍니다. 4번부터는 4×4 입력과 2×2 출력 타일로 두 K 구간의 실제 부분 곱과 누적 결과를 보여줍니다. 9번 경계 예제는 5×5 행렬에 2×2 타일을 적용합니다. 그림은 실제 Triton 커널의 타일 크기나 스레드 배치를 재현하지 않습니다. 2번 마지막의 곱은 K 구간 하나의 부분 결과이며, 전체 C의 계산 완료를 뜻하지 않습니다.

중복 전송 설명은 출력마다 입력을 HBM에서 다시 가져오는 방식을 가정합니다. 실제 HBM 접근에는 캐시의 영향도 있음을 내레이션과 화면에 표시합니다.

1-01은 A의 같은 행에서 B의 다른 열을 세 번 계산한 뒤, B의 같은 열에서 A의 다른 행을 세 번 계산합니다. 계산된 C의 칸은 남겨 두고, 음성의 ‘이번에는’ 시점에 두 번째 동작으로 전환됩니다. 그림에는 원소의 숫자 값과 횟수 카운터를 넣지 않습니다.

내레이션은 `script.md`의 각 장면에서 읽습니다. 장면 길이는 대본의 구간 길이를 기준으로 하되, 음성이 길면 해당 장면을 늘립니다. 대본 원본의 타임코드는 변경하지 않습니다.

## 브라우저에서 컷 검토

저장소 루트에서 다음 명령을 실행하고 브라우저에서 <http://127.0.0.1:8765>를 엽니다.

```bash
.venv/bin/python ai4video.py review triton-tiled-matmul
```

- 왼쪽의 스크롤 목록에서 `1-01`부터 `9-08`까지 66개 컷을 선택합니다. 첫 컷 뒤의 추가 설명은 세 컷으로 구성하며, 기존 컷 번호와 작성 중인 메모는 유지합니다.
- 슬라이더로 시간을 이동하고, 재생·일시정지와 컷 반복으로 움직임을 확인합니다.
- `←`, `→`는 한 프레임, `Shift + ←`, `Shift + →`는 1초 이동입니다. `Space`로 재생·정지합니다.
- 270p·540p·720p·1080p 중 미리보기 화질을 선택합니다. 현재 화면 저장은 선택한 화질과 관계없이 1920×1080 PNG를 내려받습니다.
- 수정 메모는 컷 번호·장면 시간·컷 내부 시간과 함께 이 폴더의 `review-notes.json`에 자동 저장됩니다. **프로젝트에 저장됨** 표시 후 채팅에서 ‘저장된 메모대로 수정해 줘’라고 요청하면 됩니다. **위치·메모 복사**로 직접 복사할 수도 있습니다.
- 수정이 반영된 메모는 자동으로 비웁니다. `project.json`의 `review.clear_resolved_notes` 설정을 사용하며, 새로 작성 중인 메모는 버전을 비교해 보호합니다.
- `visuals.py`를 저장하면 현재 위치의 화면이 자동으로 갱신됩니다. 문법 오류가 있으면 마지막 화면을 유지하고, 수정하면 자동으로 복구됩니다.
- `script.md`를 수정해 기존 음성과 달라진 컷도 화면은 확인할 수 있습니다. 해당 컷에는 음성 갱신이 필요하다고 표시하며, 예전 음성은 재생하지 않습니다. 최종 영상 출력은 음성을 다시 만든 후에만 가능합니다.

미리보기는 MP4를 만들지 않고 기존 `visuals.frame()`으로 필요한 프레임만 그립니다. 재생 화면은 최대 15fps로 요청하며, 프레임 이동과 PNG 저장은 최종 영상과 같은 30fps 시간 기준을 사용합니다. 1·2번 그림과 공통 도구는 `visuals.py`, 3~9번 그림과 첫 컷 뒤의 중복 전송 애니메이션은 `scenes.py`에서 관리합니다. 공통 UI 글씨와 배치는 저장소 루트의 `review-web/style.css`에서 관리하며, CSS 저장도 자동으로 반영됩니다. 컷을 추가·삭제할 때에는 `build.py`의 `KEYS`를 수정합니다. `CUT_IDS`는 기존 컷의 메모 번호를, `AUDIO_SLOTS`는 기존 음성 파일을 보존합니다.

다른 포트는 `--port 8766`으로 지정할 수 있습니다. 종료는 터미널에서 `Ctrl+C`입니다. 브라우저 UI와 서버는 저장소 루트의 `review-web/`, `review.py`에 있습니다. 이 폴더의 `review.py`는 예전 실행 명령을 유지하는 작은 연결 파일입니다. 추가 패키지 설치나 온라인 서비스 없이 사용할 수 있습니다.

미리보기 회귀 검사는 다음 명령으로 실행합니다. 브라우저 검사는 Playwright와 Chromium이 설치된 환경에서 실행하며, 임시 복사본을 사용해 원본 대본과 그림을 변경하지 않습니다.

```bash
.venv/bin/python -m unittest discover -s tests -p test_review.py -v
node tests/review.e2e.cjs /path/to/playwright
```

## 재생성

저장소 루트에서 실행합니다. 기존 공통 가상환경, FFmpeg/FFprobe, UnDotum 및 DejaVu 글꼴을 사용합니다.

```bash
.venv/bin/python triton-tiled-matmul/build.py audio
.venv/bin/python triton-tiled-matmul/build.py preview
.venv/bin/python triton-tiled-matmul/build.py render --jobs 2
.venv/bin/python triton-tiled-matmul/build.py assemble
.venv/bin/python triton-tiled-matmul/build.py check
```

음성 생성만 네트워크 연결과 환경변수 `ELEVENLABS_API_KEY`가 필요합니다. ElevenLabs의 `7Nah3cbXKVmGX7gQUuwz` (Joon Park) 음성과 `eleven_multilingual_v2` 모델을 사용합니다. API 키는 파일이나 브라우저에 저장하지 않습니다. 공개 음성 설정은 `project.json`, API 호출과 기술 용어의 읽는 방법은 `elevenlabs_tts.py`에 있습니다. 음성·대본·설정이 같으면 기존 오디오를 재사용하며, 변경된 컷만 API로 다시 생성합니다. 이전 Edge TTS 음성은 `audio/previous-edge-tts/`에 보관합니다.

`--scene 1`부터 `--scene 9`까지 특정 장면을 선택할 수 있습니다. `--jobs 2`로 두 장면씩 병렬 렌더링할 수 있습니다. 음성 생성과 영상 제작은 `build.py`에서 관리합니다.

공통 CLI에서도 `ai4video.py run triton-tiled-matmul render --scene 1`과 같은 방식으로 실행할 수 있습니다. 장면 번호는 대본과 같은 1~9입니다.
