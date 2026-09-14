const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="messages"><article class="message user" data-message-id="u1"><div class="text">original</div></article></div><div class="session-actions"><div id="operations"></div></div><div id="requests"></div><dialog id="question-dialog"><div id="question-content"></div><button id="question-later"></button></dialog>');
    await page.addScriptTag({ path: 'operations.js' });
    await page.evaluate(() => {
      window.writes = [];
      window.historyFixture = { runtime: { type: 'active' }, status: { state: 'running' }, metadata: {}, controls: { activeTurnId: 'turn1', lastTurnId: 'turn1', lastUserText: 'original', settings: {}, requests: [] }, timeline: [{ id: 'u1', turnId: 'turn1', type: 'userMessage' }] };
      window.refresh = (writable = true) => Operations.render(historyFixture, 'thread1', { operation: async (...args) => { writes.push(args.slice(0, 3)); return { state: 'completed' }; } }, message => { throw Error(message); }, writable);
      refresh();
    });
    assert.equal(await page.locator('.message-editor').count(), 0);
    await page.evaluate(() => { historyFixture.runtime.type = 'idle'; historyFixture.status.state = 'idle'; refresh(); });
    assert.equal(await page.locator('#operations').getByText('编辑最后一轮', { exact: true }).count(), 0);
    assert.equal(await page.locator('#operations').getByText('压缩上下文', { exact: true }).count(), 0);
    await page.locator('.message-editor summary').click();
    await page.locator('.message-editor textarea').fill('replacement');
    // A new timeline DOM snapshot must retain the unfinished edit.
    await page.evaluate(() => { document.querySelector('#messages').innerHTML = '<article class="message user" data-message-id="u1"><div class="text">original</div></article>'; refresh(); });
    assert.equal(await page.locator('.message-editor textarea').inputValue(), 'replacement');
    await page.getByRole('button', { name: '重新发送', exact: true }).click();
    assert.deepEqual(await page.evaluate(() => writes), [['thread1', 'edit', { turnId: 'turn1', prompt: 'replacement', confirmed: true }]]);
    await page.evaluate(() => refresh(false));
    assert.equal(await page.locator('.message-editor').count(), 0);
    await page.evaluate(() => { historyFixture.controls.lastTurnId = 'turn2'; refresh(); });
    assert.equal(await page.locator('.message-editor').count(), 0);
    console.log('PASS: running/read-only/stale-turn gates, inline edit, refresh draft retention, replacement operation payload. Transport mocked.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
