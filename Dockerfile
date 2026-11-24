# ITstudy 容器镜像（Linux）
# 构建上下文 = 项目根目录：docker build -t itstudy:latest .
# 运行见 docker-compose.yml；部署说明见 docs/容器部署.md
# 基础镜像钉到 bookworm：下面的 PGDG 源按 bookworm-pgdg 配置，换发行版会装错包
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai
# 时区：应用全程用本地 naive 时间（datetime.now()）判定签到窗口、课表节次
# 自动切班、作业截止。镜像默认 UTC 会让这些逻辑整体偏 8 小时（09:00 登录
# 被当成 01:00 → 不在签到窗口）。TZ 需要 tzdata 才生效，见下方 apt 行；
# 其它时区部署在 compose 里覆盖 TZ 即可

WORKDIR /app

# 先装依赖（层缓存友好）；psycopg2-binary 自带 libpq 无需系统包。
# constraints.txt 钉死与 NSIS 离线包（pack/wheels）相同的版本，防止在线解析
# 到未经验证的新版本（flask-caching 2.5 曾因此装机即崩）
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# pg_dump：管理端备份页按 shutil.which('pg_dump') 探测，slim 镜像默认无
# postgresql-client → 备份页恒 503。Debian bookworm 自带的是 PG15 客户端，
# 而 compose 服务端是 PG16；pg_dump 15 连 16 会报 "server version mismatch"
# 直接中止（备份必失败）。故经 PGDG 源安装 postgresql-client-16，与
# docker-compose.yml 的 postgres:16-alpine 对齐。
# tzdata：TZ 环境变量的时区数据（slim 镜像不保证自带）
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg tzdata; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-16; \
    apt-get purge -y --auto-remove curl gnupg; \
    rm -rf /var/lib/apt/lists/*

# 应用代码（.dockerignore 排除 venv/data/logs/instance 等运行期目录）
COPY app ./app
COPY static ./static
COPY templates ./templates
COPY migrations ./migrations
COPY frontend ./frontend
COPY tools ./tools
COPY docs ./docs
COPY entrypoint.py .

# 运行期目录（挂卷持久化：instance 密钥 / 上传文件 / 缓存 / 日志）。
# homework/submissions/chunks 是作业附件/学生提交/分块临时区，question_img
# 是题目图片——四个目录在 .dockerignore 中被排除出镜像且应用启动时不会
# 全部重建（homework 等惰性创建），必须在此建目录并声明 VOLUME，
# 否则数据写入容器可写层、容器替换/升级即全部丢失（匿名卷兜底）。
# 非 root 运行：Waitress 监听 8000（>1024）无需特权；应用或同源第三方课件
# 被攻破时不再直接获得容器 root。UID/GID 固定为 10001，便于存量卷迁移
# （docker compose down 后 `chown -R 10001:10001 <卷挂载点>`，见容器部署文档）。
RUN groupadd --system --gid 10001 itstudy \
    && useradd --system --uid 10001 --gid itstudy --home-dir /app \
       --shell /usr/sbin/nologin itstudy \
    && mkdir -p instance data logs static/uploads static/question_img \
                static/homework static/submissions static/chunks \
    && chown -R itstudy:itstudy /app
USER itstudy
VOLUME ["/app/instance", "/app/static/uploads", "/app/static/homework", \
        "/app/static/submissions", "/app/static/chunks", \
        "/app/static/question_img", "/app/data", "/app/logs"]

EXPOSE 8000
# 健康检查与应用监听端口保持一致：PORT 可覆盖（entrypoint.py 读取同一变量），
# 硬编码 8000 时自定义 PORT 的部署会恒 unhealthy（compose --wait 卡死）。
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import os,sys,urllib.request;port=os.environ.get('PORT','8000');sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+port+'/api/healthz',timeout=4).status==200 else 1)"

CMD ["python", "entrypoint.py"]
