const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const base=process.env.LOGIN_TEST_URL;assert(base,'Set LOGIN_TEST_URL to an isolated console with admin / fixture-password-123');
 const browser=await chromium.launch();
 try {
 const desktop=await browser.newContext({viewport:{width:1280,height:900}}),phone=await browser.newContext({viewport:{width:390,height:844},isMobile:true});
 const page=await desktop.newPage(),mobile=await phone.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));mobile.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);await page.locator('#login-username').fill('admin');await page.locator('#token').fill('wrong-password');await page.locator('#pair').click();
 await page.getByText('账号或密码错误',{exact:true}).waitFor();
 await page.locator('#token').fill('fixture-password-123');await page.locator('#pair').click();await page.locator('#pairing').waitFor({state:'hidden'});
 await page.reload();await page.locator('#pairing').waitFor({state:'hidden'});
 await page.locator('#account-menu summary').click();
 const created=page.waitForResponse(r=>r.url().endsWith('/qr/create'));
 await page.locator('#console-login-device').click();const qr=await (await created).json();
 await page.locator('.login-qr-dialog svg').waitFor();await page.locator('.login-qr-dialog').screenshot({path:'.runtime/login-qr.png'});
 await mobile.goto(qr.url);await mobile.getByRole('button',{name:'继续登录',exact:true}).click();
 await mobile.getByText(/确认码：/).waitFor();await page.getByRole('button',{name:'允许登录',exact:true}).waitFor();
 const text=await mobile.locator('.login-qr-dialog').innerText();const code=text.match(/确认码：(\d{6})/)[1];assert((await page.locator('.login-qr-dialog').innerText()).includes(code));
 await page.getByRole('button',{name:'允许登录',exact:true}).click();await mobile.locator('#pairing').waitFor({state:'hidden'});await page.getByText('设备已登录',{exact:true}).waitFor();
 await mobile.reload();await mobile.locator('#pairing').waitFor({state:'hidden'});
 const cookie=(await phone.cookies()).find(c=>c.name==='carryon-console');assert(cookie.httpOnly);assert.equal(cookie.sameSite,'Strict');
 await phone.clearCookies();await mobile.reload();await mobile.locator('#pairing').waitFor({state:'visible'});
 await mobile.screenshot({path:'.runtime/login-mobile.png'});
 assert(await mobile.locator('#login-username').isVisible());assert(await mobile.getByRole('button',{name:'扫码登录',exact:true}).isVisible());
 assert.equal(await mobile.locator('#token').getAttribute('autocomplete'),'current-password');
 assert.deepEqual(errors,[]);console.log('PASS: real HTTP password failure/success, session restore, QR display/claim/owner confirmation/redemption, mobile default login');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
