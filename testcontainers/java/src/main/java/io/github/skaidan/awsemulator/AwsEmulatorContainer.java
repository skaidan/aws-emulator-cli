package io.github.skaidan.awsemulator;

import com.github.dockerjava.api.command.InspectContainerResponse;
import java.io.ByteArrayInputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.TrustManagerFactory;
import org.testcontainers.containers.Container.ExecResult;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.wait.strategy.Wait;
import org.testcontainers.utility.DockerImageName;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.AwsCredentialsProvider;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.http.TlsTrustManagersProvider;
import software.amazon.awssdk.regions.Region;

/**
 * AWS Emulator in a container.
 *
 * <pre>{@code
 * try (AwsEmulatorContainer emulator = new AwsEmulatorContainer()) {
 *     emulator.start();
 *     S3Client s3 = S3Client.builder()
 *         .endpointOverride(emulator.getEndpoint())
 *         .region(emulator.getRegion())
 *         .credentialsProvider(emulator.getCredentialsProvider())
 *         .httpClient(ApacheHttpClient.builder()
 *             .tlsTrustManagersProvider(emulator.getTrustManagersProvider()).build())
 *         .build();
 * }
 * }</pre>
 *
 * <p>It runs the image that {@code awsemu image build} makes (AWS doesn't publish one), by default
 * {@code $AWSEMU_IMAGE} or {@code aws-emulator}, on a random host port. Once the emulator is ready it
 * reads its certificate and keys from the container: every start makes new ones. The trust managers
 * trust only the emulator, and only the clients you give them to: the rest of the JVM is unchanged.
 */
public class AwsEmulatorContainer extends GenericContainer<AwsEmulatorContainer> {
    public static final int PORT = 9297;
    public static final String DEFAULT_IMAGE = "aws-emulator";
    /** The keys the emulator accepts when it runs with authentication off. */
    static final String[] AUTH_OFF_KEYS = {"EMULATORAUTHOFF00000", "0".repeat(40)};
    private static final String FILES = "/home/emulator/.aws/emulator/" + PORT;

    private final boolean auth;
    private String caPem;
    private String accessKeyId;
    private String secretAccessKey;

    public AwsEmulatorContainer() {
        this(defaultImage());
    }

    public AwsEmulatorContainer(String image) {
        this(DockerImageName.parse(image), true);
    }

    /** @param auth false starts the emulator with authentication off (any request is accepted). */
    public AwsEmulatorContainer(DockerImageName image, boolean auth) {
        super(image);
        this.auth = auth;
        List<String> command = new ArrayList<>(List.of("-p", String.valueOf(PORT)));
        if (!auth) {
            command.addAll(List.of("-a", "off"));
        }
        withCommand(command.toArray(new String[0]));
        withExposedPorts(PORT);
        String telemetry = System.getenv("EMULATOR_TELEMETRY");
        if (telemetry != null && !telemetry.isEmpty()) {
            withEnv("EMULATOR_TELEMETRY", telemetry);
        }
        waitingFor(Wait.forLogMessage(".*emulator server information.*\\n", 1)
                .withStartupTimeout(Duration.ofSeconds(90)));
    }

    private static String defaultImage() {
        String image = System.getenv("AWSEMU_IMAGE");
        return image == null || image.isEmpty() ? DEFAULT_IMAGE : image;
    }

    @Override
    protected void containerIsStarted(InspectContainerResponse info) {
        caPem = read(FILES + "/ca.pem");
        if (!auth) {
            accessKeyId = AUTH_OFF_KEYS[0];
            secretAccessKey = AUTH_OFF_KEYS[1];
            return;
        }
        for (String line : read(FILES + "/emulator_credentials").split("\\R")) {
            String[] kv = line.split("=", 2);
            if (kv.length != 2) {
                continue;
            }
            String key = kv[0].trim();
            if (key.equals("aws_access_key_id") && accessKeyId == null) {
                accessKeyId = kv[1].trim();
            } else if (key.equals("aws_secret_access_key") && secretAccessKey == null) {
                secretAccessKey = kv[1].trim();
            }
        }
        if (accessKeyId == null || secretAccessKey == null) {
            throw new IllegalStateException("no keys in the emulator's credentials file");
        }
    }

    /** A file the emulator writes at start (it may lag the log line a little). */
    private String read(String path) {
        long deadline = System.nanoTime() + Duration.ofSeconds(15).toNanos();
        while (true) {
            try {
                ExecResult result = execInContainer("cat", path);
                if (result.getExitCode() == 0 && !result.getStdout().isEmpty()) {
                    return result.getStdout();
                }
                if (System.nanoTime() > deadline) {
                    throw new IllegalStateException("the emulator didn't write " + path + ": " + result.getStderr());
                }
                Thread.sleep(200);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(e);
            } catch (java.io.IOException e) {
                throw new IllegalStateException(e);
            }
        }
    }

    /** {@code https://127.0.0.1:<mapped port>}: an IP address, so S3 puts the bucket in the path. */
    public URI getEndpoint() {
        String host = getHost();
        if (host.equals("localhost") || host.equals("0.0.0.0")) {
            host = "127.0.0.1";
        }
        return URI.create("https://" + host + ":" + getMappedPort(PORT));
    }

    public Region getRegion() {
        return Region.US_EAST_1;
    }

    public String getAccessKeyId() {
        started();
        return accessKeyId;
    }

    public String getSecretAccessKey() {
        started();
        return secretAccessKey;
    }

    public AwsCredentialsProvider getCredentialsProvider() {
        return StaticCredentialsProvider.create(AwsBasicCredentials.create(getAccessKeyId(), getSecretAccessKey()));
    }

    /** The emulator's certificate, PEM. */
    public String getCaCertificatePem() {
        started();
        return caPem;
    }

    /** Trust managers that trust the emulator's certificate. */
    public TrustManager[] getTrustManagers() {
        try {
            Certificate ca = CertificateFactory.getInstance("X.509")
                    .generateCertificate(new ByteArrayInputStream(getCaCertificatePem().getBytes(StandardCharsets.US_ASCII)));
            KeyStore store = KeyStore.getInstance(KeyStore.getDefaultType());
            store.load(null, null);
            store.setCertificateEntry("aws-emulator", ca);
            TrustManagerFactory factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
            factory.init(store);
            return factory.getTrustManagers();
        } catch (Exception e) {
            throw new IllegalStateException("couldn't load the emulator's certificate", e);
        }
    }

    /** For {@code ApacheHttpClient.builder().tlsTrustManagersProvider(...)} (or the URL connection client). */
    public TlsTrustManagersProvider getTrustManagersProvider() {
        TrustManager[] managers = getTrustManagers();
        return () -> managers;
    }

    /** An SSL context that trusts the emulator, for other HTTP clients. */
    public SSLContext getSslContext() {
        try {
            SSLContext context = SSLContext.getInstance("TLS");
            context.init(null, getTrustManagers(), null);
            return context;
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    /**
     * The variables that point a process (the AWS CLI, Terraform, another SDK) at this container. The
     * certificate is in {@code AWS_CA_BUNDLE} only once written to a file: see {@link #getCaCertificatePem()}.
     */
    public Map<String, String> getAwsEnv() {
        Map<String, String> env = new LinkedHashMap<>();
        env.put("AWS_ENDPOINT_URL", getEndpoint().toString());
        env.put("AWS_ACCESS_KEY_ID", getAccessKeyId());
        env.put("AWS_SECRET_ACCESS_KEY", getSecretAccessKey());
        env.put("AWS_REGION", getRegion().id());
        env.put("AWS_DEFAULT_REGION", getRegion().id());
        env.put("AWS_DISABLE_HOST_PREFIX_INJECTION", "true");
        return env;
    }

    private void started() {
        if (caPem == null) {
            throw new IllegalStateException("the container isn't started");
        }
    }
}
