package io.github.skaidan.awsemulator;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URI;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.http.SdkHttpClient;
import software.amazon.awssdk.http.apache.ApacheHttpClient;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.sqs.SqsClient;

class AwsEmulatorContainerTest {
    static AwsEmulatorContainer emulator = new AwsEmulatorContainer();
    static SdkHttpClient http;

    @BeforeAll
    static void start() {
        emulator.start();
        http = ApacheHttpClient.builder().tlsTrustManagersProvider(emulator.getTrustManagersProvider()).build();
    }

    @AfterAll
    static void stop() {
        http.close();
        emulator.stop();
    }

    @Test
    void endpointIsAnIpAndAMappedPort() {
        URI endpoint = emulator.getEndpoint();
        assertEquals("https", endpoint.getScheme());
        assertEquals((int) emulator.getMappedPort(AwsEmulatorContainer.PORT), endpoint.getPort());
        assertTrue(emulator.getCaCertificatePem().contains("BEGIN CERTIFICATE"));
        assertEquals(endpoint.toString(), emulator.getAwsEnv().get("AWS_ENDPOINT_URL"));
    }

    @Test
    void s3() {
        try (S3Client s3 = S3Client.builder().endpointOverride(emulator.getEndpoint()).region(emulator.getRegion())
                .credentialsProvider(emulator.getCredentialsProvider()).httpClient(http).build()) {
            s3.createBucket(b -> b.bucket("tc-java"));
            s3.putObject(b -> b.bucket("tc-java").key("hello.txt"), RequestBody.fromString("hello"));
            assertEquals("hello", s3.getObjectAsBytes(b -> b.bucket("tc-java").key("hello.txt")).asUtf8String());
        }
    }

    @Test
    void sqsWithTheQueueUrlItReturns() {
        try (SqsClient sqs = SqsClient.builder().endpointOverride(emulator.getEndpoint()).region(emulator.getRegion())
                .credentialsProvider(emulator.getCredentialsProvider()).httpClient(http).build()) {
            String url = sqs.createQueue(b -> b.queueName("tc-java")).queueUrl();
            sqs.sendMessage(b -> b.queueUrl(url).messageBody("job-1"));
            assertEquals("job-1", sqs.receiveMessage(b -> b.queueUrl(url).waitTimeSeconds(5)).messages().get(0).body());
        }
    }
}
