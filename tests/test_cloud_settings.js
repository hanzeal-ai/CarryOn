const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');

test('web console keeps cloud approval and conversation entry points without local configuration',()=>{
  const html=fs.readFileSync('example.html','utf8');
  const app=fs.readFileSync('app.js','utf8');
  for(const id of ['cloud-link-form','cloud-pair-form','cloud-form','standby-enabled','service-stop','set-controller']) {
    assert.equal(html.includes(`id="${id}"`),false,id);
  }
  for(const id of ['link-approve','connection-requests','create','prompt','send'])assert.ok(html.includes(`id="${id}"`),id);
  assert.equal(app.includes('CloudSettings'),false);
  assert.equal(app.includes("api('/bridge',"),false);
  assert.equal(app.includes("api('/controller',"),false);
});
