"""Manage independent video projects and their scene clips."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
STEPS = ('draft', 'audio', 'sync', 'preview', 'render', 'assemble', 'check')


def project_path(name):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
        raise ValueError('프로젝트 이름은 영문 소문자·숫자·하이픈으로 입력하세요.')
    folder = (ROOT / name).resolve()
    if folder.parent != ROOT:
        raise ValueError('프로젝트는 ai4video 바로 아래에 있어야 합니다.')
    return folder


def read_project(name):
    folder = project_path(name)
    data = json.loads((folder / 'project.json').read_text())
    return folder, data


def save_project(folder, title):
    data = {'title': title, 'status': 'draft', 'language': 'ko',
            'build': 'build.py', 'timeline': 'timeline.json', 'clips': 'clips'}
    (folder / 'project.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def local_path(folder, value):
    path = (folder / value).resolve()
    if not path.is_relative_to(folder):
        raise ValueError('설정 경로는 프로젝트 폴더 안에 있어야 합니다.')
    return path


def main():
    parser = argparse.ArgumentParser(description='영상 프로젝트와 장면 클립 관리')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='등록된 프로젝트 목록')
    for action in ('init', 'register'):
        p = commands.add_parser(action, help='새 폴더 생성' if action == 'init' else '기존 폴더 등록')
        p.add_argument('project')
        p.add_argument('--title', required=True)
    p = commands.add_parser('clips', help='타임라인과 생성된 클립 조회')
    p.add_argument('project')
    p = commands.add_parser('run', help='프로젝트 제작 스크립트 실행')
    p.add_argument('project')
    p.add_argument('step', choices=STEPS)
    p.add_argument('--scene', type=int)
    p.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if args.command == 'list':
        for manifest in sorted(ROOT.glob('*/project.json')):
            folder, data = read_project(manifest.parent.name)
            clips = local_path(folder, data['clips'])
            count = len(list(clips.glob('*.mp4'))) if clips.exists() else 0
            print(f'{folder.name}\t{data["status"]}\t{count} clips\t{data["title"]}')
    elif args.command in ('init', 'register'):
        folder = project_path(args.project)
        if args.command == 'init':
            folder.mkdir()  # Never overwrite an existing project.
        elif not folder.is_dir():
            raise ValueError('등록할 프로젝트 폴더가 없습니다.')
        if (folder / 'project.json').exists():
            raise ValueError('이미 등록된 프로젝트입니다.')
        save_project(folder, args.title)
        if args.command == 'init':
            for name in ('audio', 'clips', 'data', 'preview'):
                (folder / name).mkdir()
            (folder / 'script.ko.md').write_text(f'# {args.title}\n\n## 대본\n\n## 장면 구성\n\n## 참고 자료\n')
            (folder / 'README.md').write_text(f'# {args.title}\n\n대본은 `script.ko.md`, 장면 영상은 `clips/`에서 관리합니다.\n'
                '\n제작 자동화가 필요하면 `build.py`를 추가하고 의존성은 루트에서 `uv add`로 관리하세요.\n')
        print(folder)
    elif args.command == 'clips':
        folder, data = read_project(args.project)
        clips = local_path(folder, data['clips'])
        timeline = local_path(folder, data['timeline'])
        if timeline.exists():
            for scene in json.loads(timeline.read_text())['scenes']:
                clip = clips / f'{scene["index"]:02}.mp4'
                state = 'ready' if clip.is_file() else 'missing'
                print(f'{scene["index"]:02}\t{scene["duration"]:.2f}s\t{state}\t{scene["title"]}')
        else:
            for clip in sorted(clips.glob('*.mp4')):
                print(clip.relative_to(folder))
    else:
        folder, data = read_project(args.project)
        build = local_path(folder, data['build'])
        if not build.is_file():
            raise ValueError('build.py가 없습니다. 프로젝트의 제작 스크립트를 먼저 추가하세요.')
        python = ROOT / '.venv' / 'bin' / 'python'
        if not python.exists():
            raise ValueError('루트 .venv가 없습니다. ai4video 폴더에서 uv sync를 실행하세요.')
        if args.jobs < 1 or (args.scene is not None and args.scene < 0):
            raise ValueError('jobs는 1 이상, scene은 0 이상이어야 합니다.')
        if args.scene is not None and args.step not in ('preview', 'render'):
            raise ValueError('--scene은 preview와 render에서만 사용할 수 있습니다.')
        cmd = [str(python), str(build), args.step]
        if args.step in ('preview', 'render'):
            cmd += ['--jobs', str(args.jobs)]
            if args.scene is not None:
                cmd += ['--scene', str(args.scene)]
        return subprocess.run(cmd, cwd=folder).returncode
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError) as exc:
        print(f'오류: {exc}', file=sys.stderr)
        sys.exit(1)
