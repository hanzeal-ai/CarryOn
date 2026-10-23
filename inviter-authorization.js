/* A link names a public fingerprint; only explicit administrator credentials grant it. */
function setupInviterAuthorization(client) {
  if (!location.hash.startsWith('#carryon-inviter=')) return;
  const digest = location.hash.slice('#carryon-inviter='.length);
  history.replaceState(null, '', location.pathname + location.search);
  const dialog = document.createElement('dialog');
  dialog.className = 'login-qr-dialog inviter-authorization-dialog';
  dialog.setAttribute('aria-labelledby', 'inviter-title');
  const title = document.createElement('h2');
  title.id = 'inviter-title'; title.textContent = '授权邀请码生成电脑';
  const message = document.createElement('p');
  message.setAttribute('role', 'status');
  const close = document.createElement('button');
  close.type = 'button'; close.className = 'quiet'; close.textContent = '关闭';
  close.onclick = () => dialog.close();
  dialog.append(title, message);
  document.body.append(dialog);
  if (!/^[0-9a-f]{64}$/.test(digest)) {
    message.textContent = '授权链接无效，请在原电脑重新生成。';
    dialog.append(close); dialog.showModal(); return;
  }
  const description = document.createElement('p');
  description.textContent = '请核对指纹与原电脑一致。确认后，该电脑可生成注册邀请码，并替换原有授权电脑。';
  message.before(description);
  const fingerprint = document.createElement('p');
  fingerprint.className = 'inviter-fingerprint'; fingerprint.textContent = digest;
  const form = document.createElement('form');
  const field = (name, text, type, autocomplete) => {
    const label = document.createElement('label'), input = document.createElement('input');
    input.id = name; input.name = name; input.type = type; input.autocomplete = autocomplete;
    input.required = true; input.autocapitalize = 'none'; label.htmlFor = name; label.textContent = text;
    form.append(label, input); return input;
  };
  const username = field('inviter-admin', '云端管理员账号', 'text', 'username');
  const password = field('inviter-password', '管理员密码', 'password', 'current-password');
  username.maxLength = 100; password.maxLength = 256;
  const actions = document.createElement('div'); actions.className = 'login-qr-actions';
  const approve = document.createElement('button'); approve.type = 'submit'; approve.className = 'primary'; approve.textContent = '确认授权本机';
  actions.append(approve, close); form.append(actions); dialog.append(fingerprint, form);
  let busy = false, closed = false;
  dialog.addEventListener('close', () => { closed = true; password.value = ''; dialog.remove(); });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  form.onsubmit = async event => {
    event.preventDefault(); if (busy || closed) return;
    busy = true; approve.disabled = true; close.disabled = true;
    try {
      const result = await client.consoleRequest('inviter/authorize', {
        username: username.value.trim(), password: password.value, issuerHash: digest, confirm: true,
      });
      if (closed) return;
      if (result.authorized !== true || result.issuerHash !== digest) throw Error('授权响应无效，请回到原电脑核对');
      message.textContent = '授权已生效。请回到原电脑点击“生成邀请码”。';
      description.remove();
      form.replaceChildren(close);
    } catch (error) {
      if (!closed) message.textContent = error.message;
    } finally {
      password.value = ''; busy = false; approve.disabled = false; close.disabled = false;
    }
  };
  dialog.showModal();
}
