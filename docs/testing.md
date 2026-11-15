# Tests y CI

El emulador es ideal para tests de integración: no hace falta cuenta de AWS, arranca en un momento y cada reinicio empieza vacío. `awsemu` añade lo necesario para usarlo desde scripts.

## Patrón básico

```bash
awsemu start --idle-timeout 900      # se para solo si alguien olvida pararlo
awsemu exec -- pytest tests/integration
code=$?
awsemu stop
exit $code
```

`awsemu exec` ejecuta el comando con las variables que apuntan al emulador y **sin** tus credenciales reales, así que un test mal configurado no puede llegar a AWS por accidente.

## Estado limpio entre suites

El emulador guarda todo en memoria y no tiene una ruta para vaciarlo. Para empezar de cero, reinícialo; con un [seed](seeds.md), vuelve además con tus datos de partida:

```bash
awsemu reset
awsemu reset --seed tests/seed.yaml
```

Para montar ese seed, crea el escenario a mano o con tu aplicación y expórtalo: `awsemu seed export -o tests/seed.yaml --no-secrets`.

## Varias suites en paralelo

Da a cada una su propio puerto. Con `--port 0` el sistema elige uno libre (solo en modo nativo) y `awsemu` lo indica en la salida; `status --all --json` lo devuelve en formato máquina:

```bash
awsemu --port 9301 start && AWSEMU_PORT=9301 awsemu exec -- pytest tests/a &
awsemu --port 9302 start && AWSEMU_PORT=9302 awsemu exec -- pytest tests/b &
wait
awsemu stop --all
```

## Desde pytest

Mientras llega el plugin oficial (ver [ROADMAP](../ROADMAP.md), v0.5), un fixture de sesión basta:

```python
# conftest.py
import json
import os
import subprocess

import boto3
import pytest

PORT = os.environ.get("AWSEMU_PORT", "9297")


@pytest.fixture(scope="session", autouse=True)
def aws_emulator():
    subprocess.run(["awsemu", "--port", PORT, "start", "--idle-timeout", "900",
                    "--seed", "tests/seed.yaml"], check=True)
    env = subprocess.run(["awsemu", "--port", PORT, "env", "--shell", "dotenv"],
                         check=True, capture_output=True, text=True).stdout
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        os.environ.pop(var, None)
    os.environ.update(line.split("=", 1) for line in env.splitlines() if "=" in line)
    yield
    subprocess.run(["awsemu", "--port", PORT, "stop"], check=True)


def test_bucket():
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="demo")
    assert "demo" in [b["Name"] for b in s3.list_buckets()["Buckets"]]
```

## GitHub Actions

En runners de Linux se puede instalar el paquete oficial (verificando su firma) y usar `awsemu`:

```yaml
jobs:
  integration:
    runs-on: ubuntu-latest
    env:
      EMULATOR_TELEMETRY: "off"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install AWS Emulator
        run: |
          BASE=https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest
          curl -fsSLO "$BASE/aws-emulator_amd64.deb"
          curl -fsSLO "$BASE/aws-emulator_amd64.deb.sig"
          curl -fsSLo aws.asc https://downloads.aws.com/keys/gpg/current.asc
          gpg --import aws.asc
          gpg --verify aws-emulator_amd64.deb.sig aws-emulator_amd64.deb
          sudo apt-get install -y ./aws-emulator_amd64.deb

      - run: pipx install git+https://github.com/skaidan/aws-emulator-cli
      - run: awsemu start --idle-timeout 1800 --seed tests/seed.yaml
      - run: awsemu exec -- pytest tests/integration
      - if: always()
        run: awsemu logs -n 200
      - if: always()
        run: awsemu stop
```

El job `real-emulator` de [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) hace exactamente esto (y además comprueba la huella de la clave GPG).

## Docker Compose

Si tu app corre en contenedores, deja el emulador en el host con `awsemu start` y genera un fichero de entorno:

```bash
awsemu env --shell dotenv > .env.emulator
```

Ten en cuenta que las rutas de ese fichero son del host: monta `~/.aws/emulator` en el contenedor en la misma ruta, y que `127.0.0.1` dentro de un contenedor es el propio contenedor (usa `network_mode: host` en Linux). La v0.5 del roadmap incluye un generador de servicio de compose.

## Comprobar que hablas con el emulador

```bash
awsemu whoami                              # falla si la cuenta no es 000000000000
awsemu exec -- aws sts get-caller-identity
```

Úsalo como primer paso de cualquier script que vaya a crear o borrar recursos.

## Salida para máquinas

| Comando | Salida |
| --- | --- |
| `awsemu status --json` | Estado de la instancia (`status`, `mode`, `pid`, `auth`, `endpoint`…). Código de salida 3 si no está sana. |
| `awsemu status --all --json` | Lista con todas las instancias conocidas. |
| `awsemu overview --json` | Recursos por servicio. |
| `awsemu s3 ls --json`, `sqs ls --json`, `sqs receive --json`, `ddb scan --json`, `sns ls --json` | Datos sin formatear. |
| `awsemu lambda invoke … --raw` | Solo la respuesta de la función; código 1 si la función falló. |
| `--plain` / `NO_COLOR=1` | Texto sin colores ni cajas. |

El formato de `--json` todavía puede cambiar antes de la v1.0.
