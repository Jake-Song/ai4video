"""Scenes 3–9: logical tiles and their computation, drawn by the export renderer.

Thread diagrams are conceptual; numerical tiles are deliberately small teaching
examples, not valid tensor-core launch configurations.
"""
from __future__ import annotations

from dataclasses import dataclass
import visuals as v

A_VALUES = [[1, 2, 3, 4], [5, 6, 7, 8], [2, 1, 0, 1], [1, 0, 2, 1]]
B_VALUES = [[1, 2, 2, 1], [0, 1, 1, 2], [1, 1, 0, 1], [2, 0, 1, 0]]
C_VALUES = [[sum(A_VALUES[i][k]*B_VALUES[k][j] for k in range(4))
             for j in range(4)] for i in range(4)]
FIRST = [[sum(A_VALUES[i][k]*B_VALUES[k][j] for k in range(2)) for j in range(2)] for i in range(2)]
SECOND = [[sum(A_VALUES[i][k]*B_VALUES[k][j] for k in range(2, 4)) for j in range(2)] for i in range(2)]
FINAL = [row[:2] for row in C_VALUES[:2]]
ZERO = [[0, 0], [0, 0]]
COLORS = (v.PURPLE, v.BLUE, v.TEAL, v.ORANGE)


def text(im, body, x, y, size=28, color=v.INK, bold=False, anchor='left', maxw=None):
    v.text(im, body, x, y, size, color, bold, anchor, maxw=maxw)


def panel(im, title, *lines, color=v.PURPLE, x=1130, y=310):
    text(im, title, x, y, 34, color, True, maxw=700)
    for i, body in enumerate(lines):
        text(im, body, x, y+63+i*43, 28, v.MUTED, maxw=700)


@dataclass(frozen=True)
class Matrix:
    x: int
    y: int
    rows: int = 4
    cols: int = 4
    cell: int = 66

    def rect(self, r=0, c=0, rows=1, cols=1):
        return (self.x+c*self.cell, self.y+r*self.cell,
                self.x+(c+cols)*self.cell, self.y+(r+rows)*self.cell)

    def center(self, r, c):
        return self.x+(c+.5)*self.cell, self.y+(r+.5)*self.cell

    def mark(self, im, r, c, rows=1, cols=1, color=v.PURPLE, alpha=1):
        v.highlight(im, self.rect(r,c,rows,cols), color, alpha, width=3)

    def draw(self, im, name, color, values=None, label=None):
        text(im, name, self.x, self.y-30, 30, color, True)
        if label:
            offset=max(55,v.label(name,30,color,True).width+22)
            text(im, label, self.x+offset, self.y-30, 23, v.MUTED)
        for j in range(1,self.cols):
            v.dashed(im,(self.x+j*self.cell,self.y),(self.x+j*self.cell,self.y+self.rows*self.cell),dash=3,gap=5,width=1)
        for i in range(1,self.rows):
            v.dashed(im,(self.x,self.y+i*self.cell),(self.x+self.cols*self.cell,self.y+i*self.cell),dash=3,gap=5,width=1)
        v.ImageDraw.Draw(im).rectangle(self.rect(0,0,self.rows,self.cols), outline=v.INK, width=2)
        if values is not None:
            for i,row in enumerate(values):
                for j,value in enumerate(row):
                    text(im, str(value), *self.center(i,j), min(30,self.cell*.43), v.INK, anchor='center')


def header(scene):
    im = v.Image.new('RGB',(v.W,v.H),v.BG)
    text(im,f'{scene["index"]:02}',70,55,26,v.PURPLE,True)
    text(im,scene['title'],124,55,36,v.INK,True,maxw=1680)
    v.equation(im,90,147)
    v.line(im,(70,967),(1850,967),v.GRID,1)
    return im


def layout(im, numeric=True):
    a,b,c = Matrix(180,585),Matrix(690,235),Matrix(690,585)
    a.draw(im,'A',v.BLUE,A_VALUES if numeric else None,'4 × 4')
    b.draw(im,'B',v.TEAL,B_VALUES if numeric else None,'4 × 4')
    c.draw(im,'C',v.PURPLE,None,'4 × 4')
    v.line(im,(1060,240),(1060,917),v.GRID,1)
    return a,b,c


def tile_outlines(im,c,labels=False):
    for n,color in enumerate(COLORS):
        i,j=divmod(n,2)
        c.mark(im,i*2,j*2,2,2,color,.6)
        if labels:
            x,y=c.center(i*2+.5,j*2+.5)
            text(im,f'({i}, {j})',x,y,26,color,True,'center')


def project(im,a,b,c,r=0,col=0):
    for i in (r,r+2):
        v.dashed(im,(a.x+4*a.cell+7,a.y+i*a.cell),(c.x-7,c.y+i*c.cell),v.BLUE,width=1)
    for j in (col,col+2):
        v.dashed(im,(b.x+j*b.cell,b.y+4*b.cell+7),(c.x+j*c.cell,c.y-7),v.TEAL,width=1)


def inputs(im,a,b,c,k=0,r=0,col=0):
    a.mark(im,r,k,2,2,v.BLUE)
    b.mark(im,k,col,2,2,v.TEAL)
    c.mark(im,r,col,2,2,v.PURPLE)
    project(im,a,b,c,r,col)


def accumulator(im,values,title='누산기 acc',color=v.PURPLE,x=1230,y=560):
    m=Matrix(x,y,2,2,88)
    m.mark(im,0,0,2,2,color,.65)
    m.draw(im,title,color,values)
    text(im,'BM × BN = 2 × 2',x,y+218,25,v.MUTED)
    return m


def repeated_transfer(im,p,color,vertical=False):
    """Repeat the same unnumbered fragment on the HBM-to-compute route."""
    v.highlight(im,(1280,535,1445,710),color,.45,False,2)
    v.highlight(im,(1600,535,1800,710),v.PURPLE,.45,False,2)
    text(im,'HBM',1362,568,29,color,True,'center')
    text(im,'출력 계산',1700,568,27,v.PURPLE,True,'center')
    if vertical:
        v.tiny_grid(im,1350,600,4,1,23,color)
    else:
        v.tiny_grid(im,1305,623,1,4,28,color)
    v.tiny_grid(im,1664,618,2,2,33,v.PURPLE)
    v.arrow(im,(1460,640),(1580,640),v.MUTED,2)
    phase=(p*2)%1
    x=1460+120*v.ease(phase)
    v.highlight(im,(x-14,628,x+14,652),color,.95,False,3)
    text(im,'같은 데이터를 또 가져옵니다',1280,775,29,v.ORANGE,True,maxw=550)
    text(im,'옮긴 값을 다시 옮기는 전송',1280,832,27,v.MUTED,maxw=550)


def render_intro_reuse(scene,beat,local):
    """Explain redundant HBM transfers using only logical grids and motion."""
    im=v.base(scene['index'],memory=True).copy()
    key=beat['key']
    p=v.clamp(local/max(1,beat['duration']))
    matrices=v.MEMORY_MATRICES
    region=lambda name,r=0,c=0,rows=1,cols=1:v.region(name,r,c,rows,cols,matrices=matrices)
    r0,c0=v.R0,v.C0
    later=p>=.5
    if key=='hbm_row_repeat':
        r,col=r0,c0+int(later)
        v.highlight(im,region('A',r,0,1,12),v.BLUE)
        v.highlight(im,region('B',0,col,12,1),v.TEAL)
        v.highlight(im,region('C',r0,c0),v.PURPLE,.5)
        v.highlight(im,region('C',r,col),v.PURPLE)
        if later:
            v.highlight(im,region('A',r,0,1,12),v.ORANGE,.9)
        v.note(im,'출력마다 HBM에서\n다시 읽으면 비효율적입니다.',
               '옆 출력에서도 같은 A 행이 필요합니다.',
               '이미 가져온 입력을 다시 전송합니다.',y=245)
        repeated_transfer(im,p,v.BLUE)
    elif key=='hbm_column_repeat':
        r,col=r0+int(later),c0
        v.highlight(im,region('A',r,0,1,12),v.BLUE)
        v.highlight(im,region('B',0,col,12,1),v.TEAL)
        v.highlight(im,region('C',r0,c0),v.PURPLE,.5)
        v.highlight(im,region('C',r,col),v.PURPLE)
        if later:
            v.highlight(im,region('B',0,col,12,1),v.ORANGE,.9)
        v.note(im,'같은 B 열도 다시 전송',
               '아래 출력에서는 A의 행만 바뀝니다.',
               'B의 열은 이미 사용한 데이터입니다.',
               '다시 가져오면 같은 값을 옮깁니다.',y=245,color=v.TEAL)
        repeated_transfer(im,p,v.TEAL,vertical=True)
    else:
        v.highlight(im,region('A',r0,0,2,12),v.BLUE,.6)
        v.highlight(im,region('B',0,c0,12,2),v.TEAL,.6)
        for i in range(min(4,int(max(0,p-.3)/.6*4)+1)):
            rr,cc=divmod(i,2)
            v.highlight(im,region('C',r0+rr,c0+cc),v.PURPLE,.9)
        v.note(im,'중복 전송이\n대역폭을 차지합니다.',y=245)
        text(im,'입력을 기다리는 시간이 길어질 수 있습니다.',1280,351,27,v.MUTED,maxw=550)
        text(im,'가져온 값을 가까이 두고 재사용합니다.',1280,394,28,v.MUTED,maxw=550)
        v.highlight(im,(1280,535,1445,715),v.BLUE,.45,False,2)
        v.highlight(im,(1535,535,1795,715),v.TEAL,.55,False,2)
        text(im,'HBM',1362,568,29,v.BLUE,True,'center')
        text(im,'빠른 메모리',1665,568,29,v.TEAL,True,'center')
        v.tiny_grid(im,1305,618,1,4,28,v.BLUE)
        v.arrow(im,(1460,640),(1520,640),v.MUTED,2)
        if p<.3:
            x=1460+60*v.ease(p/.3)
            v.highlight(im,(x-12,628,x+12,652),v.BLUE,.95,False,3)
        else:
            v.tiny_grid(im,1585,618,1,4,28,v.BLUE)
            for i,x in enumerate((1330,1540,1750)):
                v.tiny_grid(im,x,835,1,1,42,v.PURPLE)
                v.curve(im,(1665,730),(x+21,820),v.TEAL,amount=16,width=2)
                if i==min(2,int((p-.3)/.7*3)):
                    q=((p-.3)/.7*3)%1
                    v.pulse(im,1665+(x+21-1665)*q,730+90*q,v.BLUE,p)
            text(im,'가져온 입력을 여러 출력에 재사용',1280,920,26,v.TEAL,True,maxw=550)
        text(im,'실제 HBM 데이터 이동량은',1280,461,23,v.MUTED,maxw=550)
        text(im,'캐시의 영향을 받기도 합니다.',1280,493,23,v.MUTED,maxw=550)
        return im
    # The row/column relation follows the same geometry as cut 1-01.
    ax,ay,ar,ac=matrices['A']
    bx,by,br,bc=matrices['B']
    cx,cy,cr,cc=matrices['C']
    v.dashed(im,(ax+ac*v.CELL+8,ay+(r+.5)*v.CELL),
             (cx-8,cy+(r+.5)*v.CELL),v.BLUE,width=1)
    v.dashed(im,(bx+(col+.5)*v.CELL,by+br*v.CELL+8),
             (cx+(col+.5)*v.CELL,cy-8),v.TEAL,width=1)
    return im


def scene_three(im,key,p):
    input_as=[]
    for offset,name,color,description in (
        (0,'CUDA',v.BLUE,'스레드와 블록에서 출발'),
        (960,'Triton',v.TEAL,'데이터 타일에서 출발'),
    ):
        text(im,name,135+offset,215,30,color,True)
        text(im,description,280+offset,215,23,v.MUTED)
        a=Matrix(135+offset,540,4,4,60)
        b=Matrix(535+offset,245,4,4,60)
        c=Matrix(535+offset,540,4,4,60)
        a.draw(im,'A',v.BLUE,label='입력')
        b.draw(im,'B',v.TEAL,label='입력')
        c.draw(im,'C',v.PURPLE,label='출력')
        a.mark(im,2,0,2,2,v.BLUE)
        b.mark(im,0,0,2,2,v.TEAL)
        tile_outlines(im,c)
        c.mark(im,2,0,2,2,color,.8)
        project(im,a,b,c,r=2,col=0)
        v.arrow(im,(a.x+270,720),(c.x-25,720),v.BLUE,2)
        input_as.append(a)
    left,right=input_as
    # Keep both annotations attached to the lower-left A input tile.
    lx,ly=left.center(2.5,.5)
    rx,ry=right.center(2.5,.5)
    text(im,'block',lx,824,28,v.BLUE,True,'center')
    v.arrow(im,(lx,803),(lx,783),v.BLUE,3)
    left.mark(im,2,0,color=v.ORANGE,alpha=.65)
    text(im,'thread',lx,ly+39,24,v.ORANGE,True,'center',maxw=110)
    v.arrow(im,(lx-43,ly+15),(lx+43,ly+15),v.ORANGE,3)
    text(im,'program',rx,824,28,v.TEAL,True,'center')
    v.arrow(im,(rx,803),(rx,783),v.TEAL,3)
    right.mark(im,2,0,color=v.ORANGE,alpha=.65)
    text(im,'data',*right.center(2,0),19,v.ORANGE,True,'center',maxw=56)
    v.line(im,(960,245),(960,945),v.GRID,1)
    text(im,'같은 출력 타일 계산',960,147,25,v.INK,True,'center')
    text(im,'blockIdx · threadIdx → 담당 작업',135,875,29,v.BLUE,True)
    text(im,'program_id → 담당 출력 타일',1095,875,29,v.TEAL,True)
    cuda_detail='스레드 블록: 협력하는 스레드의 묶음'
    triton_detail='블록 텐서: 여러 데이터 원소의 묶음'
    if key=='indices':
        cuda_detail='ID → 주소 · 담당 연산 · 동기화'
    if key in ('compiler','tensor','difference'):
        triton_detail='컴파일러 → 여러 스레드에 배분'
        if key=='difference':
            cuda_detail='CUDA에서도 타일링을 구현할 수 있습니다.'
    elif key=='next':
        v.pulse(im,*right.center(2.5,.5),v.PURPLE,p)
        triton_detail='이제 프로그램 하나를 따라갑니다.'
    elif key=='data':
        triton_detail='어떤 데이터에 어떤 연산을 할까?'
    text(im,cuda_detail,135,920,25,v.MUTED,maxw=730)
    text(im,triton_detail,1095,920,25,v.MUTED,maxw=730)


def scene_four(im,key,p):
    a,b,c=layout(im)
    tile_outlines(im,c,True)
    if key=='example':
        panel(im,'작은 예제로 바꿔 봅니다','M = N = K = 4','BM = BN = 2','2 × 2는 애니메이션용 크기입니다.')
    elif key=='four':
        n=min(3,int(p*5))
        r,col=divmod(n,2)
        c.mark(im,r*2,col*2,2,2,COLORS[n])
        panel(im,'출력 타일은 네 개','(0,0)   (0,1)','(1,0)   (1,1)')
    elif key in ('program','id'):
        n=min(3,int(p*4)) if key=='id' else 0
        r,col=divmod(n,2)
        c.mark(im,r*2,col*2,2,2,COLORS[n])
        panel(im,'프로그램 하나 → 출력 타일 하나',f'타일 좌표: ({r}, {col})',f'행 시작 = {r} × BM',f'열 시작 = {col} × BN')
        text(im,'program_id ≠ threadIdx',1130,610,31,v.ORANGE,True)
        text(im,'ID를 타일 좌표로 변환하는 방식은',1130,680,26,v.MUTED)
        text(im,'커널의 프로그램 순서에 따라 정합니다.',1130,722,26,v.MUTED)
    elif key=='needed':
        a.mark(im,0,0,2,4,v.BLUE)
        b.mark(im,0,0,4,2,v.TEAL)
        c.mark(im,0,0,2,2,v.PURPLE)
        project(im,a,b,c)
        panel(im,'왼쪽 위 타일에 필요한 입력','A: 위쪽 두 행, K 전체','B: 왼쪽 두 열, K 전체','이 입력을 K 방향으로 나눠 읽습니다.')
    else:
        for n,color in enumerate(COLORS):
            r,col=divmod(n,2)
            v.pulse(im,*c.center(r*2+.5,col*2+.5),color,p+n/4)
            text(im,f'Program ({r}, {col})',1130,350+n*93,30,color,True)
        text(im,'독립적인 출력 타일 → 병렬 실행 가능',1130,810,27,v.MUTED)


def scene_five(im,key,p):
    a,b,c=layout(im)
    c.mark(im,0,0,2,2,v.PURPLE)
    k=0
    if key in ('advance','fixed'):
        k=2*v.ease(p/.65)
    elif key in ('position','complete'):
        k=2
    inputs(im,a,b,c,k)
    values=ZERO
    if key in ('first','remaining','advance','position','fixed'):
        values=FIRST if key!='first' or p>.45 else ZERO
    if key in ('advance','fixed') and p>.7:
        values=FINAL
    if key=='complete':
        values=FINAL
    if key=='focus':
        panel(im,'출력 타일 하나에 집중','C의 왼쪽 위 2 × 2 타일','출력 위치는 고정합니다.')
    elif key=='zero':
        panel(im,'누산기부터 0으로 만듭니다','각 칸에 중간 합을 유지합니다.','누산기도 2 × 2입니다.')
    elif key=='bk':
        panel(im,'BK = 2','K = 4를 두 구간으로 나눕니다.','첫 구간 [0, 2) · 다음 구간 [2, 4)')
        v.hdim(im,a.x,a.x+2*a.cell,a.y-65,'BK = 2',v.ORANGE)
    elif key=='first':
        panel(im,'첫 K 구간: [0, 2)','앞쪽 두 칸의 A · B를 읽고','2 × 2 행렬 곱을 누적합니다.')
    elif key=='remaining':
        panel(im,'아직 K의 절반만 처리했습니다','누산기는 첫 번째 부분 합입니다.','뒤쪽 구간 [2, 4)가 남았습니다.',color=v.ORANGE)
        a.mark(im,0,2,2,2,v.ORANGE,.35)
        b.mark(im,2,0,2,2,v.ORANGE,.35)
    elif key in ('advance','fixed'):
        panel(im,'A는 오른쪽, B는 아래로','같은 K 구간의 입력끼리 곱합니다.','결과는 같은 누산기에 더합니다.')
        v.arrow(im,(a.x+25,a.y-60),(a.x+240,a.y-60),v.ORANGE)
        v.arrow(im,(b.x+305,b.y+25),(b.x+305,b.y+240),v.ORANGE)
    elif key=='position':
        panel(im,'입력은 움직여도 출력은 고정','같은 C 타일을 완성하고 있습니다.','출력 타일을 옮기는 반복이 아닙니다.')
        v.pulse(im,*c.center(.5,.5),v.PURPLE,p)
    else:
        panel(im,'K 전체를 처리했습니다','두 부분 곱을 더한 최종 누산기','이제 저장할 출력 값이 모였습니다.')
    accumulator(im,values)
    if key in ('first','remaining'):
        text(im,'0 + A[:, 0:2] @ B[0:2, :]',1130,875,25,v.MUTED,maxw=700)
    elif key in ('advance','position','fixed','complete'):
        text(im,'부분 합 1 + 부분 합 2',1130,875,27,v.PURPLE,True)
    if key=='complete':
        for r in range(2):
            for col in range(2):
                text(im,str(FINAL[r][col]),*c.center(r,col),30,v.PURPLE,True,'center')
        text(im,'타일 좌표: C[0,0] = A[0,0] @ B[0,0] + A[0,1] @ B[1,0]',90,920,27,v.MUTED,maxw=1700)


def scene_six(im,key,p):
    a,b,c=layout(im)
    c.mark(im,0,0,2,2,v.PURPLE,.45)
    # Each cut adds the next pair of arrows; later cuts retain the finished diagram.
    phase={'reuse_intro':-1,'reuse_a':0,'reuse_b':1,'general':2,
           'same':3,'intensity':4,'cache':4}[key]
    count=0 if phase<0 else 8 if phase==4 else phase*2+min(2,1+int(p*2))
    steps=[(use_a,fixed,partner) for fixed in range(2)
           for use_a in (True,False) for partner in range(2)][:count]
    title='A의 한 행을 재사용'
    detail=['A의 같은 행을 그대로 둡니다.','B의 열을 바꿔 곱하고 더하면','C의 같은 행에 결과가 쌓입니다.']
    color=v.BLUE
    if steps:
        use_a,fixed,partner=steps[-1]
        row,col=(fixed,partner) if use_a else (partner,fixed)
        a.mark(im,row,0,1,4,v.BLUE)
        b.mark(im,0,col,4,1,v.TEAL)
        color=v.BLUE if use_a else v.TEAL
        if not use_a:
            title='B의 한 열을 재사용'
            detail=['B의 같은 열을 그대로 둡니다.','A의 행을 바꿔 곱하고 더하면','C의 같은 열에 결과가 쌓입니다.']
        for row,col in {(fixed,partner) if use_a else (partner,fixed)
                        for use_a,fixed,partner in steps}:
            c.mark(im,row,col,color=v.PURPLE,alpha=.95)
        for use_a,fixed,partner in steps:
            if use_a:
                start=(a.x+4*a.cell+8,a.center(fixed,0)[1])
                target=c.center(fixed,partner)
            else:
                shift=18*partner
                start=(b.center(0,fixed)[0]+shift,b.y+4*b.cell+8)
                target=(c.center(partner,fixed)[0]+shift,c.center(partner,fixed)[1])
            v.curve(im,start,target,v.BLUE if use_a else v.TEAL,
                    amount=40+partner*18,width=2)
        footer=('A의 행 고정 · B의 열 이동' if steps[-1][0]
                else 'B의 열 고정 · A의 행 이동')
        if count==8:
            footer='A의 행과 B의 열을 재사용한 결과'
    else:
        a.mark(im,0,0,2,4,v.BLUE,.35)
        b.mark(im,0,0,4,2,v.TEAL,.35)
        footer='출력 타일에 필요한 A의 행과 B의 열'
    text(im,footer,120,920,28,color,True,maxw=900)
    if key=='reuse_intro':
        panel(im,'행과 열을 묶어서 재사용','A의 행은 서로 다른 B의 열과,','B의 열은 서로 다른 A의 행과','곱하고 더하는 데 다시 쓰입니다.')
    elif key in ('reuse_a','reuse_b'):
        panel(im,title,*detail,color=color)
    elif key=='general':
        panel(im,'BM × BN 타일로 일반화','A의 한 행 → BN개 출력 계산','B의 한 열 → BM개 출력 계산')
    elif key=='same':
        panel(im,'같은 행·열에서 여러 결과로','출력마다 같은 입력을 다시 읽는 대신','가져온 A의 행과 B의 열을 재사용합니다.')
    elif key=='intensity':
        panel(im,'읽은 데이터당 더 많은 연산','K 전체의 곱셈·덧셈:', '약 2 × BM × BN × K 연산')
        text(im,'입력 원소: BM × K + K × BN',1130,590,27,v.MUTED)
        text(im,'입력 재사용 → 연산 집약도 증가',1130,684,29,v.PURPLE,True)
    else:
        panel(im,'재사용 구조가 성능의 출발점','실제 HBM 접근 횟수에는','캐시와 컴파일 결과도 영향을 줍니다.','그림은 논리적인 재사용을 보여줍니다.')


CODE = [
    'acc = tl.zeros((BM, BN), dtype=tl.float32)', '',
    'for k in range(tl.cdiv(K, BK)):',
    '    a = tl.load(a_ptrs, mask=a_mask, other=0)',
    '    b = tl.load(b_ptrs, mask=b_mask, other=0)',
    '    acc = tl.dot(a, b, acc)',
    '    a_ptrs += BK * stride_ak',
    '    b_ptrs += BK * stride_bk', '',
    'c = acc.to(tl.float16)',
    'tl.store(c_ptrs, c, mask=c_mask)',
]


def scene_seven(im,key,p):
    v.highlight(im,(80,240,1110,910),v.GRID,.7,False,2)
    text(im,'핵심 흐름 · 주소와 마스크의 정의는 생략',110,278,25,v.MUTED)
    selected={'connect':[0,2],'load':[3,4],'dot_api':[5],'dot_acc':[5],
              'whole':[5],'fp32':[0,5],'store':[9,10]}[key]
    mono=v.ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',28)
    for i,body in enumerate(CODE):
        y=330+i*48
        if i in selected:
            v.highlight(im,(96,y-5,1094,y+36),v.PURPLE,.6,False,1)
        v.ImageDraw.Draw(im).text((115,y),body,font=mono,fill=v.INK if i in selected else v.MUTED)
    # The two input tiles feed the same 2×2 accumulator as in scene 5.
    aa,bb=Matrix(1200,325,2,2,70),Matrix(1530,325,2,2,70)
    aa.draw(im,'a',v.BLUE,[r[:2] for r in A_VALUES[:2]])
    bb.draw(im,'b',v.TEAL,[r[:2] for r in B_VALUES[:2]])
    aa.mark(im,0,0,2,2,v.BLUE)
    bb.mark(im,0,0,2,2,v.TEAL)
    text(im,'×',1455,395,34,v.INK,anchor='center')
    if key in ('load','connect'):
        v.arrow(im,(1270,245),(1270,284),v.BLUE)
        v.arrow(im,(1600,245),(1600,284),v.TEAL)
    values=FINAL if key=='store' else FIRST if key in ('dot_acc','whole','fp32') or (key=='dot_api' and p>.5) else ZERO
    accumulator(im,values,x=1340,y=595,title='acc · FP32')
    v.arrow(im,(1270,485),(1385,548),v.BLUE,2)
    v.arrow(im,(1600,485),(1470,548),v.TEAL,2)
    if key=='store':
        text(im,'K 루프 종료 → FP16 변환 → 저장',1170,865,27,v.PURPLE,True,maxw=680)
    elif key=='fp32':
        text(im,'중간 합은 FP32로 유지',1170,865,28,v.PURPLE,True)
    elif key in ('dot_api','dot_acc','whole'):
        text(im,'a @ b + acc → 새 acc',1170,865,30,v.PURPLE,True)
    else:
        text(im,'포인터 + stride + 마스크',1170,865,28,v.MUTED)


def scene_eight(im,key,p):
    tile=Matrix(130,335,4,4,66)
    tile.draw(im,'프로그램의 데이터 타일',v.TEAL)
    for i in range(4):
        for j in range(4):
            tile.mark(im,i,j,color=COLORS[(i*4+j)%4],alpha=.6)
    v.arrow(im,(450,468),(665,468),v.TEAL,3)
    v.highlight(im,(700,365,1050,570),v.PURPLE,.6,False,2)
    text(im,'Triton',875,424,36,v.PURPLE,True,'center')
    text(im,'컴파일러',875,492,34,v.INK,True,'center')
    v.arrow(im,(1075,468),(1210,468),v.PURPLE,3)
    text(im,'협력하는 GPU 스레드들',1240,285,30,v.BLUE,True)
    for i in range(8):
        x,y=1280+(i%4)*145,365+(i//4)*115
        v.ImageDraw.Draw(im).ellipse((x-26,y-26,x+26,y+26),outline=COLORS[i%4],width=3)
        text(im,f't{i}',x,y,23,COLORS[i%4],True,'center')
        if key in ('cooperate','distribute'):
            v.pulse(im,x,y+45,COLORS[i%4],p+i/8)
    if key=='hardware':
        text(im,'Shared memory',1180,615,27,v.TEAL,True)
        v.tiny_grid(im,1180,650,2,6,32,v.TEAL)
        text(im,'Registers',1510,615,27,v.PURPLE,True)
        for i in range(4):
            v.tiny_grid(im,1510+i*68,650,2,2,24,v.PURPLE)
        text(im,'GPU · 자료형 · 형상에 맞춘 명령 선택',1130,797,27,v.MUTED)
        text(im,'지원 조건에서 Tensor Core 활용',1130,851,27,v.PURPLE,True)
    elif key in ('settings','tune'):
        for i,(body,color) in enumerate([('BM · BN · BK',v.TEAL),('num_warps',v.BLUE),('num_stages',v.ORANGE)]):
            v.highlight(im,(1150,600+i*90,1770,668+i*90),color,.5,False,2)
            text(im,body,1180,634+i*90,28,color,True)
        text(im,'개발자가 고르고 성능을 측정할 설정',1150,912,26,v.MUTED)
    else:
        text(im,'타일 연산 → 스레드 · 메모리 · GPU 명령',1100,690,29,v.PURPLE,True,maxw=735)
        text(im,'원소 하나와 스레드 하나의 고정 대응이 아닙니다.',1100,765,25,v.MUTED,maxw=735)
    text(im,'데이터 원소의 묶음',130,675,27,v.TEAL)
    text(im,'스레드별 담당 값과 연산은',130,750,26,v.MUTED)
    text(im,'컴파일 결과에 따라 달라집니다.',130,793,26,v.MUTED)
    text(im,'스레드 배치와 메모리 사용은 개념도입니다.',90,920,24,v.MUTED)


def boundary(im,key,p):
    a,b,c=Matrix(160,565,6,6,50),Matrix(690,215,6,6,50),Matrix(690,565,6,6,50)
    for m,name,color in [(a,'A',v.BLUE),(b,'B',v.TEAL),(c,'C',v.PURPLE)]:
        m.draw(im,name,color,label='유효한 크기 5 × 5')
        m.mark(im,5,0,1,6,v.RED,.55)
        m.mark(im,0,5,6,1,v.RED,.55)
        m.mark(im,0,0,5,5,color,.4)
    a.mark(im,4,4,2,2,v.BLUE)
    b.mark(im,4,4,2,2,v.TEAL)
    c.mark(im,4,4,2,2,v.PURPLE)
    if key=='mask':
        for m,vertical in [(a,True),(b,False)]:
            for i in range(2):
                r,col=(4+i,5) if vertical else (5,4+i)
                text(im,'0',*m.center(r,col),29,v.ORANGE,True,'center')
        c.mark(im,4,4,color=v.PURPLE)
        v.pulse(im,*c.center(4,4),v.PURPLE,p)
        panel(im,'마스크로 유효 범위를 구분','K 범위 밖 입력 → 0','범위 밖 메모리를 읽지 않습니다.','출력 → M · N 범위 안에만 저장')
        text(im,'tl.load(..., mask=..., other=0)',1130,665,27,v.ORANGE)
        text(im,'tl.store(..., mask=...)',1130,735,27,v.PURPLE)
    else:
        panel(im,'5 × 5 행렬, 2 × 2 타일','가장자리 타일은 일부가 바깥으로','나갈 수 있습니다.','붉은 칸은 유효하지 않은 위치입니다.')
    text(im,'마지막 K 구간: [4, 6) 중 k = 4만 유효',160,920,26,v.MUTED)


def scene_nine(im,key,p):
    if key in ('edge','mask'):
        boundary(im,key,p)
        return
    if key in ('large','resources','measure'):
        small,big=Matrix(175,350,2,2,70),Matrix(575,350,4,4,70)
        small.draw(im,'작은 타일',v.BLUE)
        big.draw(im,'큰 타일',v.PURPLE)
        small.mark(im,0,0,2,2,v.BLUE,.6)
        big.mark(im,0,0,4,4,v.PURPLE,.6)
        v.arrow(im,(395,480),(525,480),v.MUTED)
        if key=='measure':
            panel(im,'여러 조합을 실제로 측정','타일 크기 · num_warps · num_stages','GPU와 행렬 크기에 맞춰 선택')
            for i in range(4):
                x=1160+i*150
                h=(120,185,140,95)[i]
                v.highlight(im,(x,790-h*v.ease(p/.7),x+78,790),COLORS[i],.8,False,2)
                text(im,chr(65+i),x+39,825,25,v.MUTED,anchor='center')
            text(im,'개념도: 막대 높이는 실행 시간',1130,900,24,v.MUTED)
        else:
            panel(im,'입력 재사용과 자원 사용의 균형','큰 타일 → 입력 재사용 증가 가능','레지스터 · 공유 메모리 요구량 증가','동시에 실행할 수 있는 작업 감소 가능')
            text(im,'항상 더 빠르다는 뜻은 아닙니다.',1130,650,29,v.ORANGE,True)
        text(im,'타일 크기는 성능을 측정하며 조정합니다.',175,920,29,v.MUTED)
        return
    a,b,c=layout(im)
    tile_outlines(im,c)
    if key=='overview':
        panel(im,'전체 계산 다시 보기','프로그램마다 서로 다른 출력 타일 담당','입력 읽기 → 곱하고 누적 → 저장')
        return
    if key=='ending':
        count=min(4,int(p*5)+1)
        for n in range(count):
            r,col=divmod(n,2)
            c.mark(im,r*2,col*2,2,2,COLORS[n])
            for i in range(2):
                for j in range(2):
                    text(im,str(C_VALUES[r*2+i][col*2+j]),*c.center(r*2+i,col*2+j),28,COLORS[n],True,'center')
        panel(im,'출력 타일 하나를 완성하는 과정','C의 타일마다 프로그램 하나','K 전체의 부분 곱을 누적','완성된 출력 타일을 저장')
        text(im,'읽기 → 곱하고 누적 → 저장',1130,674,33,v.PURPLE,True)
    else:
        n=min(3,int(p*4))
        r,col=divmod(n,2)
        phase=(p*4)%1
        k=0 if phase<.45 else 2
        inputs(im,a,b,c,k,r*2,col*2)
        panel(im,f'Program ({r}, {col})','각 프로그램은 서로 다른 C 타일 담당','K 방향으로 입력 타일을 순회','누적을 마치면 결과를 저장')
        steps=['입력 읽기','곱하고 누적','저장']
        active=0 if phase<.18 else 1 if phase<.82 else 2
        for i,body in enumerate(steps):
            color=v.PURPLE if i==active else v.MUTED
            text(im,body,1160,635+i*75,31,color,i==active)
        if active==2:
            for i in range(2):
                for j in range(2):
                    text(im,str(C_VALUES[r*2+i][col*2+j]),*c.center(r*2+i,col*2+j),28,v.PURPLE,True,'center')


RENDERERS = {3:scene_three,4:scene_four,5:scene_five,6:scene_six,7:scene_seven,8:scene_eight,9:scene_nine}


def render_scene(scene,beat,local):
    im=header(scene)
    p=v.clamp(local/max(1,beat['duration']))
    RENDERERS[scene['index']](im,beat['key'],p)
    return im
