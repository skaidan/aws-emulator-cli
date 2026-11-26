import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { CreateBucketCommand, GetObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { CreateQueueCommand, ReceiveMessageCommand, SendMessageCommand, SQSClient } from "@aws-sdk/client-sqs";
import { AwsEmulatorContainer, PORT, parseKeys } from "../index.js";

test("parseKeys reads the credentials file", () => {
  assert.deepEqual(parseKeys("[default]\naws_access_key_id = AK\naws_secret_access_key = SK\n"), ["AK", "SK"]);
  assert.throws(() => parseKeys("[default]\n"));
});

let emulator;
before(async () => {
  emulator = await new AwsEmulatorContainer().start();
});
after(async () => {
  await emulator?.stop();
});

test("endpoint is an IP and the mapped port", () => {
  const url = new URL(emulator.getEndpoint());
  assert.equal(url.protocol, "https:");
  assert.equal(Number(url.port), emulator.getMappedPort(PORT));
  assert.match(emulator.getCaCertificate(), /BEGIN CERTIFICATE/);
});

test("s3", async () => {
  const s3 = new S3Client(emulator.clientConfig());
  await s3.send(new CreateBucketCommand({ Bucket: "tc-node" }));
  await s3.send(new PutObjectCommand({ Bucket: "tc-node", Key: "hello.txt", Body: "hello" }));
  const object = await s3.send(new GetObjectCommand({ Bucket: "tc-node", Key: "hello.txt" }));
  assert.equal(await object.Body.transformToString(), "hello");
});

test("sqs with the queue URL it returns", async () => {
  const sqs = new SQSClient(emulator.clientConfig());
  const { QueueUrl } = await sqs.send(new CreateQueueCommand({ QueueName: "tc-node" }));
  await sqs.send(new SendMessageCommand({ QueueUrl, MessageBody: "job-1" }));
  const received = await sqs.send(new ReceiveMessageCommand({ QueueUrl, WaitTimeSeconds: 5 }));
  assert.equal(received.Messages?.[0]?.Body, "job-1");
});
