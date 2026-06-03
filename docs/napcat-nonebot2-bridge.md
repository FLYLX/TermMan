# NapCat / NoneBot2 Bridge

TermMan can run the robot bridge as a standalone NoneBot2 server. In Docker
Compose, the `robot-bridge` service listens on container port `8090`; the
backend exposes it through the same public backend port with the
`/robot-bridge` prefix.

For local development, configure NapCat reverse WebSocket with:

```text
ws://127.0.0.1:8000/robot-bridge/onebot/v11/ws
```

TermMan should use these container-internal URLs:

```env
ROBOT_BRIDGE_EMBEDDED=false
ROBOT_BACKEND_URL=http://backend:8000
ROBOT_BRIDGE_URL=http://robot-bridge:8090
```

In TermMan, create a robot with platform `OneBot V11 / NapCat` and set `QQ Self
ID` to the QQ account currently logged in to NapCat.
