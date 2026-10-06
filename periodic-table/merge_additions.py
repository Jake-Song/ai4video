"""Insert the reviewed additions preview into the original video at scene boundaries."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

import build
from lesson import SCENES, SOURCES, TITLE

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'preview' / 'integrated'
FINAL = ROOT / 'periodic-table-integrated.ko.mp4'
TIMELINE = ROOT / 'integrated-timeline.json'
FPS, RATE = 30, 48000
INPUTS = {'original': ROOT / 'periodic-table.ko.mp4',
          'additions': ROOT / 'periodic-table-additions-preview.ko.mp4'}


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def plan():
    OUT.mkdir(parents=True, exist_ok=True)
    original = json.loads((ROOT / 'timeline.json').read_text())
    added = json.loads((ROOT / 'preview/additions/timeline.json').read_text())
    old = {s['key']: s for s in original['scenes']}
    new = {s['key']: s for s in added['segments']}
    start = lambda s: round(s['start'] * FPS)
    end = lambda s: start(s) + s['frames']
    parts = []
    cursor = 0

    def part(source, first, last):
        nonlocal cursor
        parts.append(dict(source=source, first=first, last=last,
                          output_frame=cursor, frames=last - first))
        cursor += last - first

    a, b = round(new['capacities']['start'] * FPS), round(new['fblock']['start'] * FPS)
    part('original', 0, start(old['pauli']))
    part('additions', 0, a)
    part('original', end(old['pauli']), end(old['capacities']))
    part('additions', a, b)
    part('original', end(old['capacities']), end(old['fblock']))
    part('additions', b, added['frames'])
    part('original', end(old['fblock']), original['frames'])

    scenes, cues = [], []
    for part_info in parts:
        source, first, last = (part_info[k] for k in ('source', 'first', 'last'))
        shift = (part_info['output_frame'] - first) / FPS
        source_cues = original['cues'] if source == 'original' else added['cues']
        for a0, b0, body in source_cues:
            if b0 <= first / FPS or a0 >= last / FPS:
                continue
            # Every cut is in inter-scene silence; no subtitle/speech may be cut.
            assert first / FPS <= a0 < b0 <= last / FPS, (source, a0, b0)
            cues.append([a0 + shift, b0 + shift, body])
        if source == 'original':
            for scene in original['scenes']:
                if first <= start(scene) < last:
                    assert end(scene) <= last
                    s = copy.deepcopy(scene)
                    s['start'] = (start(scene) + part_info['output_frame'] - first) / FPS
                    s['source'] = source
                    scenes.append(s)
        else:
            segment = next(s for s in added['segments'] if round(s['start'] * FPS) == first)
            key = segment['key']
            for beat in segment['beats']:
                assert first / FPS <= beat['start'] < beat['start'] + beat['duration'] <= last / FPS
            s = dict(key=key if key == 'pauli' else key + '_expanded',
                     chapter=old[key]['chapter'], title=segment['title'],
                     start=part_info['output_frame'] / FPS, duration=(last - first) / FPS,
                     frames=last - first, beats=[x['text'] for x in segment['beats']],
                     beats_timed=[dict(x, start=x['start'] - first / FPS) for x in segment['beats']],
                     note=next(x['note'] for x in SCENES if x['key'] == key), source=source)
            scenes.append(s)
    for i, scene in enumerate(scenes):
        scene['index'] = i
    normalize = lambda s: re.sub(r'\s+', '', s)
    expected = normalize(' '.join(b for s in SCENES for b in s['beats']))
    assert normalize(' '.join(b for s in scenes for b in s['beats'])) == expected
    assert normalize(' '.join(c[2] for c in cues)) == expected
    chapters = []
    for scene in scenes:
        if not chapters or chapters[-1]['title'] != scene['chapter']:
            chapters.append(dict(title=scene['chapter'], start=scene['start']))
    tl = dict(title=TITLE, fps=FPS, frames=cursor, duration=cursor / FPS,
              parts=parts, scenes=scenes, cues=cues, chapters=chapters,
              source_sha256={k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in INPUTS.items()})
    save(TIMELINE, tl)
    (ROOT / 'periodic-table-integrated.ko.srt').write_text('\n\n'.join(
        f'{i + 1}\n{build.stamp(a0)} --> {build.stamp(b0)}\n{body}'
        for i, (a0, b0, body) in enumerate(cues)) + '\n')
    script = [f'# {TITLE} · 추가 설명 통합본',
              f'한국어 · {cursor / FPS:.2f}초 · 1920×1080 / 30fps\n\n'
              '추가 설명은 720p 프리뷰를 1080p로 확대해 삽입했습니다.']
    for s in scenes:
        script.append(f'## {build.stamp(s["start"])[:-4]} · {s["title"]}\n\n' + '\n\n'.join(s['beats']))
    script.append('## 참고 자료\n\n' + '\n'.join(f'- [{n}]({u})' for n, u in SOURCES))
    (ROOT / 'script-integrated.ko.md').write_text('\n\n'.join(script) + '\n')
    metadata = [';FFMETADATA1', 'title=' + TITLE + ' · 추가 설명 통합본', 'language=kor']
    for i, chapter in enumerate(chapters):
        stop = chapters[i + 1]['start'] if i + 1 < len(chapters) else cursor / FPS
        metadata.extend(['[CHAPTER]', 'TIMEBASE=1/1000', f'START={round(chapter["start"] * 1000)}',
                         f'END={round(stop * 1000)}', 'title=' + chapter['title']])
    (OUT / 'chapters.ffmetadata').write_text('\n'.join(metadata) + '\n')
    print(f'Planned {len(parts)} cuts, {len(scenes)} scenes, {cursor / FPS:.2f}s', flush=True)
    return tl


def render():
    tl = plan()

    def encode(i, part):
        path = OUT / f'{i:02}.mov'
        signature = hashlib.sha256(json.dumps(dict(part=part, source=tl['source_sha256'][part['source']],
                                                    script=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
                                              sort_keys=True).encode()).hexdigest()
        cache = path.with_suffix('.json')
        if path.exists() and cache.exists() and json.loads(cache.read_text())['signature'] == signature:
            return path
        frames = part['frames']
        # Input seeking discards pre-roll during transcoding. Trim both streams to
        # integer frames / exactly corresponding PCM samples for gapless concatenation.
        args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                '-ss', f'{part["first"] / FPS:.9f}', '-i', str(INPUTS[part['source']]),
                '-map', '0:v:0', '-map', '0:a:0', '-map_metadata', '-1', '-map_chapters', '-1',
                '-vf', f'trim=end_frame={frames},setpts=PTS-STARTPTS,scale=1920:1080:flags=lanczos,setsar=1',
                '-af', f'aresample={RATE},apad,atrim=end_sample={frames * (RATE // FPS)},asetpts=PTS-STARTPTS',
                '-c:v', 'libx264', '-threads', '3', '-preset', 'fast', '-crf', '18',
                '-pix_fmt', 'yuv420p', '-r', str(FPS), '-video_track_timescale', '15360',
                '-c:a', 'pcm_s16le', '-ar', str(RATE), '-ac', '1', str(path)]
        subprocess.run(args, check=True)
        info = build.probe(path)
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
        assert int(video['nb_frames']) == frames
        assert int(audio['duration_ts']) == frames * (RATE // FPS), audio
        save(cache, dict(signature=signature, frames=frames))
        print(f'Encoded part {i + 1}/7: {frames / FPS:.2f}s', flush=True)
        return path

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda pair: encode(*pair), enumerate(tl['parts'])))
    assemble(tl)


def assemble(tl=None):
    tl = tl or json.loads(TIMELINE.read_text())
    for key, source in INPUTS.items():
        assert hashlib.sha256(source.read_bytes()).hexdigest() == tl['source_sha256'][key]
    paths = [OUT / f'{i:02}.mov' for i in range(len(tl['parts']))]
    for path, part in zip(paths, tl['parts'], strict=True):
        info = build.probe(path)
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
        assert int(video['nb_frames']) == part['frames']
        assert (video['width'], video['height'], video['r_frame_rate']) == (1920, 1080, '30/1')
        samples = part['frames'] * (RATE // FPS)
        missing = samples - int(audio['duration_ts'])
        assert 0 <= missing < RATE / 10, (path, missing)
        if missing:
            padded = path.with_suffix('.padded.mov')
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                            '-i', str(path), '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
                            '-af', f'apad,atrim=end_sample={samples},asetpts=PTS-STARTPTS',
                            '-c:a', 'pcm_s16le', '-ar', str(RATE), str(padded)], check=True)
            padded.replace(path)
            actual = next(s for s in build.probe(path)['streams'] if s['codec_type'] == 'audio')
            assert int(actual['duration_ts']) == samples
            print(f'Padded trailing silence: {path.name}, {missing / RATE:.3f}s', flush=True)
    listing = OUT / 'concat.txt'
    listing.write_text('\n'.join(f"file '{path.name}'" for path in paths) + '\n')
    partial = FINAL.with_suffix('.part.mp4')
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'concat', '-safe', '0', '-i', str(listing),
                    '-i', str(OUT / 'chapters.ffmetadata'), '-map', '0:v:0', '-map', '0:a:0',
                    '-map_metadata', '1', '-map_chapters', '1', '-c:v', 'copy',
                    '-c:a', 'aac', '-b:a', '192k', '-ar', str(RATE),
                    '-metadata:s:a:0', 'language=kor', '-movflags', '+faststart', str(partial)], check=True)
    partial.replace(FINAL)
    print(FINAL, flush=True)


def check():
    tl = json.loads(TIMELINE.read_text())
    info = build.probe(FINAL)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    assert (video['width'], video['height'], video['r_frame_rate']) == (1920, 1080, '30/1')
    assert video['codec_name'] == 'h264' and int(video['nb_frames']) == tl['frames']
    assert audio['codec_name'] == 'aac' and audio['sample_rate'] == str(RATE)
    assert abs(float(audio['duration']) - tl['duration']) < .05
    assert abs(float(info['format']['duration']) - tl['duration']) < .05
    assert len(info['chapters']) == len(tl['chapters']) == 8
    for actual, expected in zip(info['chapters'], tl['chapters'], strict=True):
        assert abs(float(actual['start_time']) - expected['start']) < .002
        assert actual['tags']['title'] == expected['title']
    prev = 0
    for a, b, body in tl['cues']:
        assert prev <= a < b <= tl['duration'] and body.strip()
        prev = b
    for key, path in INPUTS.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == tl['source_sha256'][key]
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(FINAL), '-f', 'null', '-'], check=True)
    save(OUT / 'validation.json', dict(duration=tl['duration'], frames=tl['frames'],
                                     resolution=[1920, 1080], fps=FPS, chapters=8,
                                     source_files_preserved=True, full_decode='passed',
                                     subtitle_cues=len(tl['cues']),
                                     sha256=hashlib.sha256(FINAL.read_bytes()).hexdigest()))
    print(f'Validated integrated video: {tl["duration"]:.2f}s, {tl["frames"]} frames, 8 chapters', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'render', 'assemble', 'check'])
    args = parser.parse_args()
    globals()[args.command]()
