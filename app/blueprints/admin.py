"""R09 角色与权限管理、R10 操作日志。"""
from datetime import datetime, timedelta

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required

from .. import llm
from ..extensions import db
from ..models import (ROLE_ADMIN, ROLE_NAMES, ROLE_USER, STATUS_ACTIVE,
                      STATUS_DISABLED, LlmSetting, OperationLog, Requirement,
                      TestCase, User)
from ..security import log_action, role_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------------------------- R09 用户与角色 ----------------------------
@bp.route("/users")
@login_required
@role_required(ROLE_ADMIN)
def users():
    keyword = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    query = db.session.query(User)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(db.or_(User.username.like(like),
                                    User.real_name.like(like)))
    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=10, error_out=False)
    return render_template("admin/users.html", pagination=pagination,
                           keyword=keyword, role_names=ROLE_NAMES)


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@role_required(ROLE_ADMIN)
def user_new():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        role = request.form.get("role") or ROLE_USER
        errors = []
        if not username:
            errors.append("用户名不能为空。")
        if len(password) < 6:
            errors.append("密码长度不得少于 6 位。")
        if role not in ROLE_NAMES:
            errors.append("角色取值非法。")
        if db.session.query(User).filter_by(username=username).first():
            errors.append("该用户名已存在。")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admin/user_form.html", item=None, form=request.form,
                                   role_names=ROLE_NAMES)

        user = User(
            username=username,
            real_name=(request.form.get("real_name") or "").strip(),
            email=(request.form.get("email") or "").strip(),
            role=role,
            status=STATUS_ACTIVE,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        log_action("新建用户", target_type="user", target_id=user.id,
                   detail=f"创建用户 {user.username}，角色 {ROLE_NAMES.get(role, role)}")
        flash(f"用户 {user.username} 创建成功。", "success")
        return redirect(url_for("admin.users"))

    return render_template("admin/user_form.html", item=None, form={},
                           role_names=ROLE_NAMES)


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@role_required(ROLE_ADMIN)
def user_edit(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        flash("用户不存在。", "warning")
        return redirect(url_for("admin.users"))

    if request.method == "POST":
        role = request.form.get("role") or user.role
        if role not in ROLE_NAMES:
            flash("角色取值非法。", "danger")
            return redirect(url_for("admin.user_edit", user_id=user_id))

        if user.id == current_user.id and role != ROLE_ADMIN:
            flash("不能取消自己的管理员权限。", "danger")
            return redirect(url_for("admin.user_edit", user_id=user_id))

        user.real_name = (request.form.get("real_name") or "").strip()
        user.email = (request.form.get("email") or "").strip()
        user.role = role
        db.session.commit()
        log_action("修改用户", target_type="user", target_id=user.id,
                   detail=f"更新用户 {user.username}，角色 {ROLE_NAMES.get(role, role)}")
        flash("用户信息已更新。", "success")
        return redirect(url_for("admin.users"))

    return render_template("admin/user_form.html", item=user,
                           form={"username": user.username, "real_name": user.real_name,
                                 "email": user.email, "role": user.role},
                           role_names=ROLE_NAMES)


@bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@role_required(ROLE_ADMIN)
def user_reset_password(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        flash("用户不存在。", "warning")
        return redirect(url_for("admin.users"))
    new_password = request.form.get("new_password") or ""
    if len(new_password) < 6:
        flash("新密码长度不得少于 6 位。", "danger")
        return redirect(url_for("admin.users"))
    user.set_password(new_password)
    db.session.commit()
    log_action("重置用户密码", target_type="user", target_id=user.id,
               detail=f"重置 {user.username} 的密码")
    flash(f"已重置 {user.username} 的密码。", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/toggle-status", methods=["POST"])
@login_required
@role_required(ROLE_ADMIN)
def user_toggle_status(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        flash("用户不存在。", "warning")
        return redirect(url_for("admin.users"))
    if user.id == current_user.id:
        flash("不能禁用自己的账号。", "danger")
        return redirect(url_for("admin.users"))

    user.status = STATUS_DISABLED if user.status == STATUS_ACTIVE else STATUS_ACTIVE
    db.session.commit()
    state = "启用" if user.status == STATUS_ACTIVE else "禁用"
    log_action("启用/禁用用户", target_type="user", target_id=user.id,
               detail=f"{state}用户 {user.username}")
    flash(f"已{state}用户 {user.username}。", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@role_required(ROLE_ADMIN)
def user_delete(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        flash("用户不存在。", "warning")
        return redirect(url_for("admin.users"))
    if user.id == current_user.id:
        flash("不能删除自己的账号。", "danger")
        return redirect(url_for("admin.users"))

    # 6.2 数据一致性：存在关联数据时不允许物理删除，避免产生无法识别的记录
    owned_reqs = db.session.query(Requirement).filter_by(created_by_id=user.id).count()
    owned_cases = db.session.query(TestCase).filter_by(created_by_id=user.id).count()
    if owned_reqs or owned_cases:
        log_action("删除用户", target_type="user", target_id=user_id,
                   detail="存在关联需求或用例，删除被拒绝", result="failed")
        flash(f"该用户已创建 {owned_reqs} 条需求、{owned_cases} 条用例，"
              f"为保证数据一致性不予删除，请改用【禁用】。", "danger")
        return redirect(url_for("admin.users"))

    db.session.delete(user)
    db.session.commit()
    log_action("删除用户", target_type="user", target_id=user_id,
               detail=f"删除用户 {user.username}")
    flash(f"用户 {user.username} 已删除。", "success")
    return redirect(url_for("admin.users"))


# ---------------------------- R10 操作日志 ----------------------------
@bp.route("/logs")
@login_required
@role_required(ROLE_ADMIN)
def logs():
    username = (request.args.get("username") or "").strip()
    action = (request.args.get("action") or "").strip()
    result = (request.args.get("result") or "").strip()
    days = request.args.get("days", 0, type=int)
    page = request.args.get("page", 1, type=int)

    query = db.session.query(OperationLog)
    if username:
        query = query.filter(OperationLog.username.like(f"%{username}%"))
    if action:
        query = query.filter(OperationLog.action.like(f"%{action}%"))
    if result:
        query = query.filter(OperationLog.result == result)
    if days and days > 0:
        since = datetime.now() - timedelta(days=days)
        query = query.filter(OperationLog.created_at >= since)

    pagination = query.order_by(OperationLog.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False)
    actions = [a[0] for a in db.session.query(OperationLog.action).distinct().all() if a[0]]
    return render_template("admin/logs.html", pagination=pagination, actions=actions,
                           username=username, action=action, result=result, days=days)


# ---------------------------- 大语言模型接口配置（5.2） ----------------------------
@bp.route("/settings", methods=["GET", "POST"])
@login_required
@role_required(ROLE_ADMIN)
def settings():
    setting = LlmSetting.get()

    if request.method == "POST":
        action = request.form.get("action", "save")

        if action == "clear_key":
            setting.api_key = ""
            setting.updated_by_id = current_user.id
            db.session.commit()
            log_action("修改模型设置", target_type="setting", target_id=setting.id,
                       detail="清除数据库中的 API Key，回退使用 .env 配置")
            flash("已清除系统中的 API Key，将回退使用 .env 中的配置。", "info")
            return redirect(url_for("admin.settings"))

        base_url = (request.form.get("base_url") or "").strip().rstrip("/")
        model = (request.form.get("model") or "").strip()
        timeout = request.form.get("timeout", type=int) or 90
        api_key = (request.form.get("api_key") or "").strip()

        errors = []
        if not base_url.startswith(("http://", "https://")):
            errors.append("接口地址必须以 http:// 或 https:// 开头。")
        if not model:
            errors.append("模型名称不能为空。")
        if not 5 <= timeout <= 600:
            errors.append("超时时间应在 5～600 秒之间。")
        if api_key and not api_key.startswith("sk-") and len(api_key) < 16:
            errors.append("API Key 格式看起来不正确，请确认是否复制完整。")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admin/settings.html", setting=setting,
                                   llm=llm.resolve_config())

        setting.base_url = base_url
        setting.model = model
        setting.timeout = timeout
        # 留空表示"不修改已有 Key"，避免掩码值被误存
        if api_key:
            setting.api_key = api_key
        setting.updated_by_id = current_user.id
        db.session.commit()
        log_action("修改模型设置", target_type="setting", target_id=setting.id,
                   detail=f"更新模型配置：{model} @ {base_url}，超时 {timeout}s")
        flash("模型配置已保存。", "success")
        return redirect(url_for("admin.settings"))

    return render_template("admin/settings.html", setting=setting,
                           llm=llm.resolve_config())


@bp.route("/settings/test", methods=["POST"])
@login_required
@role_required(ROLE_ADMIN)
def settings_test():
    """测试连接：优先使用页面上未保存的临时配置，便于先验证再保存。"""
    overrides = {
        "api_key": (request.form.get("api_key") or "").strip(),
        "base_url": (request.form.get("base_url") or "").strip(),
        "model": (request.form.get("model") or "").strip(),
        "timeout": request.form.get("timeout", type=int) or 0,
    }
    if not overrides["api_key"]:
        setting = LlmSetting.get()
        overrides["api_key"] = setting.api_key or current_app.config.get("DEEPSEEK_API_KEY", "")
    try:
        reply = llm.test_connection(overrides)
    except llm.LLMError as exc:
        log_action("测试模型连接", target_type="setting", detail=str(exc), result="failed")
        flash(f"连接失败：{exc}", "danger")
    else:
        log_action("测试模型连接", target_type="setting", detail=f"模型回显：{reply[:50]}")
        flash(f"连接成功，模型回显：{reply[:80]}", "success")
    return redirect(url_for("admin.settings"))


# ---------------------------- R10 日志导出 ----------------------------
@bp.route("/logs/export")
@login_required
@role_required(ROLE_ADMIN)
def logs_export():
    """导出操作日志（CSV，带 BOM 便于 Excel 打开）。"""
    import csv
    import io

    from flask import send_file

    query = db.session.query(OperationLog)
    username = (request.args.get("username") or "").strip()
    days = request.args.get("days", 0, type=int)
    if username:
        query = query.filter(OperationLog.username.like(f"%{username}%"))
    if days and days > 0:
        query = query.filter(OperationLog.created_at >= datetime.now() - timedelta(days=days))
    logs = query.order_by(OperationLog.created_at.desc()).limit(5000).all()

    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(["时间", "用户", "操作类型", "对象类型", "对象标识", "结果", "IP", "详情"])
    for log in logs:
        writer.writerow([
            log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
            log.username, log.action, log.target_type, log.target_id,
            "成功" if log.result == "success" else "失败", log.ip, log.detail,
        ])
    buf = io.BytesIO(("\ufeff" + text.getvalue()).encode("utf-8"))
    log_action("导出操作日志", target_type="log", target_id="-",
               detail=f"导出 {len(logs)} 条日志")
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name=f"operation_logs_{datetime.now():%Y%m%d%H%M%S}.csv")
