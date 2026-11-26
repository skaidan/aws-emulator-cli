// A Testcontainers module for AWS Emulator.
//
//   const emulator = await new AwsEmulatorContainer().start();
//   const s3 = new S3Client(emulator.clientConfig());
//   ...
//   await emulator.stop();
//
// It runs the image that `awsemu image build` makes (AWS doesn't publish one), by default
// $AWSEMU_IMAGE or `aws-emulator`, on a random host port. Once the emulator is ready it
// reads its certificate and keys from the container: every start makes new ones.
import https from "node:https";
import { NodeHttpHandler } from "@smithy/node-http-handler";
import { AbstractStartedContainer, GenericContainer, Wait } from "testcontainers";

export const PORT = 9297;
export const DEFAULT_IMAGE = "aws-emulator";
export const REGION = "us-east-1";
// The keys the emulator accepts when it runs with authentication off.
export const AUTH_OFF_KEYS = ["EMULATORAUTHOFF00000", "0".repeat(40)];
const FILES = `/home/emulator/.aws/emulator/${PORT}`;

export class AwsEmulatorContainer extends GenericContainer {
  /**
   * @param {string} [image] defaults to $AWSEMU_IMAGE or "aws-emulator"
   * @param {{auth?: boolean}} [options] auth: false starts it with authentication off
   */
  constructor(image = process.env.AWSEMU_IMAGE || DEFAULT_IMAGE, { auth = true } = {}) {
    super(image);
    this.auth = auth;
    this.withExposedPorts(PORT)
      .withCommand(["-p", String(PORT), ...(auth ? [] : ["-a", "off"])])
      .withWaitStrategy(Wait.forLogMessage("emulator server information"))
      .withStartupTimeout(90_000);
    if (process.env.EMULATOR_TELEMETRY) {
      this.withEnvironment({ EMULATOR_TELEMETRY: process.env.EMULATOR_TELEMETRY });
    }
  }

  /** @returns {Promise<StartedAwsEmulatorContainer>} */
  async start() {
    const started = await super.start();
    const ca = await readFile(started, `${FILES}/ca.pem`);
    const keys = this.auth ? parseKeys(await readFile(started, `${FILES}/emulator_credentials`)) : AUTH_OFF_KEYS;
    return new StartedAwsEmulatorContainer(started, ca, keys);
  }
}

export class StartedAwsEmulatorContainer extends AbstractStartedContainer {
  constructor(started, ca, [accessKeyId, secretAccessKey]) {
    super(started);
    this.ca = ca;
    this.accessKeyId = accessKeyId;
    this.secretAccessKey = secretAccessKey;
    this.region = REGION;
  }

  /** https://127.0.0.1:<mapped port>: an IP address, so S3 puts the bucket in the path. */
  getEndpoint() {
    let host = this.getHost();
    if (host === "localhost" || host === "0.0.0.0") host = "127.0.0.1";
    return `https://${host}:${this.getMappedPort(PORT)}`;
  }

  getCredentials() {
    return { accessKeyId: this.accessKeyId, secretAccessKey: this.secretAccessKey };
  }

  /** The emulator's certificate, PEM. */
  getCaCertificate() {
    return this.ca;
  }

  /**
   * The configuration for any AWS SDK v3 client: endpoint, region, credentials and an HTTPS
   * agent that trusts the emulator (only in these clients; the rest of the process is unchanged).
   */
  clientConfig() {
    return {
      endpoint: this.getEndpoint(),
      region: this.region,
      credentials: this.getCredentials(),
      requestHandler: new NodeHttpHandler({ httpsAgent: new https.Agent({ ca: this.ca, keepAlive: true }) }),
    };
  }

  /** The variables that point a child process at this container (write the CA to a file for AWS_CA_BUNDLE). */
  getEnv() {
    return {
      AWS_ENDPOINT_URL: this.getEndpoint(),
      AWS_ACCESS_KEY_ID: this.accessKeyId,
      AWS_SECRET_ACCESS_KEY: this.secretAccessKey,
      AWS_REGION: this.region,
      AWS_DEFAULT_REGION: this.region,
      AWS_DISABLE_HOST_PREFIX_INJECTION: "true",
    };
  }
}

// A file the emulator writes at start (it may lag the log line a little).
async function readFile(started, path, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const result = await started.exec(["cat", path]);
    const text = result.stdout ?? result.output;
    if (result.exitCode === 0 && text) return text;
    if (Date.now() > deadline) throw new Error(`the emulator didn't write ${path} in the container`);
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
}

export function parseKeys(ini) {
  const value = (name) => ini.match(new RegExp(`^\\s*${name}\\s*=\\s*(\\S+)`, "m"))?.[1];
  const keys = [value("aws_access_key_id"), value("aws_secret_access_key")];
  if (!keys[0] || !keys[1]) throw new Error("no keys in the emulator's credentials file");
  return keys;
}
