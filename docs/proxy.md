# The proxy: see every API call, and inject faults

AWS Emulator answers your API calls, but it doesn't log them, and it doesn't throttle, fail or slow down the way AWS sometimes does. `awsemu proxy` sits between your code and the emulator to add both:

- **every call, logged**: service, operation, resource, result (the AWS error code), latency;
- **fault injection**: throttling, AWS errors, HTTP 5xx, dropped connections and extra latency, on the services and operations you pick, at the rate you pick, to test your retries and error handling.

```
your code ──https──▶ awsemu proxy (127.0.0.1:9298) ──https──▶ AWS Emulator (127.0.0.1:9297)
                       │ logs every call
                       └ injects the faults you ask for
```

## Quick start

```bash
awsemu up                                   # the emulator, on 9297
awsemu proxy start -d                       # the proxy, on 9298, in the background
awsemu exec --proxy -- pytest               # run anything through it
awsemu watch --calls                        # in another terminal: every call, live
awsemu proxy faults add 'dynamodb=throttle@10%'
awsemu proxy stop
```

`awsemu watch --calls` prints one line per call:

```
10:42:01.112  dynamodb PutItem                         orders                           200                             12.4 ms
10:42:01.140  dynamodb PutItem                         orders                           ThrottlingException              1.1 ms  ⚡ dynamodb=throttle@10%
10:42:01.190  dynamodb PutItem                         orders                           200                              9.8 ms
10:42:01.231  sqs SendMessage                          jobs                             200                              4.0 ms
10:42:02.007  s3 GetObject                             uploads/report.pdf               NoSuchKey                        3.2 ms
```

Calls marked ⚡ were changed by a fault rule; the rest got the emulator's own answer.

## Sending your code through the proxy

The proxy listens on `https://127.0.0.1:<emulator port + 1>` with its own certificate. Your code needs that address and that certificate instead of the emulator's:

| How | Command |
| --- | --- |
| One command | `awsemu exec --proxy -- npm test` |
| A sub-shell | `awsemu shell --proxy` |
| This shell | `eval "$(awsemu env --proxy)"` |
| A `.env` file | `awsemu env --proxy --shell dotenv > .env.emulator` |
| pytest | the `aws_faults` and `aws_calls` fixtures, or `--awsemu-proxy` ([below](#in-pytest)) |
| Every command, by default | `proxy = true` in `awsemu.toml` ([below](#in-awsemutoml)) |

`env --proxy` sets `AWS_ENDPOINT_URL` to the proxy and `AWS_CA_BUNDLE` to its certificate, `~/.aws/emulator-cli/proxy/ca.pem`. Unlike the emulator's, which is new on every start, the proxy's certificate stays the same, so it can be trusted once. `--sdk node` also sets `NODE_EXTRA_CA_CERTS`. Java ignores `AWS_CA_BUNDLE`: import `ca.pem` into your truststore with `keytool -importcert`, or start the proxy with `--no-tls` (plain HTTP, nothing to trust).

The proxy forwards each request untouched, `Host` header included. So SigV4 signatures stay valid, and the URLs the emulator builds from the host (SQS queue URLs) point at the proxy, keeping later calls on it.

## Commands

```bash
awsemu proxy start                 # in the foreground, printing each call; Ctrl-C stops it
awsemu proxy start -d              # in the background
awsemu proxy start --listen 0      # any free port (or --listen PORT)
awsemu proxy start --fault 's3=latency:500ms' --fault 'sqs=503@5%'
awsemu proxy start --no-tls        # plain HTTP
awsemu proxy status [--json]       # where, how many calls, which faults (exit code 3 if not running)
awsemu proxy stop                  # (awsemu stop and awsemu down stop it too)

awsemu proxy faults                # the rules, and how many times each fired
awsemu proxy faults add RULE...    # add rules; they apply to the next calls
awsemu proxy faults set RULE...    # replace them all
awsemu proxy faults clear

awsemu proxy calls                 # the last 20 calls (-n 100 for more)
awsemu proxy calls --errors --service dynamodb
awsemu proxy calls --json          # for scripts; with --follow, one JSON object per line
awsemu watch --calls               # = awsemu proxy calls --follow
```

`awsemu --port N proxy …` works with the emulator on port N; the proxy follows it (port N + 1). Calls are also kept in `~/.aws/emulator-cli/proxy/<emulator port>/calls.jsonl`, which rotates at 20 MB, so you can read them after the proxy stops. `awsemu ui` shows them too: press `c`.

## Fault rules

A rule is `TARGET=EFFECT[,EFFECT][@RATE][xTIMES]`:

| Rule | Means |
| --- | --- |
| `dynamodb=throttle@10%` | 10% of DynamoDB calls are throttled |
| `s3=latency:500ms` | every S3 call takes 500 ms longer |
| `s3:GetObject=503@50%` | half of the GetObject calls get a 503 |
| `sqs:Send*=reset@5%` | 5% of SendMessage and SendMessageBatch calls lose the connection |
| `lambda:Invoke=latency:2s,TooManyRequestsException@20%x3` | 20% of invocations wait 2 s and fail, 3 times at most |
| `dynamodb:PutItem=ConditionalCheckFailedException x1` | the next PutItem fails with that error, once |
| `*=InternalFailure:500@1%` | 1% of everything fails with a 500 |

**TARGET**: `service` or `service:Operation`, with boto3 service names (`dynamodb`, `s3`, `stepfunctions`, `logs`…). It's case-insensitive, and `*` and `?` work as wildcards.

**EFFECT**:

- `latency:500ms`, `latency:2s` (or just `500ms`): wait that long before forwarding the call.
- `throttle`: the throttling error that service's SDKs expect and retry. That's `ThrottlingException` (JSON APIs like DynamoDB, SQS, Kinesis), `Throttling` (query APIs like SNS, IAM), `SlowDown` with a 503 (S3), `TooManyRequestsException` with a 429 (Lambda and other REST APIs), or `RequestLimitExceeded` (EC2).
- An error code, optionally with its status: `ConditionalCheckFailedException`, `InternalFailure:500`. Without a status it uses 400, or the usual one for well-known codes (500 for `InternalError`, 503 for `ServiceUnavailable`).
- An HTTP status from 400 to 599: `500`, `503`, with a matching code.
- `reset`: close the connection without answering. SDKs see a connection error and retry.

**RATE**: `10%` or `0.1`; 100% if omitted. Each matching rule rolls its own dice. **xTIMES** stops a rule after it has fired that many times.

When several rules match a call, their latencies add up and the first error wins. An injected error never reaches the emulator.

### Errors your SDK believes

Each error is written in the API's own protocol: JSON (`__type`), REST-JSON (`x-amzn-ErrorType`), query and EC2 XML, S3's XML, and Smithy RPC v2 CBOR. So the SDK raises the same exception it would raise for AWS (`ClientError` with that code in boto3, `ThrottlingException` in the JavaScript SDK…), and applies the same retry rules. The message says it was injected: `Injected by awsemu proxy (dynamodb=throttle@10%)`.

This is checked against botocore for every protocol in the tests: it reads each injected error with the right code, and counts throttling and 5xx errors as retryable.

## In pytest

Three fixtures come with awsemu's pytest plugin:

```python
import boto3

def test_retries_throttled_writes(aws_faults):
    aws_faults.add("dynamodb:PutItem=throttle x2")
    save_order({"id": "1"})                          # your code
    assert aws_faults.operations().count("dynamodb:PutItem") == 3

def test_reports_a_missing_bucket(aws_faults):
    aws_faults.add("s3:GetObject=NoSuchKey:404")
    assert load_report("2026-11") is None

def test_sends_one_message_per_order(aws_calls):
    place_orders(3)
    assert aws_calls.operations().count("sqs:SendMessage") == 3
    assert not aws_calls.errors()
```

- `aws_faults` sends the test's AWS calls through a proxy and lets you add rules with `.add(...)` or replace them with `.set(...)`. The rules are removed when the test ends.
- `aws_calls` does the same without faults, to assert on the calls your code made.
- Both give you `.calls` (dicts as in `awsemu proxy calls --json`), `.operations()` (`["dynamodb:PutItem", …]`), `.errors()` and `.client("s3")`, a boto3 client that goes through the proxy. They only include the calls made during the test.
- `aws_proxy` (session) is the proxy itself. It runs inside the pytest process, on a free port, in front of the `aws_emulator` emulator, and is started the first time a test needs it.

The fixtures point `AWS_ENDPOINT_URL` and `AWS_CA_BUNDLE` at the proxy during the test. Clients created before the test started, for example at import time or in a session fixture, keep the address they were created with. Create them in the code under test, or use `aws_faults.client(...)`.

To send **every** test's calls through the proxy, use `pytest --awsemu-proxy`, or `awsemu_proxy = true` in your pytest ini settings, or `proxy = true` in `awsemu.toml`. The `faults` in `awsemu.toml` then apply to the whole session.

## In `awsemu.toml`

```toml
proxy = true                         # awsemu up starts it; env, exec, shell and aws go through it
proxy_port = 9298                    # default: the emulator's port + 1 (0 = any free port)
faults = ["dynamodb=throttle@5%", "s3=latency:200ms"]
```

With `proxy = true`:

- `awsemu up` starts the proxy (with these `faults`) after the emulator;
- `awsemu env`, `exec`, `shell` and `aws` go through it whenever it's running (`--no-proxy` to skip it);
- `awsemu down` and `awsemu stop` stop both;
- the pytest plugin sends every test through a proxy with these faults.

## Limits

- The proxy only sees calls that are sent to it. Anything the emulator does inside, like an S3 event that triggers a Lambda function or a Lambda function calling DynamoDB, goes straight to the emulator. Those calls aren't logged and get no faults.
- Request and response bodies are kept in memory while they pass through, which is fine for tests but not for multi-gigabyte objects.
- The proxy identifies calls from the service models of your installed botocore (the first time, it builds an index of them in about 2 s, cached per botocore version). A call it can't identify still goes through, logged with its method and path.
- Errors injected into a Smithy RPC v2 CBOR API (some newer services) follow the protocol's specification, but only botocore has been checked against them.
