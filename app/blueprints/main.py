"""首页 / 工作台。"""
from flask import Blueprint, render_template
from flask_login import current_user, login_required

from ..extensions import db
from ..models import CASE_STATUS_CONFIRMED, CASE_STATUS_DRAFT, OperationLog, Requirement, TestCase, User

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return dashboard()
    from flask import redirect, url_for
    return redirect(url_for("auth.login"))


@bp.route("/dashboard")
@login_required
def dashboard():
    stats = {
        "requirements": db.session.query(Requirement).filter_by(is_deleted=False).count(),
        "testcases": db.session.query(TestCase).filter_by(is_deleted=False).count(),
        "drafts": db.session.query(TestCase).filter_by(
            is_deleted=False, status=CASE_STATUS_DRAFT).count(),
        "confirmed": db.session.query(TestCase).filter_by(
            is_deleted=False, status=CASE_STATUS_CONFIRMED).count(),
        "users": db.session.query(User).count(),
        "logs": db.session.query(OperationLog).count(),
    }
    recent_cases = (db.session.query(TestCase)
                    .filter_by(is_deleted=False)
                    .order_by(TestCase.updated_at.desc())
                    .limit(5).all())
    recent_logs = (db.session.query(OperationLog)
                   .order_by(OperationLog.created_at.desc())
                   .limit(8).all())
    return render_template("dashboard.html", stats=stats,
                           recent_cases=recent_cases, recent_logs=recent_logs)
