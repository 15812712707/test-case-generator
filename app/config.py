"""应用配置。所有敏感信息通过环境变量 / .env 注入，不写入代码。"""
import os
import secrets

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv 为可选项
    def load_dotenv(*_args, **_kwargs):
        return False

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# 示例配置中占位用的弱密钥，出现时视为"未配置"
_PLACEHOLDER_SECRETS = {
    "", "please-change-this-to-a-random-string",
    "dev-secret-key-change-in-production", "changeme", "secret",
}


def load_secret_key() -> str:
    """获取会话密钥。

    优先级：环境变量（且不是占位值）> instance/secret_key 文件 > 新生成并落盘。
    这样既不在代码里硬编码密钥，重启后已登录会话也不会失效。
    """
    env_key = (os.environ.get("SECRET_KEY") or "").strip()
    if env_key and env_key.lower() not in _PLACEHOLDER_SECRETS and len(env_key) >= 16:
        return env_key

    key_file = os.path.join(BASE_DIR, "instance", "secret_key")
    try:
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        if os.path.exists(key_file):
            with open(key_file, encoding="utf-8") as fh:
                saved = fh.read().strip()
            if saved:
                return saved
        key = secrets.token_urlsafe(48)
        with open(key_file, "w", encoding="utf-8") as fh:
            fh.write(key)
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        return key
    except OSError:
        # 只读文件系统等极端情况：进程内随机密钥，会话在重启后失效
        return secrets.token_urlsafe(48)


class Config:
    SECRET_KEY = load_secret_key()

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(BASE_DIR, "instance", "app.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ------- 大语言模型（DeepSeek）-------
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    DEEPSEEK_TIMEOUT = int(os.environ.get("DEEPSEEK_TIMEOUT", "90"))

    # ------- 分页 -------
    PAGE_SIZE = int(os.environ.get("PAGE_SIZE", "10"))

    # 会话安全
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # 由平台反向代理提供 HTTPS 时，可设置 COOKIE_SECURE=1 强制仅 HTTPS 传输
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
