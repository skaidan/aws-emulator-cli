# aws-emulator-cli (`awsemu`)

Un CLI amigable para [AWS Emulator](https://github.com/aws/aws-emulator), el emulador local de las APIs de AWS.

El emulador en sí es un único binario sin subcomandos: se ejecuta en primer plano, escribe sus credenciales y su certificado en `~/.aws/emulator/<puerto>/` y espera que configures a mano varias variables de entorno. `awsemu` se encarga de todo eso:

- **Arrancar y parar** el emulador en segundo plano, con el binario nativo o con Docker, esperando a que esté sano.
- **Conectar tu shell** con un solo comando (`eval "$(awsemu env)"`), sin tocar tus credenciales reales.
- **Ver qué hay dentro**: buckets, colas, tablas, funciones, secretos… en una sola pantalla.
- **Trabajar con S3, SQS y DynamoDB** con comandos cortos y tablas legibles (DynamoDB con JSON normal, sin `{"S": ...}`).
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

## Instalación

Requisitos: Python 3.10+ y **una** de estas dos opciones para ejecutar el emulador:

- **Linux**: el paquete `.rpm` o `.deb` de AWS Emulator (deja `aws-emulator` en el `PATH`).
- **macOS, Windows o Linux**: Docker. AWS no publica una imagen, pero `awsemu image build` la construye con la receta oficial.

```bash
pipx install git+https://github.com/skaidan/aws-emulator-cli
# o bien
pip install git+https://github.com/skaidan/aws-emulator-cli
```

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
| `awsemu start -f` | En primer plano, como el binario original (Ctrl+C para parar). |
| `awsemu start -- <opciones>` | Pasa opciones extra al emulador tal cual. |
| `awsemu status` / `awsemu ps` | Estado, modo, PID o contenedor, uptime. `--all` para todos los puertos, `--json` para scripts. |
| `awsemu logs [-f] [--grep TEXTO]` | Logs JSON del emulador, legibles. `--raw` para verlos tal cual. |
| `awsemu stop [--all]` | Parada limpia (SIGTERM): el emulador borra sus ficheros. |
| `awsemu restart` / `awsemu reset` | Reinicia. El emulador guarda todo en memoria, así que esto **vacía el estado**. |

Varias instancias a la vez: usa `--port` (o la variable `AWSEMU_PORT`) en cualquier comando.

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
```

Para cualquier otro servicio u operación: `awsemu aws <servicio> <operación> ...`.

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

- `--port 0` (puerto aleatorio) no está soportado: `awsemu` necesita conocer el puerto de antemano.
- El emulador no persiste datos: al parar o reiniciar se pierde todo. Es así por diseño del emulador.
- S3 Control no funciona contra el emulador (el SDK siempre mete el ID de cuenta en el host). Es una limitación del emulador.

## Desarrollo

```bash
git clone https://github.com/skaidan/aws-emulator-cli && cd aws-emulator-cli
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Los tests no necesitan el emulador real: `tests/fake_emulator.py` imita su comportamiento documentado (opciones, ficheros, health check, log JSON y limpieza al recibir SIGTERM). Los comandos de servicios se prueban con un cliente boto3 simulado.

## Licencia

MIT. Este proyecto no es oficial ni está afiliado a AWS.
