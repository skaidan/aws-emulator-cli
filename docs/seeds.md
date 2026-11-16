# Seeds: reproducible starting data

The emulator keeps everything in memory: stopping or restarting it loses it all. A **seed** is a YAML file describing what you want inside (buckets with objects, queues, tables with items, topics with subscriptions, secrets and parameters) so you can recreate it with one command.

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
```

Every section is optional. Paths (`from`, `items_from`) are relative to the seed file.

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

## Validation

`awsemu seed validate`, `seed apply`, `start --seed` and `reset --seed` check the whole file **before** touching the emulator. Errors show the line and the field:

```
✗ seed.yaml:4  queues[0].visibilty_timeout: unknown field (did you mean 'visibility_timeout'?)
✗ seed.yaml:5  queues[1].name: duplicate name 'jobs' (also at queues[0])
✗ seed.yaml:9  tables[0].items[0].created: must be a number (the key type is N)
✗ seed.yaml:14  parameters[0].name: parameter names can't start with 'aws' or 'ssm' (AWS rule)
```

Among other things it checks: unknown fields (with a suggestion), types, duplicate names, that items have the table's key attributes with the right type, that the `from` and `items_from` files exist, that FIFO queues end in `.fifo`, that a queue isn't its own DLQ, and AWS's rule on parameter names.

If a `dlq` or an `sqs` subscription points to a queue that isn't in the seed, that's a warning, not an error: it may already exist in the emulator.

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

`apply` **never deletes** anything. To start from scratch, use `awsemu reset --seed seed.yaml`.

If a resource fails, `apply` carries on with the rest, marks it as `failed` with the reason and exits with code 1.

The order is: buckets, queues, tables, topics, secrets and parameters (queues before topics, so they can be subscribed). Lambda subscriptions need the function to exist: deploy it first with `awsemu lambda deploy`.

## Export

```bash
awsemu seed export                          # to standard output
awsemu seed export -o seed.yaml
awsemu seed export -o seed.yaml --objects-dir seed-objects   # also saves binary and large objects
awsemu seed export --no-secrets             # without secrets or SecureString parameters
awsemu seed export -s queues -s tables      # only some sections
```

Handy for building a scenario by hand (or with your application) and saving it for your tests.

- S3 text objects up to 64 KiB are stored inside the seed (`content`). Binary or larger ones are saved in `--objects-dir` and referenced with `from`; without that option they're skipped with a warning.
- Secrets and `SecureString` parameters are exported **in plain text**, and `awsemu` warns you when writing the file. Use `--no-secrets` if the seed goes into a repository.
- Only SQS and Lambda subscriptions are exported.
- Lambda functions, EventBridge rules, Kinesis streams and Step Functions state machines aren't part of the format (yet).

The exported file can be applied as-is; CI checks that exporting, restarting and applying leaves the emulator as it was.

## In tests and CI

```bash
awsemu start --seed tests/seed.yaml --idle-timeout 900
awsemu exec -- pytest tests/integration
awsemu reset --seed tests/seed.yaml          # clean state between suites
awsemu exec -- pytest tests/other-suite
awsemu stop
```

More in [Testing and CI](testing.md).
