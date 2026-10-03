"""启动入口。

本地开发：
    python run.py                     # http://127.0.0.1:5000（开启调试）
    PORT=8080 python run.py           # 指定端口
    python run.py --no-debug          # 关闭调试模式

云端 / 容器部署：
    平台注入 PORT 环境变量后自动切换为生产模式 —— 监听 0.0.0.0、
    关闭调试（避免 Werkzeug 调试器暴露在公网）、密钥自动生成并持久化。
    例如：PORT=3000 python run.py

首次启动会自动建表；若用户表为空则创建初始账号，便于直接登录体验。
"""
import os
import sys

from app import create_app
from app.extensions import db


def is_cloud_runtime() -> bool:
    """部署平台会注入 PORT 环境变量，本地手动运行通常不会。"""
    return bool(os.environ.get("PORT"))


def ensure_seed(app) -> None:
    """用户表为空时写入初始账号，避免首次启动无法登录。"""
    from app.models import ROLE_ADMIN, ROLE_USER, STATUS_ACTIVE, LlmSetting, User

    with app.app_context():
        db.create_all()
        LlmSetting.get()
        if db.session.query(User).count() > 0:
            return
        seeds = [
            ("admin", "Admin@123", "系统管理员", ROLE_ADMIN),
            ("tester", "Tester@123", "测试人员", ROLE_USER),
        ]
        for username, password, real_name, role in seeds:
            user = User(username=username, real_name=real_name, role=role,
                        status=STATUS_ACTIVE)
            user.set_password(password)
            db.session.add(user)
        db.session.commit()
        print("=" * 68)
        print("已创建初始账号（请登录后尽快修改密码）：")
        for username, password, _, _ in seeds:
            print(f"    {username} / {password}")
        print("=" * 68)


app = create_app()

if __name__ == "__main__":
    ensure_seed(app)
    cloud = is_cloud_runtime()
    host = os.environ.get("HOST") or ("0.0.0.0" if cloud else "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    # 云端强制关闭调试，避免调试器暴露在公网
    debug = (not cloud) and ("--no-debug" not in sys.argv) \
        and os.environ.get("FLASK_DEBUG", "1") == "1"
    print(f"系统已启动：http://{host}:{port}  （调试模式：{'开' if debug else '关'}）")
    app.run(host=host, port=port, debug=debug, threaded=True)
