"""Original matrix-grid animation inspired by the user's diagram references.

The pictures show logical matrices/tiles, not CUDA thread or memory layouts.
"""
from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
W, H = 1920, 1080
BG, INK, MUTED, GRID = '#0e1420', '#e9eff8', '#a0aec0', '#3a485d'
BLUE, TEAL, PURPLE, ORANGE, RED = '#7cb7ff', '#5ed1b5', '#c2a0f5', '#f1bb71', '#ef8f91'
CELL = 36
# A: M×K, B: K×N, C: M×N. Shapes agree with M=N=9, K=12.
MATRICES = {'A': (150, 590, 9, 12), 'B': (790, 104, 12, 9), 'C': (790, 590, 9, 9)}
# Only cut 1-02 uses extra room between B and C; A stays aligned with C.
MEMORY_MATRICES = {'A': (150, 626, 9, 12), 'B': (790, 86, 12, 9), 'C': (790, 626, 9, 9)}
R0, C0, BM, BN, BK = 3, 3, 3, 3, 4
TEXT_AUDIT = None
INTRO_REUSE_KEYS = ('hbm_row_repeat', 'hbm_column_repeat', 'hbm_reuse')


def clamp(p):
    return max(0., min(1., p))


def ease(p):
    p = clamp(p)
    return p*p*(3-2*p)


def rgb(c):
    return tuple(int(c[i:i+2], 16) for i in (1, 3, 5))


def mix(a, b, p):
    return tuple(round(x+(y-x)*clamp(p)) for x, y in zip(rgb(a), rgb(b)))


@lru_cache(128)
def font(size, bold=False, latin=False):
    if latin:
        path = '/usr/share/fonts/truetype/dejavu/DejaVuSans'+('-Bold' if bold else '')+'.ttf'
    else:
        path = '/usr/share/fonts/truetype/unfonts-core/UnDotum'+('Bold' if bold else '')+'.ttf'
    return ImageFont.truetype(path, int(size))


@lru_cache(2048)
def label(body, size, color, bold):
    f = font(size, bold, all(ord(c) < 128 for c in body))
    box = f.getbbox(body)
    tile = Image.new('RGBA', (box[2]-box[0]+6, box[3]-box[1]+6))
    ImageDraw.Draw(tile).text((3-box[0], 3-box[1]), body, font=f, fill=color)
    return tile


def text(im, body, x, y, size=30, color=INK, bold=False, anchor='left', alpha=1, maxw=None):
    if alpha <= 0:
        return
    tile = label(str(body), int(size), color, bold)
    if maxw and tile.width > maxw:
        raise ValueError(f'Text exceeds its area ({tile.width}>{maxw}): {body}')
    if alpha < 1:
        tile = tile.copy()
        tile.putalpha(tile.getchannel('A').point(lambda a: round(a*clamp(alpha))))
    left = x-(tile.width/2 if anchor == 'center' else tile.width if anchor == 'right' else 0)
    top = y-tile.height/2
    if TEXT_AUDIT is not None:
        TEXT_AUDIT.append((str(body), (left, top, left+tile.width, top+tile.height)))
    im.paste(tile, (round(left), round(top)), tile)


def line(im, a, b, color=INK, width=2, alpha=1):
    ImageDraw.Draw(im).line([a, b], fill=mix(BG, color, alpha), width=width)


def dashed(im, a, b, color=GRID, width=2, dash=5, gap=7):
    distance = math.dist(a, b)
    for offset in range(0, math.ceil(distance), dash+gap):
        p, q = offset/max(1, distance), min(distance, offset+dash)/max(1, distance)
        line(im, (a[0]+(b[0]-a[0])*p, a[1]+(b[1]-a[1])*p),
             (a[0]+(b[0]-a[0])*q, a[1]+(b[1]-a[1])*q), color, width)


def arrow(im, a, b, color=INK, width=3, tip=11):
    line(im, a, b, color, width)
    angle = math.atan2(b[1]-a[1], b[0]-a[0])
    points = [b, (b[0]-tip*math.cos(angle-.43), b[1]-tip*math.sin(angle-.43)),
              (b[0]-tip*math.cos(angle+.43), b[1]-tip*math.sin(angle+.43))]
    ImageDraw.Draw(im).polygon(points, fill=color)


def curve(im, a, b, color=MUTED, amount=45, arrowhead=True, width=2):
    points = []
    for n in range(65):
        p = n/64
        points.append((a[0]+(b[0]-a[0])*p, a[1]+(b[1]-a[1])*p-amount*math.sin(math.pi*p)))
    ImageDraw.Draw(im).line(points, fill=color, width=width)
    if arrowhead:
        arrow(im, points[-3], b, color, width, 10)


@lru_cache(128)
def hatch_asset(w, h, color):
    # Supersample the hatch asset so the diagonal strokes remain smooth.
    tile = Image.new('RGBA', (w*2, h*2), (*rgb(color), 20))
    d = ImageDraw.Draw(tile)
    for x in range(-h*2, w*2+h*2, 16):
        d.line((x, h*2, x+h*2, 0), fill=(*rgb(color), 125), width=2)
    return tile.resize((w, h), Image.Resampling.LANCZOS)


def highlight(im, box, color, alpha=1, hatch=True, width=3):
    x0, y0, x1, y1 = [round(v) for v in box]
    if alpha <= 0 or x1 <= x0 or y1 <= y0:
        return
    if hatch:
        tile = hatch_asset(x1-x0, y1-y0, color)
        if alpha < 1:
            tile = tile.copy()
            tile.putalpha(tile.getchannel('A').point(lambda p: round(p*alpha)))
        im.paste(tile, (x0, y0), tile)
    else:
        layer = Image.new('RGBA', (x1-x0, y1-y0), (*rgb(color), round(45*alpha)))
        im.paste(layer, (x0, y0), layer)
    ImageDraw.Draw(im).rectangle((x0, y0, x1, y1), outline=mix(BG, color, alpha), width=width)


def region(name, r=0, c=0, rows=1, cols=1, *, matrices=MATRICES):
    x, y, _, _ = matrices[name]
    return (x+c*CELL, y+r*CELL, x+(c+cols)*CELL, y+(r+rows)*CELL)


def grid(im, name, *, matrices=MATRICES):
    x, y, rows, cols = matrices[name]
    for j in range(1, cols):
        dashed(im, (x+j*CELL, y), (x+j*CELL, y+rows*CELL), dash=2, gap=6, width=1)
    for i in range(1, rows):
        dashed(im, (x, y+i*CELL), (x+cols*CELL, y+i*CELL), dash=2, gap=6, width=1)
    ImageDraw.Draw(im).rectangle((x, y, x+cols*CELL, y+rows*CELL), outline=INK, width=2)


@lru_cache(4)
def base(scene_id, memory=False):
    im = Image.new('RGB', (W, H), BG)
    text(im, f'{scene_id:02}', 70, 55, 26, PURPLE, True)
    title = '타일링은 왜 필요할까?' if scene_id == 1 else '타일의 크기를 정하는 세 숫자'
    text(im, title, 124, 55, 38, INK, True, maxw=630)
    matrices = MEMORY_MATRICES if memory else MATRICES
    for name in matrices:
        grid(im, name, matrices=matrices)
    for name, y in [('A', 551), ('B', 66), ('C', 551)]:
        x = MATRICES[name][0]
        y += matrices[name][1]-MATRICES[name][1]
        text(im, name, x, y, 32, INK, True)
    # Keep the equation separate from the L-shaped spatial alignment diagram.
    equation(im,150,218)
    text(im, '행과 열이 만나는 위치가 출력입니다.', 150, 300, 25, MUTED, maxw=550)
    # B is above C; the equality and alignment are shown with light guides.
    line(im, (1210, 188), (1210, 869), GRID, 1)
    line(im, (70, 967), (1850, 967), GRID, 1)
    text(im, 'TRITON · TILED MATMUL', 1850, 55, 18, MUTED, anchor='right')
    return im


def equation(im,x,y,size=38):
    for body,color in [('A(M × K)',BLUE),(' × ',INK),('B(K × N)',TEAL),(' = ',INK),('C(M × N)',PURPLE)]:
        text(im,body,x,y,size,color,True)
        x += label(body,size,color,True).width


def note(im, title, *lines, color=INK, y=280):
    titles = title.split('\n')
    for i, body in enumerate(titles):
        text(im, body, 1280, y+i*44, 35, color, True, maxw=550)
    for i, body in enumerate(lines):
        text(im, body, 1280, y+62+(len(titles)-1)*44+i*43, 28, MUTED, maxw=550)


def hdim(im, x0, x1, y, body, color, below=False):
    line(im, (x0, y-7), (x0, y+7), color, 2)
    line(im, (x1, y-7), (x1, y+7), color, 2)
    line(im, (x0, y), (x1, y), color, 2)
    text(im, body, (x0+x1)/2, y+(23 if below else -23), 25, color, True, 'center')


def vdim(im, x, y0, y1, body, color, left=True):
    line(im, (x-7, y0), (x+7, y0), color, 2)
    line(im, (x-7, y1), (x+7, y1), color, 2)
    line(im, (x, y0), (x, y1), color, 2)
    text(im, body, x+(-15 if left else 15), (y0+y1)/2, 25, color, True,
         'right' if left else 'left')


def input_tiles(im, k=0, a=1, b=1, c=.6):
    highlight(im, region('A', R0, k, BM, BK), BLUE, a)
    highlight(im, region('B', k, C0, BK, BN), TEAL, b)
    if c:
        highlight(im, region('C', R0, C0, BM, BN), PURPLE, c)


def projections(im, rows=True, cols=True):
    a, b, c = MATRICES['A'], MATRICES['B'], MATRICES['C']
    if rows:
        for r in (R0, R0+BM):
            dashed(im, (a[0]+a[3]*CELL+7, a[1]+r*CELL), (c[0]-7, c[1]+r*CELL), BLUE)
    if cols:
        for col in (C0, C0+BN):
            dashed(im, (b[0]+col*CELL, b[1]+b[2]*CELL+7), (c[0]+col*CELL, c[1]-7), TEAL)


def pulse(im, x, y, color, p):
    d = ImageDraw.Draw(im)
    rad = 6+2*math.sin(math.pi*p)
    d.ellipse((x-rad, y-rad, x+rad, y+rad), fill=color)
    d.ellipse((x-11, y-11, x+11, y+11), outline=color, width=1)


def tiny_grid(im, x, y, rows, cols, size, color, border=True):
    if border:
        highlight(im, (x, y, x+cols*size, y+rows*size), color, .8, width=2)
    for j in range(1, cols):
        line(im, (x+j*size, y), (x+j*size, y+rows*size), GRID, 1)
    for i in range(1, rows):
        line(im, (x, y+i*size), (x+cols*size, y+i*size), GRID, 1)


def beat_at(scene, t):
    beat = next((b for b in scene['beats'] if b['start'] <= t < b['start']+b['duration']), scene['beats'][-1])
    return beat, max(0, t-beat['start'])


DOT_GROUPS = (
    ((3,3),(3,4),(3,5)),
    ((4,5),(5,5),(6,5)),
)
DOT_PHASES = (0.,.5,1.)


def dot_state(local,duration,phases=DOT_PHASES):
    """Three columns at a fixed A row, then three A rows at a fixed B column."""
    p=clamp(local/max(.001,duration))
    group=next((i for i in range(len(DOT_GROUPS)) if p<phases[i+1]),len(DOT_GROUPS)-1)
    start,end=phases[group:group+2]
    position=clamp((p-start)/(end-start))*3
    example=min(2,int(position))
    progress=clamp(position-example)
    completed=[pair for pairs in DOT_GROUPS[:group] for pair in pairs]
    completed+=list(DOT_GROUPS[group][:example])
    row,col=DOT_GROUPS[group][example]
    return dict(group=group,example=example,progress=progress,row=row,col=col,completed=completed)


def scene_one(im, key, local, duration, visual_phases=None):
    p = clamp(local/max(1, duration))
    if key == 'dot':
        state=dot_state(local,duration,visual_phases or DOT_PHASES)
        i,j,q=state['row'],state['col'],state['progress']
        for row,col in state['completed']:
            highlight(im,region('C',row,col),PURPLE,.68,False,2)
        highlight(im,region('A',i,0,1,12),BLUE,.9)
        highlight(im,region('B',0,j,12,1),TEAL,.9)
        highlight(im,region('C',i,j),PURPLE,.32,False,2)
        ax, ay, _, _ = MATRICES['A']
        bx, by, _, _ = MATRICES['B']
        cx, cy, _, _ = MATRICES['C']
        target=(cx+(j+.5)*CELL,cy+(i+.5)*CELL)
        dashed(im, (ax+12*CELL+8, ay+(i+.5)*CELL), (cx+j*CELL-4, cy+(i+.5)*CELL), BLUE)
        arrow(im, (cx+j*CELL-18, cy+(i+.5)*CELL), (cx+j*CELL-3, cy+(i+.5)*CELL), BLUE, 2)
        dashed(im, (bx+(j+.5)*CELL, by+12*CELL+8), (cx+(j+.5)*CELL, cy+i*CELL-4), TEAL)
        sweep=clamp((q-.12)/.55)
        if .12<=q<.72:
            k=min(11,int(sweep*12))
            highlight(im,region('A',i,k),ORANGE,.95,False,3)
            highlight(im,region('B',k,j),ORANGE,.95,False,3)
        # The result markers converge on C only after the full K sweep.
        if .7<=q<.9:
            flight=ease((q-.7)/.2)
            a_start=(ax+12*CELL+12,ay+(i+.5)*CELL)
            b_start=(bx+(j+.5)*CELL,by+12*CELL+12)
            for origin,color in ((a_start,BLUE),(b_start,TEAL)):
                pos=tuple(x+(y-x)*flight for x,y in zip(origin,target))
                pulse(im,*pos,color,flight)
        if q>=.9:
            highlight(im,region('C',i,j),PURPLE,.95,False,3)
            pulse(im,*target,PURPLE,q)
        descriptions=(
            ('A 행 고정 · B 열 이동','A의 같은 행을 유지합니다.','B의 다른 열을 차례로 계산합니다.'),
            ('B 열 고정 · A 행 이동','B의 같은 열을 유지합니다.','A의 다른 행을 차례로 계산합니다.'),
        )
        title,*lines=descriptions[state['group']]
        note(im,title,*lines,color=PURPLE)
        text(im, 'C[i, j]', 1280, 494, 37, PURPLE, True)
        text(im, 'Σ A[i, k] × B[k, j]', 1280, 555, 31, INK)
        text(im,'같은 K 위치를 따라 계산합니다.',1280,624,27,MUTED,maxw=550)
        # Unnumbered products build a sum before the result goes into C.
        for k in range(12):
            x=1280+k*33
            done=k<int(sweep*12)
            highlight(im,(x,685,x+23,708),ORANGE if done else GRID,.8 if done else .35,False,1)
        text(im,'곱한 값들을 모두 더한 결과',1280,785,28,PURPLE,True,maxw=550)
        text(im,'결과를 C에 넣습니다' if q>=.7 else '행과 열을 곱하고 더합니다',1280,850,28,MUTED,maxw=550)
    elif key == 'memory':
        matrices = MEMORY_MATRICES
        highlight(im, region('A', 0, 0, 9, 12, matrices=matrices), BLUE, .25)
        highlight(im, region('B', 0, 0, 12, 9, matrices=matrices), TEAL, .25)
        note(im, '빠르지만, 용량은 작다', 'Shared memory와 Register에', '데이터를 저장한다면 HBM보다', '빠르게 접근할 수 있지만,', '용량이 작아 큰 행렬 전체를', '담기는 어렵습니다.', y=220)
        # A single, small work area instead of a hardware/block/thread dashboard.
        text(im, 'Shared memory · Registers', 1280, 495, 25, PURPLE, True)
        line(im, (1280, 535), (1780, 535), GRID, 1)
        tiny_grid(im, 1300, 575, 3, 4, 30, BLUE)
        tiny_grid(im, 1510, 575, 4, 3, 30, TEAL)
        text(im, '작은 입력 타일', 1470, 741, 28, MUTED, anchor='center')
        # Highlight the source pieces and move their outlines into the work area.
        if p > .25:
            source_a = region('A', R0, 0, BM, BK, matrices=matrices)
            source_b = region('B', 0, C0, BK, BN, matrices=matrices)
            q = ease((p-.25)/.5)
            for box, dest, color in ((source_a, (1300, 575, 1420, 665), BLUE),
                                     (source_b, (1510, 575, 1600, 695), TEAL)):
                highlight(im, box, color)
                moving = tuple(a+(b-a)*q for a, b in zip(box, dest))
                highlight(im, moving, color, .7, False, 2)
    elif key == 'reuse':
        input_tiles(im, c=.35)
        projections(im)
        n = min(8, int(p*9))
        rr, cc = divmod(n, 3)
        for cell_index in range(n+1):
            r, c = divmod(cell_index, 3)
            highlight(im, region('C', R0+r, C0+c), PURPLE, .8, False, 2)
        # The active A row is reused across output columns; the B column across rows.
        highlight(im, region('A', R0+rr, 0, 1, BK), BLUE, .9)
        highlight(im, region('B', 0, C0+cc, BK, 1), TEAL, .9)
        pulse(im, 790+(C0+cc+.5)*CELL, 590+(R0+rr+.5)*CELL, PURPLE, p)
        note(im, '한 번 읽고, 여러 번 사용', '가져온 입력 타일을 재사용해', '여러 출력 원소를 계산합니다.', color=PURPLE)
        text(im, 'HBM에서 반복해서 읽는 양 감소', 1280, 553, 28, PURPLE, maxw=550)
        tiny_grid(im, 1300, 650, 3, 4, 29, BLUE)
        tiny_grid(im, 1500, 650, 4, 3, 29, TEAL)
    elif key == 'partition':
        note(im, '타일 별로 계산하여\n출력이 나옵니다.', '각 타일을 계산할 작업을', 'GPU에 나누어 실행합니다.', color=PURPLE)
        total = min(9, int(p*11)+1)
        for n in range(total):
            i, j = divmod(n, 3)
            highlight(im, region('C', i*3, j*3, 3, 3), PURPLE, .65, False, 3)
        text(im, 'C', 1440, 562, 44, PURPLE, True, 'center')
        for i in range(3):
            for j in range(3):
                x, y = 1280+j*110, 620+i*85
                if i*3+j < total:
                    highlight(im, (x, y, x+96, y+71), PURPLE, .65, False, 2)
    else:  # follow
        input_tiles(im, c=1)
        projections(im)
        note(im, '이 출력 타일 하나가', '어떻게 완성되는지', '따라가 보겠습니다.', color=PURPLE)
        target = region('C', R0, C0, BM, BN)
        dashed(im, (target[2]+10, target[1]), (1300, 560), PURPLE, width=1)
        dashed(im, (target[2]+10, target[3]), (1300, 770), PURPLE, width=1)
        tiny_grid(im, 1300, 560, 3, 3, 70, PURPLE)


def output_dims(im, show_bm=True, show_bn=True):
    box = region('C', R0, C0, BM, BN)
    if show_bm:
        vdim(im, box[0]-25, box[1], box[3], 'BM', PURPLE)
    if show_bn:
        hdim(im, box[0], box[2], box[1]-25, 'BN', PURPLE)


def scene_two(im, key, local, duration):
    p = clamp(local/max(1, duration))
    if key == 'shapes':
        for name, body, color, ypos in [('A', 'M × K', BLUE, 551), ('B', 'K × N', TEAL, 66), ('C', 'M × N', PURPLE, 551)]:
            text(im, body, MATRICES[name][0]+63, ypos, 27, color)
        vdim(im, 119, 590, 914, 'M', BLUE)
        hdim(im, 150, 582, 947, 'K', BLUE, below=False)
        vdim(im, 1150, 104, 536, 'K', TEAL, left=False)
        hdim(im, 790, 1114, 947, 'N', PURPLE, below=False)
        note(im, '행렬의 세 축', 'A의 행 수: M', '공통으로 곱하고 더할 축: K', 'B의 열 수: N')
    elif key == 'parameters':
        highlight(im, region('C', R0, C0, BM, BN), PURPLE, .8)
        note(im, '타일 크기를 정하는 값', 'BM', 'BN', 'BK', color=PURPLE)
    elif key == 'mn':
        show_n = p > .48
        row_count = max(1, min(BM, math.ceil(ease(p/.38)*BM)))
        col_count = max(1, min(BN, math.ceil(ease((p-.48)/.36)*BN))) if show_n else 1
        highlight(im, region('A', R0, 0, row_count, 12), BLUE, .38)
        cbox = region('C', R0, C0, row_count, col_count)
        highlight(im, cbox, PURPLE, .7)
        vdim(im, cbox[0]-25, cbox[1], cbox[3], 'BM', PURPLE)
        if show_n:
            hdim(im, cbox[0], cbox[2], cbox[1]-25, 'BN', PURPLE)
        projections(im, cols=show_n)
        if show_n:
            highlight(im, region('B', 0, C0, 12, col_count), TEAL, .38)
        note(im, '출력 타일의 행과 열', 'BM: 한 번에 계산할 행 개수', *(['BN: 한 번에 계산할 열 개수'] if show_n else []), color=PURPLE)
        if show_n:
            text(im, 'BM × BN', 1280, 558, 46, PURPLE, True)
    elif key == 'output':
        highlight(im, region('C', R0, C0, BM, BN), PURPLE)
        output_dims(im)
        note(im, '출력 타일', 'BM개의 행과 BN개의 열', color=PURPLE)
        tiny_grid(im, 1300, 510, BM, BN, 65, PURPLE)
        vdim(im, 1270, 510, 705, 'BM', PURPLE)
        hdim(im, 1300, 1495, 746, 'BN', PURPLE, below=True)
    elif key == 'k':
        input_tiles(im, c=.35)
        a = region('A', R0, 0, BM, BK)
        b = region('B', 0, C0, BK, BN)
        hdim(im, a[0], a[2], a[1]-25, 'BK', ORANGE)
        vdim(im, b[2]+27, b[1], b[3], 'BK', ORANGE, left=False)
        arrow(im, (a[0]+8, a[1]+50), (a[2]-8, a[1]+50), ORANGE, 2)
        arrow(im, (b[0]+50, b[1]+8), (b[0]+50, b[3]-8), ORANGE, 2)
        note(im, 'BK: K축을 한 번에 처리할 폭', 'A에서는 가로 방향,', 'B에서는 세로 방향입니다.', color=ORANGE)
        text(im, '같은 K 구간을 선택합니다.', 1280, 562, 28, ORANGE)
    elif key == 'inputs':
        show_b = p > .43
        input_tiles(im, b=1 if show_b else .3, c=.2)
        a = region('A', R0, 0, BM, BK)
        b = region('B', 0, C0, BK, BN)
        vdim(im, a[0]-27, a[1], a[3], 'BM', BLUE)
        hdim(im, a[0], a[2], a[1]-25, 'BK', BLUE)
        if show_b:
            vdim(im, b[2]+27, b[1], b[3], 'BK', TEAL, left=False)
            hdim(im, b[0], b[2], b[3]+27, 'BN', TEAL, below=True)
        note(im, '한 단계에서 가져오는 입력', 'A 타일: BM × BK', *(['B 타일: BK × BN'] if show_b else []))
        tiny_grid(im, 1300, 548, BM, BK, 36, BLUE)
        if show_b:
            text(im, '×', 1493, 610, 35, INK, anchor='center')
            tiny_grid(im, 1550, 548, BK, BN, 36, TEAL)
    else:  # product: one K chunk contributes a partial BM×BN result.
        input_tiles(im, c=.25)
        projections(im)
        count = min(9, int(p*11)+1)
        for n in range(count):
            i, j = divmod(n, 3)
            highlight(im, region('C', R0+i, C0+j), PURPLE, .85, False, 2)
        output_dims(im)
        note(im, '곱의 결과도 출력 타일 크기', '한 K 단계의 부분 결과입니다.', color=PURPLE)
        text(im, '(BM × BK)', 1280, 490, 35, BLUE, True)
        text(im, '× (BK × BN)', 1280, 556, 35, TEAL, True)
        line(im, (1280, 603), (1720, 603), GRID, 2)
        text(im, 'BM × BN', 1280, 662, 47, PURPLE, True)
        text(im, '같은 출력 타일에 누적', 1280, 750, 28, MUTED)


def frame(scene, t):
    beat, local = beat_at(scene, t)
    intro = scene['index']==1 and beat['key'] in INTRO_REUSE_KEYS
    if intro:
        from scenes import render_intro_reuse
        im = render_intro_reuse(scene, beat, local)
    elif scene['index'] > 2:
        from scenes import render_scene
        im = render_scene(scene, beat, local)
    else:
        im = base(scene['index'], memory=scene['index']==1 and beat['key']=='memory').copy()
    if scene['index'] == 1 and not intro:
        scene_one(im, beat['key'], local, beat['duration'],visual_phases=beat.get('visual_phases'))
    elif scene['index'] == 2:
        scene_two(im, beat['key'], local, beat['duration'])
    cue = next((c for c in scene['cues'] if c['start'] <= t < c['end']), None)
    if cue:
        lines = cue['text'].split('\n')
        for i, body in enumerate(lines):
            text(im, body, W/2, 1012+(i-(len(lines)-1)/2)*35, 28, INK, anchor='center', maxw=1760)
    return im


def preview(scenes):
    global TEXT_AUDIT
    folder = ROOT/'preview'
    folder.mkdir(exist_ok=True)
    pages = []
    for scene in scenes:
        thumbs = []
        for i, beat in enumerate(scene['beats']):
            TEXT_AUDIT = []
            im = frame(scene, beat['start']+beat['duration']*.78)
            for body, box in TEXT_AUDIT:
                if box[0] < 0 or box[1] < 0 or box[2] > W or box[3] > H:
                    raise ValueError(f'Text outside frame: {body}: {box}')
            TEXT_AUDIT = None
            im.save(folder/f'{scene["index"]:02}-{i:02}.png')
            thumbs.append(im.resize((640, 360), Image.Resampling.LANCZOS))
        rows = math.ceil(len(thumbs)/2)
        sheet = Image.new('RGB', (1280, rows*360), BG)
        for i, im in enumerate(thumbs):
            sheet.paste(im, ((i%2)*640, (i//2)*360))
        sheet.save(folder/f'{scene["index"]:02}-storyboard.jpg', quality=95)
        pages.append(sheet)
        print(folder/f'{scene["index"]:02}-storyboard.jpg', flush=True)
    combined = Image.new('RGB', (1280, sum(p.height for p in pages)), BG)
    y = 0
    for page in pages:
        combined.paste(page, (0, y))
        y += page.height
    combined.save(folder/('scenes01-09-storyboard.jpg' if len(scenes)==9 else 'selected-storyboard.jpg'), quality=94)
