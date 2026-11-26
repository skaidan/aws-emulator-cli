# Testcontainers modules for AWS Emulator

`AwsEmulatorContainer`, for Python, Java and Node, for teams that start their test dependencies with [Testcontainers](https://testcontainers.com). Each one:

- runs the Docker image that `awsemu image build` makes (AWS doesn't publish one), by default `$AWSEMU_IMAGE` or `aws-emulator`, on a random host port;
- waits until the emulator is ready and reads its certificate and keys from the container (every start makes new ones);
- gives you the endpoint (`https://127.0.0.1:<port>`, an IP so S3 puts the bucket in the path), the credentials, the region and a way to trust the certificate **only in the clients that talk to it**;
- can start it with authentication off (`auth=False` / `false`).

They're tested in CI against the real image (the `testcontainers` job). They aren't on PyPI, Maven Central or npm yet; until then, depend on this folder (or copy the one file).

First, once per machine (and in CI):

```bash
awsemu image build
```

## Python

In the `awsemu` package: `pip install "aws-emulator-cli[testcontainers]"`.

```python
from awsemu.containers import AwsEmulatorContainer

with AwsEmulatorContainer() as emulator:          # AwsEmulatorContainer(auth=False), (image="aws-emulator:1.2")
    s3 = emulator.client("s3")                    # a boto3 client for it
    s3.create_bucket(Bucket="photos")

    emulator.endpoint_url, emulator.ca_path       # for your own clients (verify=emulator.ca_path)
    emulator.aws_env()                            # AWS_ENDPOINT_URL, AWS_CA_BUNDLE, keys… for a child process
```

As a pytest fixture:

```python
@pytest.fixture(scope="session")
def emulator():
    with AwsEmulatorContainer() as container:
        yield container
```

If you don't already use Testcontainers, the [pytest plugin](../docs/testing.md#pytest-plugin) does the same with less: the `aws_emulator` fixture.

## Java

[`java/`](java): a Maven project (Testcontainers 2, Java 17+). The SDK types in its API come from your AWS SDK for Java v2.

```java
try (AwsEmulatorContainer emulator = new AwsEmulatorContainer()) {   // new AwsEmulatorContainer(DockerImageName.parse("aws-emulator"), false): auth off
    emulator.start();
    S3Client s3 = S3Client.builder()
        .endpointOverride(emulator.getEndpoint())
        .region(emulator.getRegion())
        .credentialsProvider(emulator.getCredentialsProvider())
        .httpClient(ApacheHttpClient.builder()
            .tlsTrustManagersProvider(emulator.getTrustManagersProvider())   // trusts the emulator, in this client only
            .build())
        .build();
}
```

Also `getSslContext()` and `getTrustManagers()` for other HTTP clients, `getCaCertificatePem()`, and `getAwsEnv()` for a child process. With JUnit 5 or 6, `@Testcontainers` and `@Container static AwsEmulatorContainer emulator = new AwsEmulatorContainer();` work as with any container.

## Node

[`node/`](node): an ES module (Testcontainers 12, Node 22.22+), with types.

```js
import { AwsEmulatorContainer } from "aws-emulator-testcontainers";
import { S3Client } from "@aws-sdk/client-s3";

const emulator = await new AwsEmulatorContainer().start();   // new AwsEmulatorContainer(image, { auth: false })
const s3 = new S3Client(emulator.clientConfig());           // endpoint, region, credentials, an HTTPS agent that trusts it
// ...
await emulator.stop();
```

Also `getEndpoint()`, `getCredentials()`, `getCaCertificate()` and `getAwsEnv()`.

## Notes

- The emulator inside the container thinks it listens on 9297, the host port is another. The calls tested in CI (S3, SQS with the queue URL it returns) work; URLs the emulator builds for you to open yourself, like an S3 presigned URL, carry 9297. For those, use `awsemu start` and the [pytest plugin](../docs/testing.md#pytest-plugin) or the [scripts](../docs/testing.md#scripts), where the port is the same inside and out.
- On a remote Docker host the endpoint is that host, and the emulator's certificate is for `127.0.0.1`: TLS verification fails. Run Docker locally (or in the CI runner).
- `EMULATOR_TELEMETRY` from your environment is passed on to the container.
