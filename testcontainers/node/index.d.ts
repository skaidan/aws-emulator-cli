import { AbstractStartedContainer, GenericContainer } from "testcontainers";
import type { NodeHttpHandler } from "@smithy/node-http-handler";

export declare const PORT: 9297;
export declare const DEFAULT_IMAGE: string;
export declare const REGION: string;
export declare const AUTH_OFF_KEYS: [string, string];

export declare class AwsEmulatorContainer extends GenericContainer {
  constructor(image?: string, options?: { auth?: boolean });
  start(): Promise<StartedAwsEmulatorContainer>;
}

export declare class StartedAwsEmulatorContainer extends AbstractStartedContainer {
  readonly region: string;
  getEndpoint(): string;
  getCredentials(): { accessKeyId: string; secretAccessKey: string };
  getCaCertificate(): string;
  clientConfig(): {
    endpoint: string;
    region: string;
    credentials: { accessKeyId: string; secretAccessKey: string };
    requestHandler: NodeHttpHandler;
  };
  getEnv(): Record<string, string>;
}

export declare function parseKeys(ini: string): [string, string];
