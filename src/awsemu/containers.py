"""A Testcontainers module for AWS Emulator: ``AwsEmulatorContainer``.

For teams that start their test dependencies with Testcontainers rather than
the pytest fixtures of ``awsemu.pytest_plugin``::

    from awsemu.containers import AwsEmulatorContainer

    with AwsEmulatorContainer() as emulator:
        s3 = emulator.client("s3")
        s3.create_bucket(Bucket="photos")

It runs the Docker image that ``awsemu image build`` makes (AWS doesn't publish
one) on a random host port, waits until the emulator is ready and reads its
certificate and keys from the container: every start makes new ones.
Needs ``pip install testcontainers``.
"""

from __future__ import annotations

import configparser
import os
import tempfile

from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from .envvars import AUTH_OFF_KEYS
from .paths import REGION
from .runtime import DEFAULT_IMAGE

PORT = 9297
READY_LOG = "emulator server information"
FILES_IN_CONTAINER = f"/home/emulator/.aws/emulator/{PORT}"


class AwsEmulatorContainer(DockerContainer):
    """AWS Emulator in a container.

    ``image`` defaults to ``$AWSEMU_IMAGE`` or ``aws-emulator`` (``awsemu image
    build``). ``auth=False`` starts it with authentication off. ``telemetry``
    passes ``-t on/off``; unset, the emulator's default applies (and
    ``EMULATOR_TELEMETRY`` from your environment is passed on)."""

    def __init__(
        self,
        image: str | None = None,
        *,
        auth: bool = True,
        telemetry: bool | None = None,
        startup_timeout: float = 90,
        **kwargs,
    ):
        super().__init__(image or os.environ.get("AWSEMU_IMAGE") or DEFAULT_IMAGE, **kwargs)
        self.auth = auth
        self.startup_timeout = startup_timeout
        args = ["-p", str(PORT)]
        if not auth:
            args += ["-a", "off"]
        if telemetry is not None:
            args += ["-t", "on" if telemetry else "off"]
        self.with_exposed_ports(PORT)
        self.with_command(args)
        if os.environ.get("EMULATOR_TELEMETRY"):
            self.with_env("EMULATOR_TELEMETRY", os.environ["EMULATOR_TELEMETRY"])
        self._ca_path: str | None = None
        self._keys: tuple[str, str] | None = None

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> AwsEmulatorContainer:
        super().start()
        wait_for_logs(self, READY_LOG, timeout=self.startup_timeout)
        ca = self._read(f"{FILES_IN_CONTAINER}/ca.pem")
        handle, self._ca_path = tempfile.mkstemp(prefix="aws-emulator-ca-", suffix=".pem")
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(ca)
        self._keys = self._read_keys() if self.auth else AUTH_OFF_KEYS
        return self

    def stop(self, force=True, delete_volume=True) -> None:
        try:
            super().stop(force, delete_volume)
        finally:
            if self._ca_path:
                try:
                    os.unlink(self._ca_path)
                except OSError:
                    pass
                self._ca_path = None

    def _read(self, path: str, timeout: float = 15) -> str:
        """A file the emulator writes at start (it may lag the log line a little)."""
        from .waiting import poll

        def written() -> str | None:
            result = self.exec(["cat", path])
            return result.output.decode("utf-8") if result.exit_code == 0 and result.output else None

        text = poll(written, timeout=timeout)
        if text is None:
            raise RuntimeError(f"the emulator didn't write {path} in the container")
        return text

    def _read_keys(self) -> tuple[str, str]:
        parser = configparser.ConfigParser()
        parser.read_string(self._read(f"{FILES_IN_CONTAINER}/emulator_credentials"))
        section = "default" if parser.has_section("default") else parser.sections()[0]
        return parser.get(section, "aws_access_key_id"), parser.get(section, "aws_secret_access_key")

    # ------------------------------------------------------------------ connection

    @property
    def endpoint_url(self) -> str:
        host = self.get_container_host_ip()
        # 127.0.0.1 rather than localhost, so S3 puts the bucket in the path
        host = "127.0.0.1" if host in ("localhost", "0.0.0.0") else host
        return f"https://{host}:{self.get_exposed_port(PORT)}"

    @property
    def ca_path(self) -> str:
        """The emulator's certificate (PEM) on the host, for ``verify=``/``AWS_CA_BUNDLE``."""
        if not self._ca_path:
            raise RuntimeError("the container isn't started")
        return self._ca_path

    @property
    def access_key_id(self) -> str:
        return self._started_keys()[0]

    @property
    def secret_access_key(self) -> str:
        return self._started_keys()[1]

    region = REGION

    def _started_keys(self) -> tuple[str, str]:
        if not self._keys:
            raise RuntimeError("the container isn't started")
        return self._keys

    def aws_env(self) -> dict[str, str]:
        """The variables that point an SDK, the AWS CLI or Terraform at this container."""
        return {
            "AWS_ENDPOINT_URL": self.endpoint_url,
            "AWS_CA_BUNDLE": self.ca_path,
            "AWS_ACCESS_KEY_ID": self.access_key_id,
            "AWS_SECRET_ACCESS_KEY": self.secret_access_key,
            "AWS_REGION": self.region,
            "AWS_DEFAULT_REGION": self.region,
            "AWS_DISABLE_HOST_PREFIX_INJECTION": "true",
        }

    def client(self, service: str, **kwargs):
        """A boto3 client for this container."""
        import boto3

        from .clients import emulator_config

        # botocore's own timeouts (60 s), as before: a container may be slower than a local process.
        kwargs.setdefault("config", emulator_config(connect_timeout=60, read_timeout=60))
        return boto3.client(
            service,
            endpoint_url=self.endpoint_url,
            verify=self.ca_path,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region,
            **kwargs,
        )
