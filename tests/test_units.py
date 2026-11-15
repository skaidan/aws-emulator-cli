import json
from decimal import Decimal

import click
import pytest

from awsemu import envvars, logs, runtime, settings
from awsemu.commands import dynamodb as ddb
from awsemu.commands.s3 import split_uri
from awsemu.paths import InstanceFiles


# ---------------------------------------------------------------- env vars


def test_env_has_documented_variables(isolated_home):
    env = envvars.emulator_env(9297)
    base = isolated_home / ".aws" / "emulator" / "9297"
    assert env["AWS_ENDPOINT_URL"] == "https://127.0.0.1:9297"
    assert env["AWS_CA_BUNDLE"] == str(base / "ca.pem")
    assert env["AWS_CONFIG_FILE"] == str(base / "config")
    assert env["AWS_SHARED_CREDENTIALS_FILE"] == str(base / "emulator_credentials")
    assert env["AWS_DISABLE_HOST_PREFIX_INJECTION"] == "true"
    assert env["AWS_EC2_METADATA_DISABLED"] == "true"
    assert env["AWS_REGION"] == env["AWS_DEFAULT_REGION"] == "us-east-1"


def test_env_skips_credentials_when_auth_off(isolated_home):
    files = InstanceFiles(9300)
    files.dir.mkdir(parents=True)
    files.ca.write_text("cert")  # running, but no credentials file -> --auth off
    assert "AWS_SHARED_CREDENTIALS_FILE" not in envvars.emulator_env(9300)


def test_env_sdk_extras():
    env = envvars.emulator_env(9297, ["node", "java", "rust"])
    assert env["NODE_EXTRA_CA_CERTS"].endswith("ca.pem")
    assert "truststore.p12" in env["JAVA_TOOL_OPTIONS"]
    assert env["SSL_CERT_FILE"].endswith("ca.pem")
    with pytest.raises(ValueError):
        envvars.emulator_env(9297, ["cobol"])


@pytest.mark.parametrize("shell,needle", [
    ("bash", "export AWS_REGION=us-east-1"),
    ("fish", "set -gx AWS_REGION 'us-east-1'"),
    ("powershell", "$env:AWS_REGION = 'us-east-1'"),
    ("dotenv", "AWS_REGION=us-east-1"),
])
def test_render_shells(shell, needle):
    out = envvars.render({"AWS_REGION": "us-east-1"}, shell)
    assert needle in out


def test_render_unsets_real_credentials():
    assert envvars.render({}, "bash").startswith("unset AWS_ACCESS_KEY_ID")
    assert "unset" not in envvars.render({}, "bash", unset_real=False)


def test_render_quotes_paths_with_spaces():
    out = envvars.render({"AWS_CA_BUNDLE": "/Users/Ana María/x y/ca.pem"}, "bash", unset_real=False)
    assert out.strip() == "export AWS_CA_BUNDLE='/Users/Ana María/x y/ca.pem'"


def test_child_env_drops_real_credentials():
    env = envvars.child_env(9297, base={"AWS_ACCESS_KEY_ID": "AKIAREAL", "PATH": "/bin"})
    assert "AWS_ACCESS_KEY_ID" not in env
    assert env["PATH"] == "/bin"
    assert env["AWS_ENDPOINT_URL"].startswith("https://127.0.0.1")


# ---------------------------------------------------------------- logs


def test_parse_startup_line():
    line = json.dumps({"timestamp": "2026-11-15T10:11:12.345678Z", "level": "INFO",
                       "message": "emulator server information",
                       "endpoint_url": "https://127.0.0.1:9297", "ca_file": "/x/ca.pem"})
    entry = logs.parse(line)
    assert entry.is_startup
    assert entry.time == "10:11:12.345"
    assert entry.level == "INFO"
    assert entry.extra["endpoint_url"] == "https://127.0.0.1:9297"
    assert logs.find_startup(["telemetry notice", line])["ca_file"] == "/x/ca.pem"


def test_parse_plain_and_broken_lines():
    assert not logs.parse("telemetry is on").is_json
    assert logs.format_plain(logs.parse("{not json")) == "{not json"


def test_format_plain_includes_extra_fields():
    out = logs.format_plain(logs.parse('{"level":"warn","msg":"slow","service":"s3","ms":812}'))
    assert "WARN" in out and "slow" in out and "service=s3" in out and "ms=812" in out


# ---------------------------------------------------------------- settings


def test_settings_creates_file(tmp_path):
    path = tmp_path / "config.toml"
    settings.set_value("telemetry", "enabled", False, path)
    assert settings.telemetry_enabled(path) is False
    assert path.read_text() == "[telemetry]\nenabled = false\n"


def test_settings_preserves_other_content(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("# my settings\n[other]\nx = 1\n\n[telemetry]\nenabled = true # yes\n\n[more]\ny = 2\n")
    settings.set_value("telemetry", "enabled", False, path)
    text = path.read_text()
    assert "# my settings" in text and "[more]\ny = 2" in text
    assert settings.load(path) == {"other": {"x": 1}, "telemetry": {"enabled": False},
                                   "more": {"y": 2}}


def test_settings_adds_key_to_existing_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[telemetry]\n\n[other]\nx = 1\n")
    settings.set_value("telemetry", "enabled", True, path)
    assert settings.load(path)["telemetry"] == {"enabled": True}


def test_settings_honours_emulator_config(tmp_path, monkeypatch):
    target = tmp_path / "custom.toml"
    monkeypatch.setenv("EMULATOR_CONFIG", str(target))
    settings.set_value("telemetry", "enabled", False)
    assert target.exists()


# ---------------------------------------------------------------- runtime commands


def test_native_command_flags():
    opts = runtime.StartOptions(port=9300, auth=False, telemetry=False, idle_timeout=60,
                                extra_args=["--foo"])
    assert runtime.native_command(opts) == [
        "aws-emulator", "-p", "9300", "-a", "off", "-t", "off", "--idle-timeout", "60", "--foo"]


def test_docker_command_linux_matches_docs(isolated_home):
    cmd = runtime.docker_command(runtime.StartOptions(port=9297), system="Linux")
    joined = " ".join(cmd)
    assert "-p 127.0.0.1:9297:9297" in joined  # never expose to the network
    assert "--memory=2g --memory-swap=2g" in joined
    assert f"-e HOME={isolated_home}" in joined
    root = isolated_home / ".aws" / "emulator"
    assert f"-v {root}:{root}" in joined
    assert "--rm" in cmd and "-d" in cmd
    if hasattr(__import__("os"), "getuid"):
        assert "--user" in cmd
    assert cmd[-3:] == ["aws-emulator", "-p", "9297"]


def test_docker_command_windows_mount():
    cmd = runtime.docker_command(runtime.StartOptions(port=9297), system="Windows")
    assert any(a.endswith(":/home/emulator/.aws/emulator") for a in cmd)
    assert "--user" not in cmd


def test_dockerfile_arch():
    assert "aws-emulator-aarch64.rpm" in runtime.dockerfile("aarch64")
    assert runtime.detect_arch("arm64") == "aarch64"
    assert runtime.detect_arch("AMD64") == "x86_64"


def test_resolve_mode_without_anything(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(runtime.RuntimeErrorWithHint):
        runtime.resolve_mode("auto")


# ---------------------------------------------------------------- helpers


def test_split_uri():
    assert split_uri("s3://b/a/b.txt") == ("b", "a/b.txt")
    assert split_uri("b") == ("b", "")
    with pytest.raises(click.BadParameter):
        split_uri("s3://")


def test_dynamodb_roundtrip():
    data = {"id": "u1", "age": 30, "score": Decimal("9.5"), "ok": True, "none": None,
            "tags": ["a", 1], "nested": {"x": {"y": [False]}}}
    item = ddb.to_item(data)
    assert item["age"] == {"N": "30"}
    assert item["nested"]["M"]["x"]["M"]["y"]["L"][0] == {"BOOL": False}
    back = ddb.from_item(item)
    assert back["age"] == 30 and back["score"] == 9.5 and back["nested"] == data["nested"]


def test_dynamodb_sets_and_keys():
    assert ddb.from_attr({"SS": ["b", "a"]}) == ["a", "b"]
    assert ddb.from_attr({"NS": ["2", "1.5"]}) == [1.5, 2]
    assert ddb.parse_key_spec("id") == ("id", "S")
    assert ddb.parse_key_spec("ts:n") == ("ts", "N")
    with pytest.raises(click.BadParameter):
        ddb.parse_key_spec("x:BOOL")


# ---------------------------------------------------------------- error hints


class FakeClientError(Exception):
    def __init__(self, code, message=""):
        super().__init__(f"{code}: {message}")
        self.response = {"Error": {"Code": code, "Message": message}}


@pytest.mark.parametrize("exc,needle", [
    (FakeClientError("AccessDenied", "Sign the request with the emulator credentials"), "awsemu env"),
    (FakeClientError("SignatureDoesNotMatch"), "restart"),
    (FakeClientError("InvalidClientTokenId"), "--no-auth"),
    (FakeClientError("UnknownService"), "aws-emulator/issues"),
    (FakeClientError("RequestTimeTooSkewed"), "clock"),
    (Exception("SSL: CERTIFICATE_VERIFY_FAILED"), "ca.pem"),
])
def test_error_hints(exc, needle):
    from awsemu.clients import hint_for

    assert needle in hint_for(exc)


def test_no_hint_for_ordinary_errors():
    from awsemu.clients import hint_for

    assert hint_for(FakeClientError("NoSuchBucket", "The bucket does not exist")) is None


def test_split_binary():
    assert runtime.split_binary("aws-emulator") == ["aws-emulator"]
    assert runtime.split_binary('"/opt/my emu/aws-emulator" --x') == ["/opt/my emu/aws-emulator", "--x"]


def test_parse_real_tracing_format():
    """The real emulator nests message and fields under "fields" (seen in CI)."""
    line = json.dumps({"timestamp": "2026-11-15T12:57:03.273Z", "level": "INFO",
                       "fields": {"message": "emulator server information",
                                  "endpoint_url": "https://127.0.0.1:49275"},
                       "target": "aws_emulator_router"})
    entry = logs.parse(line)
    assert entry.message == "emulator server information" and entry.is_startup
    assert "message" not in entry.extra and entry.extra["endpoint_url"].endswith(":49275")
    assert logs.find_startup([line])["endpoint_url"] == "https://127.0.0.1:49275"


# ---------------------------------------------------------------- compose


def test_compose_service_matches_docker_recipe(isolated_home):
    import yaml

    from awsemu.commands import compose

    opts = runtime.StartOptions(port=9310, mode="docker", auth=False, telemetry=False, idle_timeout=600)
    svc = compose.service(opts, system="Linux", arch="x86_64")
    assert svc["ports"] == ["127.0.0.1:9310:9310"]
    assert svc["command"] == ["-p", "9310", "-a", "off", "-t", "off", "--idle-timeout", "600"]
    assert svc["mem_limit"] == svc["memswap_limit"] == "2g"
    root = isolated_home / ".aws" / "emulator"
    assert svc["volumes"] == [f"{root}:{root}"] and svc["environment"] == {"HOME": str(isolated_home)}
    assert "aws-emulator-x86_64.rpm" in svc["build"]["dockerfile_inline"]
    text = compose.render("emu", svc, 9310)
    assert yaml.safe_load(text)["services"]["emu"] == svc  # valid YAML, round-trips

    win = compose.service(opts, system="Windows", build=False)
    assert "build" not in win and "user" not in win
    assert win["volumes"][0].endswith(":/home/emulator/.aws/emulator")
