# Pending worktree integration

Scope: integrate 9603 creation fixes and native/Web visuals with main f5edf58, plus the independent streaming-refresh fix from b20a. Original worktrees remain unchanged. Full snapshots are preserved in local codex/pending-9603 and codex/pending-b20a branches.

9603 merge retains both continuity state and text selection, list scroll restoration and new visual tokens. Creation uses its reviewed desktop deep-link wake flow only for selecting a creation controller; history display remains read-only until native readiness is confirmed.

b20a also contains a divergent account/binding and app-server implementation. Those changes are NOT integrated pending the user's choice between retaining current main foundations and migrating to the older task's binding workflow. Do not treat its preservation branch as release-ready or merge its whole tree blindly.

The streaming refresh was ported independently: finish current projection and serial display transaction, then process latest pending work; retain current new-message detection, navigation application, reading-position policy, epoch/scope/thread and view-lifecycle checks.

Validation: Python 474 tests (1 skipped), Swift 104 tests, Node 34 tests; Web 8 viewport/theme combinations and mobile 21 geometry checks plus functional flows. Cache/background simulator 27 checks passed before queue port. Independent source review accepted the creation/visual merge and the queue lifecycle; no production actions or real-device installation during integration. Final navigation result recorded below.

Recovery: no source worktree changes or production data migration; main can remain at f5edf58 until acceptance. Snapshot branches preserve original work for later analysis.
