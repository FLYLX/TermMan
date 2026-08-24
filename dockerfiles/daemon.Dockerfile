FROM python:3.12-slim

# TermPaws daemon (terminal agent node). Config: ./daemon.json next to cwd.
ARG TERMPAWS_VERSION=0.1.9

RUN pip install --no-cache-dir \
      --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      "termpaws-daemon==${TERMPAWS_VERSION}"

WORKDIR /opt/termpaws-daemon
EXPOSE 39999

CMD ["termpaws-daemon"]
