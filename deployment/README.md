# Aliyun lightweight server delivery

The gateway runs as a dedicated `carryon` service account on loopback port 8780. It does not run the macOS device service, access Codex data, or expose a SaaS console. The device connects outbound to `wss://HOST/carryon/device`; your backend uses `https://HOST/carryon/v1/...`.

## One-time host provisioning

Inspect existing workloads, ports, Python 3.11, systemd and TLS before provisioning. Run `bootstrap.sh` as root from this directory with `DEPLOY_PUBLIC_KEY` set to a dedicated Ed25519 public key. It refuses existing accounts/paths. Review before executing: it creates two service accounts, a single systemd unit, a forced SSH receiver and an exact service-specific sudo rule. It neither replaces host SSH credentials nor grants a root shell. Gateway credentials are created only on the server in `/etc/carryon/gateway.json` (0600), independently of deployment credentials.

Deploy-user SSH always runs the root-owned `receive.py`, with the requested commit SHA as `SSH_ORIGINAL_COMMAND` and wheel bytes on stdin. No SCP, terminal, SSH forwarding or arbitrary command is accepted. The receiver bounds archive size, rejects unsafe paths, checks imports before activation, switches releases atomically, restarts only CarryOn, verifies the exact release through `/healthz` and restores the old release if startup fails. Application code runs without root, with a read-only filesystem, no capabilities and resource limits. The deploy key can replace application code and therefore must be treated as granting access to gateway data; it does not grant administrative access to other applications.

Create GitHub repository secrets `DEPLOY_SSH_KEY` and `DEPLOY_KNOWN_HOSTS`. Verify the host public key through the authenticated Aliyun CLI before recording it; the workflow never uses trust-on-first-use or disables host verification. Set repository variables `DEPLOY_HOST` and, only after review/provisioning, `DEPLOY_ENABLED=true`.

The workflow runs tests and builds a pure Python wheel on Ubuntu. It then runs `python deployment/check_wheel.py dist/*.whl`, validating the uploaded archive and exercising both cloud entrypoints from its extracted contents without source-tree or installed-package fallback. Pushes to main and manual runs deploy only when enabled. Pull requests never deploy. Actions are pinned by commit; no cloud account AccessKey is copied to GitHub. The initial repository push keeps deployment disabled.

## HTTPS reverse proxy

Add a location inside the existing server block for your valid TLS address. Preserve its other routes and back up the previous configuration. Test `nginx -t` before reloading.

```nginx
location ^~ /carryon/ {
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

Check systemd active state and `https://HOST/carryon/healthz`, matching the workflow commit. Exercise WSS hello, device authentication, read-only refusal, subscriptions, offline behavior and cross-device authorization using an isolated fake local IPC. Keep real Codex sessions and user content outside smoke tests. Then give the user the device URL, device ID and device token through a local private file for manual product acceptance.

Each successful deployment records `/opt/carryon/previous`; releases and credentials are retained. To roll back, an authorized operator reads and verifies that path, switches `/opt/carryon/current` atomically to it, restarts only `carryon-gateway.service`, and checks the reported release. Do not re-run an old commit through the receiver: duplicate release directories are rejected to avoid ambiguous overwritten releases. Disable the workflow with `DEPLOY_ENABLED=false` to halt further deployments. On a failed first deployment, the receiver stops only CarryOn and removes its current symlink; it does not delete credentials or releases. No database migration is required.

GitHub workflows do not overwrite the receiver, sudoers, service unit or nginx configuration. Changes to these privileged files require separate operator installation after review. The repository contains no deployment private key, host gateway credentials or local runtime data.

## Upgrading hosts from the flat Python module layout

The September 2026 module migration moved `carryon.gateway` and `carryon.console` to
`carryon.cloud.gateway` and `carryon.cloud.console`. An older installed receiver
rejects the new wheel with `Gateway missing` because it expects `carryon/gateway.py`.
Even after replacing that receiver, an old systemd `ExecStart` cannot start the new
release. Inspect `/usr/local/libexec/carryon-receive` and the effective
`systemctl show carryon-gateway.service -p ExecStart -p FragmentPath -p DropInPaths`;
the repository's unit files do not describe what an existing host has loaded.
The current receiver rejects a missing effective service module before creating
or switching a release and imports that module before activation.

For a console host crossing this boundary, do not change only the receiver or
immediately load the final new module path. The receiver's automatic rollback
switches application releases, but does not restore systemd configuration; the
old release still needs `carryon.console`. Coordinate this one-time operation
with an operator, after approval for the privileged changes and release restart:

1. Prevent concurrent deployments. Record the current/previous release paths and
   health response. Privately back up the installed receiver, service unit and
   effective console drop-in, preserving their owners and modes. Do not alter
   gateway credentials, account records or device state.
2. Install the reviewed transitional receiver from the candidate's original
   module-migration version, which validates/imports `carryon.cloud.gateway` but
   does not require a direct `-m` systemd entrypoint. For candidate
   `972b88767766084cb3829c7007b5680bd89aa479`, its `deployment/receive.py` SHA256 is
   `1ea2d65629303c9cb10b2e9d5a72ed72acf27330a238b9e754e18e0d28d5ab06`.
   This is a reviewed one-time bridge, not the final receiver in this directory.
3. Preserve the console drop-in's other settings and temporarily replace only
   its `ExecStart` with the following. This uses the existing service account and
   `/opt/carryon/current` working directory. Run `systemctl daemon-reload`, verify
   the effective command, and leave the running service in place until deployment.

   ```ini
   ExecStart=
   ExecStart=/usr/bin/python3.11 -c "import pathlib,runpy; runpy.run_module('carryon.cloud.console' if pathlib.Path('carryon/cloud/console.py').is_file() else 'carryon.console',run_name='__main__')" serve --config /etc/carryon/gateway.json --state-dir /var/lib/carryon-console --port 8780
   ```

4. Confirm the candidate release directory does not exist, then deploy the exact
   reviewed commit through the existing receiver once. Do not run `bootstrap.sh`
   against an existing host. The temporary command supports both layouts, so the
   receiver can restart either the new release or the old rollback target.
5. On success, restore a direct `-m carryon.cloud.console` command using the
   reviewed console drop-in, update the base unit to `carryon.cloud.gateway`,
   reload systemd, and install the final receiver from this directory. Verify
   the effective command, receiver hash, active state and loopback/public health
   release. No additional restart is required just to replace the temporary
   command. On failure, verify that the receiver restored the old release and
   health, then restore the backed-up receiver/unit/drop-in and reload systemd.
   If automatic rollback did not succeed, restore those files and the recorded
   old current symlink, restart only CarryOn and verify the old release.

For a later rollback to a flat-layout release, load the same temporary command
before switching releases and restarting, verify old health, then restore the
old receiver/unit/drop-in and reload systemd. The final direct new command cannot
start the old release. Keep failed release directories for diagnosis; the
receiver intentionally refuses reusing a release directory.

## Console device registry

The multi-device console needs a persistent writable state directory for `devices.json`. Configure `--state-dir /var/lib/carryon-console` and a service-owned `StateDirectory=carryon-console` when switching to the console. Keep the gateway configuration read-only. Apply privileged service changes only through the separately authorized deployment workflow; changing source does not provision or restart the live service. See [multi-cloud bindings](../docs/MULTI_CLOUD.md) for migration, limits and rollback.


When upgrading an existing console without `--state-dir`, deploy the reviewed wheel first, then back up the current drop-in and gateway configuration privately and install `console.service.conf`. Reload systemd and restart only CarryOn. Verify the service user can write its StateDirectory and that the existing device identities remain unchanged. Never replace existing devices.json with a fresh registry.

Rollback across this CLI change must restore the old drop-in before switching to the older release, since older versions do not accept `--state-dir`. Preserve the new state directory for recovery; older code does not consume its dynamic registrations. A rollback therefore temporarily makes newly registered devices unavailable and can restore original configuration entries previously revoked in the new registry; inspect identities and revocations before any rollback after user activity.

## Existing password accounts after token-login removal

Existing `account.json` records remain bound to the complete recovery authority used when they were written, including a retired `consoleToken` field if present in the server configuration. Keep that field unchanged while such records exist; it is provenance only and cannot authenticate a login. Removing it changes the authority fingerprint and invalidates the stored account. This binding is required until an operator explicitly migrates the account and recovery configuration together. Deploying a new application version does not require rewriting account records, passwords, devices, or sessions. A failed rollout can use the receiver's existing release rollback without a data migration.
