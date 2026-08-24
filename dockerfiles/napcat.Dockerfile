# NapCatQQ — QQ protocol connector for TermPaws robot bridge.
# Thin wrapper over the official NapCat docker image (bundles QQNT runtime).
# After starting, open http://localhost:6099 and configure a reverse WebSocket
# pointing to ws://<termpaws-host>:28888/robot-bridge/onebot/v11/ws
FROM mlikiowa/napcat-docker:latest

EXPOSE 6099
