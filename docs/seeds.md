# Seeds: reproducible starting data

The emulator keeps everything in memory: stopping or restarting it loses it all. A **seed** is a YAML file describing what you want inside (buckets with objects, queues, tables with items, topics with subscriptions, secrets, parameters, Kinesis streams, Lambda functions from your local code with their triggers, Step Functions state machines and EventBridge rules) so you can recreate it with one command.

```bash
awsemu seed apply seed.yaml          # apply to an emulator that's already running
awsemu start --seed seed.yaml        # start and apply
awsemu reset --seed seed.yaml        # empty it (restart) and apply
awsemu seed validate seed.yaml       # check the file without touching the emulator
awsemu seed export -o seed.yaml      # save what's there now as a seed
```

There's a full example in [`examples/seed.yaml`](../examples/seed.yaml).

## Format

```yaml
version: 1          # optional; this awsemu reads version 1

buckets:
  - name: photos
    objects:
      - {key: hello.txt, content: "hello"}         # text
      - {key: config.json, json: {debug: true}}    # JSON (stored formatted)
      - {key: web/, from: ./site}                  # a whole local folder
      - {key: logo.png, from: ./img/logo.png}      # a local file

queues:
  - name: jobs-dlq
  - name: jobs
    dlq: jobs-dlq            # dead-letter queue
    max_receive: 3           # receives before going to the DLQ (default 5)
    visibility_timeout: 30
    delay: 0
  - name: invoices.fifo
    fifo: true
    content_dedup: true

tables:
  - name: users
    pk: id                   # partition key: NAME or NAME:S|N|B (S by default)
    sk: created:N            # sort key (optional)
    items:
      - {id: u1, created: 1, name: Ana, tags: [admin]}
    items_from: ./users.json # one object or a list, JSON or YAML (optional)

topics:
  - name: orders
    fifo: false
    subscriptions:
      - sqs: jobs                  # creates the subscription and the queue policy
        raw: true                  # without the SNS JSON envelope
        filter: {kind: [new]}      # filter policy
      - lambda: process-order      # adds the invoke permission

secrets:
  - name: db/password
    value: s3cr3t
  - name: db/config
    value: {host: db, port: 5432}  # mappings and lists are stored as JSON
    description: local connection

parameters:
  - {name: /app/host, value: localhost}
  - {name: /app/key, value: abc, type: SecureString}
  - {name: /app/hosts, value: [a, b, c]}     # a list is a StringList

streams:
  - name: clicks
    shards: 2                  # default 1
    retention_hours: 48        # default 24

functions:
  - name: resize
    code: ./functions/resize   # a folder, a single file or a .zip
    handler: app.handler       # guessed from the code if omitted (like 'awsemu lambda deploy')
    runtime: python3.12        # guessed too
    env: {BUCKET: photos}
    timeout: 30                # seconds (default 3)
    memory: 256                # MB (default 128)
    deps: true                 # install the folder's requirements.txt into the package (default true)
    triggers:                  # event source mappings
      - {sqs: jobs, batch_size: 5}
      - {kinesis: clicks, starting_position: TRIM_HORIZON}   # TRIM_HORIZON by default

state_machines:
  - name: order-flow
    definition: ./flows/order.asl.json   # a .json or .yaml file, or the definition inline
    express: false                       # EXPRESS instead of STANDARD

rules:
  - name: orders-created
    bus: default               # other buses are created if missing
    pattern: {source: [app.orders]}
    targets:
      - sqs: jobs              # sets the queue policy
      - lambda: resize         # adds the invoke permission
      - stepfunctions: order-flow
        input: {from: rule}    # optional: a fixed input instead of the event
  - name: nightly
    schedule: rate(1 day)      # instead of a pattern
    targets: [{kinesis: clicks}, {sns: alerts}]
```

Every section is optional. Paths (`from`, `items_from`, `code`, `definition`) are relative to the seed file.

### Fields

| Section | Fields | Required |
| --- | --- | --- |
| `buckets` | `name`, `objects` | `name` |
| `buckets[].objects` | `key` and one of `content`, `json` or `from` | `key` + one of the three |
| `queues` | `name`, `fifo`, `content_dedup`, `visibility_timeout`, `delay`, `dlq`, `max_receive` | `name` |
| `tables` | `name`, `pk`, `sk`, `items`, `items_from` | `name`, `pk` |
| `topics` | `name`, `fifo`, `subscriptions` | `name` |
| `topics[].subscriptions` | one of `sqs` or `lambda`, `raw`, `filter` | `sqs` or `lambda` |
| `secrets` | `name`, `value`, `description` | `name`, `value` |
| `parameters` | `name`, `value`, `type` (`String`, `SecureString`, `StringList`), `description` | `name`, `value` |
| `streams` | `name`, `shards`, `retention_hours` | `name` |
| `functions` | `name`, `code`, `handler`, `runtime`, `env`, `timeout`, `memory`, `description`, `triggers` | `name`, `code` |
| `functions[].triggers` | one of `sqs` or `kinesis`, `batch_size`, `enabled`, `starting_position` (Kinesis) | `sqs` or `kinesis` |
| `state_machines` | `name`, `definition`, `express` | `name`, `definition` |
| `rules` | `name`, `bus`, `description`, one of `pattern` or `schedule`, `enabled`, `targets` (at most 5) | `name`, `pattern` or `schedule` |
| `rules[].targets` | one of `sqs`, `lambda`, `sns`, `stepfunctions` or `kinesis`, `input` | one of the five |

## Validation

`awsemu seed validate`, `seed apply`, `start --seed` and `reset --seed` check the whole file **before** touching the emulator. Errors show the line and the field:

```
✗ seed.yaml:4  queues[0].visibilty_timeout: unknown field (did you mean 'visibility_timeout'?)
✗ seed.yaml:5  queues[1].name: duplicate name 'jobs' (also at queues[0])
✗ seed.yaml:9  tables[0].items[0].created: must be a number (the key type is N)
✗ seed.yaml:14  parameters[0].name: parameter names can't start with 'aws' or 'ssm' (AWS rule)
```

Among other things it checks: unknown fields (with a suggestion), types, duplicate names, that items have the table's key attributes with the right type, that the `from` and `items_from` files exist, that FIFO queues end in `.fifo`, that a queue isn't its own DLQ, and AWS's rule on parameter names.

If a `dlq`, a subscription, a trigger or a rule target points to something that isn't in the seed, that's a warning, not an error: it may already exist in the emulator.

With errors, `validate`, `apply`, `start --seed` and `reset --seed` exit with code 2 without doing anything (`reset` doesn't even stop the emulator).

## What `apply` does

`apply` is repeatable: it creates what's missing, updates what differs and leaves the rest alone. At the end it prints a table with the result for each resource:

```
kind       name           result     detail
bucket     photos         created    3 object(s) written
queue      jobs-dlq       created
queue      jobs           created    dlq → jobs-dlq
table      users          created    2 item(s) written
topic      orders         created    → sqs:jobs
secret     db/password    unchanged
parameter  /app/host      updated
✓ seed applied in 1.4s (5 created, 1 unchanged, 1 updated)
```

| Resource | If it doesn't exist | If it already exists |
| --- | --- | --- |
| Bucket | Creates it and uploads the objects | Uploads the seed's objects again (*updated*); doesn't delete other objects |
| Queue | Creates it | Adjusts attributes that differ; `fifo` can't be changed |
| DLQ | Sets the redrive policy | Changes it if it differs |
| Table | Creates it (on demand) and writes the items | Writes the items (the seed's overwrite those with the same key); **error** if the table's key is different |
| Topic | Creates it | Leaves it |
| Subscription | Creates it, with the queue policy or the Lambda permission | Adjusts `raw` and `filter` if they differ |
| Secret | Creates it | Stores a new version only if the value changed |
| Parameter | Creates it | Overwrites it only if the value or type changed |
| Stream | Creates it and waits until it's active | Changes the shard count or retention if they differ |
| Function | Packages the code, creates the function (with the role `awsemu-lambda-role`) and waits until it's active | Redeploys the code only if it changed (the package is reproducible, so it compares its SHA-256), and updates the settings that differ |
| Trigger | Gives the function's role the permissions Lambda needs to read the queue or stream (the emulator checks them, like AWS), then creates the event source mapping | Adjusts `batch_size` and `enabled` |
| State machine | Creates it (with the role `awsemu-sfn-role`) | Updates the definition if it differs; **error** if `express` changed (the type can't change) |
| Rule | Creates it (and its bus if missing) | Updates the pattern, schedule, state or description if they differ |
| Rule targets | Sets them, with the queue policy, the Lambda permission, or a role for Step Functions and Kinesis | Makes them match the seed: adds, changes, and removes the targets the seed no longer lists |

`apply` **never deletes** resources (only the targets of a rule the seed describes). To start from scratch, use `awsemu reset --seed seed.yaml`.

If a resource fails, `apply` carries on with the rest, marks it as `failed` with the reason and exits with code 1.

The order is: buckets, queues, tables, streams, secrets, parameters, functions, state machines, topics and rules, so everything a function, a subscription or a rule points at exists first.

## Export

```bash
awsemu seed export                          # to standard output
awsemu seed export -o seed.yaml
awsemu seed export -o seed.yaml --objects-dir seed-files     # also saves binary and large objects, and functions' code
awsemu seed export --no-secrets             # without secrets or SecureString parameters
awsemu seed export -s queues -s tables      # only some sections
```

Handy for building a scenario by hand (or with your application) and saving it for your tests.

- S3 text objects up to 64 KiB are stored inside the seed (`content`). Binary or larger ones are saved in `--objects-dir` and referenced with `from`; without that option they're skipped with a warning.
- Secrets and `SecureString` parameters are exported **in plain text**, and `awsemu` warns you when writing the file. Use `--no-secrets` if the seed goes into a repository.
- Only SQS and Lambda subscriptions are exported.
- Lambda functions are exported with `--objects-dir`, which receives their code as `functions/NAME.zip`. Without it they're skipped with a warning. Only SQS and Kinesis triggers are exported.
- State machine definitions are exported inline. Rules managed by AWS services are left out, and so are targets other than SQS, Lambda, SNS, Step Functions and Kinesis.

The exported file can be applied as-is; CI checks that exporting, restarting and applying leaves the emulator as it was.

## Snapshots

A snapshot saves **everything** in the emulator, so you can come back to it later. It's a seed export of every section, with the files it needs (S3 objects that don't fit in the seed, Lambda code) and a little metadata. The emulator has no snapshots of its own: its state lives in memory.

```bash
awsemu snapshot save checkout-ready      # everything there now
awsemu snapshot ls                       # name, when, emulator version, contents
awsemu snapshot restore checkout-ready   # empty the emulator (a restart) and recreate it
awsemu snapshot restore checkout-ready --no-reset   # apply it on top instead
awsemu snapshot rm checkout-ready
```

- Snapshots live in `~/.aws/emulator-cli/snapshots/NAME/` (`seed.yaml`, `files/`, `snapshot.json`). `--dir DIR` keeps them elsewhere, for example in your repository to share a scenario with the team.
- They may contain secret values in plain text (awsemu warns you). `--no-secrets` leaves them out, as `seed export` does.
- `save` checks the result is a valid seed and never leaves a half-written snapshot behind; `--force` replaces one with the same name.
- `restore` warns when the snapshot was saved with another emulator version.
- What a seed can't describe isn't in a snapshot either: messages waiting in queues, Kinesis records, executions, and resources of services without a seed section.

## In tests and CI

```bash
awsemu start --seed tests/seed.yaml --idle-timeout 900
awsemu exec -- pytest tests/integration
awsemu reset --seed tests/seed.yaml          # clean state between suites
awsemu exec -- pytest tests/other-suite
awsemu stop
```

More in [Testing and CI](testing.md).
