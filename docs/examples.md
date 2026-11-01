# Usage examples

Start the application using the [quick start](../README.md#quick-start).

## Browser investigation

The initial **Demo** workspace uses fictional hosts and local fixtures. It needs no backend, Docker connection, or model.

1. Choose **Crash loop** in the scenario selector.
2. Read the diagnostic conclusion and compare it with container state and startup logs.
3. Choose **Container evidence** or **Log evidence** to inspect the referenced observation.
4. Choose **Review stop** to inspect the exact target and operation before confirmation.

![English Demo confirmation showing the host, exact container, prepared action, and separate confirmation](screenshots/action-confirmation.jpg)

*This is a simulated action; confirming it in Demo never changes Docker resources.*

Other scenarios cover OOM, failed dependencies, truncated logs, an unconfirmed exit, and a running container with zero CPU.
Expand **Test error states** to explore connection, streaming, inventory, and action-result failures.

For your own Docker environment, choose **Connect API**, enter the backend token, and select a configured host.
Select a container to read its state, metrics, and logs without using the model. Choose **Diagnose** or ask a question
to start model-assisted investigation. Follow-ups stay scoped to the same host.

Ask "What happened?" without selecting a resource to get a bounded host overview across projects and containers without
an observed group. Review collection limits and missing logs, then choose **Investigate container** or an observed group
for a separate, focused investigation. A question naming an ambiguous resource still asks which target you mean.

Restart and stop require separate confirmation of a server-prepared action. After execution, refresh the container
overview for current observations; earlier diagnostic cards retain their original evidence.

## Docker example

This example creates a worker that exits on its first start and runs after a confirmed restart. Its retry marker lives
in a dedicated demo volume. Start the backend with access to the same Docker environment, configure a model, and run
these commands from the repository root:

```sh
docker compose -f examples/compose.yaml up -d
uv run --project backend python examples/demo.py diagnose
```

The Compose project is `docksight-demo`. Use a new project name if it already exists, and name the same project in the
question; reusing its volume skips the first-start failure. For example:

```sh
docker compose -p docksight-example -f examples/compose.yaml up -d
uv run --project backend python examples/demo.py diagnose "Why did the worker in Compose project docksight-example exit?"
```

Use the same `-p docksight-example` option for subsequent Compose inspection and cleanup commands.
For a backend on another port, put `--url http://127.0.0.1:18080` before `diagnose`, `execute`, or `state`.

Review the diagnosis, evidence, and `actions` in the returned card. Copy a prepared restart action ID and confirm it:

```sh
uv run --project backend python examples/demo.py execute ACTION_ID --confirm --key review-restart-1
uv run --project backend python examples/demo.py state ACTION_ID
docker compose -f examples/compose.yaml ps -a
```

Keep the same idempotency key for that execution. If a response is lost, read the action state before considering a
repeat request; never automatically retry a Docker mutation. An `indeterminate` result requires checking Docker directly.
The [API reference](api.md#actions) describes expiry, execution outcomes, and revalidation.

Reset only this demo stack and its volume with:

```sh
docker compose -f examples/compose.yaml down -v
```

This removes the example's retry marker too. Keep the project name consistent and remove only the example you created.

## HTTP integration

Open [interactive API documentation](http://127.0.0.1:8000/docs) and enter the bearer token through **Authorize**.
Use the [HTTP API reference](api.md) for container reads, POST-based diagnostic SSE streams, and action requests.
