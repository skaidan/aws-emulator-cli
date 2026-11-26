// AWS CDK against AWS Emulator.
//
//   npm install
//   awsemu exec --sdk node -- npx cdk deploy --require-approval never
//
// Two things differ from a usual CDK app, both for the same reason: the emulator
// starts empty, without the bootstrap stack ('cdk bootstrap') CDK normally relies on.
//   - BootstraplessSynthesizer: no bootstrap stack needed. It can't publish assets
//     (Lambda code, Docker images), so this stack has none.
//   - versionReporting false (cdk.json): no AWS::CDK::Metadata resource.
// Against AWS, use the default synthesizer as usual.
const cdk = require("aws-cdk-lib");
const { aws_dynamodb: dynamodb, aws_s3: s3, aws_sqs: sqs, aws_ssm: ssm } = cdk;

const app = new cdk.App();
const stack = new cdk.Stack(app, "AwsemuCdkExample", { synthesizer: new cdk.BootstraplessSynthesizer() });

const dlq = new sqs.Queue(stack, "JobsDlq", { queueName: "cdk-example-jobs-dlq" });
const jobs = new sqs.Queue(stack, "Jobs", {
  queueName: "cdk-example-jobs",
  deadLetterQueue: { queue: dlq, maxReceiveCount: 3 },
});
new dynamodb.Table(stack, "Orders", {
  tableName: "cdk-example-orders",
  partitionKey: { name: "id", type: dynamodb.AttributeType.STRING },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  removalPolicy: cdk.RemovalPolicy.DESTROY,
});
new s3.Bucket(stack, "Uploads", { bucketName: "cdk-example-uploads", removalPolicy: cdk.RemovalPolicy.DESTROY });
new ssm.StringParameter(stack, "QueueUrl", { parameterName: "/cdk-example/queue-url", stringValue: jobs.queueUrl });
new cdk.CfnOutput(stack, "QueueUrlOutput", { value: jobs.queueUrl });
