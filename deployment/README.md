# Aliyun lightweight server delivery

The gateway runs as a dedicated `connectnow` service account on loopback port 8780. It does not run the macOS device service, access Codex data, or expose a SaaS console. The device connects outbound to `wss://HOST/connectnow/device`; your backend uses `https://HOST/connectnow/v1/...`.

## One-time host provisioning

Inspect existing workloads, ports, Python 3.11, systemd and TLS before provisioning. Run `bootstrap.sh` as root from this directory with `DEPLOY_PUBLIC_KEY` set to a dedicated Ed25519 public key. It refuses existing accounts/paths. Review before executing: it creates two service accounts, a single systemd unit, a forced SSH receiver and an exact service-specific sudo rule. It neither replaces host SSH credentials nor grants a root shell. Gateway credentials are created only on the server in `/etc/connectnow/gateway.json` (0600), independently of deployment credentials.

Deploy-user SSH always runs the root-owned `receive.py`, with the requested commit SHA as `SSH_ORIGINAL_COMMAND` and wheel bytes on stdin. No SCP, terminal, SSH forwarding or arbitrary command is accepted. The receiver bounds archive size, rejects unsafe paths, checks imports before activation, switches releases atomically, restarts only ConnectNow, verifies the exact release through `/healthz` and restores the old release if startup fails. Application code runs without root, with a read-only filesystem, no capabilities and resource limits. The deploy key can replace application code and therefore must be treated as granting access to gateway data; it does not grant administrative access to other applications.

Create GitHub repository secrets `DEPLOY_SSH_KEY` and `DEPLOY_KNOWN_HOSTS`. Verify the host public key through the authenticated Aliyun CLI before recording it; the workflow never uses trust-on-first-use or disables host verification. Set repository variables `DEPLOY_HOST` and, only after review/provisioning, `DEPLOY_ENABLED=true`.

The workflow runs tests and builds a pure Python wheel on Ubuntu. Pushes to main and manual runs deploy only when enabled. Pull requests never deploy. Actions are pinned by commit; no cloud account AccessKey is copied to GitHub. The initial repository push keeps deployment disabled.

## HTTPS reverse proxy

Add a location inside the existing server block for your valid TLS address. Preserve its other routes and back up the previous configuration. Test `nginx -t` before reloading.

```nginx
location ^~ /connectnow/ {
    proxy_pass http://127.0.0.1:8780/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 90s;
    client_max_body_size 1m;
}
```

No additional public port is required. `/healthz` discloses service/version/release only; request APIs require a device-specific API token. A URL prefix routes the gateway and does not provide a cloud UI. Check existing applications before and after the reload. Monitor certificate renewal; TLS verification must not be bypassed for IP certificates.

## Verification and rollback

Check systemd active state and `https://HOST/connectnow/healthz`, matching the workflow commit. Exercise WSS hello, device authentication, read-only refusal, subscriptions, offline behavior and cross-device authorization using an isolated fake local IPC. Keep real Codex sessions and user content outside smoke tests. Then give the user the device URL, device ID and device token through a local private file for manual product acceptance.

Each successful deployment records `/opt/connectnow/previous`; releases and credentials are retained. To roll back, an authorized operator reads and verifies that path, switches `/opt/connectnow/current` atomically to it, restarts only `connectnow-gateway.service`, and checks the reported release. Do not re-run an old commit through the receiver: duplicate release directories are rejected to avoid ambiguous overwritten releases. Disable the workflow with `DEPLOY_ENABLED=false` to halt further deployments. On a failed first deployment, the receiver stops only ConnectNow and removes its current symlink; it does not delete credentials or releases. No database migration is required.

GitHub workflows do not overwrite the receiver, sudoers, service unit or nginx configuration. Changes to these privileged files require separate operator installation after review. The repository contains no deployment private key, host gateway credentials or local runtime data.

## Console device registry

The multi-device console needs a persistent writable state directory for `devices.json`. Configure `--state-dir /var/lib/connectnow-console` and a service-owned `StateDirectory=connectnow-console` when switching to the console. Keep the gateway configuration read-only. Apply privileged service changes only through the separately authorized deployment workflow; changing source does not provision or restart the live service. See [multi-cloud bindings](../docs/MULTI_CLOUD.md) for migration, limits and rollback.


When upgrading an existing console without `--state-dir`, deploy the reviewed wheel first, then back up the current drop-in and gateway configuration privately and install `console.service.conf`. Reload systemd and restart only ConnectNow. Verify the service user can write its StateDirectory and that the existing device identities remain unchanged. Never replace existing devices.json with a fresh registry.

Rollback across this CLI change must restore the old drop-in before switching to the older release, since older versions do not accept `--state-dir`. Preserve the new state directory for recovery; older code does not consume its dynamic registrations. A rollback therefore temporarily makes newly registered devices unavailable and can restore original configuration entries previously revoked in the new registry; inspect identities and revocations before any rollback after user activity.
