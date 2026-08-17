FROM python:3.12-slim

# CPU 版 torch（服务器无 GPU 时省 ~2GB），国内可换 tuna 镜像
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir \
      --index-url https://test.pypi.org/simple \
      --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      termpaws termpaws-daemon

EXPOSE 8000 9000

CMD ["termpaws", "run"]
