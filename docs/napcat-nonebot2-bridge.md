# NapCat / NoneBot2 Bridge

TermMan runs the robot bridge as a standalone NoneBot2 microservice from the
`robot/` subdirectory. In Docker Compose, the `robot-bridge` service listens on
container port `8090` for backend internal control APIs and OneBot V11 reverse
WebSocket connections.

NapCat should use OneBot V11 reverse WebSocket. The `robot-bridge` service is
the WebSocket server, and NapCat connects to it as the client.

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

TermMan should use these container-internal URLs:

```env
ROBOT_BRIDGE_EMBEDDED=false
ROBOT_BACKEND_URL=http://backend:8000
ROBOT_BRIDGE_URL=http://robot-bridge:8090
ROBOT_BRIDGE_HOST_PORT=8091
ROBOT_BRIDGE_SHARED_SECRET=changethis
```

The backend calls only `ROBOT_BRIDGE_URL`. It does not try alternate bridge
addresses at runtime.

Use `ROBOT_BRIDGE_URL=http://robot-bridge:8090` when the backend runs in the
Docker Compose network. If the backend runs directly on the host while
`robot-bridge` runs in Docker, expose the bridge with `ROBOT_BRIDGE_HOST_PORT`
and set `ROBOT_BRIDGE_URL` manually, for example:

```env
ROBOT_BRIDGE_URL=http://127.0.0.1:8091
ROBOT_BRIDGE_HOST_PORT=8091
```

Change both values together when the host port `8091` is already occupied.

`robot/.env` also has `ROBOT_BRIDGE_URL`. Set that value to the address NapCat
can reach. The Robot debug page shows the final reverse WebSocket endpoint:

```text
ws://<termman-host>:<bridge-port>/onebot/v11/ws
```

In TermMan, create a robot with platform `OneBot V11 / NapCat` and set:

- `QQ Self ID`: the QQ account currently logged in to NapCat.
- `Access Token` and `Secret`: optional, matching your NapCat settings when
  enabled.

After saving the robot, reload the bridge. Configure NapCat's OneBot V11
reverse WebSocket URL with the endpoint shown on the Robot page. The debug
page should show the NapCat socket as connected after NapCat connects.

The bridge reload endpoint restarts the `robot-bridge` process. Docker must be
allowed to restart the container after that exit; the local Compose override
keeps `robot-bridge` on `restart: unless-stopped` for this reason.
