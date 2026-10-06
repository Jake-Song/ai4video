"""Render only the three newly added explanations, using independently timed audio.

Run with the repository virtualenv: additions_preview.py audio|stills|render|check.
Original narration, scene budgets, and the full video are never overwritten.
"""
import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw

import build
from lesson import SCENES
import visuals as v

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'preview' / 'additions'
FINAL = ROOT / 'periodic-table-additions-preview.ko.mp4'
WIDTH, HEIGHT, FPS = 1280, 720, 30
SECTIONS = [
    ('pauli', 0, '파울리 배타 원리', '같은 상태에는 전자 하나'),
    ('capacities', 3, '껍질의 정원은 왜 2n²일까?', '오비탈의 수 × 두 스핀 상태'),
    ('fblock', 3, '주기율표의 끝은 어디일까?', '원소 137과 빛의 속도 한계'),
]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


async def audio():
    import edge_tts
    OUT.mkdir(parents=True, exist_ok=True)
    limit = asyncio.Semaphore(3)
    tasks = []
    for key, first, _, _ in SECTIONS:
        source = next(s for s in SCENES if s['key'] == key)
        tasks.extend((key, j, body) for j, body in enumerate(source['beats'][first:]))

    async def take(key, j, body):
        path = OUT / f'{key}-{j:02}.mp3'
        meta = path.with_suffix('.json')
        signature = hashlib.sha256((build.VOICE + '|+0%|' + body).encode()).hexdigest()
        if path.exists() and meta.exists() and json.loads(meta.read_text())['digest'] == signature:
            return
        async with limit:
            for attempt in range(3):
                try:
                    boundaries = []
                    voice = edge_tts.Communicate(body, build.VOICE, boundary='WordBoundary')
                    async with asyncio.timeout(40):
                        with path.with_suffix('.part').open('wb') as f:
                            async for chunk in voice.stream():
                                if chunk['type'] == 'audio':
                                    f.write(chunk['data'])
                                elif chunk['type'] == 'WordBoundary':
                                    boundaries.append({k: chunk[k] for k in ('offset', 'duration', 'text')})
                    if not boundaries:
                        raise RuntimeError('No word timing returned')
                    path.with_suffix('.part').replace(path)
                    save(meta, dict(digest=signature, text=body, boundaries=boundaries))
                    print(f'Voice ready: {key} {j + 1}', flush=True)
                    return
                except Exception as exc:
                    print(f'Voice retry: {key} {j + 1}: {type(exc).__name__}', flush=True)
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1 + attempt)

    await asyncio.gather(*(take(*task) for task in tasks))
    sync()


def sync():
    data = bytearray()
    segments, cues = [], []
    silence = lambda seconds: b'\0\0' * round(seconds * build.RATE)
    for key, first, title, subtitle in SECTIONS:
        source = next(s for s in SCENES if s['key'] == key)
        start = len(data) / 2 / build.RATE
        data.extend(silence(.8))
        beats = []
        for j, body in enumerate(source['beats'][first:]):
            path = OUT / f'{key}-{j:02}.mp3'
            meta = json.loads(path.with_suffix('.json').read_text())
            assert meta['text'] == body
            offset = len(data) / 2 / build.RATE
            raw = build.pcm(path, 1.0)
            duration = len(raw) / 2 / build.RATE
            data.extend(raw)
            beats.append(dict(text=body, start=offset, duration=duration))
            words = build.caption_words(body, meta['boundaries'])
            pending, begin = [], None
            for k, (w, word) in enumerate(zip(meta['boundaries'], words, strict=True)):
                if begin is None:
                    begin = offset + w['offset'] / 1e7
                pending.append(word)
                end = offset + (w['offset'] + w['duration']) / 1e7
                if len(' '.join(pending)) >= 32 or word.endswith(('.', '?', '!')) or k == len(words) - 1:
                    cues.append([begin, min(offset + duration, end + .12), ' '.join(pending)])
                    pending, begin = [], None
            data.extend(silence(.35))
        data.extend(silence(1.0))
        segments.append(dict(key=key, title=title, subtitle=subtitle, start=start,
                             end=len(data) / 2 / build.RATE, beats=beats))
    samples_per_frame = build.RATE // FPS
    frames = math.ceil(len(data) / 2 / samples_per_frame)
    data.extend(b'\0\0' * (frames * samples_per_frame - len(data) // 2))
    duration = frames / FPS
    segments[-1]['end'] = duration
    for i, cue in enumerate(cues[:-1]):
        cue[1] = min(cue[1], cues[i + 1][0] - .01)
    assert all(a < b for a, b, _ in cues)
    build.write_wav(OUT / 'narration.wav', data)
    save(OUT / 'timeline.json', dict(duration=duration, frames=frames, fps=FPS,
                                    segments=segments, cues=cues))
    (OUT / 'subtitles.ko.srt').write_text('\n\n'.join(
        f'{i + 1}\n{build.stamp(a)} --> {build.stamp(b)}\n{body}'
        for i, (a, b, body) in enumerate(cues)) + '\n')
    print(f'Timed {len(segments)} sections, {duration:.2f}s', flush=True)


def txt(im, body, x, y, size=42, color=v.FG, maxw=1700):
    v.text(im, body, x, y, size, color, maxw=maxw)


def box(im, x, y, up=True, down=False, same=False, color=v.TEAL):
    v.rounded(im, (x - 130, y - 110, x + 130, y + 110), color, width=3, r=18)
    if up:
        v.arrow(im, (x - 45, y + 60), (x - 45, y - 60), color, 8, tip=24)
    if down or same:
        a, b = ((x + 45, y - 60), (x + 45, y + 60))
        v.arrow(im, b if same else a, a if same else b, color, 8, tip=24)


def pauli(im, j):
    if j in (0, 3):
        box(im, 490, 500, down=True)
        box(im, 1070, 500, same=True, color=v.RED)
        txt(im, '허용', 490, 685, color=v.TEAL)
        txt(im, '같은 스핀은 금지', 1070, 685, color=v.RED)
        if j == 3:
            box(im, 1580, 500, color=v.GOLD)
            txt(im, '세 번째는 다른 오비탈', 1580, 685, 34, v.GOLD, 470)
        else:
            txt(im, '같은 오비탈', 490, 320, 36)
            txt(im, '같은 오비탈', 1070, 320, 36)
            txt(im, '같은 양자 상태의 중복 점유는 불가능', 960, 815, 43, v.GOLD)
    elif j in (1, 2):
        labels = [('n', '껍질'), ('l', '부껍질'), ('mₗ', '오비탈 구별'), ('mₛ', '스핀')]
        for k, (symbol, name) in enumerate(labels):
            x = 390 + 380 * k
            color = v.TEAL if k < 3 else v.GOLD
            v.rounded(im, (x - 145, 305, x + 145, 690), color, width=3, r=16)
            txt(im, symbol, x, 365, 65, color)
            txt(im, name, x, 450, 34)
            txt(im, ['1', '0', '0', '+½'][k], x, 545, 46)
            txt(im, ['1', '0', '0', '−½'][k], x, 625, 46)
        txt(im, '1s의 두 전자: 오비탈은 같고, 스핀은 다르다', 960, 800, 42, v.GOLD)
    elif j == 4:
        box(im, 640, 510, down=True)
        txt(im, 'mₛ = +½ 또는 −½', 1270, 440, 54, v.GOLD)
        txt(im, '정해진 축에 대한 두 스핀 상태', 1270, 570, 38)
        txt(im, '화살표는 이동 방향이나 고전적인 자전 표시가 아닙니다', 960, 800, 36, v.MUTED)
    elif j == 5:
        txt(im, '전기적 반발', 520, 410, 52, v.PINK)
        txt(im, '같은 전하 사이의 상호작용', 520, 540, 35)
        txt(im, '파울리 배타 원리', 1370, 410, 52, v.TEAL)
        txt(im, '같은 양자 상태의 중복 점유 제한', 1370, 540, 35)
        v.line(im, [(945, 320), (945, 650)], v.GRID, 3)
        txt(im, '전자배치를 이해하려면 두 효과를 함께 고려합니다', 960, 800, 40, v.GOLD)
    else:
        box(im, 550, 510, down=True)
        box(im, 1250, 510)
        txt(im, '1s', 550, 330, 54, v.TEAL)
        txt(im, '2s', 1250, 330, 54, v.TEAL)
        txt(im, '최대 두 전자', 550, 700, 38)
        txt(im, '리튬의 세 번째 전자', 1250, 700, 38)
        v.arrow(im, (770, 510), (1020, 510), v.GOLD, 5)
        txt(im, '점유 제약 → 전자배치 → 주기율표의 구조', 960, 820, 40, v.GOLD)


def capacities(im, j):
    if j == 0:
        txt(im, '최대 전자 수 = 2n²', 960, 455, 104, v.GOLD)
        txt(im, 'n은 껍질 번호: 1, 2, 3, 4, …', 960, 630, 45)
        txt(im, '한 껍질의 수용량을 세는 규칙', 960, 805, 36, v.MUTED)
    elif j in (1, 2):
        rows = [(1, 's: 1', '1 = 1²'), (2, 's: 1   +   p: 3', '4 = 2²'),
                (3, 's: 1   +   p: 3   +   d: 5', '9 = 3²'),
                (4, 's: 1   +   p: 3   +   d: 5   +   f: 7', '16 = 4²')]
        for k, (n, body, count) in enumerate(rows[:3 if j == 1 else 4]):
            y = 330 + k * 120
            txt(im, f'n = {n}', 270, y, 40, v.TEAL)
            txt(im, body, 920, y, 42, maxw=1050)
            txt(im, count, 1640, y, 42, v.GOLD)
        txt(im, '오비탈 수: 1 + 3 + ⋯ + (2n − 1) = n²', 960, 850, 46, v.GOLD)
    elif j == 3:
        txt(im, 'n²', 440, 430, 115, v.TEAL)
        txt(im, '오비탈', 440, 585, 40)
        txt(im, '×', 740, 440, 90)
        box(im, 1040, 440, down=True)
        txt(im, '오비탈마다 최대 2전자', 1040, 635, 37)
        txt(im, '= 2n²', 1550, 435, 100, v.GOLD, 500)
        txt(im, '두 스핀 상태 + 파울리 배타 원리', 960, 815, 43, v.GOLD)
    else:
        for k, value in enumerate([2, 8, 18, 32]):
            x = 350 + 405 * k
            v.rounded(im, (x - 155, 310, x + 155, 655), v.GRID, width=3, r=18)
            txt(im, f'n = {k + 1}', x, 370, 40, v.TEAL)
            txt(im, value, x, 515, 102, v.GOLD)
        txt(im, '껍질의 최대 정원 ≠ 주기율표 한 줄의 길이', 960, 790, 44)


def limit(im, j):
    if j == 0:
        txt(im, '새로운 원소를 끝없이 만들 수 있을까?', 960, 360, 58)
        txt(im, '137', 960, 565, 185, v.GOLD)
        txt(im, '파인만과 관련해 알려진 원소의 한계 논의', 960, 795, 40, v.MUTED)
    elif j in (1, 2):
        txt(im, 'v / c = Zα ≈ Z / 137', 960, 350, 80, v.GOLD)
        txt(im, '전자 하나인 보어 모형 · 가장 안쪽 궤도', 960, 460, 35, v.MUTED)
        for k, (z, body) in enumerate([(1, '약 0.007c'), (100, '약 0.73c'), (137, '약 c')]):
            x = 480 + 480 * k
            txt(im, f'Z = {z}', x, 605, 39, v.TEAL)
            txt(im, body, x, 700, 60, v.RED if z == 137 else v.FG)
        txt(im, '모형을 그대로 외삽한 값 · 실제 고원자번호 전자 속도가 아님', 960, 830, 33, v.MUTED)
        if j == 2:
            txt(im, '질량이 있는 전자는 c에 도달할 수 없다', 960, 235, 36, v.RED)
    elif j == 3:
        txt(im, '137', 465, 455, 128, v.GOLD)
        txt(im, '단순한 모형의 한계', 465, 620, 37)
        v.arrow(im, (730, 460), (1110, 460), v.TEAL, 6)
        txt(im, '핵의 크기 + 상대론', 930, 350, 35, v.TEAL)
        txt(im, '약 170–173', 1450, 455, 88, v.GOLD, 690)
        txt(im, '모형에 따른 초임계 영역', 1450, 620, 37)
        txt(im, '확정된 마지막 원소 번호가 아닙니다', 960, 815, 44, v.FG)
    elif j == 4:
        txt(im, '아주 강한 핵의 전기장', 960, 310, 48, v.GOLD)
        for x, symbol, name, color in [(640, 'e⁻', '전자', v.TEAL), (1280, 'e⁺', '양전자', v.PINK)]:
            v.ring(im, x, 490, 100, color, 4)
            txt(im, symbol, x, 490, 85, color)
            txt(im, name, x, 660, 41, color)
        txt(im, '빈 초임계 준위 등 조건에 따라 쌍생성 가능', 960, 795, 40)
        txt(im, '개념도 · 생성 확률이나 궤적을 계산한 그림이 아닙니다', 960, 870, 29, v.MUTED)
    else:
        for x, head, body, color in [(520, '전자 껍질의 정원', '2n²', v.TEAL),
                                    (1390, '원소 존재·합성의 한계', '전자 구조 + 핵의 안정성', v.GOLD)]:
            txt(im, head, x, 385, 46, color, 800)
            txt(im, body, x, 550, 66 if x == 520 else 43, maxw=810)
        v.line(im, [(945, 310), (945, 650)], v.GRID, 3)
        txt(im, '핵이 얼마나 오래 버티는지도 중요합니다', 960, 795, 43, v.GOLD)


def slide(segment, index, section_index):
    im = v.backdrop().copy()
    v.text(im, '주기율표 · 추가 설명 프리뷰', 85, 65, 27, v.MUTED, anchor='left')
    v.text(im, f'{section_index + 1:02} / 03', 1835, 65, 26, v.MUTED, anchor='right')
    txt(im, segment['title'], 960, 155, 59)
    {'pauli': pauli, 'capacities': capacities, 'fblock': limit}[segment['key']](im, index)
    return im.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def render(stills_only=False):
    tl = json.loads((OUT / 'timeline.json').read_text())
    slides = {}
    for k, seg in enumerate(tl['segments']):
        for j in range(len(seg['beats'])):
            tile = slide(seg, j, k)
            tile.save(OUT / f'{seg["key"]}-{j:02}.png')
            slides[k, j] = tile
    sheet = Image.new('RGB', (WIDTH, 240 * math.ceil(len(slides) / 3)), v.BG)
    for k, tile in enumerate(slides.values()):
        sheet.paste(tile.resize((426, 240)), ((k % 3) * 426, (k // 3) * 240))
    sheet.save(OUT / 'contact-sheet.jpg')
    if stills_only:
        return
    tmp = FINAL.with_suffix('.part.mp4')
    ffmpeg = subprocess.Popen([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo',
        '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', '-',
        '-i', str(OUT / 'narration.wav'), '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
        '-c:v', 'libx264', '-threads', '4', '-preset', 'fast', '-crf', '20',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-ar', '48000',
        '-metadata', 'title=주기율표 추가 설명 프리뷰', '-metadata:s:a:0', 'language=kor',
        '-t', str(tl['duration']), '-movflags', '+faststart', str(tmp)], stdin=subprocess.PIPE)
    cue_index, section_index = 0, 0
    try:
        for frame in range(tl['frames']):
            t = frame / FPS
            while section_index + 1 < len(tl['segments']) and t >= tl['segments'][section_index]['end']:
                section_index += 1
            seg = tl['segments'][section_index]
            j = max(0, sum(t >= b['start'] for b in seg['beats']) - 1)
            im = slides[section_index, j].copy()
            transition = (t - seg['beats'][j]['start']) / .35
            if j and 0 <= transition < 1:
                im = Image.blend(slides[section_index, j - 1], im, v.ease(transition))
            while cue_index + 1 < len(tl['cues']) and tl['cues'][cue_index][1] <= t:
                cue_index += 1
            a, b, body = tl['cues'][cue_index]
            if a <= t < b:
                ImageDraw.Draw(im).rounded_rectangle((35, 651, 1245, 707), radius=10, fill='#101826')
                v.text(im, body, 640, 679, 27, v.FG, maxw=1180)
            d = ImageDraw.Draw(im)
            d.line((57, 632, 1223, 632), fill=v.GRID, width=2)
            d.line((57, 632, 57 + round(1166 * t / tl['duration']), 632), fill=v.TEAL, width=3)
            fade = min(v.ease((t - seg['start']) / .35), v.ease((seg['end'] - t) / .35))
            if fade < 1:
                im = Image.blend(Image.new('RGB', im.size, v.BG), im, fade)
            ffmpeg.stdin.write(im.tobytes())
            if frame % (FPS * 20) == 0:
                print(f'Render: {t:.0f}/{tl["duration"]:.0f}s', flush=True)
    finally:
        ffmpeg.stdin.close()
        result = ffmpeg.wait()
    if result:
        raise RuntimeError(f'FFmpeg failed: {result}')
    tmp.replace(FINAL)
    print(FINAL, flush=True)


def check():
    tl = json.loads((OUT / 'timeline.json').read_text())
    info = build.probe(FINAL)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    audio_stream = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    assert (video['width'], video['height']) == (WIDTH, HEIGHT)
    assert video['r_frame_rate'] == f'{FPS}/1'
    assert int(video['nb_frames']) == tl['frames']
    assert audio_stream['codec_name'] == 'aac'
    assert abs(float(info['format']['duration']) - tl['duration']) < .1
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(FINAL), '-f', 'null', '-'], check=True)
    save(OUT / 'validation.json', dict(duration=tl['duration'], frames=tl['frames'],
                                     resolution=[WIDTH, HEIGHT], fps=FPS,
                                     decoded=True, sections=[s['title'] for s in tl['segments']]))
    print(f'Validated: {tl["duration"]:.2f}s, {WIDTH}×{HEIGHT}, {FPS}fps, H.264/AAC', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['audio', 'stills', 'render', 'check'])
    args = parser.parse_args()
    if args.command == 'audio':
        asyncio.run(audio())
    elif args.command == 'stills':
        render(stills_only=True)
    elif args.command == 'render':
        render()
    else:
        check()
