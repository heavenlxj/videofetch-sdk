# Releasing (runbook)

> Domain/accounts are still pending — this file is the checklist you (or CI)
> follow once `videofetch-py`, `@videofetch/sdk` and the Go repo are ready to go
> public. Everything below is manual until then.

## 0. Prereqs (one-time, human)

- [ ] **GitHub repo `heavenlxj/videofetch-sdk` must be PUBLIC** (Go modules are fetched
      by proxy.golang.org — private repos cannot be `go get`-ed without GOPRIVATE).
- [ ] PyPI: register account + 2FA. `videofetch` is TAKEN by an unrelated project —
      this SDK publishes as **`videofetch-sdk`** (import name stays `videofetch`).
- [ ] PyPI trusted publishing: add pending publisher —
      project `videofetch-sdk`, owner `heavenlxj`, repo `videofetch-sdk`,
      workflow `release-python.yml`, environment (leave empty).
- [ ] npm: create org `videofetch`, generate an **Automation** token →
      GitHub repo secret `NPM_TOKEN`.
- [ ] Go: nothing to register. Module path is `github.com/heavenlxj/videofetch-sdk/go`
      and the tag MUST be `go/v0.1.0` (subdirectory module rule).
- [ ] Domain `api.vidfetch.dev` resolves to the deployment (SDKs default to it).

## 1. Version bump

- Python: `python/pyproject.toml` `version = "0.1.0"` → commit.
- TS: `typescript/package.json` `"version"` → commit (changesets optional at 0.x).
- Go: no file bump — the git tag IS the version.

Keep the three versions independent (semver per language). A breaking API
change ships as a coordinated release across all three the same week.

## 1b. npm policy changes (2026) — read before your first release

Three npm changes affect us (source: github.blog/changelog 2026-07-08 + npm docs):

1. **npm v12 install-time security (GA now)** — dependency lifecycle scripts, git
   deps and remote-URL deps no longer run/resolve unless explicitly allowed.
   - Our published SDK is unaffected (zero runtime deps, no lifecycle scripts).
   - Our CI was affected when installing with npm 12: `esbuild` (devDep of tsup)
     installs its binary via a postinstall script. -> We pin **npm 11.x** in
     release-ts.yml and ci.yml (also satisfies trusted publishing's CLI >= 11.5.1).
   - If you later move CI to npm 12, run `npm approve-scripts --allow-scripts-pending`
     and commit the generated allowlist in package.json.

2. **2FA-bypass granular tokens can no longer do account/package management**
   (~Aug 2026): creating/deleting tokens, changing package access or maintainers,
   configuring trusted publishing, org/team management -> do these interactively
   on npmjs.com with 2FA.

3. **2FA-bypass tokens will lose direct publish** (~Jan 2027): they shrink to
   read-private + *stage* a publish (human 2FA approval to make it public).
   -> Migrate automated publishing to **Trusted Publishing (OIDC)**. Our
   release-ts.yml already prefers OIDC and falls back to `NPM_TOKEN` only for the
   very first release.

**Two-phase npm auth for us**
- Phase 1 (first publish 0.1.0): the package does not exist yet, so a trusted
  publisher cannot be configured -> set repo secret `NPM_TOKEN` (Automation
  token) and push `ts-v0.1.0`; the workflow publishes with the token.
- Phase 2 (0.2.0+): npmjs.com -> the package -> **Settings -> Trusted Publisher
  -> GitHub Actions** (owner `heavenlxj`, repo `videofetch-sdk`, workflow
  `release-ts.yml`). Then delete the `NPM_TOKEN` secret — OIDC takes over
  (short-lived credentials, provenance included).

## 2. Tag & push (git write ops are done by you)

```bash
git tag python-v0.1.0    # triggers .github/workflows/release-python.yml
git tag ts-v0.1.0        # triggers .github/workflows/release-ts.yml
git tag go/v0.1.0        # triggers .github/workflows/release-go.yml
git push origin --tags
```

## 3. What CI does

| workflow | trigger | action |
|---|---|---|
| `release-python.yml` | `python-v*` | build sdist+wheel → PyPI via trusted publishing (OIDC, no token) |
| `release-ts.yml` | `ts-v*` | `npm ci && test && build` → `npm publish --provenance` (NPM_TOKEN) |
| `release-go.yml` | `go/v*` | test → create GitHub Release with auto notes (proxy.golang.org picks the tag up automatically) |

Each job runs the full test suite again as a gate. Test suite also runs on every
PR (`ci.yml`).

## 4. Verify after publish

```bash
pip install videofetch-sdk && python -c "import videofetch; print(videofetch.__version__)"
npm view @videofetch/sdk version
go list -m -versions github.com/heavenlxj/videofetch-sdk/go
```

## 5. Docs

- README badges (PyPI/npm/Go tag) at the repo root.
- Link `docs/getting-started.md` from the future docs site
  (Nextra/Docusaurus/Mintlify) once the domain exists.
- Keep `openapi/openapi.json` in sync whenever the backend contract changes
  (export from `GET /openapi.json`), then bump SDK versions.
