/* Run against generated projects: node tests/review.e2e.cjs /path/to/playwright */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn, spawnSync} = require('node:child_process');
const {chromium} = require(process.argv[2] || 'playwright');
const shared = path.resolve(__dirname, '..');
const python = path.join(shared, '.venv/bin/python');
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'review-browser-'));
for (const name of ['sample-one', 'sample-two']) {
  const generated = spawnSync(python, [path.join(__dirname, 'review_fixture.py'), path.join(fixture, 'videos', name)], {encoding: 'utf8'});
  if (generated.status !== 0) {
    fs.rmSync(fixture, {recursive: true, force: true});
    throw new Error(generated.error?.message || generated.stderr);
  }
}
fs.cpSync(path.join(shared, 'review-web'), path.join(fixture, 'review-web'), {recursive: true});
const code = `import sys
sys.path.insert(0, sys.argv[1])
import review
from pathlib import Path
root = Path(sys.argv[2])
review.WEB = root/'review-web'
catalog = review.ProjectCatalog(root=root/'videos')
server = review.ThreadingHTTPServer(('127.0.0.1', 0), review.make_handler(catalog))
server.daemon_threads = True
print('READY '+str(server.server_address[1]), flush=True)
server.serve_forever()
`;
const server = spawn(python, ['-u', '-c', code, shared, fixture], {stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = '';
server.stderr.on('data', data => {serverErrors += data;});
const ready = new Promise((resolve, reject) => {
  let output = '';
  const timer = setTimeout(() => reject(new Error(`Server startup timed out: ${serverErrors}`)), 20000);
  server.on('error', error => {clearTimeout(timer); reject(error);});
  server.on('exit', code => {clearTimeout(timer); reject(new Error(`Server exited ${code}: ${serverErrors}`));});
  server.stdout.on('data', data => {
    output += data;
    const match = /READY (\d+)/.exec(output);
    if (match) {clearTimeout(timer); resolve(`http://127.0.0.1:${match[1]}`);}
  });
});
async function run() {
  let browser;
  try {
    const url = await ready;
    browser = await chromium.launch({headless: true});
    const context = await browser.newContext({viewport: {width: 1500, height: 1150}, acceptDownloads: true});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url);
    await page.waitForFunction(() => document.getElementById('frame').dataset.revision);
    assert.equal(await page.locator('.cut').count(), 4);
    assert.equal(await page.locator('#project-select option').count(), 2);
    await page.locator('[data-cut="2-02"]').click();
    await page.waitForFunction(() => document.getElementById('frame').dataset.scene === '2');
    await page.locator('#seek').evaluate(input => {input.value = '1.1'; input.dispatchEvent(new Event('input', {bubbles: true}));});
    await page.waitForFunction(() => Math.abs(Number(document.getElementById('frame').dataset.time) - 11.1) < .04);
    const before = Number(await page.locator('#frame').getAttribute('data-frame'));
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(n => Number(document.getElementById('frame').dataset.frame) === n, before + 1);
    await page.locator('#note').fill('Move this element to the left.');
    await page.waitForFunction(() => document.getElementById('note-saved').textContent === '프로젝트에 저장됨');
    const notesPath = path.join(fixture, 'videos', 'sample-one', 'review-notes.json');
    const note = JSON.parse(fs.readFileSync(notesPath, 'utf8')).notes['2-02'];
    assert.equal(note.text, 'Move this element to the left.');
    assert(note.cut_time > 1);
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#save-frame').click();
    const png = fs.readFileSync(await (await downloadPromise).path());
    assert.equal(png.readUInt32BE(16), 1920);
    assert.equal(png.readUInt32BE(20), 1080);
    await page.locator('#sound').uncheck();
    const time = Number(await page.locator('#seek').inputValue());
    await page.locator('#play').click();
    await page.waitForFunction(t => Number(document.getElementById('seek').value) > t + .3, time);
    await page.locator('#play').click();
    const range = await page.request.get(`${url}/audio/01-timed.wav?project=sample-one`, {headers: {Range: 'bytes=0-99'}});
    assert.equal(range.status(), 206);
    assert.equal((await range.body()).length, 100);
    assert.equal((await page.request.get(`${url}/api/frame?project=sample-one&scene=99`)).status(), 400);
    const cssPath = path.join(fixture, 'review-web', 'style.css');
    const geometryRevision = await page.locator('#frame').getAttribute('data-revision');
    fs.appendFileSync(cssPath, '\n:root{--accent:#c7b0ed}\n');
    await page.waitForFunction(() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() === '#c7b0ed');
    assert.equal(await page.locator('#frame').getAttribute('data-revision'), geometryRevision);
    const sourcePath = path.join(fixture, 'videos', 'sample-one', 'visuals.py');
    const original = fs.readFileSync(sourcePath, 'utf8');
    let revision = await page.locator('#frame').getAttribute('data-revision');
    fs.writeFileSync(sourcePath, original.replace('#3366cc', '#c53961'));
    await page.waitForFunction(v => document.getElementById('frame').dataset.revision !== v, revision);
    revision = await page.locator('#frame').getAttribute('data-revision');
    fs.writeFileSync(sourcePath, original + '\ninvalid syntax ???\n');
    await page.waitForFunction(() => !document.getElementById('error').hidden);
    assert.equal(await page.locator('#frame').getAttribute('data-revision'), revision);
    fs.writeFileSync(sourcePath, original);
    await page.waitForFunction(v => document.getElementById('error').hidden && document.getElementById('frame').dataset.revision !== v, revision);
    await page.locator('#project-select').selectOption('sample-two');
    await page.waitForFunction(() => state.manifest?.project === 'sample-two' && state.notesReady);
    assert.equal(await page.locator('#note').inputValue(), '');
    assert.equal(JSON.parse(fs.readFileSync(notesPath, 'utf8')).notes['2-02'].text, note.text);
    await page.setViewportSize({width: 390, height: 844});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    assert.deepEqual(errors, []);
    console.log('Browser passed: generated projects, frames, seeking, notes, PNG, playback, audio ranges, reload recovery and project switching.');
  } finally {
    if (browser) await browser.close();
    const stopped = new Promise(resolve => {
      if (server.exitCode !== null || server.signalCode !== null) resolve();
      else server.once('exit', resolve);
    });
    server.kill();
    await stopped;
    fs.rmSync(fixture, {recursive: true, force: true});
  }
}
run().catch(error => {console.error(error); process.exitCode = 1;});
