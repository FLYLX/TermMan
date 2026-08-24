FROM python:3.12-slim

# TermPaws all-in-one: backend + frontend (single port) + daemon.
ARG TERMPAWS_VERSION=0.1.9

RUN pip install --no-cache-dir \
      --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      "termpaws==${TERMPAWS_VERSION}" "termpaws-daemon==${TERMPAWS_VERSION}"

EXPOSE 28888 39999 32000-32111

CMD ["termpaws", "run"]
