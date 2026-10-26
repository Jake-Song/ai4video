/* Browser checks use an isolated project copy; the user's animation is untouched.
 * node tests/review.e2e.cjs /path/to/playwright
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require(process.argv[2] || 'playwright');

const shared = path.resolve(__dirname, '..');
const project = path.join(shared,'triton-tiled-matmul');
const python = path.join(shared,'.venv/bin/python');
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'triton-review-browser-'));
const output = path.join(project, 'preview');
fs.mkdirSync(output, {recursive: true});
for (const file of ['build.py', 'visuals.py', 'scenes.py', 'elevenlabs_tts.py', 'script.md', 'project.json', 'review_adapter.py']) fs.copyFileSync(path.join(project, file), path.join(fixture, file));
fs.cpSync(path.join(shared,'review-web'),path.join(fixture,'review-web'),{recursive:true});
fs.symlinkSync(path.join(project, 'audio'), path.join(fixture, 'audio'), 'dir');

const code = `import sys
sys.path.insert(0, sys.argv[1])
import review
from pathlib import Path
review.WEB=Path(sys.argv[2])/'review-web'
runtime=review.PreviewRuntime(sys.argv[2],'triton-tiled-matmul')
runtime.refresh()
server=review.ThreadingHTTPServer(('127.0.0.1',0),review.make_handler(runtime))
server.daemon_threads=True
print('READY '+str(server.server_address[1]),flush=True)
server.serve_forever()
`;
const server = spawn(python, ['-u', '-c', code, shared, fixture], {stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = '';
server.stderr.on('data', d => {serverErrors += d;});

async function ready() {
  return new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error(`Server startup timed out: ${serverErrors}`)), 20000);
    server.on('error', reject);
    server.on('exit', (code) => reject(new Error(`Server exited ${code}: ${serverErrors}`)));
    server.stdout.on('data', data => {
      output += data;
      const match = /READY (\d+)/.exec(output);
      if (match) {clearTimeout(timer);resolve(`http://127.0.0.1:${match[1]}`);}
    });
  });
}

async function run() {
  let browser;
  try {
    const url = await ready();
    browser = await chromium.launch({headless: true});
    const context = await browser.newContext({viewport: {width: 1500, height: 1150},
      permissions: ['clipboard-read', 'clipboard-write'], acceptDownloads: true});
    const page = await context.newPage();
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    // Simulate existing browser-only feedback from the earlier reviewer.
    await context.addInitScript(()=>{
      if(!localStorage.getItem('legacy-note-installed')){
        localStorage.setItem('triton-cut-review-v1-notes',JSON.stringify({'1-02':'기존 메모도 프로젝트로 옮겨 주세요.'}));
        localStorage.setItem('legacy-note-installed','1');
      }
    });
    await page.goto(url);
    await page.waitForFunction(() => document.getElementById('frame').dataset.revision);
    assert.equal(await page.locator('.cut').count(), 66);
    await page.waitForFunction(async()=>{
      const data=await(await fetch('/api/notes?project=triton-tiled-matmul')).json();
      return data.notes['1-02']?.text==='기존 메모도 프로젝트로 옮겨 주세요.';
    });
    assert.equal(await page.evaluate(() => getComputedStyle(document.body).fontSize), '16px');
    assert.equal(await page.locator('.cut-name').first().evaluate(el => getComputedStyle(el).fontSize), '14px');
    const manifest = await (await page.request.get(`${url}/api/state`)).json();
    assert.equal(manifest.scenes.length,9);
    assert(await page.locator('#cuts').evaluate(el=>el.scrollHeight>el.clientHeight));
    const inserted=manifest.scenes[0].cuts.filter(c=>c.key.startsWith('hbm_'));
    assert.equal(inserted.length,3);
    assert.deepEqual(inserted.map(c=>c.id),['1-01a','1-01b','1-01c']);
    for(const c of inserted){
      assert(!/[0-9]/.test(c.text));
      await page.locator(`[data-cut="${c.id}"]`).click();
      await page.locator('#seek').evaluate((input,t)=>{input.value=t;input.dispatchEvent(new Event('input',{bubbles:true}));},c.duration*.7);
      await page.waitForFunction(t=>Math.abs(Number(document.getElementById('frame').dataset.time)-t)<.05,c.start+c.duration*.7);
      const audio=await page.request.get(url+c.audio_url,{headers:{Range:'bytes=0-99'}});
      assert.equal(audio.status(),206);
      assert.equal((await audio.body()).length,100);
      assert.equal(await page.locator('#error').isVisible(),false);
    }
    for(const scene of manifest.scenes.slice(2)){
      const last=scene.cuts.at(-1);
      await page.locator(`[data-cut="${last.id}"]`).click();
      await page.waitForFunction(id=>Number(document.getElementById('frame').dataset.scene)===id,scene.index);
      assert.equal(await page.locator('#error').isVisible(),false);
    }
    const target = manifest.scenes[1].cuts[2];

    await page.locator('[data-cut="2-03"]').click();
    await page.waitForFunction(() => document.getElementById('frame').dataset.scene === '2');
    assert.equal(await page.locator('#cut-title').innerText(), '출력의 행 BM · 열 BN');
    await page.locator('#seek').evaluate((input) => {input.value = '1.1';input.dispatchEvent(new Event('input', {bubbles: true}));});
    await page.waitForFunction(t => Math.abs(Number(document.getElementById('frame').dataset.time)-t)<.04, target.start+1.1);
    const before = Number(await page.locator('#frame').getAttribute('data-frame'));
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(n => Number(document.getElementById('frame').dataset.frame) === n, before+1);

    await page.locator('#note').fill('BM 표시를 왼쪽으로 조금 이동해 주세요.');
    await page.waitForFunction(()=>document.getElementById('note-saved').textContent==='프로젝트에 저장됨');
    const savedNote=JSON.parse(fs.readFileSync(path.join(fixture,'review-notes.json'),'utf8')).notes['2-03'];
    assert.equal(savedNote.text,'BM 표시를 왼쪽으로 조금 이동해 주세요.');
    assert(savedNote.cut_time>1);
    await page.locator('#copy').click();
    const clipboard = await page.evaluate(() => navigator.clipboard.readText());
    assert.match(clipboard, /컷 2-03/);
    assert.match(clipboard, /BM 표시를 왼쪽으로/);
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#save-frame').click();
    const download = await downloadPromise;
    const pngPath = path.join(output, 'review-export-check.png');
    await download.saveAs(pngPath);
    const png = fs.readFileSync(pngPath);
    assert.equal(png.readUInt32BE(16), 1920);
    assert.equal(png.readUInt32BE(20), 1080);

    await page.locator('#sound').uncheck();
    const priorTime = Number(await page.locator('#seek').inputValue());
    await page.locator('#play').click();
    await page.waitForFunction(t => Number(document.getElementById('seek').value) > t+.3, priorTime);
    await page.locator('#play').click();
    assert.equal(await page.locator('#play').getAttribute('aria-label'), '재생');

    await page.locator('#seek').evaluate(input => {input.value=Number(input.max)-.15;input.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.locator('#play').click();
    await page.waitForFunction(() => Number(document.getElementById('seek').value)<1);
    assert.equal(await page.locator('.cut[aria-current=true]').getAttribute('data-cut'), '2-03');
    await page.locator('#play').click();
    await page.locator('#loop').uncheck();
    await page.locator('#seek').evaluate(input => {input.value=Number(input.max)-.15;input.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.locator('#play').click();
    await page.waitForFunction(() => document.querySelector('.cut[aria-current=true]').dataset.cut === '2-04');
    await page.locator('#play').click();

    // UI font/layout edits apply without regenerating an animation frame.
    const cssPath = path.join(fixture,'review-web/style.css');
    const css = fs.readFileSync(cssPath,'utf8');
    const geometryRevision = await page.locator('#frame').getAttribute('data-revision');
    fs.writeFileSync(cssPath,css+'\n:root{--accent:#c7b0ed}\n');
    await page.waitForFunction(() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()==='#c7b0ed');
    assert.equal(await page.locator('#frame').getAttribute('data-revision'), geometryRevision);
    fs.writeFileSync(cssPath,css);
    await page.waitForFunction(() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()==='#baa0ed');

    // Audio is requested directly, including HTTP Range support for seeking.
    const range = await page.request.get(`${url}/audio/01-00.mp3`, {headers: {Range: 'bytes=0-99'}});
    assert.equal(range.status(), 206);
    assert.equal((await range.body()).length, 100);
    const invalidRange = await page.request.get(`${url}/audio/01-00.mp3`, {headers: {Range: 'bytes=999999999-'}});
    assert.equal(invalidRange.status(), 416);
    assert.equal((await page.request.get(`${url}/api/frame?scene=99`)).status(), 400);
    await page.locator('[data-cut="1-01"]').click();
    await page.locator('#sound').check();
    const audioResponse = page.waitForResponse(response => response.url().includes('/audio/01-00.mp3') && [200,206].includes(response.status()));
    await page.locator('#play').click();
    await audioResponse;
    await page.locator('#play').click();

    // Stored drawing changes appear automatically, without an MP4 render.
    const sourcePath = path.join(fixture, 'visuals.py');
    const original = fs.readFileSync(sourcePath, 'utf8');
    let revision = await page.locator('#frame').getAttribute('data-revision');
    const blue = original.match(/BLUE, TEAL, PURPLE, ORANGE, RED = '(#[a-fA-F0-9]{6})'/)[1];
    fs.writeFileSync(sourcePath, original.replace(blue, '#c53961'));
    await page.waitForFunction(v => document.getElementById('frame').dataset.revision !== v, revision);
    revision = await page.locator('#frame').getAttribute('data-revision');
    fs.writeFileSync(sourcePath, original+'\ninvalid syntax ???\n');
    await page.waitForFunction(() => !document.getElementById('error').hidden);
    assert.equal(await page.locator('#frame').getAttribute('data-revision'), revision);
    fs.writeFileSync(sourcePath, original);
    await page.waitForFunction(v => document.getElementById('error').hidden && document.getElementById('frame').dataset.revision !== v, revision);

    const scriptPath = path.join(fixture, 'script.md');
    fs.writeFileSync(scriptPath, fs.readFileSync(scriptPath,'utf8').replace('여기서 타일링을 결정하는 숫자는 세 가지입니다.', '여기서 타일링을 결정하는 숫자는 세 가지가 있습니다.'));
    await page.locator('[data-cut="2-02"]').click();
    await page.waitForFunction(() => !document.getElementById('audio-notice').hidden && document.getElementById('audio-notice').textContent.includes('대본이 변경'));

    // Desktop/mobile layout and note persistence.
    await page.locator('[data-cut="2-03"]').click();
    await page.locator('#seek').evaluate(input => {input.value='1.5';input.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.waitForFunction(() => document.getElementById('frame').dataset.scene === '2');
    await page.screenshot({path: path.join(output,'review-desktop.png'), fullPage:true});
    await page.reload();
    await page.waitForFunction(() => document.getElementById('frame').dataset.revision);
    assert.match(await page.locator('#note').inputValue(), /BM 표시를 왼쪽으로/);
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1));
    await page.screenshot({path:path.join(output,'review-mobile.png'),fullPage:true});
    assert.deepEqual(pageErrors, []);
    console.log('PASS browser: 66 cuts, +2px fonts, seek/step, play/pause, loop, next cut, project notes + legacy migration, clipboard, PNG download, audio range, CSS hot reload, drawing reload/error recovery, stale narration, mobile layout');
    console.log(`Screenshots: ${output}/review-desktop.png and review-mobile.png`);
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await new Promise(resolve => server.once('exit',resolve));
    fs.rmSync(fixture,{recursive:true,force:true});
  }
}

run().catch(error => {console.error(error);process.exitCode=1;});
