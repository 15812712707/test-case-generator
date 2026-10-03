"""gunicorn 生产配置：gunicorn -c gunicorn.conf.py run:app"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
worker_class = "gthread"
threads = int(os.environ.get("WEB_THREADS", "4"))
# 大模型调用耗时较长，超时需放宽（说明书 4.1：生成时间受模型服务影响）
timeout = int(os.environ.get("WEB_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"


def when_ready(server):  # noqa: ARG001
    """服务就绪时确保初始账号存在。

    本地 `python run.py` 会在 __main__ 里建表并创建初始账号，但
    gunicorn / 容器 / Render 这类部署不会执行 __main__，缺少这一步
    会导致云端首次部署后没有任何账号可以登录。
    放在 when_ready（master 进程，单次执行）可避免多 worker 并发写入冲突。
    """
    try:
        from run import app, ensure_seed

        ensure_seed(app)
    except Exception as exc:  # 建账号失败不应阻断服务启动
        print(f"[warn] 初始账号检查失败：{exc}")
