const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {createInterface} = require('node:readline');
const {createHash} = require('node:crypto');
const fs = require('node:fs');

(async () => {
  const server = spawn('python3', ['tests/fixtures/inviter_authorization_server.py'], {
    env: {...process.env, PYTHONPATH: '.'}, stdio: ['pipe', 'pipe', 'inherit']
  });
  let browser;
  try {
    const lines = createInterface({input: server.stdout});
    const {url} = await new Promise((resolve, reject) => {
      lines.once('line', line => resolve(JSON.parse(line)));
      server.once('exit', code => reject(Error('Fixture exited: '+code)));
    });
    browser = await chromium.launch();
    const artifacts = '.runtime/inviter-authorization'; fs.mkdirSync(artifacts, {recursive: true});
    const token = 'browser-fixture-issuer-'+'x'.repeat(32);
    const digest = createHash('sha256').update(token).digest('hex');
    for (const width of [390, 1280]) {
      const context = await browser.newContext({viewport: {width, height: 844}});
      const page = await context.newPage();
      let submissions = 0;
      page.on('request', request => {if(request.url().endsWith('/console/inviter/authorize')) submissions++;});
      await page.goto(url+'/#carryon-inviter='+digest);
      const dialog = page.getByRole('dialog', {name:'授权邀请码生成电脑'});
      await dialog.waitFor();
      assert.equal(await page.evaluate(() => location.hash), '');
      assert.equal(submissions, 0);
      assert.equal(await page.locator('.inviter-fingerprint').textContent(), digest);
      await page.getByLabel('云端管理员账号').fill('member');
      await page.getByLabel('管理员密码', {exact: true}).fill('member-password-123');
      await page.getByRole('button', {name:'确认授权本机'}).click();
      await page.getByRole('status').filter({hasText:'只有云端管理员'}).waitFor();
      assert.equal(await page.getByLabel('管理员密码', {exact: true}).inputValue(), '');
      assert(await page.getByRole('button', {name:'确认授权本机'}).isEnabled());
      await page.getByLabel('云端管理员账号').fill('test-owner');
      await page.getByLabel('管理员密码', {exact: true}).fill('fixture-password-123');
      await page.screenshot({path: artifacts+'/confirm-'+width+'.png'});
      assert(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth));
      await page.getByRole('button', {name:'确认授权本机'}).click();
      await page.getByRole('status').filter({hasText:'授权已生效'}).waitFor();
      assert.equal(await page.locator('#inviter-password').count(), 0);
      await page.screenshot({path: artifacts+'/success-'+width+'.png'});
      const response = await fetch(url+'/console/account/invite', {method:'POST',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({issuerToken:token})});
      assert.equal(response.status, 200); assert.equal((await response.json()).inviteCode.length, 32);
      await dialog.getByRole('button', {name:'关闭'}).click();
      assert.equal(await page.locator('#inviter-password').count(), 0);
      await context.close();
    }
    const page = await browser.newPage();
    await page.goto(url+'/#carryon-inviter=invalid');
    await page.getByRole('status').filter({hasText:'授权链接无效'}).waitFor();
    assert.equal(await page.locator('#inviter-password').count(), 0);
    await page.goto(url+'/#carryon-inviter='+digest);
    await page.reload();
    await page.getByLabel('管理员密码', {exact: true}).fill('discard-this-password');
    await page.getByRole('dialog', {name:'授权邀请码生成电脑'}).getByRole('button', {name:'关闭'}).click();
    await page.locator('#inviter-password').waitFor({state:'detached'});
    assert.equal(await page.locator('#inviter-password').count(), 0);
    console.log('Remote inviter browser acceptance passed: real HTTP authorization, member denial, mobile/desktop, password cleanup, invalid link, live issuance.');
  } finally {
    if (browser) await browser.close();
    server.stdin.end('\n');
  }
})().catch(error => {console.error(error); process.exitCode=1;});
