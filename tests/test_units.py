import json
from decimal import Decimal

import click
import pytest

from awsemu import envvars, logs, runtime, settings
from awsemu.commands import dynamodb as ddb
from awsemu.services import dynamodb as ddb_svc
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


def test_env_with_auth_off_uses_placeholder_keys(isolated_home, monkeypatch):
    files = InstanceFiles(9300)
    files.dir.mkdir(parents=True)
    files.ca.write_text("cert")  # running, but no credentials file -> --auth off
    env = envvars.emulator_env(9300)
    assert "AWS_SHARED_CREDENTIALS_FILE" not in env
    assert (env["AWS_ACCESS_KEY_ID"], env["AWS_SECRET_ACCESS_KEY"]) == envvars.AUTH_OFF_KEYS

    # Real keys in the environment are replaced, not kept
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAREALKEY000000000")
    monkeypatch.setenv("AWS_PROFILE", "prod")
    child = envvars.child_env(9300)
    assert child["AWS_ACCESS_KEY_ID"] == envvars.AUTH_OFF_KEYS[0] and "AWS_PROFILE" not in child
    script = envvars.render(env, "bash")
    assert script.index("unset AWS_ACCESS_KEY_ID") < script.index("export AWS_ACCESS_KEY_ID=EMULATORAUTHOFF00000")
    fish = envvars.render(env, "fish")
    assert fish.index("set -e AWS_ACCESS_KEY_ID") < fish.index("set -gx AWS_ACCESS_KEY_ID 'EMULATORAUTHOFF00000'")
    ps = envvars.render(env, "powershell")
    assert ps.index("Remove-Item") < ps.index("EMULATORAUTHOFF00000")


def test_auth_off_sdk_ignores_your_real_profile(isolated_home, monkeypatch):
    boto3 = pytest.importorskip("boto3")
    files = InstanceFiles(9300)
    files.dir.mkdir(parents=True)
    files.ca.write_text("cert")
    real = isolated_home / ".aws" / "credentials"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text("[default]\naws_access_key_id = AKIAREALKEY000000000\naws_secret_access_key = secret\n")
    for key, value in envvars.child_env(9300).items():
        monkeypatch.setenv(key, value)
    assert boto3.Session().get_credentials().access_key == "EMULATORAUTHOFF00000"


def test_env_sdk_extras():
    env = envvars.emulator_env(9297, ["node", "java", "rust"])
    assert env["NODE_EXTRA_CA_CERTS"].endswith("ca.pem")
    assert "truststore.p12" in env["JAVA_TOOL_OPTIONS"]
    assert env["SSL_CERT_FILE"].endswith("ca.pem")
    with pytest.raises(ValueError):
        envvars.emulator_env(9297, ["cobol"])


@pytest.mark.parametrize(
    "shell,needle",
    [
        ("bash", "export AWS_REGION=us-east-1"),
        ("fish", "set -gx AWS_REGION 'us-east-1'"),
        ("powershell", "$env:AWS_REGION = 'us-east-1'"),
        ("dotenv", "AWS_REGION=us-east-1"),
    ],
)
def test_render_shells(shell, needle):
    out = envvars.render({"AWS_REGION": "us-east-1"}, shell)
    assert needle in out


def test_render_unsets_real_credentials():
    assert envvars.render({}, "bash").startswith("unset AWS_ACCESS_KEY_ID")
    assert "unset" not in envvars.render({}, "bash", unset_real=False)


def test_render_quotes_paths_with_spaces():
    out = envvars.render({"AWS_CA_BUNDLE": "/Users/Zoë Smith/x y/ca.pem"}, "bash", unset_real=False)
    assert out.strip() == "export AWS_CA_BUNDLE='/Users/Zoë Smith/x y/ca.pem'"


def test_child_env_drops_real_credentials():
    env = envvars.child_env(9297, base={"AWS_ACCESS_KEY_ID": "AKIAREAL", "PATH": "/bin"})
    assert "AWS_ACCESS_KEY_ID" not in env
    assert env["PATH"] == "/bin"
    assert env["AWS_ENDPOINT_URL"].startswith("https://127.0.0.1")


# ---------------------------------------------------------------- logs


def test_parse_startup_line():
    line = json.dumps(
        {
            "timestamp": "2026-11-15T10:11:12.345678Z",
            "level": "INFO",
            "message": "emulator server information",
            "endpoint_url": "https://127.0.0.1:9297",
            "ca_file": "/x/ca.pem",
        }
    )
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
    assert settings.load(path) == {"other": {"x": 1}, "telemetry": {"enabled": False}, "more": {"y": 2}}


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
    opts = runtime.StartOptions(port=9300, auth=False, telemetry=False, idle_timeout=60, extra_args=["--foo"])
    assert runtime.native_command(opts) == [
        "aws-emulator",
        "-p",
        "9300",
        "-a",
        "off",
        "-t",
        "off",
        "--idle-timeout",
        "60",
        "--foo",
    ]


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
    assert "LTS/latest/aws-emulator-aarch64.rpm" in runtime.dockerfile("aarch64")
    assert "LTS/aws-emulator-1.0.385-1-x86_64.rpm" in runtime.dockerfile("x86_64", "1.0.385")
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
    data = {
        "id": "u1",
        "age": 30,
        "score": Decimal("9.5"),
        "ok": True,
        "none": None,
        "tags": ["a", 1],
        "nested": {"x": {"y": [False]}},
    }
    item = ddb_svc.to_item(data)
    assert item["age"] == {"N": "30"}
    assert item["nested"]["M"]["x"]["M"]["y"]["L"][0] == {"BOOL": False}
    back = ddb_svc.from_item(item)
    assert back["age"] == 30 and back["score"] == 9.5 and back["nested"] == data["nested"]


def test_dynamodb_sets_and_keys():
    assert ddb_svc.from_attr({"SS": ["b", "a"]}) == ["a", "b"]
    assert ddb_svc.from_attr({"NS": ["2", "1.5"]}) == [1.5, 2]
    assert ddb.parse_key_spec("id") == ("id", "S")
    assert ddb.parse_key_spec("ts:n") == ("ts", "N")
    with pytest.raises(click.BadParameter):
        ddb.parse_key_spec("x:BOOL")


# ---------------------------------------------------------------- error hints


class FakeClientError(Exception):
    def __init__(self, code, message=""):
        super().__init__(f"{code}: {message}")
        self.response = {"Error": {"Code": code, "Message": message}}


@pytest.mark.parametrize(
    "exc,needle",
    [
        (FakeClientError("AccessDenied", "Sign the request with the emulator credentials"), "awsemu env"),
        (FakeClientError("SignatureDoesNotMatch"), "restart"),
        (FakeClientError("InvalidClientTokenId"), "--no-auth"),
        (FakeClientError("UnknownService"), "aws-emulator/issues"),
        (FakeClientError("RequestTimeTooSkewed"), "clock"),
        (Exception("SSL: CERTIFICATE_VERIFY_FAILED"), "ca.pem"),
    ],
)
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
    line = json.dumps(
        {
            "timestamp": "2026-11-15T12:57:03.273Z",
            "level": "INFO",
            "fields": {"message": "emulator server information", "endpoint_url": "https://127.0.0.1:49275"},
            "target": "aws_emulator_router",
        }
    )
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


def test_compose_with_the_proxy_for_app_containers(isolated_home):
    import yaml

    from awsemu.commands import compose

    opts = runtime.StartOptions(port=9310, mode="docker")
    client = compose.client_settings(9310, 9311, auth=True, system="Linux")
    text = compose.render("emu", compose.service(opts, system="Linux", build=False), 9310, client, 9311)
    assert "proxy start -d --host 0.0.0.0" in text and "<<: *aws-emulator-client" in text
    # an app service using the anchor, as the header says
    doc = yaml.safe_load(text + "  app:\n    image: my-app\n    <<: *aws-emulator-client\n")
    app = doc["services"]["app"]
    ca = str(isolated_home / ".aws" / "emulator-cli" / "proxy" / "ca.pem")
    creds = str(isolated_home / ".aws" / "emulator" / "9310" / "emulator_credentials")
    assert app["environment"]["AWS_ENDPOINT_URL"] == "https://host.docker.internal:9311"
    assert app["environment"]["AWS_CA_BUNDLE"] == ca and app["environment"]["AWS_SHARED_CREDENTIALS_FILE"] == creds
    assert f"{ca}:{ca}:ro" in app["volumes"] and not any("ca-key" in v for v in app["volumes"])
    assert app["extra_hosts"] == ["host.docker.internal:host-gateway"]

    off = compose.client_settings(9310, 9311, auth=False, system="Windows")
    assert off["environment"]["AWS_ACCESS_KEY_ID"] == "EMULATORAUTHOFF00000"
    assert off["environment"]["AWS_CA_BUNDLE"] == "/awsemu/proxy-ca.pem"


def test_every_command_and_option_has_help():
    """Help is part of the product: no command or option without it."""
    import click

    from awsemu.cli import cli

    missing = []

    def walk(cmd, path):
        if not (cmd.help or cmd.short_help):
            missing.append(" ".join(path) or "awsemu")
        for p in cmd.params:
            if (
                isinstance(p, click.Option)
                and not p.help
                and not p.hidden
                and "--help" not in p.opts
                and "--version" not in p.opts
            ):
                missing.append(f"{' '.join(path)} {p.opts[-1]}")
        if isinstance(cmd, click.Group):
            ctx = click.Context(cmd)
            for n in cmd.list_commands(ctx):
                walk(cmd.get_command(ctx, n), path + [n])

    walk(cli, [])
    assert missing == []


# --------------------------------------------------------------------------- setup traps


def _answers(mapping):
    return lambda port: mapping.get(port)


def test_trap_endpoint():
    from awsemu import traps

    assert traps.endpoint({}, _answers({})) == []
    assert traps.endpoint({"AWS_ENDPOINT_URL": "https://s3.amazonaws.com"}, _answers({})) == []
    found = traps.endpoint({"AWS_ENDPOINT_URL": "https://localhost:9297"}, _answers({9297: "emulator"}))
    assert [f.detail for f in found] == ["AWS_ENDPOINT_URL uses 'localhost'"]
    stale = traps.endpoint({"AWS_ENDPOINT_URL": "https://127.0.0.1:9400"}, _answers({}))
    assert "nothing answers there" in stale[0].detail and "awsemu env" in stale[0].fix
    http = traps.endpoint({"AWS_ENDPOINT_URL": "http://127.0.0.1:9297"}, _answers({9297: "emulator"}))
    assert "only speaks HTTPS" in http[0].detail
    assert traps.endpoint({"AWS_ENDPOINT_URL": "http://127.0.0.1:9298"}, _answers({9298: "proxy"})) == []


def test_trap_ca_bundle(isolated_home, tmp_path):
    from awsemu import traps

    for port in (9297, 9400):
        files = InstanceFiles(port)
        files.dir.mkdir(parents=True)
        files.ca.write_text("cert")
    up = _answers({9297: "emulator"})
    ok = {"AWS_ENDPOINT_URL": "https://127.0.0.1:9297", "AWS_CA_BUNDLE": str(InstanceFiles(9297).ca)}
    assert traps.ca_bundle(ok, up) == []
    other = {**ok, "AWS_CA_BUNDLE": str(InstanceFiles(9400).ca)}
    assert "certificate of port 9400" in traps.ca_bundle(other, up)[0].detail
    missing = {**ok, "AWS_CA_BUNDLE": str(tmp_path / "gone.pem")}
    assert "doesn't exist" in traps.ca_bundle(missing, up)[0].detail
    corporate = tmp_path / "corp.pem"
    corporate.write_text("x")
    assert "isn't the emulator's certificate" in traps.ca_bundle({**ok, "AWS_CA_BUNDLE": str(corporate)}, up)[0].detail
    assert traps.ca_bundle({"AWS_CA_BUNDLE": str(corporate)}, up) == []  # not using the emulator here


def test_trap_proxies_and_no_proxy(isolated_home, monkeypatch):
    from awsemu import traps

    assert traps.proxies({}) == [] and traps.no_proxy_value({}) is None
    env = {"HTTPS_PROXY": "http://corp:3128", "NO_PROXY": ".internal"}
    assert "NO_PROXY doesn't include 127.0.0.1" in traps.proxies(env)[0].detail
    assert traps.no_proxy_value(env) == ".internal,127.0.0.1,localhost"
    assert traps.proxies({"https_proxy": "x", "no_proxy": "127.0.0.1"}) == []
    assert traps.proxies({"HTTP_PROXY": "x", "NO_PROXY": "*"}) == []

    monkeypatch.delenv("no_proxy", raising=False)  # first: on Windows it's the same variable as NO_PROXY
    monkeypatch.setenv("HTTPS_PROXY", "http://corp:3128")
    monkeypatch.setenv("NO_PROXY", ".internal")
    variables = envvars.emulator_env(9297)
    assert variables["NO_PROXY"] == ".internal,127.0.0.1,localhost"
    assert variables.get("no_proxy", variables["NO_PROXY"]) == variables["NO_PROXY"]


def test_env_unset_keeps_your_no_proxy(runner, monkeypatch):
    from awsemu.cli import cli

    monkeypatch.setenv("HTTPS_PROXY", "http://corp:3128")
    out = runner.invoke(cli, ["env", "--unset", "--shell", "bash"]).output
    assert "NO_PROXY" not in out and "AWS_ENDPOINT_URL" in out


def test_trap_hidden_config(isolated_home, tmp_path):
    from awsemu import traps

    home = tmp_path / "me"
    (home / ".aws").mkdir(parents=True)
    assert traps.hidden_config({}, home) == []
    (home / ".aws" / "config").write_text(
        "[default]\nregion = eu-west-1\nretry_mode = standard\nmax_attempts = 7\n"
        "s3 =\n  addressing_style = virtual\n[profile prod]\nretry_mode = adaptive\n"
    )
    (finding,) = traps.hidden_config({}, home)
    assert "sets retry_mode, max_attempts, s3" in finding.detail
    assert "export AWS_RETRY_MODE=standard AWS_MAX_ATTEMPTS=7" in finding.fix
    assert "s3 have no environment variable" in finding.fix
    emulator_cfg = str(InstanceFiles(9297).config)
    assert traps.hidden_config({"AWS_CONFIG_FILE": emulator_cfg}, home)[0].detail.startswith(str(home))


def test_doctor_reports_traps(runner, monkeypatch):
    from awsemu.cli import cli

    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://localhost:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://corp:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    data = json.loads(runner.invoke(cli, ["doctor", "--json"]).output)
    checks = {(c["check"], c["detail"]) for c in data["checks"]}
    assert ("endpoint", "AWS_ENDPOINT_URL uses 'localhost'") in checks
    assert any(c == "http proxy" for c, _ in checks)
    assert any("nothing answers there" in d for _, d in checks)


def test_java_tool_options_keeps_yours():
    out = envvars.java_tool_options(
        "-Xmx512m -Dhttps.proxyHost=corp -Djavax.net.ssl.trustStore=/etc/cacerts -Djavax.net.ssl.trustStoreType=JKS",
        "/home/me/.aws/emulator/9297/truststore.p12",
    )
    assert out == (
        "-Xmx512m -Dhttps.proxyHost=corp -Djavax.net.ssl.trustStore=/home/me/.aws/emulator/9297/truststore.p12 "
        "-Djavax.net.ssl.trustStoreType=PKCS12"
    )
    assert (
        envvars.java_tool_options("", "/t.p12")
        == "-Djavax.net.ssl.trustStore=/t.p12 -Djavax.net.ssl.trustStoreType=PKCS12"
    )


def test_java_tool_options_quotes_only_spaces():
    out = envvars.java_tool_options('-Dhttp.nonProxyHosts=localhost|127.* "-Dname=a b"', "/t.p12")
    assert out.startswith('-Dhttp.nonProxyHosts=localhost|127.* "-Dname=a b" -Djavax.net.ssl.trustStore=/t.p12')


def test_java_truststore_trusts_the_emulator_and_what_java_trusted(isolated_home, monkeypatch):
    import shutil
    import subprocess

    from awsemu import javatrust
    from tests.fake_emulator import make_cert

    tool = javatrust.keytool()
    if not tool or not javatrust.jdk_cacerts(tool):
        pytest.skip("needs a JDK (keytool and cacerts)")
    files = InstanceFiles(9297)
    files.dir.mkdir(parents=True)
    make_cert(files.ca, files.dir / "key.pem")
    monkeypatch.delenv("JAVA_TOOL_OPTIONS", raising=False)

    store, password = javatrust.combined(9297)
    assert password == javatrust.PASSWORD and store.name == "truststore-9297.p12"
    listing = subprocess.run(
        [tool, "-list", "-keystore", str(store), "-storepass", password], capture_output=True, text=True
    ).stdout
    assert "awsemu-emulator-9297" in listing
    assert int(listing.split("contains ")[1].split()[0]) > 10  # the JDK's certificates are still there
    built = store.stat().st_mtime_ns
    assert javatrust.combined(9297)[0].stat().st_mtime_ns == built  # cached until the CA changes

    options = envvars.emulator_env(9297, ["java"])["JAVA_TOOL_OPTIONS"]
    assert f"-Djavax.net.ssl.trustStore={store}" in options
    assert f"-Djavax.net.ssl.trustStorePassword={password}" in options

    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.delenv("JAVA_HOME", raising=False)
    assert javatrust.combined(9297) == (files.truststore, None)  # no JDK: the emulator's own
