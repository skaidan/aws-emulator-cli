# awsemu documentation

| Document | What for |
| --- | --- |
| [Getting started](getting-started.md) | Install, start the emulator (native or Docker) and connect your tools. |
| [Exploring the emulator](explore.md) | `ui`, `watch`, `fidelity` and shell completion. |
| [Other languages and IaC tools](languages.md) | JavaScript, Java, Go, Terraform and CDK against the emulator: what each needs, with examples tested in CI. |
| [The proxy](proxy.md) | Every API call logged, and fault injection (throttling, errors, latency): `awsemu proxy`, `watch --calls`, pytest `aws_faults`. |
| [Will my project work?](compatibility.md) | `check`, `issues`, `fidelity --compare`, `install` and pinning the emulator version. |
| [Project settings](project-config.md) | `awsemu.toml`, `init`, `up` and `down`. |
| [Seeds](seeds.md) | Always start with the same data: format, validation, `apply`, `export`. Snapshots: `snapshot save/restore`. |
| [Services guide](services.md) | The 10 services with their own commands, and `describe ARN`, with end-to-end examples. |
| [Testing and CI](testing.md) | pytest plugin, GitHub Action, Testcontainers, scripts and Docker Compose. |
| [Scripting](scripting.md) | Stable JSON output and exit codes for scripts. |
| [Troubleshooting](troubleshooting.md) | What each error means and how to fix it. |
| [Command reference](reference.md) | Every command and option (generated from the code). |
| [Architecture](architecture.md) | How `awsemu` works inside. |
| [Contributing](../CONTRIBUTING.md) | Development setup, tests, adding a service and publishing releases. |

Also: [ROADMAP](../ROADMAP.md) · [CHANGELOG](../CHANGELOG.md)
