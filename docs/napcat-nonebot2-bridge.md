# QQ Robot Server / OneBot V11

TermMan runs the QQ robot server as a standalone NoneBot2 microservice from the
`robot/` subdirectory. The internal Docker Compose service name is still
`robot-bridge` for compatibility, but its public role is a robot server for QQ
connector clients.

The server exposes OneBot V11 reverse WebSocket at:

```text
ws://<termman-host>:<robot-server-port>/onebot/v11/ws
```

NapCat, Lagrange, SonwLuma, and compatible OneBot V11 QQ connector clients
should connect to this endpoint as clients. TermMan receives QQ messages from
that socket and routes them into bound terminal agents.

Environment is split by service:

- `.env` controls the backend, frontend, daemon, robot server, and Docker Compose stack.
- `robot/.env` controls only standalone robot-server local development.

Run this after checkout to create missing environment files:

```sh
sh scripts/init-env.sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/init-env.ps1
```

The init script syncs `ROBOT_BRIDGE_SHARED_SECRET` from the root `.env` into
`robot/.env` so the backend and robot server use the same internal token.

For Docker Compose, keep the backend-to-server URL on the internal network:

```env
ROBOT_BRIDGE_EMBEDDED=false
ROBOT_BACKEND_URL=http://backend:8000
ROBOT_BRIDGE_URL=http://robot-bridge:7000
ROBOT_BRIDGE_HOST_PORT=33333
ROBOT_BRIDGE_SHARED_SECRET=changethis
```

The backend calls only `ROBOT_BRIDGE_URL`. It does not try alternate robot
server addresses at runtime.

If the QQ connector runs outside Docker, expose the robot server with
`ROBOT_BRIDGE_HOST_PORT` and configure the connector with the host URL, for
example:

```text
ws://203.135.104.22:33333/onebot/v11/ws
```

In TermMan, create a robot server with platform `OneBot V11 / QQ Connectors`
and set:

- `QQ Self ID`: the QQ account currently logged in to the connector client.
- `Access Token` and `Secret`: optional, matching the connector settings when enabled.

After saving the robot server, reload the server. Configure NapCat, Lagrange,
SonwLuma, or another compatible client with the endpoint shown on the robot
server page. The debug page should show the connector socket as connected after
it connects.

The reload endpoint restarts the internal `robot-bridge` process. Docker must
be allowed to restart the container after that exit; the local Compose override
keeps `robot-bridge` on `restart: unless-stopped` for this reason.