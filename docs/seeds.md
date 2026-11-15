# Seeds: datos de partida reproducibles

El emulador guarda todo en memoria: al pararlo o reiniciarlo, se pierde. Un **seed** es un fichero YAML que describe lo que quieres que haya dentro (buckets con objetos, colas, tablas con items, temas con suscripciones, secretos y parámetros) para recrearlo con un comando.

```bash
awsemu seed apply seed.yaml          # aplicar a un emulador que ya está en marcha
awsemu start --seed seed.yaml        # arrancar y aplicar
awsemu reset --seed seed.yaml        # vaciar (reiniciar) y aplicar
awsemu seed validate seed.yaml       # comprobar el fichero sin tocar el emulador
awsemu seed export -o seed.yaml      # guardar lo que hay ahora como seed
```

Hay un ejemplo completo en [`examples/seed.yaml`](../examples/seed.yaml).

## Formato

```yaml
version: 1          # opcional; esta versión de awsemu lee la 1

buckets:
  - name: fotos
    objects:
      - {key: hola.txt, content: "hola"}           # texto
      - {key: config.json, json: {debug: true}}    # JSON (se guarda formateado)
      - {key: web/, from: ./site}                  # una carpeta local entera
      - {key: logo.png, from: ./img/logo.png}      # un fichero local

queues:
  - name: trabajos-dlq
  - name: trabajos
    dlq: trabajos-dlq        # cola de mensajes fallidos
    max_receive: 3           # recepciones antes de ir a la DLQ (por defecto 5)
    visibility_timeout: 30
    delay: 0
  - name: facturas.fifo
    fifo: true
    content_dedup: true

tables:
  - name: usuarios
    pk: id                   # clave de partición: NAME o NAME:S|N|B (S por defecto)
    sk: creado:N             # clave de ordenación (opcional)
    items:
      - {id: u1, creado: 1, nombre: Ana, tags: [admin]}
    items_from: ./usuarios.json   # un objeto o una lista, JSON o YAML (opcional)

topics:
  - name: pedidos
    fifo: false
    subscriptions:
      - sqs: trabajos              # crea la suscripción y la política de la cola
        raw: true                  # sin el sobre JSON de SNS
        filter: {tipo: [alta]}     # política de filtro
      - lambda: procesar-pedido    # añade el permiso de invocación

secrets:
  - name: db/password
    value: s3cr3t
  - name: db/config
    value: {host: db, port: 5432}  # mapas y listas se guardan como JSON
    description: conexión local

parameters:
  - {name: /app/host, value: localhost}
  - {name: /app/key, value: abc, type: SecureString}
  - {name: /app/hosts, value: [a, b, c]}     # una lista es un StringList
```

Todas las secciones son opcionales. Las rutas (`from`, `items_from`) son relativas al fichero del seed.

### Campos

| Sección | Campos | Obligatorios |
| --- | --- | --- |
| `buckets` | `name`, `objects` | `name` |
| `buckets[].objects` | `key` y uno de `content`, `json` o `from` | `key` + uno de los tres |
| `queues` | `name`, `fifo`, `content_dedup`, `visibility_timeout`, `delay`, `dlq`, `max_receive` | `name` |
| `tables` | `name`, `pk`, `sk`, `items`, `items_from` | `name`, `pk` |
| `topics` | `name`, `fifo`, `subscriptions` | `name` |
| `topics[].subscriptions` | uno de `sqs` o `lambda`, `raw`, `filter` | `sqs` o `lambda` |
| `secrets` | `name`, `value`, `description` | `name`, `value` |
| `parameters` | `name`, `value`, `type` (`String`, `SecureString`, `StringList`), `description` | `name`, `value` |

## Validación

`awsemu seed validate`, `seed apply`, `start --seed` y `reset --seed` revisan el fichero entero **antes** de tocar el emulador. Los errores indican la línea y el campo:

```
✗ seed.yaml:4  queues[0].visibilty_timeout: unknown field (did you mean 'visibility_timeout'?)
✗ seed.yaml:5  queues[1].name: duplicate name 'trabajos' (also at queues[0])
✗ seed.yaml:9  tables[0].items[0].creado: must be a number (the key type is N)
✗ seed.yaml:14  parameters[0].name: parameter names can't start with 'aws' or 'ssm' (AWS rule)
```

Se comprueba, entre otras cosas: campos desconocidos (con sugerencia), tipos, nombres duplicados, que los items tengan las claves de la tabla con el tipo correcto, que los ficheros de `from` e `items_from` existan, que las colas FIFO acaben en `.fifo`, que una cola no sea su propia DLQ y la regla de AWS sobre nombres de parámetros.

Si una `dlq` o una suscripción `sqs` apunta a una cola que no está en el seed, es un aviso, no un error: puede existir ya en el emulador.

Con errores, `validate`, `apply`, `start --seed` y `reset --seed` terminan con código 2 sin haber hecho nada (`reset` no llega a parar el emulador).

## Qué hace `apply`

`apply` se puede repetir: crea lo que falta, actualiza lo que difiere y deja lo demás como está. Al final muestra una tabla con el resultado de cada recurso:

```
kind       name           result     detail
bucket     fotos          created    3 object(s) written
queue      trabajos-dlq   created
queue      trabajos       created    dlq → trabajos-dlq
table      usuarios       created    2 item(s) written
topic      pedidos        created    → sqs:trabajos
secret     db/password    unchanged
parameter  /app/host      updated
✓ seed applied in 1.4s (5 created, 1 unchanged, 1 updated)
```

| Recurso | Si no existe | Si ya existe |
| --- | --- | --- |
| Bucket | Lo crea y sube los objetos | Vuelve a subir los objetos del seed (*updated*); no borra otros objetos |
| Cola | La crea | Ajusta los atributos que difieran; `fifo` no se puede cambiar |
| DLQ | Configura la política de redrive | La cambia si difiere |
| Tabla | La crea (bajo demanda) y escribe los items | Escribe los items (los del seed sobrescriben a los que tengan la misma clave); **error** si la clave de la tabla es distinta |
| Tema | Lo crea | Lo deja |
| Suscripción | La crea, con la política de la cola o el permiso de Lambda | Ajusta `raw` y `filter` si difieren |
| Secreto | Lo crea | Guarda una versión nueva solo si el valor cambió |
| Parámetro | Lo crea | Lo sobrescribe solo si el valor o el tipo cambiaron |

`apply` **nunca borra** nada. Para partir de cero, usa `awsemu reset --seed seed.yaml`.

Si un recurso falla, `apply` sigue con los demás, lo marca como `failed` con el motivo y termina con código 1.

El orden es: buckets, colas, tablas, temas, secretos y parámetros (las colas antes que los temas, para poder suscribirlas). Las suscripciones a Lambda necesitan que la función exista: despliégala antes con `awsemu lambda deploy`.

## Exportar

```bash
awsemu seed export                          # a la salida estándar
awsemu seed export -o seed.yaml
awsemu seed export -o seed.yaml --objects-dir seed-objects   # guarda también binarios y objetos grandes
awsemu seed export --no-secrets             # sin secretos ni parámetros SecureString
awsemu seed export -s queues -s tables      # solo algunas secciones
```

Útil para montar un escenario a mano (o con tu aplicación) y guardarlo para los tests.

- Los objetos de S3 de texto de hasta 64 KiB se guardan dentro del seed (`content`). Los binarios o más grandes se guardan en `--objects-dir` y se referencian con `from`; sin esa opción se omiten con un aviso.
- Los secretos y los parámetros `SecureString` se exportan **en claro**, y `awsemu` avisa al escribir el fichero. Usa `--no-secrets` si el seed va a un repositorio.
- Solo se exportan las suscripciones a SQS y Lambda.
- Las funciones Lambda, reglas de EventBridge, streams de Kinesis y máquinas de Step Functions no forman parte del formato (todavía).

El fichero exportado se puede aplicar tal cual; en CI se comprueba que exportar, reiniciar y aplicar deja el emulador como estaba.

## En tests y CI

```bash
awsemu start --seed tests/seed.yaml --idle-timeout 900
awsemu exec -- pytest tests/integration
awsemu reset --seed tests/seed.yaml          # estado limpio entre suites
awsemu exec -- pytest tests/otra-suite
awsemu stop
```

Más en [Tests y CI](testing.md).
