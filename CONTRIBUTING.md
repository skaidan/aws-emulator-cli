# Contribuir

## Entorno

```bash
git clone https://github.com/skaidan/aws-emulator-cli && cd aws-emulator-cli
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,ui]"
pytest
```

`[dev]` instala pytest y `cryptography` (la usa el emulador falso para generar su certificado); `[ui]` instala Textual para probar `awsemu ui` (sin él, esos tests se saltan).

## Tests

| Tipo | Dónde | Cómo se ejecuta |
| --- | --- | --- |
| Unitarios | `tests/test_units.py`, `tests/test_seed.py`, `tests/test_project.py` | `pytest` |
| Plugin de pytest | `tests/test_pytest_plugin.py` (sesiones reales con `pytester`) | `pytest` |
| Exploración | `tests/test_fidelity.py`, `tests/test_watch.py`, `tests/test_completion.py`, `tests/test_browse_ui.py` (con Textual: pilot de la app) | `pytest` |
| Ciclo de vida con el emulador falso | `tests/test_lifecycle.py` | `pytest` (Linux, macOS y Windows) |
| Servicios con cliente simulado | `tests/test_services.py`, `tests/test_sns_lambda.py`, `tests/test_more_services.py` | `pytest` |
| Contra el emulador real | `tests/test_real.py` | `AWSEMU_REAL_TESTS=1 pytest -m real -v` |

Los tests reales necesitan el binario `aws-emulator` en el `PATH` (o `AWSEMU_BINARY`) y boto3. En la CI los ejecuta el job `real-emulator`, que instala el `.deb` oficial y verifica su firma.

Jobs de la CI: `tests` (Linux, macOS y Windows; Python 3.10 y 3.13), `real-emulator`, `docker` (modo Docker y `compose` con el emulador real) y `action` (la GitHub Action de `action.yml`).

No pongas `[tool.awsemu]` en el `pyproject.toml` de este repositorio: los tests lo encontrarían como configuración de proyecto.

Cada test corre con un `HOME` temporal propio, así que nunca toca tu `~/.aws`.

### El emulador falso

`tests/fake_emulator.py` imita lo que `awsemu` usa del binario real. Si descubres que el emulador real se comporta distinto (como pasó con el formato del log), cambia primero el falso para que lo reproduzca, añade un test que falle, y luego arregla `awsemu`.

Variables para provocar casos raros: `FAKE_EMULATOR_CRASH=1` (sale con código 1) y `FAKE_EMULATOR_IGNORE_STOP=1` (ignora la parada limpia).

## Añadir un servicio

1. Crea `src/awsemu/commands/<servicio>.py` con un `click.group()`. Copia la estructura de `sns.py` o `sqs.py`:
   - obtén el cliente con `client("<servicio>", c.port)`;
   - decora cada comando con `@pass_ctx` y `@handle_errors`;
   - usa `ui.table`, `ui.kv`, `ui.success` y `ui.print_json` para la salida;
   - ofrece `--json` en los listados y `--yes` en lo que borre;
   - para roles, políticas de cola, permisos de Lambda o errores esperados (`is_error(exc, "ResourceNotFound")`), usa `commands/_common.py`.
2. Regístralo en `cli.py` (`cli.add_command(...)`).
3. Si tiene recursos que listar, añádelo a `SERVICES` en `commands/overview.py`.
4. Tests con `FakeClient` (ver `tests/test_services.py`) y, si puedes, un test en `tests/test_real.py`.
5. Si tiene sentido en un seed, añade la sección en `seed.py` (campos y validación), su `_apply_*` y su exportación en `commands/seed.py`, y amplía `examples/seed.yaml`.
6. Documenta: sección en `docs/services.md` (y `docs/seeds.md` si aplica), línea en el README, y regenera la referencia (abajo).

## Documentación

- `docs/reference.md` se genera desde la ayuda de los comandos. Después de cambiar un comando u opción:

  ```bash
  python scripts/gen_reference.py
  ```

  La CI falla si está desactualizada (`python scripts/gen_reference.py --check`).
- Las guías (`docs/*.md`), el README, el ROADMAP y el CHANGELOG se escriben a mano, en español.
- La ayuda de los comandos (`--help`) está en inglés.

## Publicar una versión

1. Mueve las entradas de `## Unreleased` de `CHANGELOG.md` a `## X.Y.Z — AAAA-MM-DD`.
2. Sube la versión en `pyproject.toml` y en `src/awsemu/__init__.py`.
3. Actualiza el ROADMAP.
4. Haz push a `main`. Cuando la CI pasa (incluidos los tests contra el emulador real), el workflow `Release` crea el tag `vX.Y.Z` y la release de GitHub con el wheel y el sdist, usando la sección del CHANGELOG como notas. Si la CI falla, no se publica nada.

## Estilo

- Mensajes de error con una pista concreta (`RuntimeErrorWithHint(mensaje, pista)`).
- Nada de llamadas a AWS real: los clientes se crean siempre contra el puerto del emulador.
- No escribir en `~/.aws/emulator/`, que es del emulador.
