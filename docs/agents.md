# AI coding agents

A coding agent writes code that calls AWS; the only way to know it works is to run it. With the emulator, the agent runs that code on your machine, reads the real AWS error when something is wrong, fixes it and tries again, without an AWS account and without waiting for deployments. `awsemu` gives the agent that loop as tools, through an **MCP server**, with guard rails so it can never test against a real account by mistake.

## Add the server to your agent

```bash
awsemu mcp config claude-code        # prints: claude mcp add awsemu -- /path/to/awsemu mcp
awsemu mcp config claude-desktop     # JSON for claude_desktop_config.json
awsemu mcp config cursor             # JSON for .cursor/mcp.json
awsemu mcp config vscode             # JSON for .vscode/mcp.json
awsemu mcp config                    # the generic "mcpServers" JSON most agents take
```

The agent starts `awsemu mcp` itself and talks to it over stdio. Start the agent from your project's folder, so `awsemu.toml` (port, seed, proxy, faults) applies. For another port, `awsemu --port 9400 mcp config …` puts it in the command.

The server needs nothing beyond `awsemu`: no MCP library, no network.

## The tools

| Tool | What it does |
| --- | --- |
| `emulator_status` | Is it running and healthy; port, mode, uptime. The agent's first call. |
| `emulator_start` / `emulator_stop` | Start it (native or Docker, and wait until healthy), optionally applying a seed; stop it. |
| `emulator_env` | The variables that point SDKs, the AWS CLI and Terraform at the emulator (or the proxy), and the advice to run commands as `awsemu exec -- …`. |
| `seed_apply` | Create the starting data a seed file describes. |
| `list_resources` / `describe_resource` | What's in the emulator, per service; one resource from its ARN. |
| `aws_call` | Any operation of any service (like `awsemu call`), with JMESPath and pagination. |
| `fidelity` | How closely the emulator matches AWS per service, and which tests fail. |
| `check_project` | The operations the project uses and the known emulator differences for them (from the code, or from the proxy's log). |
| `proxy_start`, `proxy_calls`, `proxy_faults` | Start the [proxy](proxy.md) (with bodies, masked), read every call the code made, inject throttling, errors or outages. |
| `explain_failure` | For a failed call: a known emulator difference, or probably the code? ([below](#explaining-a-failure)) |

Each tool runs the matching `awsemu` command and returns its output; with `--json` commands, also as structured content. The tools say whether they only read (`readOnlyHint`) or can lose data (`emulator_stop` is marked destructive), so agents that ask before such calls do.

A typical session: the agent calls `emulator_status`, starts the emulator if needed, runs your tests with `awsemu exec -- pytest` in its shell, and when one fails, looks at `proxy_calls` and `explain_failure` before changing your code.

## Guard rails

The tools exist to keep an agent away from your AWS account, so:

- **No real credentials.** Each command runs with `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_PROFILE`, the config and credentials file variables, role and container credential variables, and every `AWS_ENDPOINT_URL*` removed from its environment. awsemu's own clients use the emulator's keys and address in any case; this makes sure nothing else can leak in.
- **Only 127.0.0.1.** Tools that talk to the emulator refuse to run unless its endpoint, both the one awsemu uses and the one in the emulator's own config file, is `127.0.0.1`, `::1` or `localhost`.
- **Nothing to aim it elsewhere.** No tool takes an endpoint, a region, a profile or keys as an argument (the tests check this).
- **Every answer says where it ran.** Each result starts with `AWS Emulator on 127.0.0.1:9297 (this machine, not AWS; no real AWS account or credentials are used)`, so the agent, and you reading its transcript, can't mistake an answer for AWS.

These rules cover the MCP tools. What the agent runs in its own shell is up to the agent and your permissions; running commands as `awsemu exec -- …` gives them the emulator's environment, without your real keys (it removes them too).

## Explaining a failure

When a test fails on an AWS call, the question is whether the code is wrong or the emulator differs from AWS. `explain_failure` (and `awsemu explain CALL` on the command line) answers from evidence, with the call from the proxy's log and the fidelity tests of your emulator release:

| Verdict | When |
| --- | --- |
| `injected` | the proxy made the error (a fault rule) |
| `known_difference` | a fidelity test fails at the same operation with the same answer from the emulator |
| `possible_difference` | fidelity tests fail at that operation, with another answer |
| `emulator_gap` | a server error, or the emulator doesn't implement it (501) |
| `likely_your_code` | the operation's fidelity tests pass, and it's the kind of error AWS returns for a bad request |
| `unknown` | no fidelity tests cover the operation |
| `succeeded` | the call didn't fail |

The answer lists the tests and what AWS and the emulator answered in each, with the emulator's open issue that explains it, if any. It's evidence, not proof: an agent should read `likely_your_code` as "look at the request first", and `known_difference` as "your code may be right". For an emulator difference that isn't known yet, `awsemu report CALL` drafts the issue.

```bash
awsemu proxy start -d --bodies
awsemu exec --proxy -- pytest
awsemu explain                 # the last failed call
awsemu explain 42 --json
```

## With AWS's `aws-emulator` skill

AWS's emulator README suggests installing an `aws-emulator` skill (`aws agent-toolkit add-skill --skill-name aws-emulator --region us-east-1`, with AWS CLI 2.35.0 or later) and asking the agent to set up the emulator. The skill teaches the agent about the emulator; awsemu's server gives it tools to run it. They work together: the skill for what the emulator is and how to install it, `awsemu mcp` for starting it, seeding it, looking inside and explaining failures.

The same Agent Toolkit also configures the **AWS MCP Server**, which reaches your **real** AWS account with your credentials. Keep the two apart in the agent's instructions: `awsemu` tools for testing, the AWS MCP Server only when you mean to touch AWS.

## A line for your `AGENTS.md`

Agents follow the project's instructions file (`AGENTS.md`, `CLAUDE.md`…). Something like:

```markdown
## Testing AWS code
- Run tests against AWS Emulator, never a real account: `awsemu up`, then `awsemu exec -- pytest`.
- The awsemu MCP tools manage the emulator; when an AWS call fails, use explain_failure before
  changing the code: the emulator may differ from AWS.
```
