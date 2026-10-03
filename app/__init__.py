"""应用工厂。"""
import os

from flask import Flask, render_template

from .config import Config
from .extensions import db, login_manager


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)

    # 确保 sqlite 目录存在
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:///"):
        path = uri.replace("sqlite:///", "", 1)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from . import models  # noqa: F401  注册模型

    from .blueprints import admin, auth, main, recycle, requirements, testcases
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(requirements.bp)
    app.register_blueprint(testcases.bp)
    app.register_blueprint(recycle.bp)
    app.register_blueprint(admin.bp)

    # 模板全局变量
    from .models import PRIORITY_NAMES, ROLE_NAMES, CASE_STATUS_NAMES
    from . import llm

    @app.context_processor
    def inject_globals():
        return {
            "ROLE_NAMES": ROLE_NAMES,
            "PRIORITY_NAMES": PRIORITY_NAMES,
            "CASE_STATUS_NAMES": CASE_STATUS_NAMES,
            "llm_configured": llm.is_configured(),
        }

    @app.template_filter("reject_page")
    def reject_page(args):
        """分页 / 导出链接用：剔除由当前动作决定的参数，避免重复或污染查询串。"""
        drop = {"page", "format", "ids"}
        return {k: v for k, v in (args or {}).items() if k not in drop and v != ""}

    # 错误处理（4.4 可用性：错误提示能够帮助用户定位问题）
    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/error.html", code=403,
                               message="没有访问该功能的权限。"), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/error.html", code=404,
                               message="请求的页面不存在。"), 404

    @app.errorhandler(500)
    def server_error(_e):
        db.session.rollback()
        return render_template("errors/error.html", code=500,
                               message="服务器内部错误，请稍后重试。"), 500

    with app.app_context():
        db.create_all()

    _register_cli(app)

    return app


def _register_cli(app):
    """初始化与演示数据命令：flask init-db / flask seed-demo。"""
    import click

    @app.cli.command("init-db")
    def init_db():
        """创建数据库表并写入初始账号（admin / tester）。"""
        from .extensions import db as _db
        from .models import (ROLE_ADMIN, ROLE_USER, STATUS_ACTIVE, LlmSetting, User)

        _db.create_all()
        created = []
        seeds = [
            ("admin", "Admin@123", "系统管理员", ROLE_ADMIN),
            ("tester", "Tester@123", "测试人员", ROLE_USER),
        ]
        for username, password, real_name, role in seeds:
            if _db.session.query(User).filter_by(username=username).first() is None:
                user = User(username=username, real_name=real_name, role=role,
                            status=STATUS_ACTIVE)
                user.set_password(password)
                _db.session.add(user)
                created.append(f"{username}/{password}")
        LlmSetting.get()
        _db.session.commit()
        if created:
            click.echo("已创建初始账号：" + "，".join(created))
        else:
            click.echo("初始账号已存在，未重复创建。")
        click.echo("数据库初始化完成。")

    @app.cli.command("seed-demo")
    def seed_demo():
        """写入一条示例软件需求，便于直接体验生成流程。"""
        from .extensions import db as _db
        from .models import Requirement, User
        from .security import next_code

        admin = _db.session.query(User).filter_by(username="admin").first()
        if _db.session.query(Requirement).count() > 0:
            click.echo("已存在需求数据，跳过。")
            return
        item = Requirement(
            code=next_code(Requirement, "REQ"),
            name="用户登录",
            description="用户输入用户名和密码进行登录，登录成功后进入系统首页；"
                        "密码连续输入错误达到 5 次时锁定账号 10 分钟。",
            business_rules="1. 用户名和密码均为必填；\n"
                           "2. 用户名不存在或密码错误时统一提示，不区分具体原因；\n"
                           "3. 连续失败 5 次锁定账号 10 分钟；\n"
                           "4. 账号被禁用的用户不允许登录。",
            created_by_id=admin.id if admin else None,
        )
        _db.session.add(item)
        _db.session.commit()
        click.echo(f"已写入示例需求 {item.code} {item.name}")
