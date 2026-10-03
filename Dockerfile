# 基于大语言模型的软件测试用例自动生成与管理系统
# 多阶段构建：先装依赖，再拷贝源码，镜像更小
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖，利用镜像层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# 再拷贝源码
COPY . .

# 数据库与会话密钥存放目录（生产环境请挂载卷以持久化数据）
RUN mkdir -p /app/instance
VOLUME ["/app/instance"]

# 非 root 运行
RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=8000 \
    HOST=0.0.0.0 \
    DATABASE_URL=sqlite:////app/instance/app.db

EXPOSE 8000

# 首次启动自动建表并创建初始账号
CMD ["sh", "-c", "python -c \"from run import app, ensure_seed; ensure_seed(app)\" && gunicorn -w 2 -k gthread --threads 4 -b 0.0.0.0:${PORT} --timeout 120 run:app"]
