# Security

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue: use [Report a vulnerability](https://github.com/skaidan/aws-emulator-cli/security/advisories/new) in this repository's Security tab. Say what's affected, how to reproduce it, and what an attacker could do. You'll get an answer within a week; once there's a fix, the advisory is published with credit to you, unless you'd rather not.

Only the latest release gets security fixes.

## What's in scope

awsemu runs on developers' machines and in CI, and some of it handles credentials and network traffic. These matter most:

- **The proxy** (`awsemu proxy`): it listens on 127.0.0.1, or the network with `--host`; its admin API is protected by a token; it masks secrets in the calls log with `--bodies`.
- **Credentials**: awsemu must never send your real AWS credentials to the emulator, or the emulator's to anywhere else; `env`, `exec`, the MCP server and the pytest plugin remove real credentials from the environment they set up.
- **Reading real accounts**: `awsemu seed import` and the proxy's shadow mode must only ever read configuration, with the profile you name.
- **The MCP server**: its tools must only act on an emulator on this machine.
- **Release artifacts**: the wheels and source archives attached to releases, their provenance attestations and SBOMs.

## What isn't

- **The emulator itself** (AWS Emulator, `aws-emulator`): report its vulnerabilities to AWS, at https://aws.amazon.com/security/vulnerability-reporting/.
- The emulator not enforcing IAM permissions, or accepting requests other AWS emulators would reject: that's how it's designed (see `docs/iam.md`).
- Anything that needs an attacker who can already run code as you on your machine.

## Verifying a release

Each release's wheel and source archive have a signed build provenance (Sigstore, through GitHub attestations), a CycloneDX SBOM and SHA-256 checksums:

```bash
gh release download v0.12.0 -R skaidan/aws-emulator-cli
gh attestation verify aws_emulator_cli-0.12.0-py3-none-any.whl -R skaidan/aws-emulator-cli
sha256sum -c SHA256SUMS
```
