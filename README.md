# aws-emulator-cli (`awsemu`)

Un CLI amigable para [AWS Emulator](https://github.com/aws/aws-emulator), el emulador local de las APIs de AWS.

El emulador en sí es un único binario sin subcomandos: se ejecuta en primer plano, escribe sus credenciales y su certificado en `~/.aws/emulator/<puerto>/` y espera que configures a mano varias variables de entorno. `awsemu` se encarga de todo eso:

- **Arrancar y parar** el emulador en segundo plano, con el binario nativo o con Docker, esperando a que esté sano.
- **Conectar tu shell** con un solo comando (`eval "$(awsemu env)"`), sin tocar tus credenciales reales.
- **Ver qué hay dentro**: buckets, colas, tablas, funciones, secretos… en una sola pantalla.
- **Trabajar con S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, EventBridge, Kinesis y Step Functions** con comandos cortos y tablas legibles: DynamoDB con JSON normal, `lambda deploy` desde una carpeta, reglas de EventBridge con su destino y permisos en un paso, y `describe` para cualquier ARN.
- **Arrancar siempre con los mismos datos** con un *seed* en YAML: `awsemu start --seed seed.yaml`, `awsemu reset --seed seed.yaml`, y `seed export` para guardar el estado actual.
- **Diagnosticar** problemas típicos (`awsemu doctor`).

```
$ awsemu start
Starting AWS Emulator (native) on port 9297…
✓ AWS Emulator is up at https://127.0.0.1:9297

$ awsemu s3 mb fotos && awsemu s3 put ./gato.jpg fotos/
$ awsemu sqs create trabajos && awsemu sqs send trabajos '{"id": 1}'
$ awsemu ddb create usuarios --pk id
$ awsemu ddb put usuarios '{"id": "u1", "nombre": "Ana", "edad": 30}'

$ awsemu overview
AWS Emulator on port 9297
resource         count  names
S3 buckets       1      fotos
SQS queues       1      trabajos
DynamoDB tables  1      usuarios
```

## Documentación

- [Primeros pasos](docs/getting-started.md): instalar, arrancar y conectar tus herramientas.
- [Seeds](docs/seeds.md): datos de partida reproducibles (formato, validación, `apply` y `export`).
- [Guía de servicios](docs/services.md): S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, EventBridge, Kinesis, Step Functions y `describe`, con ejemplos.
- [Tests y CI](docs/testing.md): pytest, scripts y GitHub Actions.
- [Solución de problemas](docs/troubleshooting.md): qué significa cada error.
- [Referencia de comandos](docs/reference.md): todos los comandos y opciones.
- [Arquitectura](docs/architecture.md) y [cómo contribuir](CONTRIBUTING.md).

## Instalación

Requisitos: Python 3.10+ y **una** de estas dos opciones para ejecutar el emulador:

- **Linux**: el paquete `.rpm` o `.deb` de AWS Emulator (deja `aws-emulator` en el `PATH`).
- **macOS, Windows o Linux**: Docker. AWS no publica una imagen, pero `awsemu image build` la construye con la receta oficial.

```bash
pipx install git+https://github.com/skaidan/aws-emulator-cli
# o una versión concreta, desde las releases:
pipx install https://github.com/skaidan/aws-emulator-cli/releases/download/v0.4.0/aws_emulator_cli-0.4.0-py3-none-any.whl
```

Todas las versiones: [Releases](https://github.com/skaidan/aws-emulator-cli/releases).

Después:

```bash
awsemu doctor          # comprueba qué tienes y qué falta
awsemu image build     # solo si vas a usar Docker
```

## Uso

### Ciclo de vida

| Comando | Qué hace |
| --- | --- |
| `awsemu start` | Arranca en segundo plano y espera al health check. Usa el binario si está instalado; si no, Docker. |
| `awsemu start --docker` / `--native` | Fuerza el modo. |
| `awsemu start --no-auth` | Sin firma SigV4 (el emulador acepta cualquier petición). |
| `awsemu start --idle-timeout 600` | Se para solo tras 10 min sin llamadas (útil en CI). |
| `awsemu --port 0 start` | El sistema elige un puerto libre (solo en modo nativo); `awsemu` te dice cuál. |
| `awsemu start -f` | En primer plano, como el binario original (Ctrl+C para parar). |
| `awsemu start -- <opciones>` | Pasa opciones extra al emulador tal cual. |
| `awsemu status` / `awsemu ps` | Estado, modo, PID o contenedor, uptime. `--all` para todos los puertos, `--json` para scripts. |
| `awsemu logs [-f] [--grep TEXTO]` | Logs JSON del emulador, legibles, también después de pararlo y también en Docker. `--raw` para verlos tal cual. |
| `awsemu stop [--all]` | Parada limpia (SIGTERM; Ctrl+Break en Windows): el emulador borra sus ficheros. |
| `awsemu stop --force` | Si no responde. `awsemu` borra los ficheros que el emulador no haya podido limpiar. |
| `awsemu restart` / `awsemu reset` | Reinicia. El emulador guarda todo en memoria, así que esto **vacía el estado**. |

Varias instancias a la vez: usa `--port` (o la variable `AWSEMU_PORT`) en cualquier comando.

Si el binario no está en el `PATH`, indícalo con `AWSEMU_BINARY` (admite argumentos):

```bash
export AWSEMU_BINARY=/opt/aws-emulator/bin/aws-emulator
```

```bash
awsemu --port 9300 start
awsemu --port 9300 overview
```

### Conectar tus herramientas

```bash
eval "$(awsemu env)"                       # bash / zsh
awsemu env --shell fish | source           # fish
awsemu env --shell powershell | iex        # PowerShell
awsemu env --shell dotenv > .env.emulator  # docker compose, IDEs…
awsemu env --sdk node --sdk java           # añade NODE_EXTRA_CA_CERTS / JAVA_TOOL_OPTIONS
eval "$(awsemu env --unset)"               # volver a AWS real
```

`awsemu env` exporta las mismas variables que indica la documentación oficial (`AWS_ENDPOINT_URL`, `AWS_CA_BUNDLE`, `AWS_CONFIG_FILE`, `AWS_SHARED_CREDENTIALS_FILE`, `AWS_DISABLE_HOST_PREFIX_INJECTION`…) y además **desactiva** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` y `AWS_PROFILE`, que si no tendrían prioridad y harían fallar la autenticación.

Si no quieres tocar tu shell actual:

```bash
awsemu exec -- pytest -k integration       # cualquier comando, ya apuntando al emulador
awsemu aws s3 ls                           # el AWS CLI, apuntando al emulador
awsemu shell                               # una sub-shell conectada ('exit' para salir)
awsemu whoami                              # comprueba que hablas con la cuenta 000000000000
```

### Servicios

```bash
awsemu overview [--all] [-s s3 -s sqs] [--json]   # alias: awsemu ls

awsemu s3 ls [BUCKET[/PREFIJO]] [-r]
awsemu s3 mb BUCKET...
awsemu s3 put FICHERO_O_CARPETA BUCKET[/CLAVE]
awsemu s3 get BUCKET/CLAVE [DESTINO]
awsemu s3 cat BUCKET/CLAVE
awsemu s3 rm BUCKET/CLAVE   |   awsemu s3 rm -r BUCKET/PREFIJO
awsemu s3 rb BUCKET [--force]
awsemu s3 presign BUCKET/CLAVE [--put] [--expires 600]

awsemu sqs ls
awsemu sqs create NOMBRE [--fifo] [--dlq OTRA_COLA]
awsemu sqs send COLA 'cuerpo' [-a clave=valor] [--group G]
awsemu sqs receive COLA [-n 10] [--delete]
awsemu sqs info COLA
awsemu sqs purge COLA   |   awsemu sqs rm COLA

awsemu ddb ls                                      # ddb = dynamodb
awsemu ddb create TABLA --pk id [--sk fecha:N]
awsemu ddb put TABLA '{"id": "u1", "edad": 30}'    # o --file items.json (objeto o lista)
awsemu ddb get TABLA '{"id": "u1"}'
awsemu ddb scan TABLA [-n 50] [--json]
awsemu ddb delete TABLA '{"id": "u1"}'
awsemu ddb drop TABLA

awsemu sns ls
awsemu sns create TOPIC [--fifo]
awsemu sns subscribe TOPIC --to-sqs COLA [--raw]     # configura la política de la cola
awsemu sns subscribe TOPIC --to-lambda FUNCION
awsemu sns publish TOPIC 'mensaje' [--subject S] [-a clave=valor]
awsemu sns subs [TOPIC]   |   awsemu sns rm TOPIC

awsemu lambda deploy NOMBRE ./carpeta|fichero.py|code.zip [-e CLAVE=valor]   # alias: fn
awsemu lambda invoke NOMBRE '{"name": "Ana"}' [--raw] [--async]
awsemu lambda logs NOMBRE [-f]
awsemu lambda ls   |   awsemu lambda info NOMBRE   |   awsemu lambda rm NOMBRE
```

`lambda deploy` adivina el handler y el runtime a partir del código (`def handler(...)` en Python, `exports.handler` / `export const handler` en Node), crea un rol de ejecución si no le pasas `--role` y, si la función ya existe, la actualiza.

Y además `awsemu secrets`, `ssm`, `events`, `kinesis`, `sfn` y `describe ARN`: ejemplos de todos en la [guía de servicios](docs/services.md).

Para cualquier otro servicio u operación: `awsemu aws <servicio> <operación> ...`.

### Seeds

```bash
awsemu seed validate seed.yaml     # errores con línea y campo
awsemu start --seed seed.yaml      # arrancar + aplicar
awsemu seed apply seed.yaml        # se puede repetir: crea, actualiza o deja igual
awsemu reset --seed seed.yaml      # estado vacío + seed
awsemu seed export -o seed.yaml    # el estado actual, como seed
```

Formato y detalles en [docs/seeds.md](docs/seeds.md); ejemplo completo en [examples/seed.yaml](examples/seed.yaml).

### Configuración del emulador

```bash
awsemu config show                 # ~/.aws/emulator/config.toml (o $EMULATOR_CONFIG)
awsemu config telemetry off        # escribe [telemetry] enabled = false
awsemu start --no-telemetry        # solo para esta ejecución
```

### Otras opciones

- `--plain` o `NO_COLOR=1`: salida en texto plano, sin colores ni cajas.
- Prefijos y alias: `awsemu stat` → `status`, `ps`, `up`, `down`, `reset`, `ddb`, `ls`.
- Códigos de salida: `status` devuelve `3` si el emulador no está sano, útil en scripts.

## Cómo funciona

- El emulador escribe `config`, `emulator_credentials`, `ca.pem` y `truststore.p12` en `~/.aws/emulator/<puerto>/` y los borra al pararse limpiamente. `awsemu` los lee, pero nunca escribe ahí.
- `awsemu` guarda su propio estado (PID o contenedor, y el log en modo nativo) en `~/.aws/emulator-cli/<puerto>/`. Se puede cambiar con `AWSEMU_HOME`.
- Para saber si el emulador está listo usa `GET /__admin/health`, que es la única ruta de control que ofrece el emulador.
- En Docker sigue la receta oficial: publica el puerto **solo** en `127.0.0.1`, limita la memoria a 2 GiB, monta `~/.aws/emulator` y, en Linux, usa tu UID para que los ficheros sean tuyos.
- Los comandos de servicios usan boto3 con el endpoint, el certificado y las claves del emulador configurados de forma explícita. Aunque tu shell tenga credenciales reales, `awsemu` nunca llama a AWS.

## Limitaciones

- `--port 0` solo funciona en modo nativo: Docker no puede redirigir un puerto que se elige al arrancar.
- En Windows, la parada limpia usa Ctrl+Break. Si el emulador no la atiende, `awsemu` borra igualmente sus ficheros, pero el emulador no llega a enviar su último lote de telemetría.
- El emulador no persiste datos: al parar o reiniciar se pierde todo. Es así por diseño del emulador; los [seeds](docs/seeds.md) lo resuelven.
- S3 Control no funciona contra el emulador (el SDK siempre mete el ID de cuenta en el host). Es una limitación del emulador.

## Roadmap

Hecho: ciclo de vida nativo y Docker, validación contra el emulador real en Linux, macOS y Windows (v0.2), y 10 servicios con comandos propios más `describe` (v0.3), y seeds para arrancar con datos reproducibles (v0.4). Lo que viene: plugin de pytest, GitHub Action y `awsemu.toml` por proyecto (v0.5), y autocompletado y una TUI (v0.6). Detalles en [ROADMAP.md](ROADMAP.md) y cambios por versión en [CHANGELOG.md](CHANGELOG.md).

## Desarrollo

```bash
git clone https://github.com/skaidan/aws-emulator-cli && cd aws-emulator-cli
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Guía completa (tests, añadir un servicio, documentación y releases) en [CONTRIBUTING.md](CONTRIBUTING.md).

Los tests normales no necesitan el emulador real: `tests/fake_emulator.py` imita su comportamiento documentado (opciones, `-p 0`, ficheros, health check, log JSON y limpieza al pararse). Los comandos de servicios se prueban con un cliente boto3 simulado. Corren en Linux, macOS y Windows.

Los tests contra el emulador real (`tests/test_real.py`) se activan aparte:

```bash
AWSEMU_REAL_TESTS=1 pytest -m real -v
```

En CI, el job `real-emulator` descarga el `.deb` oficial, verifica su firma GPG y los ejecuta.

## Licencia

MIT. Este proyecto no es oficial ni está afiliado a AWS.
