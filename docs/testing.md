# Tests y CI

El emulador es ideal para tests de integración: no hace falta cuenta de AWS, arranca en un momento y cada reinicio empieza vacío. `awsemu` trae tres formas de usarlo según dónde corran tus tests:

| Dónde | Cómo |
| --- | --- |
| pytest | [Plugin](#plugin-de-pytest): fixture `aws_emulator`, sin configuración |
| GitHub Actions | [Action](#github-actions): `uses: skaidan/aws-emulator-cli@v0.5.0` |
| Cualquier otro sitio | [Scripts](#scripts) con `awsemu start`/`exec`/`stop`, o [Docker Compose](#docker-compose) |

En todos los casos, los datos de partida van en un [seed](seeds.md).

## Plugin de pytest

Se instala con `awsemu` y no hace nada hasta que un test pide uno de sus fixtures.

```python
import boto3


def test_upload(aws_emulator):
    s3 = boto3.client("s3")                      # ya apunta al emulador
    s3.create_bucket(Bucket="demo")
    assert "demo" in [b["Name"] for b in s3.list_buckets()["Buckets"]]


def test_with_clean_state(aws_emulator_fresh):
    # reiniciado y con el seed aplicado de nuevo: lo que hiciera otro test ya no está
    names = [b["Name"] for b in aws_emulator_fresh.client("s3").list_buckets()["Buckets"]]
    assert "demo" not in names
```

```bash
pytest --awsemu-seed tests/seed.yaml
```

### Qué hace `aws_emulator`

Una vez por sesión de pytest:

1. Valida el seed (si lo hay) **antes** de arrancar nada.
2. Arranca un emulador en un **puerto libre** (así no choca con el que tengas abierto ni con otros procesos de pytest, por ejemplo con `pytest-xdist`), con `idle_timeout` de 30 minutos como red de seguridad.
3. Aplica el seed.
4. Apunta `os.environ` al emulador (las mismas variables que `awsemu env`) y quita tus credenciales reales: boto3, el AWS CLI o tu propio código lo usan sin configurar nada.
5. Al terminar la sesión restaura el entorno y para el emulador.

El fixture devuelve un objeto con:

| Atributo / método | Para qué |
| --- | --- |
| `port`, `endpoint_url` | Dónde escucha |
| `env` | Las variables que ha puesto en el entorno |
| `client("s3")` | Un cliente de boto3 conectado a este emulador |
| `apply_seed(ruta=None)` | Aplicar otro seed (o el mismo otra vez) |
| `reset()` | Reiniciar (estado vacío) y volver a aplicar el seed |

`aws_emulator_fresh` es el mismo emulador, reiniciado antes de cada test que lo pida. Es más lento (unos segundos por test), así que úsalo solo donde necesites partir de cero.

### Opciones

| Línea de comandos | `pytest.ini` / `[tool.pytest.ini_options]` | Para qué |
| --- | --- | --- |
| `--awsemu-seed FILE` | `awsemu_seed = tests/seed.yaml` | Seed (relativo a la raíz de pytest) |
| `--awsemu-port N` | `awsemu_port = 9350` | Puerto fijo en vez de uno libre |
| `--awsemu-reuse` | `awsemu_reuse = true` | Usar un emulador ya arrancado (`awsemu up`) en vez de arrancar otro; no se para al final |
| `--awsemu-docker` | `awsemu_mode = docker` | Arrancarlo en Docker |

Si no indicas nada, se usa lo que haya en [`awsemu.toml`](project-config.md) (`seed`, `mode`, `auth`, `telemetry`, `sdk`…).

`--awsemu-reuse` es cómodo mientras desarrollas: deja el emulador encendido con `awsemu up` y tus tests arrancan al instante.

## GitHub Actions

```yaml
jobs:
  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: skaidan/aws-emulator-cli@v0.5.0
        with:
          seed: tests/seed.yaml
      - run: pytest tests/integration      # AWS_ENDPOINT_URL & co. ya están puestas
```

La Action:

1. Descarga el paquete oficial del emulador, **verifica su firma GPG** (y la huella de la clave) y lo instala.
2. Instala `awsemu` (la versión de la propia Action).
3. Arranca el emulador (`--no-telemetry` por defecto, `idle_timeout` de una hora) y aplica el seed.
4. Exporta las variables del emulador para los pasos siguientes (`AWS_ENDPOINT_URL`, `AWS_CA_BUNDLE`, `AWS_CONFIG_FILE`, `AWS_SHARED_CREDENTIALS_FILE`, región…) y `AWSEMU_PORT`, así que `awsemu` y el AWS CLI también funcionan sin `--port`.

| Entrada | Por defecto | |
| --- | --- | --- |
| `seed` | — | Ruta del seed en tu repositorio |
| `port` | `9297` | |
| `auth` | `true` | `false` acepta peticiones sin firmar |
| `telemetry` | `false` | |
| `idle-timeout` | `3600` | Segundos sin llamadas antes de pararse |
| `export-env` | `true` | `false` para solo arrancarlo |

| Salida | |
| --- | --- |
| `port` | Puerto |
| `endpoint-url` | `https://127.0.0.1:PUERTO` |
| `ca-bundle` | Ruta del certificado |

Notas:

- Necesita un runner **Linux** (x64 o ARM64): el emulador se distribuye como paquete de Linux.
- No uses credenciales reales de AWS en el mismo job: tendrían prioridad sobre las del emulador (la Action avisa si las detecta). Si las necesitas, ejecuta los comandos contra el emulador con `awsemu exec -- …`.
- Para ver qué pasó si algo falla:

  ```yaml
      - if: failure()
        run: awsemu logs -n 200
  ```

El job `action` de [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) prueba la Action en cada cambio.

## Scripts

```bash
awsemu start --idle-timeout 900 --seed tests/seed.yaml
awsemu exec -- pytest tests/integration      # o npm test, go test, terraform…
code=$?
awsemu stop
exit $code
```

`awsemu exec` ejecuta el comando con las variables del emulador y **sin** tus credenciales reales, así que un test mal configurado no puede llegar a AWS por accidente.

### Estado limpio entre suites

El emulador guarda todo en memoria y no tiene una ruta para vaciarlo. Reinícialo; con un seed, vuelve además con tus datos de partida:

```bash
awsemu reset --seed tests/seed.yaml
```

Para montar ese seed, crea el escenario a mano o con tu aplicación y expórtalo: `awsemu seed export -o tests/seed.yaml --no-secrets`.

### Varias suites en paralelo

Cada una en su puerto:

```bash
awsemu --port 9301 start && AWSEMU_PORT=9301 awsemu exec -- pytest tests/a &
awsemu --port 9302 start && AWSEMU_PORT=9302 awsemu exec -- pytest tests/b &
wait
awsemu stop --all
```

## Docker Compose

`awsemu compose` genera el servicio del emulador con la misma configuración que `awsemu start --docker`: la receta oficial de AWS, el puerto publicado solo en `127.0.0.1`, la memoria limitada y la carpeta de credenciales montada en la misma ruta que en tu máquina.

```bash
awsemu compose -o compose.emulator.yaml
docker compose -f compose.emulator.yaml up -d
awsemu status                                 # espera a que esté sano
eval "$(awsemu env)"
```

Usa la configuración del proyecto (`port`, `auth`, `telemetry`, `idle_timeout`, `image`, `memory`) y acepta `--no-auth`, `--no-telemetry`, `--idle-timeout`, `--name` y `--no-build` (si ya construiste la imagen con `awsemu image build`).

Para que **otros contenedores** hablen con el emulador: en Linux, `network_mode: host` y las variables de `awsemu env --shell dotenv`, montando `~/.aws/emulator` en la misma ruta para que `AWS_CA_BUNDLE` exista dentro del contenedor. El certificado del emulador es para `127.0.0.1`, así que acceder por el nombre del servicio fallaría la verificación TLS.

El job `docker` de la CI construye la imagen, prueba `awsemu start --docker` y levanta el fichero que genera `awsemu compose`.

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
| `awsemu s3 ls --json`, `sqs ls --json`, `sqs receive --json`, `ddb scan --json`, `sns ls --json`, `events rules --json`, `kinesis read --json` | Datos sin formatear. |
| `awsemu lambda invoke … --raw`, `sfn start … --raw`, `secrets get … --raw` | Solo el resultado; código 1 si falló. |
| `awsemu seed export` | El estado como YAML. |
| `--plain` / `NO_COLOR=1` | Texto sin colores ni cajas. |

El formato de `--json` todavía puede cambiar antes de la v1.0.
