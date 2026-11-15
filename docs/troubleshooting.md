# Solución de problemas

Primer paso siempre:

```bash
awsemu doctor
```

Revisa Python, el binario, Docker y la imagen, el AWS CLI, boto3, el estado del emulador, si tienes credenciales reales en la shell, si `AWS_ENDPOINT_URL` usa `localhost`, y la telemetría. Cada problema viene con su solución.

## Errores al arrancar

| Mensaje | Causa | Solución |
| --- | --- | --- |
| `Neither the 'aws-emulator' binary nor Docker was found` | No hay forma de ejecutar el emulador. | Instala el paquete (Linux), define `AWSEMU_BINARY`, o instala Docker y ejecuta `awsemu image build`. |
| `Docker image 'aws-emulator' not found` | AWS no publica imagen. | `awsemu image build` |
| `Something is already listening on 127.0.0.1:9297` | Ya hay un emulador (u otra cosa) en ese puerto. | `awsemu status --all`, o usa `--port`. |
| `The emulator did not become healthy: emulator exited with code N` | El emulador se cerró al arrancar. `awsemu` muestra el final de su log. | Lee esas líneas. Código 137 en Docker = sin memoria: sube `--memory`. |
| `Port 0 doesn't work with Docker` | Docker no puede redirigir un puerto elegido al arrancar. | Usa un puerto fijo o `--native`. |
| `An emulator is listening on port N but wasn't started by awsemu` | Lo arrancaste a mano. | Páralo donde corre (Ctrl+C o SIGTERM). |
| `pid N is still running after 15s` | El emulador no responde a la parada limpia. | `awsemu stop --force` (borra también los ficheros que deje). |

## Errores al hablar con el emulador

`awsemu` añade una pista concreta a estos errores; aquí está el porqué.

| Error | Causa | Solución |
| --- | --- | --- |
| `AccessDenied: Sign the request with the emulator credentials` | La petición se firmó con claves que el emulador no acepta: tus claves reales de AWS, o las de una ejecución anterior (cambian en cada arranque). | `eval "$(awsemu env)"` otra vez, o usa `awsemu exec` / `awsemu aws`. Asegúrate de que `AWS_ACCESS_KEY_ID` no está definida. |
| `SignatureDoesNotMatch` | La clave secreta no es la de esta ejecución. | El emulador se reinició: recarga el entorno. |
| `InvalidClientTokenId`, `MissingAuthenticationToken` | Petición sin firmar. | Configura las credenciales del emulador, o arráncalo con `--no-auth`. |
| `UnknownService` (HTTP 404) | El emulador no sabe a qué servicio va la petición: casi siempre porque no está firmada; si no, el servicio no está emulado. | Firma la petición; consulta [los issues del emulador](https://github.com/aws/aws-emulator/issues). |
| `RequestTimeTooSkewed`, `Signature expired` | Tu reloj se desvía más de 15 minutos. | Sincroniza la hora (NTP). |
| `UnknownOperationException`, `NotImplemented` | Esa operación aún no está emulada. | Mira las notas de fidelidad de la release del emulador. |
| `CERTIFICATE_VERIFY_FAILED` | El emulador crea un `ca.pem` nuevo en cada arranque. | `AWS_CA_BUNDLE` debe apuntar a `~/.aws/emulator/<puerto>/ca.pem` (la ruta, no una copia). Comprueba que el puerto es del emulador. |
| `Could not connect to the endpoint URL` | No hay nada escuchando. | `awsemu status`, `awsemu start`. |

## Configuración del proyecto y tests

| Mensaje | Causa | Solución |
| --- | --- | --- |
| `…/awsemu.toml: unknown setting 'X'` o `'port' must be int` | Error en `awsemu.toml` o `[tool.awsemu]`; afecta a todos los comandos de esa carpeta. | Corrígelo (el mensaje sugiere el nombre correcto) o usa `AWSEMU_CONFIG` para apuntar a otro. |
| `awsemu: --awsemu-reuse but no healthy emulator on port N` | El plugin de pytest debía usar un emulador ya arrancado. | `awsemu up` antes de `pytest`, o quita `--awsemu-reuse`. |
| `awsemu: invalid seed` en pytest | El seed del plugin tiene errores; no se arranca nada. | `awsemu seed validate` con el mismo fichero. |
| `This action needs a Linux runner` | La GitHub Action solo funciona en Linux. | `runs-on: ubuntu-latest`. |
| Los comandos usan otro puerto del que esperas | `awsemu.toml` en esta carpeta o en una superior, o `AWSEMU_PORT`. | `awsemu config show` dice qué fichero se usa; `--port` siempre gana. |

## Problemas típicos

**Mis tests llegan a AWS real.** `AWS_ENDPOINT_URL` no estaba definida en la shell que ejecuta los tests. Usa `awsemu exec -- <comando>`, o ejecuta `awsemu whoami` al principio del script: falla si la cuenta no es `000000000000`.

**S3 falla con `localhost`.** Con `localhost`, los SDK de JavaScript, Java y Go ponen el nombre del bucket en el host (`fotos.localhost`) y el emulador no lo acepta. Usa `127.0.0.1`, que es lo que exporta `awsemu env`.

**Operaciones que van a `data-127.0.0.1`.** Algunos SDK añaden un prefijo al host (Cloud Map, Step Functions síncrono, CloudWatch Logs Live Tail). `awsemu env` exporta `AWS_DISABLE_HOST_PREFIX_INJECTION=true` (AWS CLI y boto3); en otros SDK hay que desactivarlo en el cliente.

**S3 Control no funciona.** El SDK siempre pone el ID de cuenta en el host. Es una limitación conocida del emulador.

**Node, Java, Rust o .NET no confían en el certificado.** No leen `AWS_CA_BUNDLE`: `eval "$(awsemu env --sdk node)"` (o `java`, `rust`, `dotnet`).

**Mi proceso tiene que hablar con el emulador y con AWS real a la vez.** `AWS_CA_BUNDLE` sustituye los certificados de confianza. Crea un bundle con los certificados del sistema más `ca.pem`, y regenéralo tras cada arranque. `NODE_EXTRA_CA_CERTS` es la excepción: añade en vez de sustituir.

**`lambda logs` no encuentra nada.** El emulador no envía la salida de las funciones a CloudWatch Logs. Usa `awsemu lambda invoke`, que muestra el log de esa invocación.

**`ParameterPatternMismatchException` en SSM.** Los nombres de parámetro no pueden empezar por `aws` ni `ssm` (tampoco `/awsapp/...`), igual que en AWS.

**Los recursos desaparecen.** Es por diseño: el emulador guarda todo en memoria. Al parar o reiniciar, se pierde. Usa un [seed](seeds.md): `awsemu start --seed seed.yaml`.

**`seed apply`: "exists with a different key".** La tabla ya existe con otra clave de partición u ordenación. `apply` nunca borra: usa `awsemu reset --seed seed.yaml` para partir de cero.

**`seed apply` termina con código 1.** Algún recurso falló (fila `failed` con el motivo); el resto se aplicó. Corrige y vuelve a aplicar: lo ya creado aparecerá como `unchanged`.

**El seed tiene errores.** `awsemu seed validate seed.yaml` muestra todos con su línea y campo, sin tocar el emulador.

**Windows: tras parar, quedan ficheros en `~/.aws/emulator/<puerto>/`.** `awsemu` intenta una parada limpia con Ctrl+Break y, si el emulador no la atiende, borra él mismo esos ficheros. `awsemu stop` en un puerto sin emulador también los limpia.

**Docker en Linux: los ficheros son de root.** Pasa si `~/.aws/emulator` no existía antes de montar el volumen. `awsemu` lo crea y ejecuta el contenedor con tu UID; si ya está mal, `sudo chown -R $USER ~/.aws/emulator`.

## Información para un issue

```bash
awsemu --version
awsemu doctor --plain
awsemu status --json
awsemu logs -n 100 --raw
```
