"""Render the complete script as narrated matrix-grid animations."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor

from elevenlabs_tts import config as voice_config, signature as voice_signature, synthesize

ROOT = Path(__file__).resolve().parent
FPS, WIDTH, HEIGHT = 30, 1920, 1080
VOICE, RATE = voice_config()['voice_id'], str(voice_config()['voice_settings']['speed'])
KEYS = {
    1: ['dot', 'hbm_row_repeat', 'hbm_column_repeat', 'hbm_reuse', 'memory', 'reuse', 'partition', 'follow'],
    2: ['shapes', 'parameters', 'mn', 'output', 'k', 'inputs', 'product'],
    3: ['compare', 'cuda', 'indices', 'data', 'tensor', 'compiler', 'difference', 'next'],
    4: ['example', 'four', 'program', 'id', 'needed', 'parallel'],
    5: ['focus', 'zero', 'bk', 'first', 'remaining', 'advance', 'position', 'fixed', 'complete'],
    6: ['reuse_intro', 'reuse_a', 'reuse_b', 'general', 'same', 'intensity', 'cache'],
    7: ['connect', 'load', 'dot_api', 'dot_acc', 'whole', 'fp32', 'store'],
    8: ['lowering', 'cooperate', 'distribute', 'hardware', 'settings', 'tune'],
    9: ['edge', 'mask', 'large', 'resources', 'measure', 'overview', 'cycle', 'ending'],
}
CUT_IDS = {1: dict(dot='1-01', hbm_row_repeat='1-01a', hbm_column_repeat='1-01b',
                   hbm_reuse='1-01c', memory='1-02',
                   reuse='1-03', partition='1-04', follow='1-05')}
# Audio slots are independent of display order, preserving all existing speech.
AUDIO_SLOTS = {1: dict(dot=0, memory=1, reuse=2, partition=3, follow=4,
                       hbm_row_repeat=5, hbm_column_repeat=6, hbm_reuse=7)}


def save(path, data):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, suffix='.tmp', delete=False) as output:
        output.write(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
        partial = Path(output.name)
    partial.replace(path)


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))


def sources():
    script = (ROOT/'script.md').read_text()
    scenes = []
    for number, keys in KEYS.items():
        pattern = rf'^## {number}\. ([^\n]+)\n(.*?)(?=^## |\Z)'
        match = re.search(pattern, script, re.S | re.M)
        heading, section = match.groups()
        body = re.search(r'“(.*?)”', section.split('**내레이션**', 1)[1], re.S).group(1)
        body = body.replace('`', '')
        texts = [p.strip() for p in body.split('\n\n') if p.strip()]
        if len(texts) != len(keys):
            raise ValueError(f'Scene {number}: update visual keys for {len(texts)} narration paragraphs')
        timing, title = heading.split('|', 1)
        start, end = timing.strip().split('–')
        seconds = lambda stamp: sum(int(n)*60**i for i,n in enumerate(reversed(stamp.split(':'))))
        scenes.append(dict(index=number, title=title.strip(), nominal=seconds(end)-seconds(start),
                           beats=[dict(key=k, text=t, id=CUT_IDS.get(number,{}).get(k,f'{number}-{i+1:02}'))
                                  for i,(k,t) in enumerate(zip(keys,texts,strict=True))]))
    return scenes


def audio_paths(scene, beat):
    slot = AUDIO_SLOTS.get(scene, {}).get(KEYS[scene][beat], beat)
    path = ROOT/'audio'/f'{scene:02}-{slot:02}.mp3'
    return path, path.with_suffix('.json')


def signature(body):
    return voice_signature(body)


async def audio(selected):
    (ROOT/'audio').mkdir(exist_ok=True)
    for scene in selected:
        for i, beat in enumerate(scene['beats']):
            path, meta = audio_paths(scene['index'], i)
            digest = signature(beat['text'])
            if path.exists() and meta.exists() and json.loads(meta.read_text()).get('signature') == digest:
                continue
            if path.exists() and meta.exists() and json.loads(meta.read_text()).get('provider') != 'elevenlabs':
                backup = ROOT/'audio'/'previous-edge-tts'
                backup.mkdir(exist_ok=True)
                for old in (path, meta):
                    if not (backup/old.name).exists():
                        shutil.copy2(old, backup/old.name)
            partial = path.with_suffix('.part.mp3')
            contents, details = await asyncio.to_thread(synthesize, beat['text'])
            partial.write_bytes(contents)
            probe(partial)
            partial.replace(path)
            save(meta, dict(details, voice=VOICE, rate=RATE))
            print(f'Voice {scene["index"]:02}/{i+1:02}: {float(probe(path)["format"]["duration"]):.2f}s', flush=True)


def wrap(body, limit=43):
    lines, line = [], ''
    for word in body.split():
        if line and len(line+' '+word) > limit:
            lines.append(line)
            line = word
        else:
            line = f'{line} {word}'.strip()
    if line:
        lines.append(line)
    return lines


def captions(beat):
    sentences = re.split(r'(?<=[.?!])\s+', beat['text'])
    segments = []
    for sentence in sentences:
        lines = wrap(sentence)
        segments.extend('\n'.join(lines[i:i+2]) for i in range(0, len(lines), 2))
    weights = [len(s) for s in segments]
    total = sum(weights)
    duration = beat['speech_duration'] or beat['duration']-.6
    cursor = beat['start']+.2
    cues = []
    for text, weight in zip(segments, weights, strict=True):
        end = cursor+duration*weight/total
        cues.append(dict(start=cursor, end=end, text=text))
        cursor = end
    return cues


def dot_phase_boundaries(metadata,duration):
    """Match the row transitions to the generated narration's character timing."""
    alignment=metadata.get('alignment') or {}
    characters=''.join(alignment.get('characters',[]))
    starts=alignment.get('character_start_times_seconds',[])
    anchors=[]
    for phrase in ('이번에는',):
        index=characters.find(phrase)
        if index<0 or index>=len(starts):
            return None
        anchors.append((.2+starts[index])/duration)
    boundaries=[0.,*anchors,1.]
    return boundaries if all(a<b for a,b in zip(boundaries,boundaries[1:])) else None


def timeline(*, allow_stale=False):
    scenes = []
    global_start = 0.
    for source in sources():
        beats = []
        audio_metadata = []
        for i, original in enumerate(source['beats']):
            path, meta = audio_paths(source['index'], i)
            details=json.loads(meta.read_text()) if meta.exists() else {}
            audio_metadata.append(details)
            speech = float(probe(path)['format']['duration']) if path.exists() else 0
            stale = path.exists() and details.get('signature') != signature(original['text'])
            if stale and not allow_stale:
                raise RuntimeError('Narration is stale; run audio')
            beats.append(dict(original, speech_duration=speech,
                              audio=str(path.relative_to(ROOT)) if speech and not stale else None,
                              audio_stale=bool(stale),
                              duration=max(2.5, speech+.75 if speech else len(original['text'])/7+.75)))
        spare = max(0, source['nominal']-sum(b['duration'] for b in beats))
        cursor = 0.
        for beat,details in zip(beats,audio_metadata,strict=True):
            beat['duration'] = math.ceil((beat['duration']+spare/len(beats))*FPS)/FPS
            beat['start'] = cursor
            if beat['key']=='dot' and beat['audio']:
                phases=dot_phase_boundaries(details,beat['duration'])
                if phases:
                    beat['visual_phases']=phases
            cursor += beat['duration']
        scenes.append(dict(index=source['index'], title=source['title'], start=global_start,
                           duration=round(cursor*FPS)/FPS, beats=beats,
                           cues=[cue for beat in beats for cue in captions(beat)]))
        global_start += cursor
    return dict(title='Triton tiled matmul · 출력 타일 하나를 따라가 보기', width=WIDTH, height=HEIGHT,
                fps=FPS, duration=global_start, voice=VOICE, rate=RATE, scenes=scenes)


def stamp(seconds):
    ms = round(seconds*1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def metadata(tl):
    save(ROOT/'timeline.json', tl)
    for scene in tl['scenes']:
        (ROOT/f'scene{scene["index"]:02}.ko.srt').write_text('\n\n'.join(
            f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}'
            for i, c in enumerate(scene['cues']))+'\n')
    cues = [dict(c,start=c['start']+s['start'],end=c['end']+s['start'])
            for s in tl['scenes'] for c in s['cues']]
    (ROOT/'triton-tiled-matmul.ko.srt').write_text('\n\n'.join(
        f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}'
        for i,c in enumerate(cues))+'\n')


def render(scene):
    import visuals
    if not all(b['audio'] for b in scene['beats']):
        raise RuntimeError('Run audio before rendering the narrated clip')
    clips = ROOT/'clips'
    clips.mkdir(exist_ok=True)
    index = scene['index']
    scratch = ROOT/'preview'
    scratch.mkdir(exist_ok=True)
    silent = scratch/f'{index:02}-silent.mp4'
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo',
           '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', '-',
           '-an', '-c:v', 'libx264', '-threads', '4', '-preset', 'fast', '-crf', '18',
           '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(silent)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for f in range(round(scene['duration']*FPS)):
            proc.stdin.write(visuals.frame(scene, f/FPS).tobytes())
            if f % (FPS*10) == 0:
                print(f'Scene {index}: {f/FPS:.0f}s / {scene["duration"]:.1f}s', flush=True)
    finally:
        proc.stdin.close()
    if proc.wait():
        raise RuntimeError('FFmpeg video encoding failed')
    if not all(b['audio'] for b in scene['beats']):
        raise RuntimeError('Run audio before rendering the narrated clip')
    args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(silent)]
    filters = []
    for i, b in enumerate(scene['beats']):
        args += ['-i', str(ROOT/b['audio'])]
        filters.append(f'[{i+1}:a]aresample=48000,adelay={round((b["start"]+.2)*1000)}:all=1[a{i}]')
    filters.append(''.join(f'[a{i}]' for i in range(len(scene['beats'])))+
                   f'amix=inputs={len(scene["beats"])}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,apad[a]')
    final = clips/f'{index:02}.mp4'
    partial = clips/f'{index:02}.part.mp4'
    args += ['-filter_complex', ';'.join(filters), '-map', '0:v', '-map', '[a]',
             '-t', str(scene['duration']), '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
             '-ar', '48000', '-ac', '2', '-movflags', '+faststart', str(partial)]
    run(args)
    partial.replace(final)
    print(final, flush=True)


def assemble(tl):
    listing = ROOT/'clips'/'concat.txt'
    listing.write_text(''.join(f"file '{s['index']:02}.mp4'\n" for s in tl['scenes']))
    chapters = ROOT/'clips'/'chapters.ffmeta'
    chapters.write_text(';FFMETADATA1\n'+''.join(
        f'[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(s["start"]*1000)}\n'
        f'END={round((s["start"]+s["duration"])*1000)}\ntitle={s["index"]}. {s["title"]}\n'
        for s in tl['scenes']))
    final = ROOT/'triton-tiled-matmul.ko.mp4'
    partial = final.with_suffix('.part.mp4')
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0',
         '-i', listing, '-i', chapters, '-map', '0', '-map_metadata', '1', '-map_chapters', '1',
         '-c', 'copy', '-movflags', '+faststart', partial])
    partial.replace(final)
    print(final, flush=True)


def check(tl, selected):
    for scene in selected:
        path = ROOT/'clips'/f'{scene["index"]:02}.mp4'
        data = probe(path)
        video = next(s for s in data['streams'] if s['codec_type'] == 'video')
        audio = next(s for s in data['streams'] if s['codec_type'] == 'audio')
        assert (video['width'], video['height']) == (WIDTH, HEIGHT)
        assert int(video['nb_frames']) == round(scene['duration']*FPS)
        assert video['r_frame_rate'] == '30/1'
        assert abs(float(data['format']['duration'])-scene['duration']) < .15
        assert all(b['audio'] and b['speech_duration']+.2 < b['duration'] for b in scene['beats'])
        assert all(c['start'] < c['end'] <= scene['duration'] for c in scene['cues'])
        run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'null', '-'])
        print(f'PASS {scene["index"]:02}: {scene["duration"]:.2f}s, {video["nb_frames"]} frames, {audio["codec_name"]}', flush=True)
    combined = ROOT/'triton-tiled-matmul.ko.mp4'
    if len(selected) == len(tl['scenes']) and combined.exists():
        duration = float(probe(combined)['format']['duration'])
        assert abs(duration-tl['duration']) < .3
        chapters = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_chapters','-of','json',str(combined)]))
        assert len(chapters['chapters']) == len(tl['scenes'])
        run(['ffmpeg', '-v', 'error', '-i', combined, '-f', 'null', '-'])
        print(f'PASS combined: {duration:.2f}s', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('step', choices=['audio', 'sync', 'preview', 'render', 'assemble', 'check'])
    parser.add_argument('--scene', type=int, choices=list(KEYS))
    parser.add_argument('--jobs', type=int, default=1)
    args = parser.parse_args()
    selected = [s for s in sources() if args.scene is None or s['index'] == args.scene]
    if args.step == 'audio':
        asyncio.run(audio(selected))
    tl = timeline()
    metadata(tl)
    selected = [s for s in tl['scenes'] if args.scene is None or s['index'] == args.scene]
    if args.step == 'preview':
        import visuals
        visuals.preview(selected)
    elif args.step == 'render':
        if args.jobs > 1:
            with ProcessPoolExecutor(max_workers=min(args.jobs,4)) as pool:
                list(pool.map(render, selected))
        else:
            for scene in selected:
                render(scene)
    elif args.step == 'assemble':
        assemble(tl)
    elif args.step == 'check':
        check(tl, selected)


if __name__ == '__main__':
    main()
