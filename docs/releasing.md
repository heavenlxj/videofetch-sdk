# Releasing (runbook)

> Domain/accounts are still pending — this file is the checklist you (or CI)
> follow once `videofetch-py`, `@videofetch/sdk` and the Go repo are ready to go
> public. Everything below is manual until then.

## 0. Prereqs (one-time, human)

- [ ] PyPI: register account + 2FA. Reserve the name `videofetch`
      (fallback: `videofetch-py`).
- [ ] PyPI trusted publishing: add pending publisher for
      `github.com/<org>/videofetch-sdks`, workflow `release-python.yml`.
- [ ] npm: create org `videofetch` (or verify availability), generate an
      automation token with publish rights → GitHub secret `NPM_TOKEN`.
- [ ] Go: nothing to register — git tag + public GitHub repo is all it takes.
- [ ] GitHub repo `videofetch-sdks` is public, LICENSE = MIT.
- [ ] Domain `api.videofetch.dev` resolves to the deployment (or override
      `base_url` in each SDK release until then).

## 1. Version bump

- Python: `python/pyproject.toml` `version = "0.1.0"` → commit.
- TS: `typescript/package.json` `"version"` → commit (changesets optional at 0.x).
- Go: no file bump — the git tag IS the version.

Keep the three versions independent (semver per language). A breaking API
change ships as a coordinated release across all three the same week.

## 2. Tag & push (git write ops are done by you)

```bash
git tag python-v0.1.0    # triggers .github/workflows/release-python.yml
git tag ts-v0.1.0        # triggers .github/workflows/release-ts.yml
git tag go-v0.1.0        # triggers .github/workflows/release-go.yml
git push origin --tags
```

## 3. What CI does

| workflow | trigger | action |
|---|---|---|
| `release-python.yml` | `python-v*` | build sdist+wheel → PyPI via trusted publishing (OIDC, no token) |
| `release-ts.yml` | `ts-v*` | `npm ci && test && build` → `npm publish --provenance` (NPM_TOKEN) |
| `release-go.yml` | `go-v*` | test → create GitHub Release with auto notes (proxy.golang.org picks the tag up automatically) |

Each job runs the full test suite again as a gate. Test suite also runs on every
PR (`ci.yml`).

## 4. Verify after publish

```bash
pip install videofetch && python -c "import videofetch; print(videofetch.__version__)"
npm view @videofetch/sdk version
go list -m -versions github.com/heavenlxj/videofetch-go
```

## 5. Docs

- README badges (PyPI/npm/Go tag) at the repo root.
- Link `docs/getting-started.md` from the future docs site
  (Nextra/Docusaurus/Mintlify) once the domain exists.
- Keep `openapi/openapi.json` in sync whenever the backend contract changes
  (export from `GET /openapi.json`), then bump SDK versions.
