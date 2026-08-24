FROM node:20-slim

# NapCatQQ — QQ protocol connector for TermPaws robot bridge.
# After starting, configure a reverse WebSocket in the NapCat WebUI (default :6099)
# pointing to ws://<termpaws-host>:28888/robot-bridge/onebot/v11/ws
ARG NAPCAT_VERSION=4.7.6

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fSL -o /tmp/napcat.zip \
      "https://github.com/NapNeko/NapCatQQ/releases/download/v${NAPCAT_VERSION}/NapCat.Shell.zip" \
 && unzip /tmp/napcat.zip -d /opt/napcat \
 && rm /tmp/napcat.zip

WORKDIR /opt/napcat

EXPOSE 6099

CMD ["node", "napcat.mjs"]
