"""Shared local cut reviewer for video projects. No FFmpeg in the preview path.

Run from the repository root:
    .venv/bin/python ai4video.py review triton-tiled-matmul
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.abc
import importlib.util
import inspect
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import math
from pathlib import Path
import re
import sys
import threading
import time
import types
from urllib.parse import parse_qs, unquote, urlsplit

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
WEB = ROOT/'review-web'
PROJECT_IMPORT_LOCK = threading.RLock()
STATIC = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
    '/style.css': ('style.css', 'text/css; charset=utf-8'),
}


class FreshProjectLoader(importlib.abc.Loader):
    def __init__(self, path):
        self.path = path

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__file__ = str(self.path)
        exec(compile(self.path.read_text(), str(self.path), 'exec'), module.__dict__)


class ProjectFinder(importlib.abc.MetaPathFinder):
    def __init__(self, root, names):
        self.root, self.names = root, names

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.names:
            source = self.root/f'{fullname}.py'
            return importlib.util.spec_from_loader(fullname, FreshProjectLoader(source), origin=str(source))
        return None


class PreviewRuntime:
    def __init__(self, root, project_slug=None):
        self.root = Path(root).resolve()
        self.project_slug = project_slug or self.root.name
        self.project_modules = {}
        self.lock = threading.RLock()
        self.version = None
        self.source_signature = None
        self.generation = 0
        self.error = None
        self.last_failed_signature = None
        self.scenes = {}
        self.visuals = None
        self.payload = None
        self.cache = OrderedDict()

    @contextmanager
    def imports(self, fresh=False):
        """Keep projects' visuals/facts/lesson modules from leaking into each other."""
        with PROJECT_IMPORT_LOCK:
            names = {p.stem for p in self.root.glob('*.py') if p.stem != 'review' and not p.stem.startswith('test_')}
            previous = {name: sys.modules.get(name) for name in names}
            if fresh:
                self.project_modules.clear()
            for name in names:
                if name in self.project_modules:
                    sys.modules[name] = self.project_modules[name]
                else:
                    sys.modules.pop(name, None)
            finder = ProjectFinder(self.root, names)
            sys.meta_path.insert(0, finder)
            sys.path.insert(0, str(self.root))
            try:
                yield
            finally:
                self.project_modules = {name: sys.modules[name] for name in names if name in sys.modules}
                for name, module in previous.items():
                    if module is None:
                        sys.modules.pop(name, None)
                    else:
                        sys.modules[name] = module
                sys.meta_path.remove(finder)
                sys.path.remove(str(self.root))

    def config(self):
        path = self.root/'project.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def project_path(self, relative):
        path = (self.root/relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Project paths must remain inside the project')
        return path

    def signature(self):
        digest = hashlib.sha256()
        paths = set(self.root.glob('*.py')) | set(self.root.glob('*.md'))
        config = self.config()
        paths |= {self.root/'project.json', self.project_path(config.get('timeline', 'timeline.json'))}
        for path in sorted(paths):
            if not path.exists():
                continue
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        resources = list((self.root/'audio').glob('*')) + list((self.root/'data').rglob('*'))
        resources += list(self.root.glob('facts.json'))
        for path in sorted(resources):
            if path.is_file() and path.suffix in ('.mp3', '.wav', '.json', '.png', '.jpg'):
                stat = path.stat()
                digest.update(f'{path.name}:{stat.st_size}:{stat.st_mtime_ns}'.encode())
        return digest.hexdigest()[:16]

    def load_module(self, name):
        with self.imports():
            return importlib.import_module(name)

    def prepare(self):
        """Adapter hooks are optional; existing timeline.json projects work directly."""
        config = self.config()
        if (self.root/'review_adapter.py').exists():
            adapter = importlib.import_module('review_adapter')
            timeline = adapter.timeline()
        else:
            adapter = None
            timeline = json.loads(self.project_path(config.get('timeline', 'timeline.json')).read_text())
        visuals = importlib.import_module('visuals')
        mode = getattr(adapter, 'FRAME_MODE', None) or config.get('review', {}).get('frame_mode')
        if not mode:
            mode = 'index' if next(iter(inspect.signature(visuals.frame).parameters)) == 'index' else 'scene'
        self.frame_mode = mode
        self.frame_has_captions = getattr(adapter, 'FRAME_HAS_CAPTIONS', mode == 'scene')
        self.timeline_data = timeline
        self.adapter = adapter
        return config, timeline, visuals

    def public_scenes(self, timeline):
        labels = getattr(self.adapter, 'CUT_LABELS', {})
        result = []
        for pos, scene in enumerate(timeline['scenes']):
            raw = scene.get('beats_timed') or scene.get('beats') or []
            if not raw or isinstance(raw[0], str):
                raw = [dict(start=0., duration=scene['duration'], text=' '.join(raw) or scene['title'])]
            cuts = []
            for i, beat in enumerate(raw):
                explicit = bool(beat.get('key'))
                start = float(beat['start']) if explicit or i else 0.
                end = float(raw[i+1]['start']) if i+1 < len(raw) else scene['duration']
                key = beat.get('key', f'{scene.get("key", "scene")}-{i+1:02}')
                label = labels.get(key) or beat['text'].split('.')[0]
                if len(label) > 24:
                    label = label[:24]+'…'
                audio = beat.get('audio')
                audio_offset, audio_duration = -.2, beat.get('speech_duration', beat.get('duration', end-start))
                if not explicit:
                    timed = self.root/'audio'/f'{scene["index"]:02}-timed.wav'
                    mp3 = self.root/'audio'/f'{scene["index"]:02}-{i:02}.mp3'
                    if timed.exists():
                        audio, audio_offset, audio_duration = str(timed.relative_to(self.root)), start, scene['duration']
                    elif mp3.exists():
                        audio, audio_offset = str(mp3.relative_to(self.root)), start-beat['start']
                url = f'/{audio}?project={self.project_slug}' if audio else None
                cuts.append(dict(id=beat.get('id') or f'{pos+1}-{i+1:02}', key=key, label=label,
                                 start=start, duration=end-start, text=beat['text'],
                                 speech_duration=audio_duration, audio_offset=audio_offset,
                                 audio_url=url, audio_stale=beat.get('audio_stale', False)))
            result.append(dict(index=scene['index'], number=pos+1, title=scene['title'],
                               duration=scene['duration'], cuts=cuts))
        return result

    def refresh(self, force=False):
        with self.lock:
            signature = self.signature()
            if not force and signature == self.source_signature and not self.error:
                return
            if not force and signature == self.last_failed_signature:
                raise ValueError(self.error)
            try:
                with self.imports(fresh=True):
                    config, tl, visuals = self.prepare()
                    public_scenes = self.public_scenes(tl)
                scenes = {s['index']: s for s in tl['scenes']}
                version = f'{signature}-{self.generation+1}'
                payload = dict(version=version, fps=tl.get('fps', getattr(visuals, 'FPS', 30)),
                               width=tl.get('width', getattr(visuals, 'W', 1920)),
                               height=tl.get('height', getattr(visuals, 'H', 1080)),
                               title=config.get('title', tl.get('title', self.project_slug)),
                               project=self.project_slug,
                               scenes=public_scenes, cut_count=sum(len(s['cuts']) for s in public_scenes))
            except Exception as exc:
                self.error = f'{type(exc).__name__}: {exc}'
                self.last_failed_signature = signature
                raise ValueError(self.error) from exc
            # Commit a complete good revision; keep the old frame on reload errors.
            self.source_signature = signature
            self.generation += 1
            self.version, self.scenes, self.visuals, self.payload = version, scenes, visuals, payload
            self.error, self.last_failed_signature = None, None
            self.cache.clear()

    def state(self, force=False):
        self.refresh(force)
        with self.lock:
            result = dict(self.payload)
            result['css_version'] = hashlib.sha256((WEB/'style.css').read_bytes()).hexdigest()[:12]
            result['app_version'] = hashlib.sha256((WEB/'index.html').read_bytes()+(WEB/'app.js').read_bytes()).hexdigest()[:12]
            result['notes_version'] = str((self.root/'review-notes.json').stat().st_mtime_ns) if (self.root/'review-notes.json').exists() else '0'
            return result

    def read_notes(self):
        with self.lock:
            path = self.root/'review-notes.json'
            if not path.exists():
                return dict(project=self.project_slug, notes={})
            data = json.loads(path.read_text())
            if not isinstance(data.get('notes'), dict):
                raise ValueError('Invalid review-notes.json')
            return data

    def save_note(self, body):
        self.refresh()
        if not isinstance(body, dict) or not isinstance(body.get('text'), str) or len(body['text']) > 20000:
            raise ValueError('A note must contain text of at most 20000 characters')
        with self.lock:
            found = next(((s,c) for s in self.payload['scenes'] for c in s['cuts'] if c['id'] == body.get('cut_id')), None)
            if not found:
                raise ValueError('Unknown cut')
            scene, cut = found
            scene_time = body.get('scene_time', cut['start'])
            if not isinstance(scene_time, (int,float)) or not math.isfinite(scene_time):
                raise ValueError('Invalid note time')
            scene_time = max(cut['start'], min(scene_time, cut['start']+cut['duration']))
            data = self.read_notes()
            if body.get('import_if_absent') and cut['id'] in data['notes']:
                return data
            now = datetime.now(timezone.utc).isoformat()
            old = data['notes'].get(cut['id'], {})
            if body.get('status') == 'resolved':
                if body.get('expected_revision') != old.get('revision') or body['text'] != old.get('text'):
                    raise ValueError('메모가 변경되었습니다. 최신 메모를 다시 확인해 주세요.')
                if self.config().get('review', {}).get('clear_resolved_notes'):
                    # Keep an empty revision marker so old browser backups cannot
                    # re-import a finished note. Its text and resolution are removed.
                    data['notes'][cut['id']] = dict(cut_id=cut['id'],text='',status='cleared',
                        revision=old['revision']+1,updated_at=now,resolved_at=now)
                else:
                    data['notes'][cut['id']] = dict(old,status='resolved',revision=old['revision']+1,
                        updated_at=now,resolved_at=now,resolution=str(body.get('resolution',''))[:2000])
            else:
                data['notes'][cut['id']] = dict(
                    cut_id=cut['id'], scene_index=scene['index'], scene_number=scene['number'],
                    key=cut['key'], label=cut['label'], text=body['text'],
                    scene_time=round(scene_time, 5), cut_time=round(scene_time-cut['start'], 5),
                    frame=round(scene_time*self.payload['fps']),
                    status='pending' if body['text'].strip() else 'cleared',
                    revision=old.get('revision',0)+1, updated_at=now)
            data.update(schema=1, project=self.project_slug, updated_at=now)
            path = self.root/'review-notes.json'
            temporary = path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
            temporary.replace(path)
            return data

    def overlay_caption(self, image, scene, seconds):
        when = scene.get('start',0)+seconds
        cues = self.timeline_data.get('cues', [])
        caption = next((c[2] for c in cues if c[0] <= when < c[1]), None)
        if not caption:
            return image
        font = ImageFont.truetype('/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf', 32)
        lines, current = [], ''
        for word in caption.split():
            attempt = (current+' '+word).strip()
            if current and font.getlength(attempt) > image.width*.86:
                lines.append(current)
                current = word
            else:
                current = attempt
        lines.append(current)
        overlay = Image.new('RGBA', image.size)
        d = ImageDraw.Draw(overlay)
        for i, line in enumerate(lines[-2:]):
            d.text((image.width/2,image.height-47-(len(lines[-2:])-1-i)*40), line,
                   font=font, fill='white', anchor='mm', stroke_width=3, stroke_fill='#080c14')
        return Image.alpha_composite(image.convert('RGBA'),overlay).convert('RGB')

    def frame(self, scene_id, seconds, width=960, fmt='jpeg', expected_version=None):
        self.refresh()
        with self.lock:
            if expected_version and expected_version != self.version:
                raise RevisionChanged('파일이 변경되었습니다. 새 장면 정보를 불러옵니다.')
            if scene_id not in self.scenes:
                raise ValueError('Unknown scene')
            if width not in (480, 960, 1280, 1920):
                raise ValueError('Width must be 480, 960, 1280, or 1920')
            if fmt not in ('jpeg', 'png') or not math.isfinite(seconds):
                raise ValueError('Invalid frame format or time')
            scene = self.scenes[scene_id]
            fps = self.payload['fps']
            frame_no = max(0, min(round(seconds*fps), round(scene['duration']*fps)-1))
            key = (scene_id, frame_no, width, fmt)
            if key in self.cache:
                data = self.cache.pop(key)
                self.cache[key] = data
                return data, frame_no, True, self.version
            before = time.perf_counter()
            with self.imports():
                argument = scene_id if self.frame_mode == 'index' else scene
                im = self.visuals.frame(argument, frame_no/fps)
            if not self.frame_has_captions:
                im = self.overlay_caption(im, scene, frame_no/fps)
            im = im.convert('RGB')
            if width != im.width:
                im = im.resize((width, round(width*im.height/im.width)), Image.Resampling.BILINEAR)
            output = BytesIO()
            if fmt == 'jpeg':
                im.save(output, 'JPEG', quality=86, subsampling=0)
            else:
                im.save(output, 'PNG', compress_level=3)
            data = output.getvalue()
            self.cache[key] = data
            while len(self.cache) > 120:
                self.cache.popitem(last=False)
            self.last_render_ms = (time.perf_counter()-before)*1000
            return data, frame_no, False, self.version


class RevisionChanged(Exception):
    pass


class ProjectCatalog:
    def __init__(self, root=ROOT, default_project=None, runtime=None):
        self.root, self.default_project = Path(root), default_project
        self.runtimes = {}
        self.lock = threading.RLock()
        if runtime:
            self.runtimes[runtime.project_slug] = runtime
            self.default_project = runtime.project_slug
            self.single = True
        else:
            self.single = False

    def projects(self):
        if self.single:
            runtimes = list(self.runtimes.values())
            return [dict(id=r.project_slug, title=r.config().get('title',r.project_slug),ready=True) for r in runtimes]
        result = []
        for file in sorted(self.root.glob('*/project.json')):
            data = json.loads(file.read_text())
            ready = (file.parent/'visuals.py').exists() and ((file.parent/'review_adapter.py').exists() or (file.parent/data.get('timeline','timeline.json')).exists())
            result.append(dict(id=file.parent.name,title=data.get('title',file.parent.name),ready=ready))
        return result

    def get(self, name=None):
        with self.lock:
            if name is None:
                name = self.default_project or next((p['id'] for p in self.projects() if p['ready']),None)
            if not name or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name):
                raise ValueError('Unknown project')
            available = {p['id']:p for p in self.projects()}
            if name not in available:
                raise ValueError('Unknown project')
            if not available[name]['ready']:
                raise ValueError('이 프로젝트에 visuals.py와 타임라인을 먼저 준비해 주세요.')
            if name not in self.runtimes:
                self.runtimes[name] = PreviewRuntime(self.root/name,name)
            return self.runtimes[name]


def make_handler(projects):
    catalog = ProjectCatalog(runtime=projects) if isinstance(projects,PreviewRuntime) else projects
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, fmt, *args):
            if getattr(self.server, 'verbose', False):
                super().log_message(fmt, *args)

        def send(self, data, mime, status=200, headers=None, head=False):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            for key, value in (headers or {}).items():
                self.send_header(key, str(value))
            self.end_headers()
            if not head:
                self.wfile.write(data)

        def json(self, data, status=200, head=False):
            self.send(json.dumps(data, ensure_ascii=False).encode(), 'application/json; charset=utf-8', status, head=head)

        def audio(self, runtime, path, head=False):
            if not re.fullmatch(r'/audio/(\d{2}-\d{2}\.mp3|\d{2}-timed\.wav)', path):
                self.json(dict(error='Audio file not found'), 404, head)
                return
            target = runtime.root/path.lstrip('/')
            if not target.is_file():
                self.json(dict(error='Audio file not found'), 404, head)
                return
            size = target.stat().st_size
            start, end, status = 0, size-1, 200
            headers = {'Accept-Ranges': 'bytes'}
            request_range = self.headers.get('Range')
            if request_range:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', request_range)
                if not match or not any(match.groups()):
                    self.send(b'', 'audio/mpeg', 416, {'Content-Range': f'bytes */{size}'}, head)
                    return
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                else:
                    start = max(0, size-int(last))
                if start >= size or end < start:
                    self.send(b'', 'audio/mpeg', 416, {'Content-Range': f'bytes */{size}'}, head)
                    return
                status = 206
                headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            with target.open('rb') as audio_file:
                audio_file.seek(start)
                data = audio_file.read(end-start+1)
            self.send(data, 'audio/wav' if path.endswith('.wav') else 'audio/mpeg', status, headers, head)

        def do_HEAD(self):
            self.handle_request(head=True)

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            parsed=urlsplit(self.path)
            if parsed.path != '/api/notes':
                self.json(dict(error='Not found'),404)
                return
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                self.json(dict(error='Origin not allowed'),403)
                return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if self.headers.get('Content-Type','').split(';')[0] != 'application/json' or not 0 < length <= 100000:
                    raise ValueError('Expected a JSON note')
                query=parse_qs(parsed.query)
                runtime=catalog.get(query.get('project',[None])[0])
                body=json.loads(self.rfile.read(length))
                self.json(runtime.save_note(body))
            except (ValueError,KeyError) as exc:
                self.json(dict(error=str(exc)),400)

        def handle_request(self, head=False):
            try:
                parsed = urlsplit(self.path)
                path, query = unquote(parsed.path), parse_qs(parsed.query)
                if path in STATIC:
                    file, mime = STATIC[path]
                    self.send((WEB/file).read_bytes(), mime, head=head)
                elif path in ('/font/regular.ttf', '/font/bold.ttf'):
                    name = 'UnDotumBold.ttf' if path.endswith('/bold.ttf') else 'UnDotum.ttf'
                    self.send((Path('/usr/share/fonts/truetype/unfonts-core')/name).read_bytes(), 'font/ttf', head=head)
                elif path == '/favicon.ico':
                    self.send(b'', 'image/x-icon', 204, head=head)
                elif path == '/api/projects':
                    self.json(dict(projects=catalog.projects(), default=catalog.get().project_slug),head=head)
                elif path == '/api/state':
                    try:
                        runtime=catalog.get(query.get('project',[None])[0])
                        self.json(runtime.state(force=query.get('force') == ['1']), head=head)
                    except Exception as exc:
                        self.json(dict(error=str(exc), recoverable=True), 503, head)
                elif path == '/api/frame':
                    runtime=catalog.get(query.get('project',[None])[0])
                    data, number, cached, version = runtime.frame(
                        int(query.get('scene', ['1'])[0]), float(query.get('t', ['0'])[0]),
                        int(query.get('width', ['960'])[0]), query.get('format', ['jpeg'])[0],
                        query.get('version', [None])[0])
                    fmt = query.get('format', ['jpeg'])[0]
                    self.send(data, 'image/'+fmt, headers={
                        'X-Frame': number, 'X-Revision': version,
                        'X-Frame-Cache': 'hit' if cached else 'miss'}, head=head)
                elif path == '/api/notes':
                    self.json(catalog.get(query.get('project',[None])[0]).read_notes(),head=head)
                elif path.startswith('/audio/'):
                    self.audio(catalog.get(query.get('project',[None])[0]),path,head)
                else:
                    self.json(dict(error='Not found'), 404, head)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except RevisionChanged as exc:
                self.json(dict(error=str(exc), changed=True), 409, head)
            except (ValueError, KeyError) as exc:
                self.json(dict(error=str(exc)), 400, head)
            except Exception as exc:
                self.json(dict(error=f'{type(exc).__name__}: {exc}'), 500, head)

    return Handler


def main(default_project=None):
    parser = argparse.ArgumentParser(description='영상 프로젝트 컷 미리보기 — MP4 렌더링 없이 확인')
    parser.add_argument('--project', default=default_project)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    projects = ProjectCatalog(default_project=args.project)
    runtime = projects.get()
    runtime.refresh()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(projects))
    server.daemon_threads = True
    server.verbose = args.verbose
    port = server.server_address[1]
    print(f'컷 미리보기: http://{args.host}:{port}/?project={runtime.project_slug}', flush=True)
    print('그림·대본 파일을 저장하면 자동으로 반영됩니다. 종료: Ctrl+C', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
