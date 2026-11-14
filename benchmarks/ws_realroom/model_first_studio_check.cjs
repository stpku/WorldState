// Browser regression on an already-running, isolated Studio development draft.
// Automated actions and timing are NOT human annotation or productivity data.
// NODE_PATH must point to a separately installed playwright; no data is uploaded
// outside the local Studio server. Screenshot/report are written outside Git.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

async function main() {
  const [url, imageDir, outputDir] = process.argv.slice(2);
  if (!url || !imageDir || !outputDir) throw Error('expected local URL, image directory, new output directory');
  if (!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(url) || fs.existsSync(outputDir)) throw Error('invalid local URL or existing output');
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.WS_CHROMIUM || '/usr/bin/chromium', args:['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  try {
    await page.goto(url, { waitUntil:'networkidle' });
    await page.locator('#projection-panel').waitFor({ state:'visible' });
    const initial = await page.evaluate(async () => await (await fetch('/api/model/projections')).json());
    if (initial.views.length < 3) throw Error('expected at least three real registered camera views');
    for (const name of ['DSC_6497.JPG','DSC_6508.JPG']) {
      await page.locator('#upload').setInputFiles(path.join(imageDir,name), { timeout:120000 });
      await page.waitForFunction(file => [...document.querySelector('#projection-view').options]
        .some(o => o.textContent.includes(file) && !o.textContent.includes('请先上传')), name, { timeout:90000 });
    }
    await page.locator('#projection-view').selectOption(String(initial.views[0].image_id));
    await page.waitForFunction(() => document.querySelector('#projection-message').textContent.includes('残差 RMS'), null, {timeout:30000});
    const beforeMessage = await page.locator('#projection-message').textContent();
    await page.locator('#attribute').selectOption('height');
    const height = Number(await page.locator('#value').inputValue());
    await page.locator('#value').fill(String(height+.04));
    await page.locator('#reason').fill('Automated projection regression; no real measurement');
    await page.locator('#save').click();
    await page.waitForFunction(() => document.querySelector('#projection-message').textContent.includes('版本 3'), null, {timeout:30000});
    const after = await page.evaluate(async () => await (await fetch('/api/model/projections')).json());
    const afterMessage = await page.locator('#projection-message').textContent();
    if (after.revision !== initial.revision+1 || JSON.stringify(after.views[0].polygon_px) === JSON.stringify(initial.views[0].polygon_px))
      throw Error('current revision projection did not change');
    await page.locator('#projection-correction').selectOption('left_top');
    const canvas = page.locator('#photo-projection');
    await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox();
    const point = after.views[0].corners.find(p => p.kind === 'left_top').pixel_xy;
    await page.mouse.click(box.x + point[0]*box.width/after.views[0].width_px + .1,
                           box.y + point[1]*box.height/after.views[0].height_px);
    try {
      await page.waitForFunction(() => document.querySelector('#projection-message').textContent.includes('版本 4'), null, {timeout:30000});
    } catch (error) {
      throw Error('correction did not finish: ' + await page.locator('#projection-message').textContent() + '; ' + error);
    }
    const corrected = await page.evaluate(async () => await (await fetch('/api/model')).json());
    const last = corrected.history[corrected.history.length-1];
    if (corrected.revision !== 4 || last.action !== 'correct_source_corner_and_reoptimize' || last.operator !== 'automation')
      throw Error('corner correction or automation provenance was not recorded');
    if (errors.length) throw Error('browser errors: '+errors.join('; '));
    await page.locator('#projection-panel').screenshot({ path:path.join(outputDir,'projection.png') });
    fs.writeFileSync(path.join(outputDir,'report.json'), JSON.stringify({status:'PASS', operator:'automation',
      inputs:['DSC_6497.JPG','DSC_6508.JPG'], initial_revision:initial.revision, revised_revision:after.revision,
      corrected_revision:corrected.revision, corner_correction:last,
      before_message:beforeMessage, after_message:afterMessage, errors,
      caveats:['No real human operation or productivity measured.','Image observations and model remain unverified.']},null,2)+'\n');
    console.log(JSON.stringify({status:'PASS',beforeMessage,afterMessage},null,2));
  } finally { await browser.close(); }
}
main().catch(e => { console.error(e); process.exitCode=1; });
