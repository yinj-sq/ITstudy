# ITstudy 容器部署入口（Linux）
# 职责：等待 PostgreSQL 就绪 → 启动 Waitress。
# 数据库建库/建表/迁移由 create_app() 启动流程自动完成（幂等）。
import os
import sys
import time

import psycopg2


def wait_db(max_wait=120):
    dsn = dict(
        host=os.environ.get('DB_HOST', 'db'),
        port=os.environ.get('DB_PORT', '5432'),
        user=os.environ.get('DB_USER', 'postgres'),
        password=os.environ.get('DB_PASS', '@@'),
        dbname=os.environ.get('DB_NAME', 'itstudy'),
    )
    # 先连 postgres 库建业务库（create_app 也会兜底，这里提前探活）
    dsn['dbname'] = 'postgres'
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            psycopg2.connect(**dsn).close()
            print('[entrypoint] PostgreSQL 已就绪', flush=True)
            return
        except Exception as e:
            print(f'[entrypoint] 等待数据库: {e}', flush=True)
            time.sleep(2)
    print('[entrypoint] 数据库等待超时', flush=True)
    sys.exit(1)


if __name__ == '__main__':
    wait_db()
    from app import create_app
    app = create_app()
    from waitress import serve
    port = int(os.environ.get('PORT', '8000'))
    print(f'[entrypoint] Serving on 0.0.0.0:{port}', flush=True)
    serve(app, host='0.0.0.0', port=port,
          threads=app.config['WAITRESS_THREADS'],
          connection_limit=400, channel_timeout=120)