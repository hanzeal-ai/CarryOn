# Pending worktree integration

## Accepted scope

Integrate 9603 creation fixes and native/Web visuals, and migrate b20a account/workspace binding onto main f5edf58. The user explicitly selected b20a's phone-confirmed binding flow. Both source worktrees are unchanged; every snapshot blob was compared with the original files. Local codex/pending-9603 and codex/pending-b20a branches preserve the sources. The separate c6d7 Web parity task is excluded.

## Integrated behavior and impact

- 9603 creation parsing, idle controller selection and reviewed desktop wake flow coexist with current availability, permissions, background continuity and navigation. Existing project/session switching is retained.
- Stream refresh completes the current projection and then processes the newest pending work, preserving navigation, unread state and epoch/scope/thread/view isolation.
- Scan and target-account bindings require authenticated phone confirmation. Old direct-account binding bypasses and obsolete entrances are removed. Main cancellation, cloud recovery, account isolation and authorization remain authoritative.
- Independent workspaces retain immutable isolated Codex homes and separate model login. Main app-server pagination, protocol mapping, locking and uncertain-delivery handling are retained. Creation remains accepted until native terminal evidence resolves it.
- Cancelled invitations cannot be confirmed by a stale phone; removed registry entries cannot be silently reinitialized. Regression tests cover both cases and preserve session files.
- iOS and desktop include password/account/workspace controls. Web binding routes are migrated. Product configuration drives the cloud default and Apple association generation; signing generation is outside the build graph.

## Verification and review

Independent source review accepted the creation/visual and stream changes, then identified two binding/lifecycle blockers. Both were fixed and the independent reviewer accepted the final migration after rerunning focused binding/workspace tests.

Observed integration checks: Swift 104 tests; Node 34 tests; Web 8 viewport/theme combinations and mobile 21 geometry checks plus interactions; iOS cache/background 27 checks; final iOS navigation and permission alignment simulator checks passed. Full arm64 simulator build and isolated desktop lifecycle smoke passed, including distinct workspace homes/processes, account isolation and deletion retaining files. Generated signing plist matches product configuration. Final full Python suite: 494 tests, 1 skipped, passed; final workspace suite after CI portability adjustment: 4 passed.

The native app-server integration test runs against installed Codex locally and explicitly skips on hosts without it; unit configuration coverage does not require that executable. Physical-device signing, hosted Apple association and real-cloud end-to-end binding have not been verified by these local checks.

## Recovery and delivery

No source worktree is removed or modified. Existing account/device registries remain the authority and are not reset. Existing bindings remain usable; old clients using removed binding-creation routes must update to the phone-confirmation flow. No database migration is required. Keep f5edf58 and the source snapshots for recovery. Before rolling back after new account/device activity, preserve persistent console state and inspect revocations; do not restore an old registry over new changes. The existing deployment receiver health-checks the release and restores its previous release symlink on failure. Privileged service/nginx provisioning is outside this integration.

User authorization includes local commit and merge, push, and automatic deployment. Final delivery must distinguish repository merge, workflow deployment, and actual health verification. The separate c6d7 Web parity changes remain pending integration.
