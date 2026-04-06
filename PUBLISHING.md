# Publishing circuit-weaver to PyPI

## One-Time Setup

### 1. Create PyPI Account
- Go to https://pypi.org/account/register/
- Register or sign in with existing account

### 2. Generate API Token
- Visit https://pypi.org/manage/account/tokens/
- Click "Add API token"
- **Scope:** "Entire account" (or specific project after first publish)
- **Name:** `github-actions` or similar
- Copy the token (looks like: `pypi-AgEIcHlwaS5vcmc...`)

### 3. Add to GitHub Secrets
1. Go to your GitHub repo → Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. **Name:** `PYPI_API_TOKEN`
4. **Value:** Paste the token from step 2
5. Click "Add secret"

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
4. ✅ GitHub Actions automatically builds and publishes to PyPI

### Manual (If needed)
```bash
# Install build tools
pip install build twine

# Build distribution
python -m build

# Upload (will prompt for credentials)
twine upload dist/*
```

## Verification

After publishing, verify on PyPI:
- https://pypi.org/project/circuit-weaver/
- Check version and download link exist
- Install to test: `pip install --upgrade circuit-weaver`

## Troubleshooting

| Issue | Solution |
|-|-|
| `Error 403: Invalid authentication` | Check PyPI token is correct in GitHub Secrets → `PYPI_API_TOKEN` |
| `Error 400: Invalid distribution` | Run `twine check dist/*` locally to validate package |
| `FileNotFoundError: dist/` not found | Check `python -m build` output for errors |
| Token leaked | Go to PyPI → Manage Account → revoke token, create new one |

## Files Modified for Publishing

- `.github/workflows/publish.yml` — GitHub Actions workflow
- `pyproject.toml` — Python package config (already set up)
- `PUBLISHING.md` — This guide

## Next Steps

1. ✅ Get PyPI token
2. ✅ Add GitHub secret
3. Build `dist/` locally for testing (optional)
4. Create first release on GitHub
5. Watch Actions tab for build status
6. Verify package on PyPI
