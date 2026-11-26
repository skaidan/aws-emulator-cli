// AWS SDK for JavaScript v3 against AWS Emulator.
//
//   npm install
//   awsemu exec --sdk node -- node smoke.mjs
//
// Nothing here knows about the emulator: the endpoint, region and credentials come
// from the environment awsemu sets, and --sdk node makes Node trust its certificate
// (NODE_EXTRA_CA_CERTS). The same code runs against AWS.
import { CreateBucketCommand, GetObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { CreateQueueCommand, ReceiveMessageCommand, SendMessageCommand, SQSClient } from "@aws-sdk/client-sqs";
import {
  CreateTableCommand, DynamoDBClient, GetItemCommand, PutItemCommand, waitUntilTableExists,
} from "@aws-sdk/client-dynamodb";

const s3 = new S3Client({});
await s3.send(new CreateBucketCommand({ Bucket: "node-example" }));
await s3.send(new PutObjectCommand({ Bucket: "node-example", Key: "hello.txt", Body: "hello from node" }));
const object = await s3.send(new GetObjectCommand({ Bucket: "node-example", Key: "hello.txt" }));
check("s3", await object.Body.transformToString(), "hello from node");

const sqs = new SQSClient({});
const { QueueUrl } = await sqs.send(new CreateQueueCommand({ QueueName: "node-example" }));
await sqs.send(new SendMessageCommand({ QueueUrl, MessageBody: "job-1" }));
const received = await sqs.send(new ReceiveMessageCommand({ QueueUrl, WaitTimeSeconds: 5 }));
check("sqs", received.Messages?.[0]?.Body, "job-1");

const ddb = new DynamoDBClient({});
await ddb.send(new CreateTableCommand({
  TableName: "node-example", BillingMode: "PAY_PER_REQUEST",
  AttributeDefinitions: [{ AttributeName: "id", AttributeType: "S" }],
  KeySchema: [{ AttributeName: "id", KeyType: "HASH" }],
}));
await waitUntilTableExists({ client: ddb, maxWaitTime: 60 }, { TableName: "node-example" });
await ddb.send(new PutItemCommand({ TableName: "node-example", Item: { id: { S: "1" }, name: { S: "Ana" } } }));
const item = await ddb.send(new GetItemCommand({ TableName: "node-example", Key: { id: { S: "1" } } }));
check("dynamodb", item.Item?.name?.S, "Ana");

console.log("node: all checks passed");

function check(what, got, want) {
  if (got !== want) {
    console.error(`${what}: expected ${JSON.stringify(want)}, got ${JSON.stringify(got)}`);
    process.exit(1);
  }
  console.log(`✓ ${what}`);
}
