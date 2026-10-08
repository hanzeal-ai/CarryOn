// Real Console HTML/CSP behind a prefix-only HTTP reverse proxy; no native or account writes.
const {spawn}=require('node:child_process');
const {createInterface}=require('node:readline');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const server=spawn('python3',['-u','-c',`
import http.client, json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from carryon.cloud.console import ConsoleServer
from carryon.cloud.console_auth import password_record
console=ConsoleServer(('127.0.0.1',0),{'publicUrl':'http://127.0.0.1/carryon','account':password_record('fixture','x'*40),'devices':{}})
threading.Thread(target=console.serve_forever,daemon=True).start()
class Proxy(BaseHTTPRequestHandler):
 def do_GET(self):
  if not self.path.startswith('/carryon/'):
   self.send_error(404); return
  connection=http.client.HTTPConnection('127.0.0.1',console.server_port)
  connection.request('GET',self.path[len('/carryon'):],headers={'Host':f'127.0.0.1:{console.server_port}'})
  response=connection.getresponse(); body=response.read(); self.send_response(response.status)
  for key,value in response.getheaders():
   if key.lower() not in ('connection','server','date','transfer-encoding'):self.send_header(key,value)
  self.end_headers();self.wfile.write(body);connection.close()
 def log_message(self,*args):pass
proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy)
console.origin=f'http://127.0.0.1:{proxy.server_port}';console.public_url=console.origin+'/carryon'
print(json.dumps({'url':console.public_url}),flush=True)
proxy.serve_forever()
`],{stdio:['ignore','pipe','pipe']});
let browser;
(async()=>{
 const lines=createInterface({input:server.stdout});
 const {url}=await new Promise((resolve,reject)=>{lines.once('line',line=>{try{resolve(JSON.parse(line));}catch(error){reject(error);}});server.once('exit',code=>reject(Error('Console exited '+code)));});
 browser=await chromium.launch();const page=await browser.newPage();const requests=[],errors=[];
 page.on('request',request=>requests.push(new URL(request.url()).pathname));page.on('pageerror',error=>errors.push(error.message));
 await page.goto(url+'/example.html');await page.waitForFunction(()=>typeof CodeHighlight!=='undefined'&&typeof MessageMarkdown!=='undefined');
 await page.waitForTimeout(200);
 await page.evaluate(()=>{const root=MessageMarkdown.render('```swift\npublic enum Prefix { case ready }\n```');root.id='prefix-highlight';document.body.append(root);});
 await page.locator('#prefix-highlight .hljs-keyword').first().waitFor();
 assert.equal(await page.locator('#prefix-highlight code').textContent(),'public enum Prefix { case ready }');
 assert(requests.includes('/carryon/code-highlight-worker.js'));
 assert(requests.includes('/carryon/highlight-engine.js'));
 assert(requests.includes('/carryon/unified-diff.js'));
 assert(!requests.includes('/unified-diff.js'));
 assert(!requests.includes('/code-highlight-worker.js')&&!requests.includes('/highlight-engine.js'));
 const license=await page.request.get(url+'/highlight-engine.LICENSE');assert.equal(license.status(),200);assert((await license.text()).includes('Redistribution and use'));
 assert.deepEqual(errors,[]);console.log('PASS real Console prefix-only reverse proxy syntax colors',JSON.stringify(requests.filter(path=>path.includes('highlight')||path.includes('unified-diff'))));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{await browser?.close();server.kill();});
