FROM python:3.12-slim

# TermPaws web frontend only (static UI, expects a reachable backend API).
ARG TERMPAWS_VERSION=

RUN pip install --no-cache-dir \
      --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      "termpaws-frontend${TERMPAWS_VERSION:+==${TERMPAWS_VERSION}}" \
 && mkdir -p /srv \
 && cp -r /usr/local/lib/python3.12/site-packages/termpaws_frontend/dist /srv/dist

EXPOSE 27777

CMD ["python", "-m", "http.server", "27777", "--directory", "/srv/dist"]
