"""Original procedural animation: probability clouds, state filling and table morphs."""
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from facts import elements, nist, configuration, occupation, SYMBOLS, KOREAN

ROOT=Path(__file__).resolve().parent
W,H,FPS=1920,1080,30
BG='#080c14'; FG='#edf1f4'; MUTED='#8b99ae'; GRID='#263244'
TEAL='#57d9ca'; GOLD='#f3cf76'; PINK='#e597ca'; VIOLET='#b5a0f2'; BLUE='#73a9f5'; RED='#f18488'; GREEN='#93d7a7'
COLORS={'s':TEAL,'p':PINK,'d':VIOLET,'f':BLUE,'series':BLUE}
KFONT='/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf'
MFONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
ES=elements()
ENERGIES={r['z']:r['ionization_eV'] for r in nist()}
TEXT_AUDIT=None


def clamp(t): return max(0.,min(1.,float(t)))
def ease(t):
    t=clamp(t); return t*t*(3-2*t)
def lerp(a,b,t): return a+(b-a)*t
def rgb(c): return tuple(int(c[k:k+2],16) for k in (1,3,5)) if isinstance(c,str) else tuple(c[:3])
def tint(c,a): return tuple(round(lerp(b,v,clamp(a))) for b,v in zip(rgb(BG),rgb(c)))


@lru_cache(256)
def font(size,korean=True): return ImageFont.truetype(KFONT if korean else MFONT,int(size))


@lru_cache(8192)
def label(body,size,color):
    runs=[]
    for char in str(body):
        korean='\uac00'<=char<='\ud7a3' or '\u3130'<=char<='\u318f'
        if runs and runs[-1][0]==korean: runs[-1][1]+=char
        else: runs.append([korean,char])
    width=sum(font(size,k).getlength(s) for k,s in runs)
    im=Image.new('RGBA',(math.ceil(width)+10,int(size*1.7)+10))
    d=ImageDraw.Draw(im); x=5
    for k,body in runs:
        f=font(size,k); d.text((x,size+3),body,font=f,fill=color,anchor='ls'); x+=f.getlength(body)
    bbox=im.getbbox()
    return im.crop(bbox) if bbox else im


def text(im,body,x,y,size=38,color=FG,alpha=1.,anchor='center',maxw=1780):
    if alpha<=0: return
    tile=label(str(body),int(size),color)
    if tile.width>maxw:
        tile=tile.resize((int(maxw),max(1,round(tile.height*maxw/tile.width))),Image.Resampling.LANCZOS)
    if alpha<.999:
        tile=tile.copy(); tile.putalpha(tile.getchannel('A').point(lambda a:round(a*clamp(alpha))))
    x=x if anchor=='left' else x-tile.width if anchor=='right' else x-tile.width/2
    if TEXT_AUDIT is not None and alpha>=.5:
        TEXT_AUDIT.append(dict(text=str(body),box=[round(x),round(y-tile.height/2),
                                                  round(x+tile.width),round(y+tile.height/2)]))
    im.paste(tile,(round(x),round(y-tile.height/2)),tile)


def line(im,pts,color=FG,width=3,alpha=1.):
    if alpha>0: ImageDraw.Draw(im).line([(round(x),round(y)) for x,y in pts],fill=tint(color,alpha),width=width,joint='curve')


def arrow(im,a,b,color=TEAL,width=4,alpha=1.,tip=15):
    line(im,[a,b],color,width,alpha)
    ang=math.atan2(b[1]-a[1],b[0]-a[0])
    line(im,[(b[0]-tip*math.cos(ang-.5),b[1]-tip*math.sin(ang-.5)),b,
             (b[0]-tip*math.cos(ang+.5),b[1]-tip*math.sin(ang+.5))],color,width,alpha)


def dot(im,x,y,r=7,color=TEAL,alpha=1.):
    ImageDraw.Draw(im).ellipse((x-r,y-r,x+r,y+r),fill=tint(color,alpha))


def ring(im,x,y,r,color=GRID,width=2,alpha=1.):
    ImageDraw.Draw(im).ellipse((x-r,y-r,x+r,y+r),outline=tint(color,alpha),width=width)


def rounded(im,xy,color=GRID,fill=None,width=2,r=8,alpha=1.):
    ImageDraw.Draw(im).rounded_rectangle(tuple(round(x) for x in xy),radius=r,
        outline=tint(color,alpha),fill=tint(fill,alpha) if fill else None,width=width)


def progress(s,t,k=0,length=1.7):
    return ease((t-s['beats_timed'][k]['start'])/length)


def sweep(s,t,k=0):
    b=s['beats_timed'][k]
    return clamp((t-b['start'])/max(1,b['duration']-.5))


def beat(s,t):
    return max(0,sum(t>=b['start'] for b in s['beats_timed'])-1)


def word_time(s,k,needle):
    b=s['beats_timed'][k]
    return next((w['start'] for w in b['word_times'] if needle in w['text']),b['start'])


@lru_cache(1)
def timeline(): return json.loads((ROOT/'timeline.json').read_text())


@lru_cache(1)
def backdrop():
    yy,xx=np.mgrid[0:H,0:W]
    field=np.exp(-((xx-W*.5)/(W*.8))**2-((yy-H*.5)/(H*.9))**2)
    a=np.empty((H,W,3),np.uint8)
    for c,v in enumerate(rgb(BG)): a[:,:,c]=v+field*(3 if c==0 else 5)
    return Image.fromarray(a)


def footer(im,body,color=MUTED,alpha=1.): text(im,body,960,913,27,color,alpha)


@lru_cache(128)
def cloud_image(kind='1s',color=TEAL,angle=0):
    size=440
    y,x=np.mgrid[-1:1:complex(size),-1:1:complex(size)]
    u=x*math.cos(angle)+y*math.sin(angle)
    r=np.sqrt(x*x+y*y)*7
    if kind=='2p': psi=u*7*np.exp(-r/2)
    elif kind=='2s': psi=(2-r)*np.exp(-r/2)
    else: psi=np.exp(-r*.9)
    rho=psi*psi
    # Monotonic exposure curve for visibility; not a quantitative brightness scale.
    alpha=np.clip((rho/(rho.max()+1e-12))**.48*220,0,220)
    alpha*=np.clip((1-np.sqrt(x*x+y*y))*8,0,1)
    a=np.zeros((size,size,4),np.uint8)
    a[:,:,:3]=rgb(color);a[:,:,3]=alpha.astype(np.uint8)
    return Image.fromarray(a)


def cloud(im,x,y,size=420,kind='1s',color=TEAL,alpha=1.,angle=0):
    if size<=1 or alpha<=0: return
    tile=cloud_image(kind,color,angle).resize((round(size),round(size)),Image.Resampling.BILINEAR)
    if alpha<.999:
        tile.putalpha(tile.getchannel('A').point(lambda a:round(a*clamp(alpha))))
    im.paste(tile,(round(x-size/2),round(y-size/2)),tile)


def nucleus(im,x,y,z=1,size=24,alpha=1.,labelled=True):
    dot(im,x,y,size,GOLD,alpha)
    if labelled: text(im,f'+{z}',x,y,max(20,size),BG,alpha)


def element_card(im,z,x,y,w=110,h=122,alpha=1.,color=None,show_name=False):
    color=color or COLORS[ES[z-1]['block']]
    rounded(im,(x-w/2,y-h/2,x+w/2,y+h/2),color,tint(color,.07),2,6,alpha)
    text(im,z,x-w*.34,y-h*.32,17,color,alpha)
    text(im,SYMBOLS[z-1],x,y+3,min(56,w*.48),FG,alpha)
    if show_name and z<=20: text(im,KOREAN[z-1],x,y+h/2+32,30,FG,alpha)


def table(im,x=173,y=280,cw=86,ch=52,highlight=None,names=1.,alpha=1.,max_z=118,groups=False):
    highlight=highlight or set()
    for e in ES:
        z=e['z']
        if z>max_z: continue
        xx=x+(e['col']-1)*cw; yy=y+(e['row']-1)*ch
        a=alpha*(1 if not highlight or z in highlight else .22)
        color=COLORS[e['block']]
        rounded(im,(xx,yy,xx+cw-5,yy+ch-5),color,tint(color,.09 if z not in highlight else .22),2,3,a)
        text(im,e['symbol'],xx+(cw-5)/2,yy+ch*.56,min(31,ch*.49),FG,a*names)
        if ch>=70: text(im,z,xx+12,yy+15,14,color,a*names,anchor='left')
    if max_z>56:
        for row,body in [(6,'57–71'),(7,'89–103')]:
            xx=x+2*cw;yy=y+(row-1)*ch
            rounded(im,(xx,yy,xx+cw-5,yy+ch-5),BLUE,width=1,alpha=alpha)
            text(im,body,xx+cw/2,yy+ch/2,17,BLUE,alpha)
    if groups:
        for col in range(1,19): text(im,col,x+(col-.5)*cw,y-22,19,MUTED,alpha)


def spin(im,x,y,up=True,color=TEAL,alpha=1.):
    a,b=((x,y+20),(x,y-20)) if up else ((x,y-20),(x,y+20))
    arrow(im,a,b,color,3,alpha,11)


def slots(im,x,y,orb,n,count=None,cell=92,color=None,alpha=1.,labels=True):
    count=count or {'s':1,'p':3,'d':5,'f':7}[orb[-1]]
    color=color or COLORS[orb[-1]]
    if labels: text(im,orb,x-65,y,38,color,alpha)
    for j,(up,down) in enumerate(occupation(int(n),count)):
        xx=x+j*cell
        rounded(im,(xx-cell*.4,y-38,xx+cell*.4,y+38),color,width=2,alpha=alpha)
        if up: spin(im,xx-12,y,True,color,alpha)
        if down: spin(im,xx+12,y,False,color,alpha)


def fill_diagram(im,z,x=580,y=750,active=None,alpha=1.):
    config=configuration(z)
    for j,orb in enumerate(['1s','2s','2p','3s','3p','4s']):
        yy=y-j*83
        a=alpha*(1 if active is None or orb==active else .32)
        slots(im,x,yy,orb,config[orb],cell=84,alpha=a)
    text(im,'오비탈 채움 기록 · H–Ca',x+50,y+75,25,MUTED,alpha)


def measurement_cloud(im,x,y,t,alpha=1.):
    rng=np.random.default_rng(31)
    r=rng.gamma(2,.5,900)*48
    a=rng.uniform(0,math.tau,900)
    count=min(900,max(0,int(t*90)))
    d=ImageDraw.Draw(im)
    for xx,yy in zip(x+r[:count]*np.cos(a[:count]),y+r[:count]*np.sin(a[:count])):
        d.ellipse((xx-2,yy-2,xx+2,yy+2),fill=tint(TEAL,alpha*.65))


def curve(im,points,color=TEAL,width=4,fraction=1.):
    n=max(0,min(len(points),round(len(points)*fraction)))
    if n>=2: line(im,points[:n],color,width)


def energy_graph(im,fraction=1.,highlight=None):
    x0,x1,y0,y1=210,1720,790,280
    arrow(im,(x0,y0),(x1+30,y0),MUTED,2)
    arrow(im,(x0,y0),(x0,y1-25),MUTED,2)
    for v in (0,5,10,15,20,25):
        yy=y0-(y0-y1)*v/25
        line(im,[(x0,yy),(x1,yy)],GRID,1)
        text(im,v,x0-32,yy,24,MUTED)
    text(im,'제1 이온화 에너지 / eV',x0,y1-63,29,MUTED,anchor='left')
    text(im,'원자번호 Z',x1,862,28,MUTED,anchor='right')
    pts=[]
    for z in range(1,21):
        xx=x0+(z-1)*(x1-x0)/19; yy=y0-ENERGIES[z]/25*(y0-y1)
        pts.append((xx,yy))
        text(im,SYMBOLS[z-1],xx,y0+31,24,MUTED)
    n=1+clamp(fraction)*19
    for k in range(19):
        if n<=k+1: break
        p=clamp(n-k-1)
        end=(lerp(pts[k][0],pts[k+1][0],p),lerp(pts[k][1],pts[k+1][1],p))
        line(im,[pts[k],end],TEAL,4)
    for z,(xx,yy) in enumerate(pts,1):
        if z>n+.01: continue
        c=GOLD if z in (2,10,18) else TEAL
        if highlight and z in highlight: c=PINK
        dot(im,xx,yy,7,c)
        if z in (2,3,10,11,18,19) or highlight and z in highlight:
            text(im,f'{ENERGIES[z]:.2f}',xx,yy-28,23,c)
    return pts


def draw_mystery(im,s,t):
    p=progress(s,t,1,2)
    table(im)
    if p>0:
        rounded(im,(166,380,1723,438),TEAL,width=3,alpha=p)
        rounded(im,(166,326,256,646),GOLD,width=3,alpha=p)
        text(im,'가로: 주기',720,833,38,TEAL,p)
        text(im,'세로: 족',1210,833,38,GOLD,p)
    footer(im,'원소의 위치 → 전자 구조 → 반응과 결합',FG,progress(s,t,2))


def draw_repetition(im,s,t):
    p=progress(s,t,1,3)
    for i,z in enumerate([3,11,19]):
        x=lerp(480+i*480,960,p); y=lerp(470,315+i*205,p)
        element_card(im,z,x,y,135,130,show_name=False)
        text(im,['2s¹','3s¹','4s¹'][i],x+lerp(0,220,p),y+lerp(115,0,p),43,TEAL)
    footer(im,'번호순 나열 → 같은 성질이 같은 열로',FG)


def draw_protons(im,s,t):
    for j,z in enumerate([1,2,3]):
        x=480+j*480
        a=clamp(sweep(s,t,0)*3-j+1)
        cloud(im,x,490,340,alpha=.4*a)
        nucleus(im,x,490,z,32,alpha=a)
        element_card(im,z,x,735,108,110,a)
        text(im,f'양성자 {z}개',x,320,37,GOLD,a)
    p=progress(s,t,1)
    text(im,'원자번호 Z = 양성자 수',960,220,45,GOLD,p)
    footer(im,'서로 다른 원자의 비교 · 크기 비율은 도식',alpha=progress(s,t,2))


def draw_electrons(im,s,t):
    p=progress(s,t,1,3)
    cloud(im,650,500,540,alpha=.85)
    nucleus(im,650,500,11,36)
    dot(im,lerp(840,1430,p),lerp(480,410,p),12,TEAL)
    text(im,'e⁻',lerp(840,1430,p),lerp(445,365,p),39,TEAL)
    text(im,'Na' if p<.7 else 'Na⁺',650,250,83,FG)
    text(im,'양성자 11개',650,785,38,GOLD)
    text(im,'전자 11개' if p<.7 else '전자 10개',650,846,38,TEAL)
    arrow(im,(920,515),(1370,430),TEAL,3,p)
    text(im,'원소의 정체는 유지된다',1375,640,39,FG,progress(s,t,2),maxw=660)
    footer(im,'중성 원자: 양성자 수 = 전자 수')


def draw_attraction(im,s,t):
    nucleus(im,960,505,1,34)
    phase=0  # The points illustrate forces, not planetary electron trajectories.
    for ang in (math.pi*.1,math.pi*.85,math.pi*1.5):
        x=960+310*math.cos(ang+phase);y=505+220*math.sin(ang+phase)
        dot(im,x,y,11,TEAL);text(im,'−',x,y-35,30,TEAL)
        arrow(im,(x*.7+960*.3,y*.7+505*.3),(x*.3+960*.7,y*.3+505*.7),GOLD,4)
    text(im,'인력',960,710,35,GOLD)
    p=progress(s,t,1)
    text(im,'왜 모두 핵에 모이지 않을까?',960,280,44,FG,p)
    text(im,'전기적 상호작용 + 허용되는 양자 상태',960,820,43,TEAL,progress(s,t,2))
    footer(im,'전하 사이 힘을 나타낸 도식 · 전자의 궤적 아님')


def draw_waves(im,s,t):
    for n,y in enumerate([330,540,750],1):
        a=1 if n==1 else progress(s,t,1,n*.8)
        line(im,[(410,y),(1570,y)],GRID,2,a)
        dot(im,410,y,8,GOLD,a);dot(im,1570,y,8,GOLD,a)
        pts=[(410+1160*u,y-57*math.sin(n*math.pi*u)*math.cos(t*2.3)) for u in np.linspace(0,1,241)]
        curve(im,pts,[TEAL,PINK,VIOLET][n-1],4,a)
        text(im,f'n = {n}',260,y,38,[TEAL,PINK,VIOLET][n-1],a)
        for j in range(n+1): dot(im,410+1160*j/n,y,4,GOLD,a)
    footer(im,'양끝 고정이라는 조건 → 허용되는 정상파 패턴',FG,progress(s,t,2))


def draw_cloud(im,s,t):
    p=progress(s,t,1,3)
    measurement_cloud(im,700,500,t,(1-.75*p))
    cloud(im,700,500,650,alpha=p)
    nucleus(im,700,500,1,14,labelled=False)
    text(im,'반복한 위치 측정',700,815,35,TEAL,1-p)
    text(im,'확률밀도',700,815,40,TEAL,p)
    text(im,'밝을수록 발견 가능성이 크다',1430,435,35,FG,p,maxw=690)
    text(im,'오비탈: 전자 상태의 표현',1430,590,40,FG,progress(s,t,2),maxw=690)
    footer(im,'수소형 1s 밀도의 단면 도식 · 밝기는 가시성을 위해 조정')


def draw_orbitals(im,s,t):
    cloud(im,450,465,490);nucleus(im,450,465,1,12,labelled=False)
    text(im,'s',450,240,62,TEAL)
    p=progress(s,t,1,2)
    for j,(x,ang) in enumerate([(1050,0),(1350,math.pi/4),(1650,math.pi/2)]):
        cloud(im,x,465,320,'2p',PINK,alpha=1 if j==0 else p,angle=ang)
        nucleus(im,x,465,1,8,alpha=1 if j==0 else p,labelled=False)
        text(im,['p_x','p_y','p_z'][j],x,700,40,PINK,1 if j==0 else p)
    text(im,'p',1350,240,62,PINK)
    q=progress(s,t,2)
    slots(im,450,790,'s',0,alpha=q,labels=False)
    slots(im,1260,790,'p',0,alpha=q,labels=False)
    arrow(im,(690,470),(840,470),MUTED,2)
    footer(im,'세 방향 p 오비탈의 투영 개념도 → 상태를 기록하는 자리',alpha=q)


def draw_pauli(im,s,t):
    p=progress(s,t,0,2);q=progress(s,t,1)
    rounded(im,(775,350,1145,660),TEAL,width=3,r=12)
    if p>.08: arrow(im,(895,590),(895,420),TEAL,8,clamp(p*2),27)
    if p>.5: arrow(im,(1020,420),(1020,590),TEAL,8,clamp((p-.5)*2),27)
    text(im,'하나의 오비탈',960,285,40,FG)
    text(im,'↑↓',450,500,100,TEAL,q)
    text(im,'반대 스핀',450,630,38,TEAL,q)
    r=progress(s,t,2)
    xx=lerp(1510,1240,r)
    arrow(im,(xx,590),(xx,420),RED,8,r,27)
    line(im,[(1205,425),(1295,535)],RED,6,r);line(im,[(1295,425),(1205,535)],RED,6,r)
    text(im,'세 번째는 다른 상태로',1410,730,36,RED,r,maxw=650)
    footer(im,'스핀 화살표는 운동 방향이나 고전적인 회전 표시가 아닙니다',alpha=q)


def draw_capacities(im,s,t):
    slots(im,510,460,'s',2,cell=125)
    slots(im,1110,460,'p',round(sweep(s,t,1)*6),cell=125)
    text(im,'1개 오비탈 × 2',510,310,40,TEAL)
    text(im,'3개 오비탈 × 2',1240,310,40,PINK)
    text(im,'2',510,665,90,TEAL)
    text(im,'6',1240,665,90,PINK)
    text(im,'+',840,665,72,FG)
    p=progress(s,t,2)
    text(im,'= 8',1570,665,90,GOLD,p)
    footer(im,'같은 에너지의 p 오비탈: 먼저 하나씩, 그다음 짝짓기')


def selected_z(s,t):
    k=s['key']
    if k=='first': return 1 if t<s['beats_timed'][1]['start'] else 2
    if k=='second':
        milestones=[(s['beats_timed'][0]['start'],3),
                    (word_time(s,0,'베릴륨'),4),(word_time(s,0,'붕소'),5),
                    (word_time(s,1,'탄소'),6),(word_time(s,1,'질소'),7),
                    (word_time(s,1,'산소'),8),(word_time(s,1,'플루오린'),9),
                    (word_time(s,2,'네온'),10)]
        return max([3]+[z for when,z in milestones if t>=when])
    if beat(s,t)==0: return 11
    if beat(s,t)==1: return 12+min(6,int(sweep(s,t,1)*7))
    return 18


def draw_filling(im,s,t):
    z=selected_z(s,t)
    active=next(orb for orb in reversed(['1s','2s','2p','3s','3p','4s']) if configuration(z)[orb])
    fill_diagram(im,z,x=580,y=775,active=active)
    element_card(im,z,1330,365,200,220,show_name=True)
    config=configuration(z)
    for j,orb in enumerate(['1s','2s','2p','3s','3p','4s']):
        if config[orb]: text(im,f'{orb}{str(config[orb]).translate(str.maketrans("0123456789","⁰¹²³⁴⁵⁶⁷⁸⁹"))}',1130+(j%3)*180,650+(j//3)*75,42,COLORS[orb[-1]])
    period=1 if z<=2 else 2 if z<=10 else 3
    seq=range(1,3) if period==1 else range(3,11) if period==2 else range(11,19)
    for j,n in enumerate(seq):
        element_card(im,n,1050+j*85,820,73,69,1 if n<=z else .22)
    footer(im,'한 원자의 핵을 바꾸는 과정이 아니라 서로 다른 중성 원자를 비교합니다')


def draw_fold(im,s,t):
    p=progress(s,t,0,3.5)
    zlist=list(range(1,19))
    for j,z in enumerate(zlist):
        e=ES[z-1]
        x=lerp(150+j*95,300+(e['col']-1)*86,p)
        y=lerp(450,335+(e['row']-1)*165,p)
        element_card(im,z,x,y,75,92)
    for row,color in [(1,MUTED),(2,TEAL),(3,GOLD)]:
        y=335+(row-1)*165
        text(im,f'{row}주기',165,y-18,30,color,p)
        text(im,f'n = {row}',165,y+25,25,color,p)
    q=progress(s,t,1)
    for row,color in [(2,TEAL),(3,GOLD)]:
        y=335+(row-1)*165
        rounded(im,(252,y-57,1810,y+57),color,width=3,alpha=q)
    arrow(im,(310,774),(1750,774),TEAL,3,p)
    text(im,'같은 바깥 껍질 · 달라지는 전자 수',1040,835,39,TEAL,progress(s,t,2))
    footer(im,'첫 세 주기의 중성 원자 · 껍질은 같은 n을 갖는 전자 상태의 묶음')


def draw_families(im,s,t):
    p=progress(s,t,1)
    q=progress(s,t,2)
    x,y,cw,ch=190,310,82,115
    table(im,x=x,y=y,cw=cw,ch=ch,max_z=18,highlight={3,11} if q>.5 else None)
    for col in range(1,19):
        main=col in (1,2) or col>=13
        xx=x+(col-.5)*cw-2
        text(im,f'{col}족',xx,270,22,GOLD if main else MUTED)
        if main:
            count=col if col<=2 else col-10
            text(im,f'{count}개',xx,739,27,TEAL,p)
            for j in range(count): dot(im,xx+(j-(count-1)/2)*8,779,3,TEAL,p)
    text(im,'주족 원소의 바깥 전자 수',960,690,32,FG,p)
    text(im,'He: 2개',x+17.5*cw-2,y+93,20,GOLD)
    arrow(im,(1702,335),(1702,635),GOLD,4)
    text(im,'같은 족',1780,475,27,GOLD)
    text(im,'He는 2개 · 전이 원소에는 이 대응을 적용하지 않음',960,835,30,MUTED,p)
    footer(im,'Li와 Na: 바깥 전자 1개 → 비슷한 결합과 반응',FG,q)


def draw_fourth(im,s,t):
    p=progress(s,t,0,3)
    for y,orb,color,n in [(710,'3p',PINK,6),(535,'4s',TEAL,1+int(progress(s,t,2)>.5)),(365,'3d',VIOLET,int(progress(s,t,2)>.85))]:
        slots(im,690,y,orb,n,cell=93,alpha=1 if orb=='3p' else p)
        line(im,[(1210,y),(1460,y)],color,2)
    text(im,'Ar → K → Ca → Sc',1000,245,43,FG)
    arrow(im,(500,760),(500,300),MUTED,2)
    text(im,'채움 기록',380,520,32,MUTED)
    text(im,'껍질 번호 ≠ 채움 순서',1010,835,43,GOLD,progress(s,t,1))
    footer(im,'실제 에너지 준위도 아님 · 4s와 3d의 상대 에너지는 원자와 점유에 따라 달라집니다')


def draw_blocks(im,s,t):
    q=progress(s,t,1,2)
    for name,x,count,color in [('s',230,2,TEAL),('d',420,10,VIOLET),('p',1340,6,PINK)]:
        for j in range(count):
            a=1 if name=='d' else q
            rounded(im,(x+j*83,425,x+j*83+75,540),color,tint(color,.09),2,4,a)
        text(im,name,x+(count*83-8)/2,335,55,color,1 if name=='d' else q)
        text(im,count,x+(count*83-8)/2,625,75,color,1 if name=='d' else q)
    text(im,'2 + 10 + 6 = 18',960,795,64,FG,q)
    footer(im,'블록의 너비는 오비탈 수용량을 반영 · 실제 배치에는 예외가 있습니다',alpha=progress(s,t,2))


def draw_fblock(im,s,t):
    p=progress(s,t,1,3.5)
    q=progress(s,t,2)
    # A labelled schematic 14-state block grows horizontally, then folds beneath.
    slots(im,640,305,'f',round(min(1,sweep(s,t,0)*1.25)*14),cell=92,color=BLUE)
    text(im,'7 × 2 = 14',960,405,50,BLUE)
    for j in range(32):
        c=TEAL if j<2 else BLUE if j<16 else VIOLET if j<26 else PINK
        x0=115+j*53; y0=535
        if 2<=j<16: x1=440+(j-2)*71;y1=730
        else: x1=310+(j if j<2 else j-14)*72;y1=535
        x=lerp(x0,x1,p);y=lerp(y0,y1,p)
        rounded(im,(x,y,x+47,y+62),c,tint(c,.12),2,3)
    text(im,'가로로 펼친 구조',960,490,28,MUTED,1-p)
    text(im,'아래로 옮겨도 같은 표의 일부',960,855,35,FG,q)
    footer(im,'구조 모식도 · 실제 아래 계열 La–Lu, Ac–Lr는 각각 15원소이며 f 정원 14와 구별합니다')


def draw_helium(im,s,t):
    table(im,x=100,y=275,cw=90,ch=150,max_z=18,highlight={2,10,18})
    p=progress(s,t,1)
    slots(im,580,640,'1s',2,cell=100,alpha=1-p*.75)
    text(im,'He : 1s²',730,440,59,TEAL)
    text(im,'닫힌 첫 껍질',730,525,37,TEAL)
    text(im,'18족',1670,225,33,GOLD)
    text(im,'같은 화학적 성질',1060,815,44,GOLD,p)
    footer(im,'He는 s 전자배치를 가지며, 화학적 성질에 따라 18족에 놓입니다')


def draw_outer(im,s,t):
    p=progress(s,t,1,2);q=progress(s,t,2,2)
    cloud(im,560,510,640,'2s',TEAL)
    cloud(im,560,510,235,'1s',MUTED,.6)
    nucleus(im,560,510,11,28)
    text(im,'Na',560,275,55,FG)
    line(im,[(560,480),(670,350),(780,350)],MUTED,2,p)
    text(im,'안쪽: 핵에 단단히 묶임',920,350,29,MUTED,p,maxw=380)
    line(im,[(730,580),(810,735),(910,735)],TEAL,2,p)
    text(im,'바깥: 넓게 퍼진 분포',680,803,34,TEAL,p)
    text(im,'안쪽 10개 + 바깥 1개',560,861,30,FG)
    text(im,'원자가 전자: 결합에 참여하는 전자',1390,265,35,TEAL,maxw=760)
    for center,body in [(1180,'주고받기'),(1620,'공유하기')]:
        rounded(im,(center-185,405,center+185,792),GRID,width=2,r=16,alpha=q)
        text(im,body,center,450,37,FG,q)
    for x in (1080,1280):
        cloud(im,x,595,170,'1s',MUTED,q*.6)
        nucleus(im,x,595,size=14,alpha=q,labelled=False)
    arrow(im,(1090,538),(1270,538),TEAL,3,q)
    dot(im,lerp(1090,1270,sweep(s,t,2)),538,8,TEAL,q)
    text(im,'전자 이동',1180,735,29,TEAL,q)
    for x in (1560,1680):
        cloud(im,x,595,280,'1s',TEAL,q)
        nucleus(im,x,595,size=14,alpha=q,labelled=False)
    text(im,'두 원자에 걸친 분포',1620,735,26,TEAL,q,maxw=330)
    footer(im,'주족 원소에서 바깥 전자가 주로 결합에 참여 · 구름과 결합은 정성적 도식')


def draw_shield(im,s,t):
    cloud(im,690,520,610,'2s',TEAL)
    cloud(im,690,520,270,'1s',MUTED,.7)
    nucleus(im,690,520,11,32)
    dot(im,980,470,11,TEAL)
    arrow(im,(950,470),(770,510),GOLD,7)
    p=progress(s,t,1)
    arrow(im,(790,560),(941,507),PINK,5,p)
    text(im,'핵까지의 거리 + 안쪽 전자의 차폐',1370,325,35,GOLD,maxw=780)
    text(im,'안쪽 전자가 인력을 일부 상쇄',1370,455,36,PINK,maxw=760)
    text(im,'바깥 전자가 더 쉽게 재배치',1370,600,38,TEAL,p,maxw=760)
    text(im,'같은 족도 반응의 정도는 다름',1370,755,35,FG,progress(s,t,2),maxw=760)
    footer(im,'차폐는 전기적 상호작용의 효과 · 전자를 막는 물리적인 벽이 아닙니다')


def draw_across(im,s,t):
    p=progress(s,t,1,3)
    for j,z in enumerate([3,4,5,6,7,8,9]):
        x=295+j*220
        size=lerp(260,300-j*24,p)
        cloud(im,x,440,size)
        nucleus(im,x,440,z,17)
        text(im,SYMBOLS[z-1],x,300,39,FG)
    arrow(im,(270,640),(1600,640),GOLD,4)
    text(im,'핵전하 증가 → 대체로 더 강하게 붙잡는다',960,715,40,GOLD,p)
    q=progress(s,t,2)
    text(im,'같은 족 아래로: 새 껍질 → 대체로 더 큰 원자',960,833,38,TEAL,q)
    footer(im,'주족의 정성적 경향 · 그려진 구름의 반지름은 측정값이 아닙니다')


def draw_ionization(im,s,t):
    p=progress(s,t,1,4)
    cloud(im,540,500,465,'2s');nucleus(im,540,500,11,30)
    text(im,'Na(g)' if p<.7 else 'Na⁺(g)',540,770,55,FG)
    x=lerp(710,1520,p); y=lerp(430,360,p)
    dot(im,x,y,12,TEAL);text(im,'e⁻',x,y-45,43,TEAL)
    arrow(im,(790,515),(1370,405),TEAL,3,p)
    text(im,'e⁻',1520,770,53,FG,p)
    text(im,'에너지 공급: 5.14 eV',1050,290,47,GOLD,p)
    text(im,'Na(g) → Na⁺(g) + e⁻',960,850,35,MUTED)
    footer(im,'NIST ASD · Na의 제1 이온화 에너지 5.13907696 eV')


def draw_graph(im,s,t):
    milestones=[(0,1),(word_time(s,0,'헬륨')+.6,2),(word_time(s,0,'리튬')+.6,3),
                (word_time(s,0,'네온')+.6,10),(word_time(s,0,'나트륨')+.6,11),
                (word_time(s,1,'아르곤')+.6,18),(word_time(s,1,'칼륨')+.6,19),
                (s['beats_timed'][1]['start']+s['beats_timed'][1]['duration'],20)]
    z=float(np.interp(t,[x[0] for x in milestones],[x[1] for x in milestones]))
    fraction=(z-1)/19
    energy_graph(im,fraction)
    footer(im,'NIST ASD 5.12 · 중성 원자 H–Ca · 제1 이온화 에너지 · 단위 eV')


def draw_exceptions(im,s,t):
    pts=energy_graph(im,1,{4,5,7,8})
    p=progress(s,t,1)
    for a,b in [(4,5),(7,8)]:
        mid=((pts[a-1][0]+pts[b-1][0])/2,(pts[a-1][1]+pts[b-1][1])/2)
        ring(im,*mid,57,PINK,3)
    text(im,'새 p 오비탈',450,300,28,PINK,p)
    text(im,'p 오비탈의 짝짓기',885,365,28,PINK,p)
    footer(im,'Be > B, N > O의 작은 하강도 원자 구조를 알려 주는 단서입니다')


def draw_transfer(im,s,t):
    p=progress(s,t,0,4)
    for x,z,kind in [(520,11,'2s'),(1420,17,'2p')]:
        cloud(im,x,485,440,kind,TEAL if z==11 else PINK)
        nucleus(im,x,485,z,28)
    dot(im,lerp(700,1270,p),440-100*math.sin(p*math.pi),11,TEAL)
    text(im,'Na' if p<.8 else 'Na⁺',520,730,60,TEAL)
    text(im,'Cl' if p<.8 else 'Cl⁻',1420,730,60,PINK)
    arrow(im,(815,390),(1100,390),TEAL,3)
    text(im,'전자 이동',960,310,37,FG)
    text(im,'전자 이동 ≠ 결합의 전체 설명',960,825,45,GOLD,progress(s,t,1))
    footer(im,'고립된 기체 원자 사이 전자 이동에는 에너지 비용이 남습니다')


def draw_lattice(im,s,t):
    p=progress(s,t,0,4)
    cx,cy=670,530;spacing=98
    for row in range(5):
        for col in range(6):
            x=cx+(col-2.5)*spacing;y=cy+(row-2)*spacing
            a=clamp(p*2-(abs(col-2.5)+abs(row-2))/5)
            c=TEAL if (row+col)%2==0 else PINK
            dot(im,x,y,29,c,a)
            text(im,'+' if c==TEAL else '−',x,y,28,BG,a)
            if col<5: line(im,[(x+34,y),(x+spacing-34,y)],GRID,2,a)
            if row<4: line(im,[(x,y+34),(x,y+spacing-34)],GRID,2,a)
    text(im,'Na⁺',475,835,35,TEAL)
    text(im,'Cl⁻',835,835,35,PINK)
    q=progress(s,t,1)
    text(im,'많은 이온의 상호작용',1410,365,42,FG,q,maxw=700)
    arrow(im,(1410,440),(1410,625),GOLD,6,q)
    text(im,'전체 에너지 감소',1410,705,44,GOLD,q)
    footer(im,'NaCl 결정 격자의 2D 단면 도식 · 독립적인 NaCl 분자들의 배열이 아닙니다')


@lru_cache(128)
def bond_cloud(separation):
    yy,xx=np.mgrid[-235:235,-380:380]
    r1=np.sqrt((xx+separation/2)**2+yy**2)/65
    r2=np.sqrt((xx-separation/2)**2+yy**2)/65
    density=(np.exp(-r1)+np.exp(-r2))**2
    a=np.zeros((470,760,4),np.uint8)
    a[:,:,:3]=rgb(TEAL)
    edge=np.minimum(np.clip((380-abs(xx))/45,0,1),np.clip((235-abs(yy))/45,0,1))
    a[:,:,3]=np.clip((density/density.max())**.6*220*edge,0,220).astype(np.uint8)
    return Image.fromarray(a)


def draw_covalent(im,s,t):
    p=sweep(s,t,0)
    separation=lerp(390,175,ease(p))
    tile=bond_cloud(round(separation/4)*4)
    im.paste(tile,(200,205),tile)
    for x in (580-separation/2,580+separation/2):
        nucleus(im,x,440,1,18)
    text(im,'H₂',580,715,61,FG)
    q=progress(s,t,1)
    x0,y0=1060,740;ww,hh=645,405
    arrow(im,(x0,y0),(x0+ww+20,y0),MUTED,2,q)
    arrow(im,(x0,y0),(x0,y0-hh-25),MUTED,2,q)
    # Morse-shaped qualitative potential; no numerical molecular result implied.
    rs=np.linspace(.64,3.7,220)
    potential=(1-np.exp(-1.6*(rs-1.2)))**2-1
    points=[(x0+(r-.5)/3.3*ww,y0-200-180*v) for r,v in zip(rs,potential)]
    curve(im,points,GOLD,4,q)
    text(im,'전체 에너지',x0+110,260,30,GOLD,q)
    text(im,'핵 사이 거리',x0+ww-40,y0+61,31,MUTED,q)
    q2=progress(s,t,2)
    px=x0+(.7/3.3)*ww;py=y0-20
    dot(im,px,py,9,TEAL,q2)
    text(im,'안정한 거리',px+70,py-140,29,TEAL,q2)
    line(im,[(px,py-112),(px,py-18)],TEAL,2,q2)
    footer(im,'전자밀도와 에너지 곡선은 정성적 도식 · 수치 분자 계산 결과가 아닙니다')


def draw_octet(im,s,t):
    text(im,'“원자는 8개를 원한다”',960,320,63,MUTED)
    line(im,[(550,320),(1370,320)],RED,5,progress(s,t,0))
    p=progress(s,t,1)
    slots(im,650,550,'s',2,cell=110,alpha=p)
    slots(im,1010,550,'p',6,cell=110,alpha=p)
    text(im,'많은 주족 화합물에서 유용한 경험칙',960,700,40,TEAL,p)
    text(im,'허용되는 상태 + 전기적 상호작용 + 에너지',960,835,40,FG,progress(s,t,2))
    footer(im,'옥텟은 보편적인 원인이나 모든 원소에 적용되는 법칙이 아닙니다')


def draw_quiz_family(im,s,t):
    element_card(im,19,960,345,160,155,show_name=True)
    element_card(im,11,570,650,180,170,show_name=True)
    element_card(im,18,1350,650,180,170,show_name=True)
    p=progress(s,t,1)
    arrow(im,(850,460),(650,540),TEAL,5,p)
    rounded(im,(455,545,685,755),TEAL,width=4,alpha=p)
    text(im,'4s¹',1230,345,50,TEAL)
    text(im,'3s¹',365,650,41,TEAL,p)
    text(im,'3s² 3p⁶',1610,650,39,MUTED,p)
    q=progress(s,t,2)
    text(im,'K  4.34 eV  <  Na  5.14 eV',960,870,38,GOLD,q)
    if t<s['beats_timed'][1]['start']: footer(im,'잠시 멈추고 바깥 전자배치를 떠올려 보세요',FG)


def draw_quiz_period(im,s,t):
    text(im,'첫 주기',500,295,43,FG)
    text(im,'둘째 주기',1300,295,43,FG)
    p=progress(s,t,1)
    slots(im,500,450,'1s',2,cell=110,labels=False,alpha=p)
    slots(im,1110,450,'2s',2,cell=90,labels=False,alpha=p)
    slots(im,1340,450,'2p',6,cell=90,labels=False,alpha=p)
    text(im,'1 × 2 = 2',500,670,62,TEAL,p)
    text(im,'(1 + 3) × 2 = 8',1300,670,62,GOLD,p,maxw=820)
    text(im,'껍질의 최대 정원 ≠ 모든 주기의 길이',960,845,41,FG,progress(s,t,2))
    if t<s['beats_timed'][1]['start']: footer(im,'한 오비탈에 들어가는 전자 수는?',FG)


def draw_finale(im,s,t):
    table(im,x=175,y=240,cw=86,ch=48)
    p=progress(s,t,1)
    text(im,'주기 ↔ 전자 껍질',670,747,34,GOLD)
    text(im,'족 ↔ 바깥 전자배치',1260,747,34,TEAL)
    for j,(body,color) in enumerate([('바깥 전자',GOLD),('결합과 반응',TEAL),('물질 예측',PINK)]):
        x=490+j*475
        text(im,body,x,850,43,color,p)
        if j<2: arrow(im,(x+155,850),(x+315,850),MUTED,3,p)
    footer(im,'원소의 위치에서 출발해, 어떤 물질을 만들 수 있을지 생각한다',FG,progress(s,t,2))
    text(im,'구성 참고: EBS 취미는 과학 49화 · 과학 자료: IUPAC · NIST ASD · RSC',960,951,20,MUTED,progress(s,t,2))


DRAW={'mystery':draw_mystery,'repetition':draw_repetition,'protons':draw_protons,
      'electrons':draw_electrons,'attraction':draw_attraction,'waves':draw_waves,
      'cloud':draw_cloud,'orbitals':draw_orbitals,'pauli':draw_pauli,'capacities':draw_capacities,
      'first':draw_filling,'second':draw_filling,'third':draw_filling,'fold':draw_fold,'families':draw_families,
      'fourth':draw_fourth,'blocks':draw_blocks,'fblock':draw_fblock,'helium':draw_helium,
      'outer':draw_outer,'shield':draw_shield,'across':draw_across,'ionization':draw_ionization,
      'graph':draw_graph,'exceptions':draw_exceptions,'transfer':draw_transfer,'lattice':draw_lattice,
      'covalent':draw_covalent,'octet':draw_octet,'quiz_family':draw_quiz_family,
      'quiz_period':draw_quiz_period,'finale':draw_finale}


def frame(index,t):
    s=timeline()['scenes'][index]
    im=backdrop().copy()
    text(im,s['chapter'],85,66,25,MUTED,anchor='left')
    text(im,f'{index+1:02} / {len(timeline()["scenes"]):02}',1835,66,23,MUTED,anchor='right')
    text(im,s['title'],960,155,58,FG)
    DRAW[s['key']](im,s,t)
    line(im,[(85,980),(1835,980)],GRID,1)
    line(im,[(85,980),(85+1750*(s['start']+t)/timeline()['duration'],980)],TEAL,3)
    fade=min(ease(t/.3),ease((s['duration']-t)/.3))
    if fade<1: im=Image.blend(Image.new('RGB',(W,H),BG),im,fade)
    return im


def signature(index):
    h=hashlib.sha256()
    for path in [Path(__file__),ROOT/'lesson.py',ROOT/'facts.py',ROOT/'facts.json',Path(KFONT),Path(MFONT)]:
        h.update(path.read_bytes())
    h.update(json.dumps(timeline()['scenes'][index],ensure_ascii=False,sort_keys=True).encode())
    return h.hexdigest()


def render_one(index):
    s=timeline()['scenes'][index]
    folder=ROOT/'clips';folder.mkdir(exist_ok=True)
    target=folder/f'{index:02}.mp4';meta=target.with_suffix('.json');sig=signature(index)
    if target.exists() and meta.exists() and json.loads(meta.read_text()).get('signature')==sig:
        print(f'Cached {index:02} {s["key"]}',flush=True);return
    part=target.with_suffix('.part.mp4')
    proc=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo',
        '-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-an','-c:v','libx264',
        '-threads','2','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(part)],stdin=subprocess.PIPE)
    try:
        for n in range(s['frames']): proc.stdin.write(frame(index,n/FPS).tobytes())
        proc.stdin.close()
        if proc.wait(): raise RuntimeError(f'FFmpeg failed at scene {index}')
    except BaseException:
        proc.kill();proc.wait();raise
    part.replace(target)
    meta.write_text(json.dumps(dict(signature=sig,frames=s['frames'])))
    print(f'Rendered {index:02} {s["key"]}: {s["duration"]:.2f}s',flush=True)


def render(only=None,jobs=4):
    if only is not None: render_one(only)
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            list(pool.map(render_one,range(len(timeline()['scenes']))))


def preview(only=None,jobs=1):
    out=ROOT/'preview';out.mkdir(exist_ok=True)
    ids=[only] if only is not None else list(range(len(timeline()['scenes'])))
    sheet=Image.new('RGB',(4*480,math.ceil(len(ids)/4)*270),BG)
    for j,i in enumerate(ids):
        s=timeline()['scenes'][i]
        times=[b['start']+min(b['duration']*.7,5.) for b in s['beats_timed']]
        for k,t in enumerate(times): frame(i,t).save(out/f'{i:02}-{k}.png')
        im=frame(i,times[-1]);sheet.paste(im.resize((480,270)),((j%4)*480,(j//4)*270))
    sheet.save(out/'contact-sheet.jpg',quality=92)
    print(out/'contact-sheet.jpg')
