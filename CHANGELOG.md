# Changelog

## Unreleased

- `awsemu sns`: `ls`, `create`, `publish`, `subscribe` (`--to-sqs` configura la política de la cola; `--to-lambda` añade el permiso), `subs`, `unsubscribe`, `rm`.
- `awsemu lambda` (alias `fn`): `deploy` desde carpeta, fichero o `.zip` (adivina handler y runtime, crea el rol si hace falta, actualiza si ya existe), `invoke` con payload JSON y log, `logs`, `info`, `ls`, `rm`.
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
