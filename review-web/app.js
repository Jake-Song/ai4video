'use strict';

const $ = (id) => document.getElementById(id);
const storageKey = 'ai4video-cut-review-v1';
function readStorage(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function writeStorage(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private storage may be disabled */ }
}
const legacySaved = readStorage('triton-cut-review-v1', {});
let saved = readStorage(storageKey, legacySaved);
let notes = {}, noteRecords = {}, pendingNotes = {};
const initialQuery = new URLSearchParams(location.search);
const state = {
  projectId: initialQuery.get('project') || saved.projectId || null,
  manifest: null, sceneId: Number(initialQuery.get('scene') || saved.sceneId || 1),
  cutKey: initialQuery.get('cut') || saved.cutKey || null, t: 0,
  playing: false, anchorT: 0, anchorClock: 0, raf: 0, lastFrameRequest: 0,
  frameInFlight: false, pendingFrame: false, requestSerial: 0,
  frameURL: null, refreshing: false, audioKey: null, audio: new Audio(),
  notesReady: false, notesVersion: null, notesSyncing: false, noteInFlight: false,
};
state.audio.preload = 'auto';
if (['480', '960', '1280', '1920'].includes(String(saved.quality))) $('quality').value = saved.quality;
if (['0.5', '1', '1.5', '2'].includes(String(saved.speed))) $('speed').value = saved.speed;
$('sound').checked = saved.sound !== false;
$('loop').checked = saved.loop !== false;

function scene() { return state.manifest?.scenes.find((s) => s.index === state.sceneId); }
function cut() { return scene()?.cuts.find((c) => c.key === state.cutKey); }
function frameStep() { return 1 / (state.manifest?.fps || 30); }
function cutMax(c) { return c.start + Math.max(0, c.duration - frameStep()); }
function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
function stamp(seconds) {
  const centis = Math.max(0, Math.round(seconds * 100));
  return `${String(Math.floor(centis / 6000)).padStart(2, '0')}:${String(Math.floor(centis / 100) % 60).padStart(2, '0')}.${String(centis % 100).padStart(2, '0')}`;
}
function remember() {
  const value={projectId:state.projectId,sceneId: state.sceneId, cutKey: state.cutKey,
    offset: cut() ? state.t - cut().start : 0,
    quality: $('quality').value, speed: $('speed').value,
    sound: $('sound').checked, loop: $('loop').checked};
  writeStorage(storageKey,value);
  if(state.projectId) writeStorage(`${storageKey}:${state.projectId}:selection`,value);
}
function noteStorage(kind,project=state.projectId){return `${storageKey}:${project}:${kind}`;}
function projectQuery(values={}){return new URLSearchParams({project:state.projectId,...values});}
function setStatus(message, kind = '') {
  $('status').textContent = message;
  $('status').className = `status ${kind}`;
}
function showError(message) {
  $('error').textContent = `미리보기를 갱신하지 못했습니다. 마지막 화면을 유지합니다.\n${message}`;
  $('error').hidden = false;
  setStatus('변경 내용을 확인해 주세요', 'error-status');
}
function clearError() { $('error').hidden = true; }

function renderCutList() {
  document.body.dataset.project=state.projectId;
  const nav = $('cuts');
  nav.replaceChildren();
  for (const s of state.manifest.scenes) {
    const group = document.createElement('section');
    group.className = 'scene-group';
    const heading = document.createElement('h2');
    heading.append(`장면 ${String(s.number ?? s.index).padStart(2, '0')} · ${Math.round(s.duration)}초`);
    const title = document.createElement('span');
    title.textContent = s.title;
    heading.append(title);
    group.append(heading);
    for (const c of s.cuts) {
      const button = document.createElement('button');
      button.className = 'cut';
      button.type = 'button';
      button.dataset.scene = s.index;
      button.dataset.key = c.key;
      button.dataset.cut = c.id;
      const id = document.createElement('span');
      id.className = 'cut-number';
      id.textContent = c.id;
      const name = document.createElement('span');
      name.className = 'cut-name';
      name.textContent = c.label;
      const duration = document.createElement('span');
      duration.className = 'cut-duration';
      duration.textContent = `${stamp(c.start)} · ${c.duration.toFixed(1)}초`;
      name.append(duration);
      button.append(id, name);
      button.addEventListener('click', () => selectCut(s.index, c.key));
      group.append(button);
    }
    nav.append(group);
  }
  $('cut-count').textContent = `${state.manifest.cut_count}개 컷`;
}

function paintSelection() {
  const s = scene(), c = cut();
  if (!c) return;
  $('scene-title').textContent = `장면 ${s.number ?? s.index} · ${s.title}`;
  $('cut-title').textContent = c.label;
  $('cut-id').textContent = c.id;
  $('narration').textContent = c.text;
  $('note').value = typeof notes[c.id] === 'string' ? notes[c.id] : '';
  paintNoteStatus();
  $('seek').max = Math.max(0, c.duration - frameStep());
  $('seek').step = frameStep();
  for (const button of document.querySelectorAll('.cut')) {
    button.setAttribute('aria-current', String(Number(button.dataset.scene) === s.index && button.dataset.key === c.key));
    button.classList.toggle('has-note', Boolean(notes[button.dataset.cut]));
  }
  const stale = c.audio_stale;
  $('audio-notice').hidden = !(stale || !c.audio_url);
  $('audio-notice').textContent = stale
    ? '대본이 변경된 컷입니다. 새 음성을 만들기 전까지 이 컷의 음성은 재생하지 않습니다.'
    : '이 컷의 음성 파일이 없습니다. 화면 미리보기는 사용할 수 있습니다.';
  $('play').disabled = false;
  $('seek').disabled = false;
  $('save-frame').disabled = false;
  remember();
  paintTime();
}

function paintTime() {
  const c = cut();
  if (!c) return;
  $('seek').value = clamp(state.t - c.start, 0, c.duration);
  $('cut-position').textContent = `${stamp(state.t - c.start)} / ${stamp(c.duration)}`;
  $('scene-position').textContent = `장면 ${stamp(state.t)} / ${stamp(scene().duration)}`;
  $('play').textContent = state.playing ? 'Ⅱ 정지' : '▶ 재생';
  $('play').setAttribute('aria-label', state.playing ? '일시정지' : '재생');
}

function pause() {
  state.playing = false;
  cancelAnimationFrame(state.raf);
  state.audio.pause();
  paintTime();
  if (state.manifest) remember();
}

function selectCut(sceneId, key) {
  pause();
  state.sceneId = sceneId;
  state.cutKey = key;
  state.t = cut().start;
  state.audioKey = null;
  paintSelection();
  queueFrame();
}

function adjacentCut(direction) {
  if (!state.manifest) return;
  const all = state.manifest.scenes.flatMap((s) => s.cuts.map((c) => ({scene: s.index, ...c})));
  const index = all.findIndex((c) => c.scene === state.sceneId && c.key === state.cutKey);
  const next = all[clamp(index + direction, 0, all.length - 1)];
  selectCut(next.scene, next.key);
}

function seekTo(relativeTime) {
  if (!cut()) return;
  pause();
  state.t = clamp(cut().start + relativeTime, cut().start, cutMax(cut()));
  paintTime();
  queueFrame();
}

function syncAudio(force = false) {
  const c = cut();
  const elapsed = state.t - c.start + (c.audio_offset ?? -.2);
  if (!state.playing || !$('sound').checked || !c.audio_url || elapsed < 0 || elapsed >= c.speech_duration) {
    state.audio.pause();
    return;
  }
  const key = `${state.manifest.version}:${c.audio_url}`;
  if (state.audioKey !== key) {
    state.audio.pause();
    state.audioKey = key;
    const url=new URL(c.audio_url,location.href);
    url.searchParams.set('v',state.manifest.version);
    state.audio.src=url.href;
    state.audio.load();
    force = true;
  }
  state.audio.playbackRate = Number($('speed').value);
  if (force || Math.abs(state.audio.currentTime - elapsed) > .25) {
    try { state.audio.currentTime = elapsed; } catch { /* metadata will trigger another sync */ }
  }
  if (state.audio.paused) {
    state.audio.play().catch((error) => {
      if (error.name === 'NotAllowedError') {
        $('audio-notice').hidden = false;
        $('audio-notice').textContent = '음성을 켜고 재생 버튼을 다시 눌러 주세요.';
      }
    });
  }
}
state.audio.addEventListener('loadedmetadata', () => syncAudio(true));

function play() {
  if (!cut()) return;
  if (state.t >= cutMax(cut())) state.t = cut().start;
  state.playing = true;
  state.anchorT = state.t;
  state.anchorClock = performance.now();
  state.lastFrameRequest = 0;
  paintTime();
  syncAudio(true);
  state.raf = requestAnimationFrame(tick);
}

function tick(now) {
  if (!state.playing) return;
  let target = state.anchorT + (now - state.anchorClock) * Number($('speed').value) / 1000;
  const c = cut();
  if ($('loop').checked && target >= c.start + c.duration) {
    target = c.start + ((target - c.start) % c.duration);
    state.anchorT = target;
    state.anchorClock = now;
  } else if (!$('loop').checked && target >= scene().duration) {
    state.t = scene().duration - frameStep();
    pause();
    queueFrame();
    return;
  }
  state.t = target;
  if (!$('loop').checked && (target < c.start || target >= c.start + c.duration)) {
    const next = scene().cuts.find((b) => target >= b.start && target < b.start + b.duration);
    if (next) { state.cutKey = next.key; paintSelection(); }
  }
  paintTime();
  syncAudio();
  if (now - state.lastFrameRequest >= 1000 / 15) {
    queueFrame();
    state.lastFrameRequest = now;
  }
  state.raf = requestAnimationFrame(tick);
}

function queueFrame() {
  if (!state.manifest || !cut()) return;
  state.requestSerial += 1;
  state.pendingFrame = true;
  if (!state.frameInFlight) void loadFrame();
}

async function loadFrame() {
  if (!state.pendingFrame || !cut()) return;
  state.frameInFlight = true;
  state.pendingFrame = false;
  const request = {serial: state.requestSerial, project:state.projectId, scene: state.sceneId, cut: state.cutKey,
    t: state.t, version: state.manifest.version, width: $('quality').value};
  const query = new URLSearchParams({project:request.project,scene: request.scene, t: request.t,
    width: request.width, version: request.version});
  try {
    const response = await fetch(`/api/frame?${query}`, {cache: 'no-store'});
    if (!response.ok) {
      const body = await response.json();
      if (response.status === 409) { void refresh(); return; }
      throw new Error(body.error || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    // During playback show the most recent available frame; scrubbing discards stale responses.
    if (state.projectId !== request.project || state.sceneId !== request.scene || state.cutKey !== request.cut || state.manifest.version !== request.version ||
        (!state.playing && request.serial !== state.requestSerial)) return;
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.src = url;
    await image.decode();
    if (state.projectId !== request.project || state.sceneId !== request.scene || state.cutKey !== request.cut || state.manifest.version !== request.version) {
      URL.revokeObjectURL(url); return;
    }
    const old = state.frameURL;
    $('frame').src = url;
    $('frame').dataset.scene = request.scene;
    $('frame').dataset.time = request.t;
    $('frame').dataset.frame = response.headers.get('X-Frame');
    $('frame').dataset.revision = request.version;
    state.frameURL = url;
    if (old) URL.revokeObjectURL(old);
    $('loading').hidden = true;
  } catch (error) {
    pause();
    showError(error.message);
  } finally {
    state.frameInFlight = false;
    if (state.pendingFrame) void loadFrame();
  }
}

async function refresh(force = false) {
  if (state.refreshing) return;
  state.refreshing = true;
  const requestedProject=state.projectId;
  if (force) { pause(); setStatus('변경 내용 확인 중'); }
  try {
    const response = await fetch(`/api/state?${projectQuery(force?{force:1}:{})}`, {cache: 'no-store'});
    const manifest = await response.json();
    if(state.projectId!==requestedProject) return;
    if (!response.ok) throw new Error(manifest.error || `HTTP ${response.status}`);
    if (state.manifest?.app_version && manifest.app_version !== state.manifest.app_version) {
      remember();
      location.reload();
      return;
    }
    if (state.manifest?.css_version && manifest.css_version !== state.manifest.css_version) {
      document.querySelector('link[rel="stylesheet"]').href = `/style.css?v=${manifest.css_version}`;
      state.manifest.css_version = manifest.css_version;
      setStatus('화면 변경 반영됨');
    }
    if (state.manifest?.version === manifest.version && !force) {
      if(!state.notesReady || state.notesVersion!==manifest.notes_version){
        if(await loadNotes(!state.notesReady)) state.notesVersion=manifest.notes_version;
      }
      void flushNotes();
      return;
    }
    const previous = cut();
    const offset = previous ? state.t - previous.start : Number(initialQuery.get('t') ?? saved.offset ?? 0);
    pause();
    state.manifest = manifest;
    document.title=`컷 미리보기 · ${manifest.title}`;
    if (!scene()) state.sceneId = manifest.scenes[0].index;
    if (!cut()) state.cutKey = scene().cuts[0].key;
    state.t = clamp(cut().start + offset, cut().start, cutMax(cut()));
    state.audioKey = null;
    renderCutList();
    paintSelection();
    $('note').disabled=false;
    clearError();
    setStatus('저장한 변경 자동 반영');
    queueFrame();
    if(await loadNotes(!state.notesReady)) state.notesVersion=manifest.notes_version;
  } catch (error) {
    pause();
    showError(error.message);
  } finally {
    state.refreshing = false;
  }
}

$('play').addEventListener('click', () => state.playing ? pause() : play());
$('seek').addEventListener('pointerdown', pause);
$('seek').addEventListener('input', (event) => seekTo(Number(event.target.value)));
$('prev').addEventListener('click', () => adjacentCut(-1));
$('next').addEventListener('click', () => adjacentCut(1));
$('step-back').addEventListener('click', () => seekTo(state.t - cut().start - frameStep()));
$('step-forward').addEventListener('click', () => seekTo(state.t - cut().start + frameStep()));
$('reload').addEventListener('click', () => void refresh(true));
$('quality').addEventListener('change', () => { remember(); queueFrame(); });
$('sound').addEventListener('change', () => { remember(); syncAudio(true); });
$('loop').addEventListener('change', remember);
$('speed').addEventListener('change', () => {
  state.anchorT = state.t;
  state.anchorClock = performance.now();
  remember();
  syncAudio(true);
});

let noteTimer;
$('note').addEventListener('focus',pause);
$('note').addEventListener('input', () => {
  const c = cut();
  if (!c) return;
  notes[c.id] = $('note').value;
  pendingNotes[c.id]={cut_id:c.id,text:$('note').value,scene_time:state.t};
  writeStorage(noteStorage('notes'),notes);
  writeStorage(noteStorage('pending'),pendingNotes);
  paintNoteStatus();
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => {
    void flushNotes();
  }, 250);
  for (const button of document.querySelectorAll('.cut')) button.classList.toggle('has-note', Boolean(notes[button.dataset.cut]));
});

$('copy').addEventListener('click', async () => {
  const c = cut();
  if (!c) return;
  pause();
  const body = `프로젝트 ${state.projectId}\n컷 ${c.id} · ${c.label}\n장면 ${scene().number ?? state.sceneId}의 ${stamp(state.t)} / 컷 안에서 ${stamp(state.t - c.start)}\n수정 요청: ${$('note').value.trim() || '이 위치의 화면을 수정해 주세요.'}`;
  try {
    await navigator.clipboard.writeText(body);
    $('copy').textContent = '복사됨';
    setTimeout(() => { $('copy').textContent = '위치·메모 복사'; }, 1500);
  } catch {
    $('copy').textContent = '복사하지 못했습니다';
    setTimeout(() => { $('copy').textContent = '위치·메모 복사'; }, 2000);
  }
});

$('save-frame').addEventListener('click', async () => {
  if (!cut()) return;
  pause();
  $('save-frame').disabled = true;
  try {
    const query = projectQuery({scene: state.sceneId, t: state.t, width: 1920,
      format: 'png', version: state.manifest.version});
    const response = await fetch(`/api/frame?${query}`);
    if (!response.ok) throw new Error((await response.json()).error);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = url;
    link.download = `${state.projectId}-cut-${cut().id}-frame-${Math.round(state.t / frameStep())}.png`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { showError(error.message); }
  finally { $('save-frame').disabled = false; }
});

document.addEventListener('keydown', (event) => {
  if (event.target.closest('textarea,select,[contenteditable="true"]') ||
      (event.target.tagName === 'INPUT' && event.target.type !== 'range')) return;
  if (!cut()) return;
  if (event.code === 'Space') {
    event.preventDefault();
    state.playing ? pause() : play();
  } else if (event.code === 'ArrowLeft' || event.code === 'ArrowRight') {
    event.preventDefault();
    const amount = event.shiftKey ? 1 : frameStep();
    seekTo(state.t - cut().start + (event.code === 'ArrowRight' ? amount : -amount));
  }
});
document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });
window.addEventListener('pagehide', () => {
  pause();
  writeStorage(noteStorage('notes'), notes);
  writeStorage(noteStorage('pending'), pendingNotes);
  if (state.frameURL) URL.revokeObjectURL(state.frameURL);
});

function paintNoteStatus(){
  const c=cut(); if(!c) return;
  const label=$('note-saved');
  label.classList.toggle('save-error',Boolean(state.noteFailure && pendingNotes[c.id]));
  if(pendingNotes[c.id]) label.textContent=state.noteFailure?'브라우저에 임시 저장':'프로젝트 저장 중';
  else if(noteRecords[c.id]) label.textContent=noteRecords[c.id].status==='cleared'?'':noteRecords[c.id].status==='resolved'?'반영 완료':'프로젝트에 저장됨';
  else label.textContent=notes[c.id]?'불러오는 중':'';
}

function adoptNotes(data){
  noteRecords=data.notes || {};
  notes=Object.fromEntries(Object.entries(noteRecords).map(([id,entry])=>[id,entry.text || '']));
  for(const [id,entry] of Object.entries(pendingNotes)) notes[id]=entry.text;
  writeStorage(noteStorage('notes'),notes);
  if(cut() && document.activeElement!==$('note')) $('note').value=notes[cut().id] || '';
  for(const button of document.querySelectorAll('.cut')) button.classList.toggle('has-note',Boolean(notes[button.dataset.cut]));
  paintNoteStatus();
}

async function loadNotes(importLocal=false){
  if(state.notesSyncing || !state.manifest) return false;
  state.notesSyncing=true;
  const project=state.projectId;
  try{
    const response=await fetch(`/api/notes?${projectQuery()}`,{cache:'no-store'});
    const data=await response.json();
    if(!response.ok) throw new Error(data.error);
    if(state.projectId!==project) return false;
    if(importLocal){
      // Migrate the earlier browser-only notes, without overwriting project notes.
      const local={...notes};
      if(project==='triton-tiled-matmul'){
        const legacy=readStorage('triton-cut-review-v1-notes',{});
        for(const [id,text] of Object.entries(legacy || {})) if(!(id in local)) local[id]=text;
      }
      for(const s of state.manifest.scenes) for(const c of s.cuts){
        const body=local[c.id];
        if(typeof body==='string' && body.trim() && !(c.id in data.notes) && !pendingNotes[c.id]){
          const previous=legacySaved.sceneId===s.index && legacySaved.cutKey===c.key;
          pendingNotes[c.id]={cut_id:c.id,text:body,scene_time:c.start+(previous?Number(legacySaved.offset || 0):0),import_if_absent:true};
        }
      }
      writeStorage(noteStorage('pending'),pendingNotes);
    }
    state.notesReady=true;
    adoptNotes(data);
    void flushNotes();
    return true;
  }catch(error){
    state.noteFailure=true;
    paintNoteStatus();
    return false;
  }finally{state.notesSyncing=false;}
}

async function flushNotes(){
  if(state.noteInFlight || !state.notesReady) return;
  const project=state.projectId, queue=pendingNotes;
  state.noteInFlight=true;
  try{
    while(Object.keys(queue).length){
      const id=Object.keys(queue)[0], entry=queue[id];
      const response=await fetch(`/api/notes?${new URLSearchParams({project})}`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(entry)});
      const data=await response.json();
      if(!response.ok) throw new Error(data.error);
      if(queue[id]===entry) delete queue[id];
      writeStorage(noteStorage('pending',project),queue);
      if(state.projectId===project){state.noteFailure=false;adoptNotes(data);}
    }
  }catch(error){
    if(state.projectId===project){state.noteFailure=true;paintNoteStatus();}
  }finally{
    state.noteInFlight=false;
    if(state.projectId!==project && Object.keys(pendingNotes).length) void flushNotes();
  }
}

function loadProjectStorage(){
  saved=readStorage(`${storageKey}:${state.projectId}:selection`,state.projectId==='triton-tiled-matmul'?legacySaved:{});
  state.sceneId=initialQuery.has('scene')?Number(initialQuery.get('scene')):(saved.sceneId ?? null);
  state.cutKey=initialQuery.get('cut') || saved.cutKey || null;
  notes=readStorage(noteStorage('notes'),{});
  pendingNotes=readStorage(noteStorage('pending'),{});
  noteRecords={};
  state.notesReady=false;state.notesVersion=null;state.noteFailure=false;
}

async function selectProject(project){
  if(project===state.projectId) return;
  pause();
  clearTimeout(noteTimer);
  await flushNotes();
  state.projectId=project;
  state.manifest=null;state.audioKey=null;
  state.audio.pause();
  loadProjectStorage();
  $('cuts').replaceChildren();
  $('note').value='';$('note').disabled=true;
  $('loading').textContent='프로젝트를 불러오고 있습니다.';
  $('loading').hidden=false;
  $('play').disabled=true;$('seek').disabled=true;
  await refresh(true);
}

async function start(){
  try{
    const response=await fetch('/api/projects',{cache:'no-store'});
    const catalog=await response.json();
    if(!response.ok) throw new Error(catalog.error);
    const select=$('project-select');select.replaceChildren();
    for(const project of catalog.projects){
      const option=document.createElement('option');option.value=project.id;
      option.textContent=project.title+(project.ready?'':' · 장면 준비 필요');
      option.disabled=!project.ready;select.append(option);
    }
    if(!catalog.projects.some(p=>p.id===state.projectId && p.ready)) state.projectId=catalog.default;
    select.value=state.projectId;
    select.addEventListener('change',()=>void selectProject(select.value));
    loadProjectStorage();
    await refresh();
  }catch(error){showError(error.message);}
}

void start();
setInterval(() => { void refresh(); }, 1000);
