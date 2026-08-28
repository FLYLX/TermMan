FROM python:3.12-slim

# TermPaws daemon (terminal agent node). Config: ./daemon.json next to cwd.
ARG TERMPAWS_VERSION=

RUN pip install --no-cache-dir \
      --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      "termpaws-daemon${TERMPAWS_VERSION:+==${TERMPAWS_VERSION}}"

WORKDIR /opt/termpaws-daemon
EXPOSE 39999
# 游戏服务器端口范围（Minecraft 等，由 daemon 拉起的进程绑定）
EXPOSE 25565-43906

CMD ["termpaws-daemon"]
