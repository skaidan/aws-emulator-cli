# Explorar el emulador

Herramientas para ver qué hay dentro del emulador, qué está pasando y hasta qué punto puedes fiarte de él para un servicio concreto.

| Quiero… | Comando |
| --- | --- |
| Una foto de lo que hay | `awsemu overview` |
| Navegar por servicios y recursos | `awsemu ui` |
| Ver cambios en directo mientras mi app trabaja | `awsemu watch` |
| Saber cómo de bien emula un servicio | `awsemu fidelity` |
| Ver un recurso concreto | `awsemu describe ARN` |
| Escribir menos | `awsemu completion` |

## `awsemu ui`: interfaz en la terminal

Una interfaz para navegar el emulador sin recordar comandos: a la izquierda los servicios con sus recursos, a la derecha el detalle del que selecciones.

```bash
pipx install 'aws-emulator-cli[ui] @ git+https://github.com/skaidan/aws-emulator-cli'
awsemu ui
```

| Tecla | Acción |
| --- | --- |
| Flechas, Intro | Moverse, abrir un servicio, ver un recurso |
| `r` | Refrescar |
| `w` | Activar o desactivar el refresco automático (cada 5 s) |
| `q` | Salir |

Qué muestra cada recurso:

| Servicio | Detalle |
| --- | --- |
| S3 | Los primeros 50 objetos (clave, tamaño, fecha) |
| SQS | Todos los atributos (mensajes visibles, en vuelo, DLQ…) |
| DynamoDB | Descripción de la tabla y los primeros 20 items en JSON normal |
| SNS | Atributos y suscripciones |
| Lambda | Configuración de la función |
| Secrets Manager | Metadatos y versiones; **nunca el valor** |
| SSM | El parámetro; los `SecureString` se muestran como `****` |
| Kinesis | Resumen del stream |
| EventBridge | El bus y sus reglas |
| Step Functions | La máquina de estados y sus últimas ejecuciones |
| CloudWatch Logs, IAM | El grupo de logs, el rol |

La interfaz usa [Textual](https://textual.textualize.io/), que se instala aparte con el extra `ui` para no añadir peso a quien no la use. Sin él, `awsemu ui` explica cómo instalarlo.

## `awsemu watch`: cambios en directo

Muestra lo que se crea, se borra o cambia mientras tu aplicación o tus tests trabajan. Por ejemplo:

```
$ awsemu watch -s sqs -s dynamodb
kind   name      count
queue  pedidos   0 message(s)
table  usuarios  2 item(s)
Watching dynamodb, sqs every 2s. Ctrl+C to stop.
10:42:03  + queue         pedidos-dlq
10:42:05  ~ queue         pedidos  0 → 3 message(s) (+3)
10:42:07  ~ table         usuarios  2 → 5 item(s) (+3)
10:42:09  - queue         temporal
```

- `+` creado, `-` borrado, `~` cambiado. Los buckets muestran su número de objetos (hasta 1000), las colas sus mensajes visibles y las tablas sus items (hasta 10 000).
- Vigila S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, Kinesis, EventBridge (reglas) y Step Functions. Con `-s` eliges cuáles; con `-i` el intervalo (por defecto 2 s); con `--once`, solo la foto inicial.
- Si un servicio falla en una consulta, se mantiene su último estado: un fallo puntual no aparece como "todo borrado".

**Por qué consulta en lugar de mostrar las llamadas:** el emulador no registra las peticiones que recibe. Lo comprobamos en CI: ni con `RUST_LOG=debug` aparece en su log nada más que el arranque, la parada y el *handshake* TLS. Así que `watch` compara el estado cada pocos segundos: verás el efecto de las llamadas, no las llamadas.

## `awsemu fidelity`: cuánto puedes fiarte de cada servicio

AWS publica con cada versión del emulador sus *fidelity scores*: cuántas pruebas de fidelidad pasa cada servicio (pruebas que comparan el comportamiento del emulador con el de AWS real: resultados, estado y errores exactos). `awsemu` las descarga **para la versión que tienes instalada** y te las enseña:

```bash
awsemu fidelity                       # todos los servicios
awsemu fidelity s3 sqs dynamodb       # los que usas
awsemu fidelity --sort score          # de peor a mejor
awsemu fidelity lambda --failures     # qué pruebas fallan y cómo
awsemu fidelity --release latest      # ¿mejora la última versión?
awsemu fidelity s3 --json
```

Salida de ejemplo (formato real; los números son ilustrativos, consulta los tuyos con el comando):

```
release          v1.0.385
emulator commit  813af480bf7f
scored           2026-11-14 18:34:58
your emulator    1.0.385

service   passed   score  multi-service
dynamodb  412/431  96%    37/41
s3        603/688  88%    55/63
```

- **passed / score:** pruebas que llaman solo a ese servicio, el mismo "k de n" que publica AWS. Las que combinan varios servicios aparecen aparte en **multi-service**.
- **`--failures`:** para cada prueba que falla, la operación, qué difiere (`status`, `errorCode`…), lo que esperaba AWS y lo que devolvió el emulador. Las pruebas están en el repositorio [aws-emulator-evaluation-suite](https://github.com/aws/aws-emulator-evaluation-suite), en `behavioral/<servicio>/`.
- La versión instalada sale de `aws-emulator -v`. Si no tienes el binario (por ejemplo, usas Docker), se usa la última release; con `--release` eliges otra.
- Los datos se descargan de las [releases del emulador en GitHub](https://github.com/aws/aws-emulator/releases) (`scores.json.gz`, ~1 MB) y se guardan en `~/.aws/emulator-cli/fidelity/`; `--refresh` los vuelve a bajar. Si GitHub limita las peticiones, define `GITHUB_TOKEN`.
- Compara puntuaciones solo entre releases medidas con la misma versión de las pruebas: AWS añade pruebas nuevas y el total crece.

Útil antes de empezar a usar un servicio con el emulador, y para saber si un fallo de tus tests puede deberse a una diferencia ya conocida.

## Autocompletado

```bash
# bash
echo 'eval "$(awsemu completion bash)"' >> ~/.bashrc
# zsh
echo 'eval "$(awsemu completion zsh)"' >> ~/.zshrc
# fish
awsemu completion fish > ~/.config/fish/completions/awsemu.fish
```

Completa comandos y opciones y, además, **los nombres de lo que hay en el emulador**:

```bash
awsemu sqs send <TAB>            # tus colas
awsemu s3 cat fotos/<TAB>        # carpetas y objetos del bucket
awsemu ddb scan <TAB>            # tus tablas
awsemu sns subscribe pedidos --to-sqs <TAB>
```

Funciona con buckets (y rutas dentro de ellos), colas, tablas, temas, funciones, secretos, parámetros, streams, máquinas de estados y reglas, y respeta `--port` y `awsemu.toml`. Si el emulador no está en marcha, simplemente no sugiere nombres. PowerShell no está soportado.
