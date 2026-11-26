# Other languages and infrastructure tools

Any AWS SDK or tool works with the emulator once it has three things: the emulator's **address**, its **certificate** and its **credentials**. `awsemu exec` (or `awsemu env`, `awsemu shell`) sets them in the environment, so your code and configuration don't change: the same code runs against AWS.

```bash
awsemu exec -- COMMAND                  # Python, Go, Rust, Terraform, the AWS CLI
awsemu exec --sdk node -- COMMAND       # JavaScript / TypeScript (and CDK)
awsemu exec --sdk java -- COMMAND       # Java / Kotlin
```

Each example below is in [`examples/`](../examples) and runs in CI against the real emulator on every change.

| Language or tool | Example | Command |
| --- | --- | --- |
| Python (boto3) | the pytest plugin, [testing.md](testing.md) | `awsemu exec -- pytest` |
| JavaScript / TypeScript, SDK v3 | [`examples/sdks/node`](../examples/sdks/node) | `awsemu exec --sdk node -- node smoke.mjs` |
| Java, SDK v2 | [`examples/sdks/java`](../examples/sdks/java) | `awsemu exec --sdk java -- mvn -q -o exec:java` |
| Go, SDK v2 | [`examples/sdks/go`](../examples/sdks/go) | `awsemu exec -- go run .` |
| Terraform | [`examples/terraform`](../examples/terraform) | `awsemu exec -- terraform apply` |
| AWS CDK | [`examples/cdk`](../examples/cdk) | `awsemu exec --sdk node -- npx cdk deploy` |

## What awsemu sets, and who reads it

| Variable | What it is | Read by |
| --- | --- | --- |
| `AWS_ENDPOINT_URL` | `https://127.0.0.1:<port>` | every current SDK, the AWS CLI, Terraform's AWS provider, the CDK CLI |
| `AWS_CA_BUNDLE` | the emulator's certificate | Python, Go, Rust, the AWS CLI, Terraform; **not** Node or Java |
| `NODE_EXTRA_CA_CERTS` (`--sdk node`) | the same certificate, for Node.js | JavaScript SDK, CDK CLI |
| `JAVA_TOOL_OPTIONS` (`--sdk java`) | the emulator's truststore for the JVM, added to your own options | Java and Kotlin SDKs |
| `AWS_CONFIG_FILE`, `AWS_SHARED_CREDENTIALS_FILE` | region and credentials written by the emulator | every SDK |
| `AWS_DISABLE_HOST_PREFIX_INJECTION` | no `account-id.` or similar host prefixes | every SDK |

Always use `127.0.0.1`, never `localhost`: with an IP address the SDKs put the S3 bucket in the path. With `localhost`, the JavaScript, Java and Go SDKs put it in the host name (`bucket.localhost`), which the emulator doesn't serve. `awsemu doctor` warns about it.

## JavaScript and TypeScript

```bash
cd examples/sdks/node
npm install
awsemu exec --sdk node -- node smoke.mjs
```

Create clients without options (`new S3Client({})`): endpoint, region and credentials come from the environment. Node.js doesn't read `AWS_CA_BUNDLE`, so pass `--sdk node`, which sets `NODE_EXTRA_CA_CERTS`. For a test runner: `awsemu exec --sdk node -- npm test`.

## Java and Kotlin

```bash
cd examples/sdks/java
mvn -q compile dependency:resolve-plugins     # first, outside awsemu exec
awsemu exec --sdk java -- mvn -q -o exec:java
```

`--sdk java` adds `-Djavax.net.ssl.trustStore=<the emulator's truststore>` to your `JAVA_TOOL_OPTIONS`, keeping your other options (proxy settings, memory). The JVM then trusts **only** the emulator. Anything else in that process that uses HTTPS fails, for example Maven or Gradle downloading dependencies. So build first, then run with the emulator's truststore (`mvn -o` works offline). In your tests, run the test task itself through `awsemu exec --sdk java`, after a build that downloaded everything.

## Go

```bash
cd examples/sdks/go
go mod tidy
awsemu exec -- go run .
```

`config.LoadDefaultConfig` reads everything from the environment, including `AWS_CA_BUNDLE`; nothing else is needed. The same works for `go test ./...`.

## Terraform

```bash
cd examples/terraform
terraform init
awsemu exec -- terraform apply -auto-approve
awsemu exec -- terraform destroy -auto-approve
```

The `provider "aws" {}` block has nothing emulator-specific: the AWS provider reads `AWS_ENDPOINT_URL`, `AWS_CA_BUNDLE` and the credentials from the environment. Avoid per-service `endpoints {}` blocks and `skip_*` settings written for other emulators; they aren't needed. In CI, the example also checks that a second `plan` finds nothing to change, so every resource reads back the way it was written.

Fidelity of the resources you use: `awsemu check examples/terraform` (it reads `.tf` files).

## AWS CDK

```bash
cd examples/cdk
npm install
awsemu exec --sdk node -- npx cdk deploy --require-approval never
awsemu exec --sdk node -- npx cdk destroy --force
```

CDK normally relies on the bootstrap stack that `cdk bootstrap` creates (a bucket and roles for assets), and the emulator starts empty. The example uses `BootstraplessSynthesizer` and turns off version reporting (`versionReporting: false` in `cdk.json`, so there's no `AWS::CDK::Metadata` resource). That deploys stacks without assets: no Lambda code or Docker images. Against AWS, use the default synthesizer as usual.

CloudFormation and SAM templates deploy the same way, with the AWS CLI: `awsemu aws cloudformation deploy --template-file template.yaml --stack-name app`. `awsemu check` reads them and shows how the fidelity tests that deploy each service through CloudFormation do.

## In CI

The [GitHub Action](testing.md#github-actions) exports the variables to the rest of the job. For Node or Java, ask for them with the `sdk` input:

```yaml
- uses: skaidan/aws-emulator-cli@v0.9.0
  with:
    sdk: node          # or java, or "node,java"
- run: npm test        # no awsemu exec needed
```
