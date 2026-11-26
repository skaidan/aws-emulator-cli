// AWS SDK for Java v2 against AWS Emulator.
//
//   awsemu exec --sdk java -- mvn -q compile exec:java
//
// Nothing here knows about the emulator: the endpoint, region and credentials come
// from the environment awsemu sets, and --sdk java points the JVM at the emulator's
// truststore (JAVA_TOOL_OPTIONS). The same code runs against AWS.

import java.util.Map;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.dynamodb.model.AttributeDefinition;
import software.amazon.awssdk.services.dynamodb.model.AttributeValue;
import software.amazon.awssdk.services.dynamodb.model.BillingMode;
import software.amazon.awssdk.services.dynamodb.model.KeySchemaElement;
import software.amazon.awssdk.services.dynamodb.model.KeyType;
import software.amazon.awssdk.services.dynamodb.model.ScalarAttributeType;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.sqs.SqsClient;

public class Smoke {
    public static void main(String[] args) {
        try (S3Client s3 = S3Client.create()) {
            s3.createBucket(b -> b.bucket("java-example"));
            s3.putObject(b -> b.bucket("java-example").key("hello.txt"), RequestBody.fromString("hello from java"));
            check("s3", s3.getObjectAsBytes(b -> b.bucket("java-example").key("hello.txt")).asUtf8String(),
                  "hello from java");
        }
        try (SqsClient sqs = SqsClient.create()) {
            String url = sqs.createQueue(b -> b.queueName("java-example")).queueUrl();
            sqs.sendMessage(b -> b.queueUrl(url).messageBody("job-1"));
            var messages = sqs.receiveMessage(b -> b.queueUrl(url).waitTimeSeconds(5)).messages();
            check("sqs", messages.isEmpty() ? null : messages.get(0).body(), "job-1");
        }
        try (DynamoDbClient ddb = DynamoDbClient.create()) {
            ddb.createTable(b -> b.tableName("java-example").billingMode(BillingMode.PAY_PER_REQUEST)
                    .attributeDefinitions(AttributeDefinition.builder().attributeName("id")
                            .attributeType(ScalarAttributeType.S).build())
                    .keySchema(KeySchemaElement.builder().attributeName("id").keyType(KeyType.HASH).build()));
            ddb.waiter().waitUntilTableExists(b -> b.tableName("java-example"));
            ddb.putItem(b -> b.tableName("java-example").item(Map.of(
                    "id", AttributeValue.fromS("1"), "name", AttributeValue.fromS("Ana"))));
            var item = ddb.getItem(b -> b.tableName("java-example").key(Map.of("id", AttributeValue.fromS("1")))).item();
            check("dynamodb", item.containsKey("name") ? item.get("name").s() : null, "Ana");
        }
        System.out.println("java: all checks passed");
    }

    static void check(String what, String got, String want) {
        if (!want.equals(got)) {
            System.err.printf("%s: expected %s, got %s%n", what, want, got);
            System.exit(1);
        }
        System.out.println("✓ " + what);
    }
}
