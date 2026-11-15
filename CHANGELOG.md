# Changelog

## 0.5.0 — 2026-11-15

Integración con proyectos y CI.

- `awsemu.toml` (o `[tool.awsemu]` en `pyproject.toml`), buscado desde la carpeta actual hacia arriba (o `AWSEMU_CONFIG`): `port`, `mode`, `auth`, `telemetry`, `idle_timeout`, `seed`, `sdk`, `image`, `memory`. Todos los comandos lo respetan; los flags y `AWSEMU_PORT` siguen teniendo prioridad.
- `awsemu init`, `awsemu up` (arranca si hace falta y aplica el seed) y `awsemu down`. `up` y `down` ya no son alias de `start` y `stop`.
- Plugin de pytest (se instala con awsemu): fixtures `aws_emulator` y `aws_emulator_fresh`; opciones `--awsemu-seed`, `--awsemu-port`, `--awsemu-reuse`, `--awsemu-docker` y sus equivalentes ini.
- GitHub Action en `action.yml`: paquete del emulador con firma verificada, `awsemu`, seed y variables para los pasos siguientes.
- `awsemu compose`: servicio de Docker Compose con la receta oficial.
- `doctor` y `config show` muestran el proyecto activo.
- CI: jobs para el modo Docker con el emulador real y para la propia Action.

## 0.4.0 — 2026-11-15

Seeds: el mismo estado de partida después de cada arranque o reinicio.

- `awsemu seed apply FILE`: crea buckets (con objetos en texto, JSON o desde carpetas locales), colas con DLQ, tablas con items, temas con suscripciones a SQS/Lambda (con filtros y entrega raw), secretos y parámetros. Se puede repetir: informa de lo creado, actualizado o sin cambios, y nunca borra.
- `awsemu start --seed FILE` y `awsemu reset --seed FILE`, que validan el seed antes de arrancar o parar.
- `awsemu seed validate FILE`: errores con línea y campo, y sugerencias para campos mal escritos.
- `awsemu seed export`: el estado actual como seed (`--no-secrets`, `--objects-dir`, `-s SECCIÓN`).
- `examples/seed.yaml` y la guía `docs/seeds.md`.
- Nueva dependencia: PyYAML.

## 0.3.0 — 2026-11-15

Más servicios, todos probados contra el emulador real.

- `awsemu sns`: `ls`, `create`, `publish`, `subscribe` (`--to-sqs` configura la política de la cola; `--to-lambda` añade el permiso), `subs`, `unsubscribe`, `rm`.
- `awsemu lambda` (alias `fn`): `deploy` desde carpeta, fichero o `.zip` (adivina handler y runtime, crea el rol si hace falta, actualiza si ya existe), `invoke` con payload JSON y log, `logs`, `info`, `ls`, `rm`.
- `awsemu secrets` (Secrets Manager) y `awsemu ssm` (Parameter Store): `put` crea o versiona, `get` formatea JSON, `ls` nunca muestra valores secretos.
- `awsemu events` (alias `eb`): `rule` crea la regla y su destino (`--to-sqs`, `--to-lambda`, `--to-sns`) con los permisos; `put`, `rules`, `buses`, `create-bus`, `rm`.
- `awsemu kinesis`: `create`, `put`, `read` (todos los shards, JSON/texto/hex, `--follow`), `ls`, `rm`.
- `awsemu sfn`: `deploy` (crea el rol), `start` (espera; muestra salida o error y causa; código 1 si falla), `executions`, `rm`.
- `awsemu describe ARN` para S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, Kinesis, EventBridge, Step Functions, CloudWatch Logs e IAM.
- `lambda logs` explica que el emulador no envía la salida de Lambda a CloudWatch Logs y remite a `lambda invoke`.
- Documentación completa en `docs/` y `CONTRIBUTING.md`; `docs/reference.md` se genera desde el código y la CI comprueba que está al día.
- Workflow de release: cada versión nueva en `pyproject.toml` se publica sola en GitHub con su wheel.

## 0.2.0 — 2026-11-15

Validación contra el emulador real y robustez.

- Tests de integración contra el AWS Emulator real (`pytest -m real`) y job de CI que instala el `.deb` oficial verificando su firma.
- CI en Linux, macOS y Windows.
- `--port 0`: el sistema elige un puerto libre y `awsemu` lo lee de la línea de arranque.
- Parada limpia en Windows (Ctrl+Break). Tras una parada forzada o un cierre inesperado, `awsemu stop` borra los ficheros que el emulador dejó en `~/.aws/emulator/<puerto>/`.
- Los logs se guardan en disco también en Docker y se pueden leer después de parar.
- Errores con pistas concretas (credenciales de otra ejecución, peticiones sin firmar, `UnknownService`, reloj desfasado, TLS…).
- `AWSEMU_BINARY` para indicar el binario del emulador.

## 0.1.0 — 2026-11-15

Primera versión: `start`/`stop`/`restart`/`status`/`logs`, `env`/`exec`/`shell`/`aws`/`whoami`, `overview`, comandos de S3, SQS y DynamoDB, `doctor`, `image build` y `config telemetry`.
