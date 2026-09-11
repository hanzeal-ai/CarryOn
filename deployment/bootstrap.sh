#!/bin/bash
# Run once as root after checking the target host. Keep DEPLOY_PUBLIC_KEY out of source.
set -euo pipefail
: "${DEPLOY_PUBLIC_KEY:?Provide the dedicated deploy public key}"
[[ "$DEPLOY_PUBLIC_KEY" == ssh-ed25519\ * ]]
command -v /usr/bin/python3.11 >/dev/null
[[ -f receive.py && -f connectnow-gateway.service ]]
if id connectnow >/dev/null 2>&1 || id connectnow-deploy >/dev/null 2>&1 || [[ -e /opt/connectnow || -e /etc/connectnow || -e /usr/local/libexec/connectnow-receive || -e /etc/sudoers.d/connectnow-deploy || -e /etc/systemd/system/connectnow-gateway.service ]]; then
  echo 'ConnectNow already provisioned; inspect and update explicitly.' >&2
  exit 1
fi
useradd --system --no-create-home --shell /sbin/nologin connectnow
useradd --system --home-dir /var/lib/connectnow-deploy --shell /bin/bash connectnow-deploy
install -d -m 755 -o root -g root /var/lib/connectnow-deploy /var/lib/connectnow-deploy/.ssh
printf 'restrict,command="/usr/local/libexec/connectnow-receive" %s\n' "$DEPLOY_PUBLIC_KEY" > /var/lib/connectnow-deploy/.ssh/authorized_keys
chmod 644 /var/lib/connectnow-deploy/.ssh/authorized_keys
install -d -m 755 -o connectnow-deploy -g connectnow-deploy /opt/connectnow /opt/connectnow/releases
install -d -m 700 -o connectnow -g connectnow /etc/connectnow
install -d -m 755 /usr/local/libexec
install -m 755 -o root -g root receive.py /usr/local/libexec/connectnow-receive
install -m 644 -o root -g root connectnow-gateway.service /etc/systemd/system/connectnow-gateway.service
printf '%s\n' 'connectnow-deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart connectnow-gateway.service, /usr/bin/systemctl stop connectnow-gateway.service' > /etc/sudoers.d/connectnow-deploy
chmod 440 /etc/sudoers.d/connectnow-deploy
visudo -cf /etc/sudoers.d/connectnow-deploy
/usr/bin/python3.11 - <<'PY'
import json,os,pwd,secrets
path='/etc/connectnow/gateway.json'
data={'devices':{'my-mac':{'deviceToken':secrets.token_urlsafe(32),'apiToken':secrets.token_urlsafe(32)}}}
with open(path,'x') as stream:json.dump(data,stream)
user=pwd.getpwnam('connectnow');os.chown(path,user.pw_uid,user.pw_gid);os.chmod(path,0o600)
PY
systemctl daemon-reload
systemctl enable connectnow-gateway.service
printf 'ConnectNow provisioned; gateway remains stopped until first deployment.\n'
