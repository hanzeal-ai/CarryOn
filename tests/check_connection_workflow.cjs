const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch();
  try {
    for (const origin of ['https://carryon.hanzeal.com', 'https://private.test']) {
      const page = await browser.newPage({viewport: {width: 1280, height: 900}});
      const errors = [], writes = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.addInitScript(() => {window.CARRYON_CLOUD = true;});
      await page.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url());
        if (url.pathname.startsWith('/console/')) {
          if (request.method() === 'POST') writes.push(url.pathname);
          const data = url.pathname.endsWith('/session') ? {devices: [], publicUrl: origin, account:{username:'Alice'}} : {requests: [], history: []};
          await route.fulfill({contentType:'application/json', body:JSON.stringify(data)});
        } else {
          const response = await route.fetch({url:'http://127.0.0.1:8923' + url.pathname});
          await route.fulfill({response});
        }
      });
      await page.goto(origin + '/example.html');
      await page.locator('#account-menu > summary').click();
      await page.getByRole('button', {name:'扫码或粘贴链接绑定',exact:true}).click();
      await page.getByLabel('工作区二维码链接').waitFor();
      assert.equal(await page.getByText('获取备用配对码', {exact:true}).count(), 0);
      await page.keyboard.press('Escape');
      const expected = origin.includes('private') ? "carryon init --url 'https://private.test/'" : 'carryon init';
      await page.setViewportSize({width:390, height:844});
      await page.waitForFunction(() => document.body.classList.contains('mobile-ready'));
      await page.locator('#mobile-connect').evaluate(dialog => dialog.showModal());
      assert.equal(await page.locator('#mobile-connect pre').textContent(), expected);
      const help = await page.locator('#mobile-connect').textContent();
      assert(!help.includes('bridge on') && !help.includes('cloud connect') && !help.includes('复制云端地址'));
      assert.equal(writes.length, 0, 'opening binding UI never creates a binding');
      assert(help.includes('目标账号绑定也需要手机确认'));
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('PASS: desktop/mobile default and custom cloud guidance; no legacy pairing write.');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
