#!/usr/bin/env bash
# TermPaws 一键生产部署：下载 dockerfiles -> 构建 -> 启动
# 用法: curl -fsSL https://raw.githubusercontent.com/FLYLX/TermPaws/master/scripts/install.sh | bash
set -euo pipefail

DIR="${TERMPAWS_DIR:-termpaws-deploy}"
REPO="FLYLX/TermPaws"
BRANCH="master"

TARBALL_URLS=(
  "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
  "https://ghfast.top/https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
  "https://gh-proxy.com/https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
)

info() { printf '\033[1;34m[TermPaws]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[TermPaws] ERROR: %s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "需要 Docker: https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose 插件（Docker 20.10+ 自带）"

info "下载 dockerfiles..."
mkdir -p "$DIR"
TMP_TAR="$(mktemp /tmp/termpaws-XXXXXX.tar.gz)"
ok=0
for url in "${TARBALL_URLS[@]}"; do
  if curl -fsSL --connect-timeout 15 -o "$TMP_TAR" "$url"; then
    info "来源: $url"
    ok=1
    break
  fi
done
[ "$ok" = "1" ] || fail "所有下载源都不可达（github 及其镜像）"
tar xzf "$TMP_TAR" -C "$DIR" --strip-components=1 --wildcards "*/dockerfiles/*"
rm -f "$TMP_TAR"

cd "$DIR/dockerfiles"
info "构建并启动（首次约 3-8 分钟，之后秒级）..."
docker compose up -d termpaws daemon

info "部署完成!"
echo
echo "  管理后台:  http://<服务器IP>:28888   (首次打开创建管理员)"
echo "  daemon:    39999 端口"
echo "  daemon key:"
docker logs termpaws-daemon 2>/dev/null | grep -o 'API Key: [^ ]*' | tail -1 | sed 's/^/    /' || echo "    (稍后执行: docker logs termpaws-daemon | grep 'API Key')"
echo
echo "  数据目录:  $(pwd)/termpaws-data 和 $(pwd)/daemon-data"
echo "  常用命令:  docker compose ps | logs -f | down"
echo "  NapCat(可选): docker compose --profile napcat up -d"
