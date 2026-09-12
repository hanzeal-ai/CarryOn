#!/bin/bash
# Run once as root after checking the target host. Keep DEPLOY_PUBLIC_KEY out of source.
set -euo pipefail
: "${DEPLOY_PUBLIC_KEY:?Provide the dedicated deploy public key}"
[[ "$DEPLOY_PUBLIC_KEY" == ssh-ed25519\ * ]]
command -v /usr/bin/python3.11 >/dev/null
[[ -f receive.py && -f carryon-gateway.service ]]
if id carryon >/dev/null 2>&1 || id carryon-deploy >/dev/null 2>&1 || [[ -e /opt/carryon || -e /etc/carryon || -e /usr/local/libexec/carryon-receive || -e /etc/sudoers.d/carryon-deploy || -e /etc/systemd/system/carryon-gateway.service ]]; then
  echo 'CarryOn already provisioned; inspect and update explicitly.' >&2
  exit 1
fi
useradd --system --no-create-home --shell /sbin/nologin carryon
useradd --system --home-dir /var/lib/carryon-deploy --shell /bin/bash carryon-deploy
install -d -m 755 -o root -g root /var/lib/carryon-deploy /var/lib/carryon-deploy/.ssh
printf 'restrict,command="/usr/local/libexec/carryon-receive" %s\n' "$DEPLOY_PUBLIC_KEY" > /var/lib/carryon-deploy/.ssh/authorized_keys
chmod 644 /var/lib/carryon-deploy/.ssh/authorized_keys
install -d -m 755 -o carryon-deploy -g carryon-deploy /opt/carryon /opt/carryon/releases
install -d -m 700 -o carryon -g carryon /etc/carryon
install -d -m 755 /usr/local/libexec
install -m 755 -o root -g root receive.py /usr/local/libexec/carryon-receive
install -m 644 -o root -g root carryon-gateway.service /etc/systemd/system/carryon-gateway.service
printf '%s\n' 'carryon-deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart carryon-gateway.service, /usr/bin/systemctl stop carryon-gateway.service' > /etc/sudoers.d/carryon-deploy
chmod 440 /etc/sudoers.d/carryon-deploy
visudo -cf /etc/sudoers.d/carryon-deploy
/usr/bin/python3.11 - <<'PY'
import json,os,pwd,secrets
path='/etc/carryon/gateway.json'
data={'devices':{'my-mac':{'deviceToken':secrets.token_urlsafe(32),'apiToken':secrets.token_urlsafe(32)}}}
with open(path,'x') as stream:json.dump(data,stream)
user=pwd.getpwnam('carryon');os.chown(path,user.pw_uid,user.pw_gid);os.chmod(path,0o600)
PY
systemctl daemon-reload
systemctl enable carryon-gateway.service
printf 'CarryOn provisioned; gateway remains stopped until first deployment.\n'
