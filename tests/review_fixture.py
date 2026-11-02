"""Generate a small reviewer project in a temporary directory, without video assets."""
import json
from pathlib import Path
import struct
import sys
import wave


VISUALS = '''from PIL import Image, ImageDraw

BLUE = '#3366cc'
SIZE = (1920, 1080)

def frame(scene, t):
    image = Image.new('RGB', SIZE, BLUE)
    x = int(t * 60) % 1800
    ImageDraw.Draw(image).rectangle((x, 300, x + 100, 500), fill='white')
    return image
'''


def create_project(root, title='Sample video', size=(1920, 1080)):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root/'project.json').write_text(json.dumps({
        'title': title, 'status': 'review', 'clips': 'clips',
        'timeline': 'timeline.json', 'build': 'build.py',
        'review': {'clear_resolved_notes': True}}))
    scenes = []
    for number in (1, 2):
        scenes.append({
            'index': number, 'title': f'Scene {number}', 'duration': 20,
            'beats_timed': [
                {'id': f'{number}-{cut:02}', 'key': f'cut-{cut}',
                 'start': (cut-1)*10, 'duration': 10,
                 'text': f'Sample narration {number}-{cut}.',
                 'audio': 'audio/01-timed.wav', 'speech_duration': 9}
                for cut in (1, 2)]})
    (root/'timeline.json').write_text(json.dumps({
        'fps': 30, 'width': size[0], 'height': size[1], 'scenes': scenes}))
    (root/'visuals.py').write_text(VISUALS.replace('(1920, 1080)', repr(tuple(size))))
    (root/'audio').mkdir(exist_ok=True)
    # A deterministic silent WAV exercises audio URLs and byte ranges offline.
    with wave.open(str(root/'audio'/'01-timed.wav'), 'wb') as audio:
        audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(struct.pack('<h', 0) * (8000*20))
    return root


if __name__ == '__main__':
    create_project(sys.argv[1])
