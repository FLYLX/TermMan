# NapCat / NoneBot2 Bridge

TermMan runs the robot bridge as a standalone NoneBot2 server from the `robot/`
subdirectory. In Docker Compose, the `robot-bridge` service listens on
container port `8090`; the backend exposes it through the same public backend
port with the `/robot-bridge` prefix.

Environment is split by service:

- `.env` controls the backend, frontend, daemon, and Docker Compose stack.
- `robot/.env` controls only the standalone `robot-bridge` microservice.

Run this after checkout to create missing environment files:

```sh
sh scripts/init-env.sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/init-env.ps1
```

When `robot/.env` is first created, the script copies the bridge token from
the root `.env` `ROBOT_BRIDGE_SHARED_SECRET`, or from `SECRET_KEY` when no
explicit bridge token exists. The backend token and `robot/.env`
`ROBOT_BRIDGE_SHARED_SECRET` must match.

For local development, configure NapCat reverse WebSocket with:

```text
ws://127.0.0.1:8000/robot-bridge/r/<route_key>/onebot/v11/ws
```

TermMan should use these container-internal URLs:

```env
ROBOT_BRIDGE_EMBEDDED=false
ROBOT_BACKEND_URL=http://backend:8000
ROBOT_BRIDGE_URL=http://robot-bridge:8090
ROBOT_BRIDGE_PUBLIC_BASE_URL=http://127.0.0.1:8000/robot-bridge
ROBOT_BRIDGE_SHARED_SECRET=changethis
```

`ROBOT_BRIDGE_URL` is the backend-to-bridge internal service URL. NapCat and
browser-facing guides use `ROBOT_BRIDGE_PUBLIC_BASE_URL` plus the robot route
key, for example `/r/office-qq/onebot/v11/ws`.

In TermMan, create a robot with platform `OneBot V11 / NapCat` and set `QQ Self
ID` to the QQ account currently logged in to NapCat.
