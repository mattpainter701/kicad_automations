# Publishing circuit-weaver to PyPI

Uses **OpenID Connect (OIDC)** — no credentials stored in GitHub Secrets.

## One-Time Setup

### 1. Create PyPI Account
- Go to https://pypi.org/account/register/ (if not done)
- Sign in with your account

### 2. Register Trusted Publisher on PyPI
1. Go to https://pypi.org/manage/account/publishing/
2. Under **"Add a new pending publisher"**, fill in:
   - **PyPI Project Name:** `circuit-weaver`
   - **Owner:** `mattpainter701` (your GitHub username)
   - **Repository name:** `kicad_automations`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi` (optional but recommended)
3. Click "Add pending publisher"
4. ✅ Done — no tokens needed!

### 3. (Optional) Create GitHub Environment
For extra security, create a dedicated publishing environment:
1. Go to your repo → Settings → Environments
2. Click "New environment"
3. Name: `pypi`
4. Click "Configure environment"
5. (Optional) Restrict who can deploy from this environment
6. Save

## Publishing Process

### Automatic (Recommended)
1. Update `version` in `pyproject.toml`:
   ```toml
   [project]
   version = "0.11.0"
   ```
2. Commit and push: `git add . && git commit -m "chore: Bump version to 0.11.0" && git push`
3. Create release in GitHub UI:
   - Go to repo → Releases → "Create a new release"
   - **Tag version:** `v0.11.0`
   - **Release title:** `Release 0.11.0`
   - **Description:** Summary of changes (copy from CHANGELOG.md)
   - **Publish release** button
4. ✅ GitHub Actions automatically builds and publishes to PyPI (via OIDC)
   - Check "Actions" tab to see workflow progress
   - Should complete in ~2 minutes

### Manual (If needed)
```bash
# Install build tools
pip install build twine

# Build distribution
python -m build

# Authenticate via browser (no credentials needed)
twine upload dist/
```

## Verification

After publishing, verify on PyPI:
- https://pypi.org/project/circuit-weaver/
- Check version and download link exist
- Install to test: `pip install --upgrade circuit-weaver`

## Troubleshooting

| Issue | Solution |
|-|-|
| `Error 403: OIDC token error` | Ensure trusted publisher is registered at https://pypi.org/manage/account/publishing/ |
| `Error 400: Invalid distribution` | Run `python -m build` locally, then `twine check dist/*` to validate |
| Workflow never runs | Ensure release was "published" (not drafted). Drafted releases don't trigger workflow. |
| Version mismatch | Verify `version` in `pyproject.toml` matches the git tag (e.g., both `0.11.0`) |

## How OIDC Works

1. GitHub Actions creates a temporary OpenID Connect token
2. Workflow presents token to PyPI
3. PyPI verifies:
   - GitHub org/repo matches trusted publisher
   - Workflow file name matches
   - (Optional) GitHub environment matches
4. If valid, allows publish — no API tokens needed ✅

## Files Modified for Publishing

- `.github/workflows/publish.yml` — GitHub Actions workflow (uses OIDC via pypa/gh-action-pypi-publish)
- `pyproject.toml` — Python package config (already set up)
- `PUBLISHING.md` — This guide

## Security Benefits

| Feature | API Token | OIDC |
|-|-|-|
| Credentials stored | GitHub Secrets ⚠️ | None ✅ |
| Token expiry | Manual | Automatic (5 min) ✅ |
| Leaked token risk | High | None ✅ |
| Revocation | Manual | Automatic ✅ |

## Next Steps

1. ✅ Register trusted publisher at PyPI
2. ✅ (Optional) Create GitHub `pypi` environment
3. Create first release on GitHub
4. Watch Actions tab for build status
5. Verify package published on PyPI
