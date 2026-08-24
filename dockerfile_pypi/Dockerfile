FROM python:3.12-slim

# Pin version; China users can swap the extra index for a local mirror
ARG TERMPAWS_VERSION=0.1.9

RUN pip install --no-cache-dir \
      --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      "termpaws==${TERMPAWS_VERSION}" "termpaws-daemon==${TERMPAWS_VERSION}"

EXPOSE 28888 39999 32000-32111

CMD ["termpaws", "run"]
