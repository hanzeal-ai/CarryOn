const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    await page.setContent('<form><label for="token">密码</label><input id="token" type="password"><button id="pair" type="button">登录</button></form><button id="console-logout">退出</button>');
    await page.addScriptTag({path: path.resolve('console-login.js')});
    await page.evaluate(() => {
      window.requests = [];
      window.loggedIn = false;
      setupConsoleLogin({consoleRequest: async (route, body) => {
        window.requests.push({route, body});
        if (body.inviteCode === 'used-code') throw Error('邀请码无效或已使用');
      }}, async () => {window.loggedIn = true;});
    });
    await page.locator('#login-username').fill('alice');
    await page.locator('#token').fill('a long password 123');
    await page.getByRole('button', {name: '创建账号', exact: true}).click();
    assert(await page.getByLabel('邀请码', {exact: true}).isVisible());
    await page.getByRole('button', {name: '注册并登录'}).click();
    assert.equal(await page.getByRole('alert').textContent(), '请输入邀请码');
    assert.equal(await page.evaluate(() => window.requests.length), 0);
    await page.getByLabel('邀请码', {exact: true}).fill('used-code');
    await page.getByRole('button', {name: '注册并登录'}).click();
    assert.equal(await page.getByRole('alert').textContent(), '邀请码无效或已使用');
    await page.getByLabel('邀请码', {exact: true}).fill(' valid-code ');
    await page.getByRole('button', {name: '注册并登录'}).click();
    assert.equal(await page.evaluate(() => window.loggedIn), true);
    assert.deepEqual(await page.evaluate(() => window.requests.at(-1)), {
      route: 'register', body: {username: 'alice', password: 'a long password 123', inviteCode: 'valid-code'}
    });
    assert.equal(await page.locator('#token').inputValue(), '');
    assert.equal(await page.locator('#registration-invite').inputValue(), '');
    console.log('Registration login UI passed');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
