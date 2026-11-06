# =============================================================================
# mini-harness（day05 交付形态 full profile）→ Harbor → K8s 的镜像定义
#
#   构建:  docker build -t 172.31.0.3:7777/dsh/mini-harness:day05 .
#   推送:  docker push 172.31.0.3:7777/dsh/mini-harness:day05
#   拉起:  kubectl apply -f deploy/k8s.yaml （清单同仓库）
#
# 零第三方依赖（Python 3.12 stdlib-only），slim 基础镜像即可；
# LLM 走 deploy/settings.yaml（ENV DSH_SETTINGS），指向集群可达的 Qwen 端点。
# =============================================================================
FROM python:3.12-slim

WORKDIR /app

# 只要运行所需：启动器 + 运行时内核 + 插件 + profile + 容器 settings
# （tests/docs/.data 由 .dockerignore 排除）
COPY run.py ./
COPY mini_cordis/ ./mini_cordis/
COPY plugins/ ./plugins/
COPY profiles/ ./profiles/
COPY deploy/settings.yaml ./deploy/settings.yaml

# 非 root 运行；数据目录预建并授权（K8s 里会被 emptyDir 挂走）
RUN useradd -m -u 10001 app \
    && mkdir -p /app/.data && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1 \
    DSH_SETTINGS=/app/deploy/settings.yaml

EXPOSE 8080

# serve 模式 = Web UI 常驻；host 必须 0.0.0.0（容器内 127.0.0.1 出不了 Pod）
CMD ["python3", "run.py", "-p", "full", "--mode", "serve", \
     "--set", "webui.host=0.0.0.0", "--set", "webui.port=8080"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/state',timeout=3)" || exit 1
