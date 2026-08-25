FROM python:3.12-slim

# TermPaws backend only (API + embedded robot bridge, no web UI).
ARG TERMPAWS_VERSION=

RUN pip install --no-cache-dir \
      --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      "termpaws-backend${TERMPAWS_VERSION:+==${TERMPAWS_VERSION}}"

EXPOSE 28888

CMD ["termpaws", "run"]
