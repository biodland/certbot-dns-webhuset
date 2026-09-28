# Release process

Repository: https://github.com/biodland/certbot-dns-webhuset

This is an independent third-party plugin under the MIT license. A PyPI or Snap
release does not imply endorsement by Certbot, Webhuset, or Nginx Proxy Manager.
The current version is an alpha. Before recommending production use, record
successful live staging issuance for an apex plus wildcard, cleanup, and
`certbot renew --dry-run`. See [validation](VALIDATION.md). NPM integration is
still a proposal and must be tested separately.

## One-time account setup

1. Enable GitHub Actions for this repository.
2. Create GitHub environments `testpypi` and `pypi`. Configure required reviewers
   where supported and restrict deployment to version tags. The workflow names
   environments but cannot configure their protection rules.
3. On each of TestPyPI and PyPI, configure a GitHub Trusted Publisher (or pending
   publisher for the first release) with these exact values:

   | Field | Value |
   | --- | --- |
   | PyPI project | `certbot-dns-webhuset` |
   | GitHub owner | `biodland` |
   | GitHub repository | `certbot-dns-webhuset` |
   | Workflow filename | `publish.yml` |
   | Environment | `testpypi` or `pypi`, matching the destination |

   These are separate registries and separate registrations. Package name
   availability and account ownership must be verified there. No API token is
   needed: the publishing job uses GitHub OIDC.

## Publish a version

1. Update `pyproject.toml`, the NPM draft's version pin, and `CHANGELOG.md`.
   Keep prerelease versions until live validation is complete.
2. Run CI and review the built wheel and source archive. Confirm no credentials,
   HAR captures, or legacy scripts are included.
3. Commit reviewed changes, create a matching tag such as `v0.1.0a1`, and push
   the commit and tag. Do not move a published release tag.
4. In Actions, select **Publish Python package**, **Run workflow**, select the
   version tag, and choose `testpypi`. A branch or mismatched tag is rejected.
5. Test the uploaded package in a fresh environment. Download the exact wheel
   from the TestPyPI project page, then `pip install ./downloaded-file.whl` so
   dependencies are resolved from the normal PyPI index. Check `certbot plugins`.
6. Run the same workflow from the same tag with `pypi` selected after review.
   Registry releases cannot be overwritten; corrections need a new version.
7. Create release notes documenting validation, compatibility, and known limits.

Normal pushes and pull requests run tests only. Publishing always requires a
manual workflow dispatch and registry authorization. Nothing is published by
creating these files locally.

## Certbot and NPM integration

Certbot discovers the installed package through its `certbot.plugins` entry
point. That is the standard third-party integration; inclusion in Certbot's
source tree is a separate decision by its maintainers. Certbot's contribution
guide currently says new plugins should be maintained separately.

For Snap users, build and test the content snap using [SNAP.md](SNAP.md). For
NPM, publish a tested package version first, then propose the provider entry to
the upstream NPM repository following its contribution process. The draft in
`integrations/npm` alone does not add the provider to installed NPM instances.

References:

- [Certbot plugin contributions](https://eff-certbot.readthedocs.io/en/stable/contributing.html)
- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
- [Publishing with GitHub Actions](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
