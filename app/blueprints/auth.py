"""R01 用户管理：登录、登出、个人信息维护。"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import STATUS_ACTIVE, User
from ..security import log_action

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if not username or not password:
            flash("用户名和密码不能为空。", "danger")
            return render_template("login.html", username=username)

        user = db.session.query(User).filter_by(username=username).first()

        if user is None:
            log_action("登录失败", target_type="user", target_id=username,
                       detail="账号不存在", result="failed")
            flash("账号不存在或密码错误。", "danger")
            return render_template("login.html", username=username)

        if not user.verify_password(password):
            log_action("登录失败", target_type="user", target_id=username,
                       detail="密码错误", result="failed")
            flash("账号不存在或密码错误。", "danger")
            return render_template("login.html", username=username)

        if user.status != STATUS_ACTIVE:
            log_action("登录失败", target_type="user", target_id=username,
                       detail="账号已被禁用", result="failed")
            flash("该账号已被禁用，请联系管理员。", "danger")
            return render_template("login.html", username=username)

        login_user(user)
        log_action("用户登录", target_type="user", target_id=user.id,
                   detail=f"{user.username} 登录成功")
        flash(f"欢迎回来，{user.real_name or user.username}！", "success")

        next_url = request.args.get("next")
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("main.dashboard"))

    return render_template("login.html", username="")


@bp.route("/logout")
@login_required
def logout():
    log_action("用户登出", target_type="user", target_id=current_user.id,
               detail=f"{current_user.username} 退出登录")
    logout_user()
    flash("已安全退出登录。", "info")
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "info":
            real_name = (request.form.get("real_name") or "").strip()
            email = (request.form.get("email") or "").strip()
            if email and "@" not in email:
                flash("邮箱格式不正确。", "danger")
                return render_template("profile.html")
            current_user.real_name = real_name
            current_user.email = email
            db.session.commit()
            log_action("修改个人信息", target_type="user", target_id=current_user.id)
            flash("个人信息已更新。", "success")

        elif action == "password":
            old = request.form.get("old_password") or ""
            new = request.form.get("new_password") or ""
            confirm = request.form.get("confirm_password") or ""
            if not current_user.verify_password(old):
                flash("原密码不正确。", "danger")
            elif len(new) < 6:
                flash("新密码长度不得少于 6 位。", "danger")
            elif new != confirm:
                flash("两次输入的新密码不一致。", "danger")
            else:
                current_user.set_password(new)
                db.session.commit()
                log_action("修改密码", target_type="user", target_id=current_user.id)
                flash("密码修改成功，请重新登录。", "success")
                logout_user()
                return redirect(url_for("auth.login"))

        return redirect(url_for("auth.profile"))

    return render_template("profile.html")
