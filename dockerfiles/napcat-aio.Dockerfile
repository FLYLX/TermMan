FROM node:20-slim

# TermPaws backend+frontend + NapCatQQ in one image (two processes).
# NapCat reverse WS -> ws://127.0.0.1:28888/robot-bridge/onebot/v11/ws (same container).
ARG TERMPAWS_VERSION=0.1.9
ARG NAPCAT_VERSION=4.7.6

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip python3-venv curl unzip ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir --break-system-packages \
      --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      "termpaws==${TERMPAWS_VERSION}" \
 && curl -fSL -o /tmp/napcat.zip \
      "https://github.com/NapNeko/NapCatQQ/releases/download/v${NAPCAT_VERSION}/NapCat.Shell.zip" \
 && unzip /tmp/napcat.zip -d /opt/napcat \
 && rm /tmp/napcat.zip

WORKDIR /opt/napcat

EXPOSE 28888 6099 32000-32111

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
