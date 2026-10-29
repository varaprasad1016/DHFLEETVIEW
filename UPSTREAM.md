# DH FleetView — upstream Traccar

DH FleetView is a customised, **squashed** snapshot of [Traccar](https://www.traccar.org)
(Apache-2.0). Our repo was created from a Traccar snapshot rather than a git fork,
so it has **no shared git history** with upstream. We therefore track upstream by
**watch + cherry-pick**, never a wholesale merge.

## The three upstreams

| Ours | Upstream | Default branch |
|------|----------|----------------|
| `src/**` (Java backend) | [`traccar/traccar`](https://github.com/traccar/traccar) | `master` |
| `traccar-web/**` (React) | [`traccar/traccar-web`](https://github.com/traccar/traccar-web) | `master` |
| `traccar-manager/**` (Flutter) | [`traccar/traccar-manager`](https://github.com/traccar/traccar-manager) | `main` |

## Our overlay over Traccar (must survive any cherry-pick)

- **CNMS/CMSV9 video** — `Cmsv9Manager.java`, `Cmsv9Resource.java`, `VideoStreamResource.java`, `TaskCnmsSync.java`, `traccar-web/src/other/Cmsv9VideoPage.jsx`.
- **Tachograph** — `TachographResource.java`, the tacho-bridge WebSocket, the Tachograph page + compliance links.
- **GPS hierarchy / DVR auto-link** — `TaskCnmsSync.java`.
- **Branding / UX** — London timezone (`formatter.js`, `UserUtil.getTimezone`), Google-maps default (`MapView.jsx`), the compliance suite links, foldable error-recovery.

The **overlay guard** (`scripts/check-overlay.sh`, CI `dhfleetview-overlay-guard.yml`)
fails if any of these markers disappear, so a bad edit or cherry-pick can't silently
revert us.

## How we take upstream changes

We do **not** merge upstream wholesale (no shared history → thousands of conflicts,
and this is the live production system). Instead:

1. **Watch** — `traccar-upstream-watch.yml` runs weekly and opens a tracking issue
   for each new upstream release with the changelog + a cherry-pick checklist.
2. **Decide** — review the changelog for security fixes, protocol additions or bug
   fixes worth pulling. Often the answer is "nothing to pull".
3. **Cherry-pick** — apply only the specific change (add `traccar`/`traccar-web` as a
   read-only remote, `git fetch`, then `git cherry-pick <sha>` or port the diff by
   hand into the matching file), keeping our overlay.
4. **Verify** — `bash scripts/check-overlay.sh` stays green; build + test locally.
5. **Deploy** — manually (jar rebuild + `web/` copy), as normal.

### Adding the upstream remotes locally (read-only, for cherry-picking)

```bash
git remote add traccar        https://github.com/traccar/traccar.git
git remote add traccar-web    https://github.com/traccar/traccar-web.git
git remote add traccar-manager https://github.com/traccar/traccar-manager.git
git fetch traccar             # then inspect: git log traccar/master --oneline
```

Because histories are unrelated, a cherry-pick of a backend commit applies to `src/**`
at the repo root; a `traccar-web` commit targets our `traccar-web/**` (paths line up).
Resolve any conflicts in our favour and re-run the overlay guard.
