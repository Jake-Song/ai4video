"""Project-local ElevenLabs narration; credentials come only from the environment."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
API_BASE = 'https://api.elevenlabs.io/v1'
DEFAULT_VOICE = '7Nah3cbXKVmGX7gQUuwz'


def config():
    settings = json.loads((ROOT/'project.json').read_text()).get('narration', {})
    return dict(provider='elevenlabs', voice_id=settings.get('voice_id', DEFAULT_VOICE),
                model_id=settings.get('model_id', 'eleven_multilingual_v2'),
                output_format='mp3_44100_128',
                voice_settings=dict(stability=.65, similarity_boost=.75, style=0.,
                                    use_speaker_boost=True, speed=1.0))


def spoken_text(body):
    aliases = [('tl.load', '티엘 로드'), ('tl.dot', '티엘 닷'), ('tl.store', '티엘 스토어'),
               ('FP32', '에프피 삼십이'), ('CUDA', '쿠다'), ('Tensor Core', '텐서 코어'),
               ('acc', '누산기'), ('stride', '스트라이드'), ('a', '에이'), ('b', '비'),
               ('Shared memory', '공유 메모리'), ('HBM', '에이치 비 엠'),
               ('GPU', '지피유'), ('Triton', '트리톤'), ('BM', '비 엠'),
               ('BN', '비 엔'), ('BK', '비 케이'), ('M', '엠'), ('N', '엔'),
               ('K', '케이'), ('A', '에이'), ('B', '비'), ('C', '씨')]
    for original, spoken in aliases:
        body = re.sub(r'(?<![A-Za-z])'+re.escape(original)+r'(?![A-Za-z])', spoken, body)
    return body


def signature(body):
    payload = dict(config(), text=body, spoken_text=spoken_text(body))
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def request(path, payload=None, timeout=45):
    key = os.environ.get('ELEVENLABS_API_KEY')
    if not key:
        raise RuntimeError('Set ELEVENLABS_API_KEY before generating narration')
    req = Request(API_BASE+path,
                  data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
                  headers={'xi-api-key': key, 'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.load(response), response.headers.get('request-id')
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get('detail', {})
            message = detail.get('message', str(detail)) if isinstance(detail, dict) else str(detail)
        except (ValueError, AttributeError):
            message = exc.reason
        safe = str(message).replace(key, '[redacted]')[:350]
        raise RuntimeError(f'ElevenLabs HTTP {exc.code}: {safe}') from None
    except (URLError, TimeoutError) as exc:
        safe = str(getattr(exc, 'reason', exc)).replace(key, '[redacted]')[:250]
        raise RuntimeError(f'ElevenLabs connection failed: {safe}') from None


def synthesize(body):
    cfg = config()
    voice = cfg['voice_id']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', voice):
        raise ValueError('Invalid ElevenLabs voice ID')
    response, request_id = request(
        f'/text-to-speech/{voice}/with-timestamps?output_format={cfg["output_format"]}',
        dict(text=spoken_text(body), model_id=cfg['model_id'],
             voice_settings=cfg['voice_settings'], seed=42))
    audio = base64.b64decode(response['audio_base64'], validate=True)
    if len(audio) < 100:
        raise RuntimeError('ElevenLabs returned empty audio')
    metadata = dict(cfg, signature=signature(body), text=body, spoken_text=spoken_text(body),
                    request_id=request_id, alignment=response.get('alignment'),
                    normalized_alignment=response.get('normalized_alignment'))
    return audio, metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check-voice'])
    parser.parse_args()
    voice, _ = request('/voices/'+config()['voice_id'], timeout=12)
    print(json.dumps({k: voice.get(k) for k in ('voice_id', 'name', 'category', 'labels')},
                     ensure_ascii=False, indent=2))
