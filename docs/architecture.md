# Arquitectura

`awsemu` es una capa fina sobre el emulador: no reimplementa nada de AWS, solo automatiza lo que la documentación oficial pide hacer a mano.

## Qué hace el emulador y qué hace `awsemu`

| El emulador (`aws-emulator`) | `awsemu` |
| --- | --- |
| Corre en primer plano; no tiene subcomandos. | Lo lanza en segundo plano y guarda su PID o su contenedor. |
| Escribe `config`, `emulator_credentials`, `ca.pem` y `truststore.p12` en `~/.aws/emulator/<puerto>/` y los borra al pararse limpiamente. | Los lee (nunca escribe ahí) y, si quedan tras una parada forzada, los borra. |
| Expone `GET /__admin/health`. | Lo usa para esperar al arranque y para `status`. |
| Escribe su log como JSON (formato `tracing`, con el mensaje en `fields`). | Lo guarda en disco y lo muestra legible. Usa la línea `emulator server information` para saber el puerto real con `-p 0`. |
| Acepta SIGTERM / Ctrl+C como parada limpia. | Envía SIGTERM (Ctrl+Break en Windows) y espera. |
| Genera claves y certificado nuevos en cada arranque. | No cachea claves entre arranques; `env` exporta rutas, no valores. |

## Ficheros

```
~/.aws/emulator/                  ← del emulador
  config.toml                     ← sus ajustes (awsemu config)
  <puerto>/config, emulator_credentials, ca.pem, truststore.p12

~/.aws/emulator-cli/              ← de awsemu ($AWSEMU_HOME)
  <puerto>/state.json             ← modo, pid o contenedor, comando, ruta del log
  <puerto>/emulator.log           ← log (nativo y Docker), se conserva tras parar
  pending/<n>.log                 ← log temporal de un arranque con --port 0
```

## Módulos

```
src/awsemu/
  cli.py          comandos de ciclo de vida, entorno, doctor, image, config; registra el resto
  context.py      --port global y manejo de errores (botocore → mensaje + pista)
  runtime.py      start/stop/status: nativo, Docker, --port 0, limpieza, Dockerfile
  health.py       comprobación de /__admin/health con el ca.pem de la instancia
  envvars.py      variables de entorno y su sintaxis por shell
  clients.py      clientes boto3 explícitos por puerto; pistas de error (hint_for)
  logs.py         parseo del log JSON del emulador
  settings.py     edición de config.toml conservando comentarios
  seed.py         formato de seed: parseo YAML con mapa de líneas y validación (sin llamadas a AWS)
  project.py      awsemu.toml / [tool.awsemu]: búsqueda hacia arriba, validación, caché por fichero
  pytest_plugin.py  plugin de pytest (entry point pytest11): fixtures aws_emulator y aws_emulator_fresh
  paths.py        rutas y constantes (puerto, región, cuenta 000000000000)
  ui.py           salida con Rich, o texto plano si no está o con --plain
  commands/       un módulo por servicio: overview, s3, sqs, dynamodb, sns, lambda_,
                  secrets (secrets + ssm), events, kinesis, sfn, describe,
                  seed (apply idempotente, export), compose
action.yml        GitHub Action compuesta (paquete verificado, awsemu, seed, variables)
  commands/_common.py  roles de servicio, políticas de cola, permisos de Lambda, códigos de error
```

## Decisiones de diseño

**Clientes explícitos, no variables de entorno.** Los comandos de servicio crean los clientes de boto3 con endpoint, certificado y claves del puerto elegido. Así `awsemu` nunca usa credenciales reales aunque estén en la shell, y puede hablar con varias instancias.

**`env` exporta rutas.** Las claves y el certificado cambian en cada arranque, pero sus rutas no: un `eval "$(awsemu env)"` sigue valiendo tras un reinicio para el certificado y el `config`. (Las herramientas que cacheen claves en memoria sí necesitan recargarlas.)

**Click en lugar de Typer.** Typer está construido sobre Click; usar Click directamente evita una dependencia y permite probar todo con `CliRunner`.

**Rich opcional en tiempo de ejecución.** Si falta, la salida es texto plano. Útil en imágenes mínimas y en CI.

**Errores esperados sin traceback.** `handle_errors` convierte `RuntimeErrorWithHint` y cualquier error de botocore (incluidas las subclases que genera por código, como `NoSuchBucket`) en una línea de error y una pista. Lo demás sí se muestra con traceback: es un bug.

**Seeds idempotentes y que nunca borran.** `seed apply` compara antes de escribir (secretos, parámetros, atributos de colas y suscripciones) para que repetirlo no genere versiones ni cambios innecesarios, y no elimina nada que no esté en el seed: para partir de cero está `reset --seed`. La validación es una capa aparte (`seed.py`) que se ejecuta entera antes de tocar el emulador.

**Precedencia única.** Flag > variable de entorno > `awsemu.toml` > valor por defecto, en todos los comandos. Por eso las opciones de `start` no tienen valor por defecto en Click: `None` significa "no lo has dicho" y deja paso al proyecto.

**El plugin de pytest no hace nada si no se usa.** Se registra para todo el que instale `awsemu`, así que solo añade opciones y fixtures; el emulador arranca únicamente cuando un test pide `aws_emulator`, y en un puerto libre para no interferir con nada.

**No escribir en la carpeta del emulador.** El estado propio va en `~/.aws/emulator-cli/`. La única excepción es borrar, tras comprobar que el puerto está libre, los ficheros documentados que el emulador dejó al no poder pararse limpiamente.

## Cómo se prueba

- `tests/fake_emulator.py` imita el comportamiento documentado del binario: opciones, `-p 0`, ficheros, certificado, health check, log en formato `tracing` y limpieza al pararse. Permite probar el ciclo de vida en Linux, macOS y Windows sin el emulador.
- Los comandos de servicio se prueban con un cliente boto3 simulado (`tests/test_services.py`).
- `tests/test_real.py` corre contra el emulador real (`AWSEMU_REAL_TESTS=1`), en el job `real-emulator` de la CI.
- El job `docker` prueba `image build`, `start --docker` y `compose` con el emulador real, y el job `action` usa la GitHub Action del propio repositorio.

Más detalles en [CONTRIBUTING.md](../CONTRIBUTING.md).
