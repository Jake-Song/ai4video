"""Reproducible video production: audio, sync, preview, render, assemble, check."""
import argparse
import asyncio
import hashlib
import html
import json
import math
from pathlib import Path
import re
import subprocess
import wave

from lesson import SCENES, SOURCES, TITLE
import facts

ROOT = Path(__file__).resolve().parent
VOICE = 'ko-KR-SunHiNeural'
FPS, RATE = 30, 48000
FINAL = ROOT/'periodic-table.ko.mp4'
PREVIEW = ROOT/'periodic-table-preview.ko.mp4'


def timing_budget():
    budget=json.loads((ROOT/'timing-budget.json').read_text())
    assert budget['fps']==FPS and budget['voice']==VOICE
    assert list(budget['scene_frames'])==[s['key'] for s in SCENES]
    assert all(isinstance(n,int) and n>0 for n in budget['scene_frames'].values())
    assert sum(budget['scene_frames'].values())==budget['total_frames']
    assert abs(budget['total_frames']/FPS-budget['duration'])<1e-8
    assert 1<=budget['tempo']<=1.1
    return budget


def write_script(scenes, duration, path):
    script=[f'# {TITLE}', f'한국어 {VOICE} · {duration/60:.2f}분 · 1920×1080 / 30fps']
    if path.name=='script-draft.ko.md':
        script.append('영상 제작 전 내레이션 원고 · [참고 영상과 반영 범위](./reference-notes.ko.md)')
    for s in scenes:
        script.append(f'## {stamp(s["start"])[:-4]} · {s["title"]}\n\n'+'\n\n'.join(s['beats']))
        if s['note']: script.append('제작 주석: '+s['note'])
    script.append('## 참고 자료\n\n'+'\n'.join(f'- [{n}]({u})' for n,u in SOURCES))
    path.write_text('\n\n'.join(script)+'\n')


def draft():
    """Write the complete script before any voice generation or rendering."""
    budget=timing_budget();cursor=0;scenes=[]
    for s in SCENES:
        scenes.append(dict(s,start=cursor/FPS))
        cursor+=budget['scene_frames'][s['key']]
    write_script(scenes,cursor/FPS,ROOT/'script-draft.ko.md')
    print(ROOT/'script-draft.ko.md')


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams',
                                              '-show_chapters','-of','json',str(path)]))


def digest(body):
    return hashlib.sha256((VOICE+'|WordBoundary|+0%|'+body).encode()).hexdigest()


async def audio():
    import edge_tts
    folder = ROOT/'audio'
    folder.mkdir(exist_ok=True)
    limit = asyncio.Semaphore(3)

    async def take(i, j, body):
        path = folder/f'{i:02}-{j:02}.mp3'
        meta = path.with_suffix('.json')
        if path.exists() and meta.exists() and json.loads(meta.read_text()).get('digest') == digest(body):
            return
        async with limit:
            for attempt in range(4):
                try:
                    boundaries = []
                    stream = edge_tts.Communicate(body, voice=VOICE, boundary='WordBoundary')
                    with path.with_suffix('.part').open('wb') as f:
                        async for chunk in stream.stream():
                            if chunk['type'] == 'audio':
                                f.write(chunk['data'])
                            elif chunk['type'] == 'WordBoundary':
                                boundaries.append({k:chunk[k] for k in ('offset','duration','text')})
                    if not boundaries:
                        raise RuntimeError('No word boundaries returned')
                    path.with_suffix('.part').replace(path)
                    save(meta, dict(digest=digest(body), voice=VOICE, text=body, boundaries=boundaries))
                    print(f'Voice {i+1:02}/{len(SCENES)} beat {j+1}: {probe(path)["format"]["duration"]}s',flush=True)
                    return
                except Exception as e:
                    print(f'Voice retry {i}:{j} {attempt+1}: {type(e).__name__}: {e}',flush=True)
                    if attempt == 3:
                        raise
                    await asyncio.sleep(2*(attempt+1))
    await asyncio.gather(*(take(i,j,body) for i,s in enumerate(SCENES) for j,body in enumerate(s['beats'])))
    sync()


def stamp(t, ass=False):
    if ass:
        cs = round(t*100)
        return f'{cs//360000}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}'
    ms=round(t*1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def pcm(path, tempo):
    return subprocess.check_output(['ffmpeg','-hide_banner','-loglevel','error','-i',str(path),
        '-af',f'atempo={tempo},aresample={RATE}', '-ar',str(RATE),'-ac','1','-f','s16le','-'])


def write_wav(path, data):
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(RATE); f.writeframes(data)


def caption_words(body, boundaries):
    """Use provider timestamps but preserve source text when boundary text is truncated.

    Edge can return e.g. '여덟. 익' followed by '숫자', omitting '숙한' from its
    boundary metadata. Span ends come from the next source anchor, never the
    provider's truncated text length. Unalignable tokens stop production.
    """
    positions=[];cursor=0
    for w in boundaries:
        token=html.unescape(w['text'])
        pos=body.find(token,cursor)
        if pos<0:
            raise ValueError(f'Cannot align speech boundary {token!r} in {body!r}')
        positions.append(pos);cursor=pos+len(token)
    positions[0]=0
    positions.append(len(body))
    return [body[positions[j]:positions[j+1]].strip() for j in range(len(boundaries))]


def sync():
    budget=timing_budget()
    original=[]
    for i,s in enumerate(SCENES):
        lengths=[]
        for j,body in enumerate(s['beats']):
            path=ROOT/'audio'/f'{i:02}-{j:02}.mp3'
            meta=json.loads(path.with_suffix('.json').read_text())
            if meta['digest'] != digest(body):
                raise RuntimeError(f'Stale voice take {i}:{j}; run audio')
            lengths.append(float(probe(path)['format']['duration']))
        original.append(lengths)
    spoken=sum(map(sum,original))
    tempo=budget['tempo']
    timeline=[]; cues=[]; full=bytearray(); frame_cursor=0;timed_audio=[]
    def silence(seconds): return b'\0\0'*round(seconds*RATE)
    for i,s in enumerate(SCENES):
        data=bytearray(silence(.45)); beats=[]
        start=frame_cursor/FPS
        for j,body in enumerate(s['beats']):
            path=ROOT/'audio'/f'{i:02}-{j:02}.mp3'
            meta=json.loads(path.with_suffix('.json').read_text())
            captions=caption_words(body,meta['boundaries'])
            offset=len(data)/2/RATE
            raw=pcm(path,tempo)
            seconds=len(raw)/2/RATE
            data.extend(raw)
            beats.append(dict(text=body,start=offset,duration=seconds,source_duration=original[i][j],
                              word_times=[dict(text=txt,
                                               start=offset+w['offset']/1e7/tempo,
                                               end=offset+(w['offset']+w['duration'])/1e7/tempo)
                                          for w,txt in zip(meta['boundaries'],captions,strict=True)]))
            words=[]; begin=None
            for k,(w,txt) in enumerate(zip(meta['boundaries'],captions,strict=True)):
                a=start+offset+w['offset']/1e7/tempo
                b=min(start+offset+seconds,start+offset+(w['offset']+w['duration'])/1e7/tempo)
                if begin is None: begin=a
                words.append(txt)
                if len(' '.join(words))>=29 or txt.endswith(('.', '?', '!')) or k==len(meta['boundaries'])-1:
                    cues.append([begin,max(begin+.12,b+.12),' '.join(words)])
                    words=[]; begin=None
            gap=float(s['pause_after'].get(j,.32)) if j<len(s['beats'])-1 else .8
            data.extend(silence(gap))
        frames=budget['scene_frames'][s['key']]
        available_samples=frames*(RATE//FPS)
        samples=len(data)//2
        if samples>available_samples:
            raise RuntimeError(f'Scene {i:02} {s["key"]} exceeds its {frames/FPS:.3f}s budget '
                               f'by {(samples-available_samples)/RATE:.3f}s. Shorten narration; '
                               'the original tempo and scene boundaries are locked.')
        # Preserve each scene boundary; no speech is cut and no extra speedup is used.
        data.extend(b'\0\0'*(available_samples-samples))
        timed_audio.append((ROOT/'audio'/f'{i:02}-timed.wav',data))
        timeline.append(dict(s,index=i,start=start,duration=frames/FPS,frames=frames,
                             beats_timed=beats,tempo=tempo))
        frame_cursor+=frames; full.extend(data)
    duration=frame_cursor/FPS
    if frame_cursor!=budget['total_frames'] or abs(duration-budget['duration'])>1e-8:
        raise RuntimeError(f'Unexpected final duration: {duration:.2f}s')
    for k,c in enumerate(cues):
        c[1]=min(c[1],cues[k+1][0]-.01 if k+1<len(cues) else duration)
        if not c[0]<c[1]: raise RuntimeError(f'Invalid cue {c}')
    # Do not replace any synced outputs until every scene passes the duration check.
    facts.export()
    for path,data in timed_audio: write_wav(path,data)
    write_wav(ROOT/'audio'/'narration.wav',full)
    save(ROOT/'timeline.json',dict(title=TITLE,duration=duration,frames=frame_cursor,fps=FPS,
                                  voice=VOICE,scenes=timeline,cues=cues))
    (ROOT/'periodic-table.ko.srt').write_text('\n\n'.join(f'{i+1}\n{stamp(a)} --> {stamp(b)}\n{txt}'
                                             for i,(a,b,txt) in enumerate(cues))+'\n')
    header='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,UnDotum,40,&H00F4F2EA,&H00F4F2EA,&H00120C08,&H00120C08,0,0,0,0,100,100,0,0,1,2,0,2,100,100,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    (ROOT/'periodic-table.ko.ass').write_text(header+'\n'.join(
        f'Dialogue: 0,{stamp(a,True)},{stamp(b,True)},Default,,0,0,0,,{txt}' for a,b,txt in cues)+'\n')
    chapters=[]
    for s in timeline:
        if not chapters or chapters[-1]['title'] != s['chapter']:
            chapters.append(dict(title=s['chapter'],start=s['start']))
    write_script(timeline,duration,ROOT/'script.ko.md')
    write_script(timeline,duration,ROOT/'script-draft.ko.md')
    lines=[';FFMETADATA1','title='+TITLE,'language=kor']
    for i,ch in enumerate(chapters):
        end=chapters[i+1]['start'] if i+1<len(chapters) else duration
        lines.extend(['[CHAPTER]','TIMEBASE=1/1000',f'START={round(ch["start"]*1000)}',
                      f'END={round(end*1000)}','title='+ch['title']])
    (ROOT/'chapters.ffmetadata').write_text('\n'.join(lines)+'\n')
    print(f'Synced {len(timeline)} scenes; speech={spoken:.2f}s; tempo={tempo:.4f}; final={duration:.2f}s',flush=True)


def assemble():
    import visuals
    tl=json.loads((ROOT/'timeline.json').read_text())
    for s in tl['scenes']:
        meta=json.loads((ROOT/'clips'/f'{s["index"]:02}.json').read_text())
        assert meta['signature']==visuals.signature(s['index'])
    listing=ROOT/'clips'/'concat.txt'
    listing.write_text('\n'.join(f"file '{s['index']:02}.mp4'" for s in tl['scenes']))
    part=FINAL.with_suffix('.part.mp4')
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',listing,
         '-i',ROOT/'audio'/'narration.wav','-i',ROOT/'chapters.ffmetadata',
         '-map','0:v','-map','1:a','-map_metadata','2','-map_chapters','2',
         '-vf',f"ass='{ROOT/'periodic-table.ko.ass'}'",
         '-af','loudnorm=I=-16:TP=-1.5:LRA=11','-c:v','libx264','-threads','6',
         '-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
         '-ar',RATE,'-metadata:s:a:0','language=kor','-t',tl['duration'],'-movflags','+faststart',part])
    part.replace(FINAL)
    make_highlight()
    print(f'Assembled {FINAL}',flush=True)


def make_highlight():
    """60 seconds of complete narration: periods, groups, and valence electrons."""
    tl=json.loads((ROOT/'timeline.json').read_text())
    ranges=[];used_frames=0
    for key in ('fold','families','outer'):
        s=next(s for s in tl['scenes'] if s['key']==key)
        first,last=s['beats_timed'][0],s['beats_timed'][-1]
        a=math.floor((s['start']+first['start']-.15)*FPS)
        b=math.ceil((s['start']+last['start']+last['duration']+.3)*FPS)
        assert s['start']<=a/FPS<b/FPS<=s['start']+s['duration']
        ranges.append((a/FPS,(b-a)/FPS));used_frames+=b-a
    if not 0<used_frames<=60*FPS:
        raise RuntimeError('Highlight narration does not fit in 60 seconds; choose complete beats.')
    padding=(60*FPS-used_frames)/FPS
    args=['ffmpeg','-hide_banner','-loglevel','error','-y']
    for start,length in ranges: args+=['-ss',start,'-t',length,'-i',FINAL]
    parts=[]
    for i in range(3):
        parts.append(f'[{i}:v]setpts=PTS-STARTPTS[v{i}];[{i}:a]asetpts=PTS-STARTPTS[a{i}]')
    graph=(';'.join(parts)+';'+''.join(f'[v{i}][a{i}]' for i in range(3))+
           'concat=n=3:v=1:a=1[joinedv][joineda];'
           f'[joinedv]tpad=stop_mode=clone:stop_duration={padding}[v];'
           f'[joineda]apad=pad_dur={padding}[a]')
    part=PREVIEW.with_suffix('.part.mp4')
    args+=['-filter_complex',graph,'-map','[v]','-map','[a]','-map_chapters','-1',
           '-t','60','-r',FPS,'-c:v','libx264','-threads','4','-preset','fast','-crf','18',
           '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar',RATE,'-movflags','+faststart',part]
    run(args);part.replace(PREVIEW)
    print(f'Highlight ready: {PREVIEW}',flush=True)


def check():
    import visuals
    budget=timing_budget()
    result=facts.verify()
    tl=json.loads((ROOT/'timeline.json').read_text())
    assert len(tl['scenes'])==len(SCENES)==32
    cursor=0
    for original,s in zip(SCENES,tl['scenes'],strict=True):
        assert s['key']==original['key'] and s['beats']==original['beats']
        assert abs(s['start']-cursor/FPS)<1e-8
        assert s['frames']==budget['scene_frames'][s['key']]
        assert s['tempo']==budget['tempo']
        for j,b in enumerate(s['beats_timed']):
            meta=json.loads((ROOT/'audio'/f'{s["index"]:02}-{j:02}.json').read_text())
            assert meta['digest']==digest(b['text']) and meta['voice']==VOICE and meta['boundaries']
            assert b['start']+b['duration']<s['duration']
        clip=json.loads((ROOT/'clips'/f'{s["index"]:02}.json').read_text())
        assert clip['signature']==visuals.signature(s['index']) and clip['frames']==s['frames']
        cursor+=s['frames']
    assert cursor==tl['frames']==budget['total_frames']
    assert abs(tl['duration']-budget['duration'])<1e-8
    with wave.open(str(ROOT/'audio'/'narration.wav')) as w:
        assert w.getnframes()==cursor*(RATE//FPS) and w.getframerate()==RATE
    prev=0
    for a,b,txt in tl['cues']:
        assert prev<=a<b<=tl['duration'] and txt.strip()
        prev=b
    normalized=lambda value: re.sub(r'\s+','',value)
    assert normalized(' '.join(b for s in SCENES for b in s['beats']))==normalized(' '.join(c[2] for c in tl['cues']))
    data=probe(FINAL)
    v=next(x for x in data['streams'] if x['codec_type']=='video')
    assert (v['width'],v['height'],v['r_frame_rate'],int(v['nb_frames']))==(1920,1080,'30/1',cursor)
    assert v['codec_name']=='h264'
    a=next(x for x in data['streams'] if x['codec_type']=='audio')
    assert a['codec_name']=='aac' and a['sample_rate']=='48000'
    assert abs(float(a['duration'])-tl['duration'])<.05
    assert abs(float(data['format']['duration'])-tl['duration'])<.1
    assert len(data['chapters'])==8
    expected=[s for i,s in enumerate(tl['scenes']) if i==0 or s['chapter']!=tl['scenes'][i-1]['chapter']]
    for chapter,s in zip(data['chapters'],expected,strict=True):
        assert abs(float(chapter['start_time'])-s['start'])<.002
        assert chapter['tags']['title']==s['chapter']
    preview=probe(PREVIEW)
    pv=next(x for x in preview['streams'] if x['codec_type']=='video')
    assert abs(float(preview['format']['duration'])-60)<.1
    assert (pv['width'],pv['height'],int(pv['nb_frames']))==(1920,1080,1800)
    run(['ffmpeg','-hide_banner','-loglevel','error','-xerror','-i',FINAL,'-f','null','-'])
    run(['ffmpeg','-hide_banner','-loglevel','error','-xerror','-i',PREVIEW,'-f','null','-'])
    result.update(duration=tl['duration'],frames=cursor,resolution=[1920,1080],fps=30,
                  voice=VOICE,tempo=tl['scenes'][0]['tempo'],scenes=len(SCENES),chapters=8,
                  subtitle_cues=len(tl['cues']),full_decode='passed',preview_full_decode='passed',
                  subtitle_source_match='passed',
                  original_duration_preserved='passed',scene_budgets_preserved='passed',
                  sha256=hashlib.sha256(FINAL.read_bytes()).hexdigest(),
                  preview_sha256=hashlib.sha256(PREVIEW.read_bytes()).hexdigest(),
                  preview_duration=float(preview['format']['duration']))
    save(ROOT/'validation.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['draft','audio','sync','preview','render','assemble','check'])
    p.add_argument('--scene',type=int)
    p.add_argument('--jobs',type=int,default=4)
    args=p.parse_args()
    if args.command=='audio': asyncio.run(audio())
    elif args.command in ('preview','render'):
        import visuals
        getattr(visuals,args.command)(args.scene,args.jobs)
    else: globals()[args.command]()
