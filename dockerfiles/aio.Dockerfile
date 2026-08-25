FROM python:3.12-slim

# TermPaws all-in-one: backend + frontend (single port, embedded robot bridge).
ARG TERMPAWS_VERSION=0.2.7

RUN pip install --no-cache-dir \
      --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      "termpaws==${TERMPAWS_VERSION}"

EXPOSE 28888 32000-32111

CMD ["termpaws", "run"]
