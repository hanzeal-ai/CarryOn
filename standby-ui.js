/* Local service setting; the cloud console never initializes this control. */
(() => {
  if (window.CONNECTNOW_CLOUD === true) return;
  const toggle = document.getElementById('standby-enabled');
  const state = document.getElementById('standby-state');
  let busy = false;
  async function update(enabled) {
    if (busy) return;
    busy = true;
    toggle.disabled = true;
    try {
      const s = await api('/service/standby', enabled === undefined ? undefined : {enabled});
      toggle.checked = s.enabled;
      state.textContent = s.error || (!s.supported ? '此系统不支持远程待机' :
        !s.enabled ? '已关闭，使用系统正常睡眠策略' :
        s.effective ? '已生效 · 接电时保持后台运行，屏幕可以熄灭' :
        s.powerSource === 'battery' ? '等待接电 · 使用电池时不阻止睡眠' : '无法确认电源状态，请检查电源连接');
      toggle.disabled = !s.supported;
    } catch (error) {
      state.textContent = error.message;
      if (enabled !== undefined) toggle.checked = !enabled;
      // Allow retry after a transient failure or after local pairing.
      toggle.disabled = false;
    } finally { busy = false; }
  }
  toggle.onchange = () => update(toggle.checked);
  window.addEventListener('focus', () => update());
  const timer = setInterval(() => { if (!document.hidden) update(); }, 15000);
  window.addEventListener('pagehide', () => clearInterval(timer), {once:true});
  update();
})();
