"""R07 测试用例删除 —— 回收站（逻辑删除的查看、还原与彻底删除）。

说明书 3.7 的约束为"是否逻辑删除待确定"。本系统采用**逻辑删除**：
  - 删除仅置 is_deleted 标记，数据不物理丢失，满足 4.3 可靠性要求；
  - 普通用户可在回收站中还原本人删除的用例/需求；
  - 仅管理员可执行"彻底删除"，彻底删除为不可逆操作，界面会二次确认。
"""
from datetime import datetime

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from ..extensions import db
from ..models import ROLE_ADMIN, Requirement, TestCase
from ..security import log_action, role_required

bp = Blueprint("recycle", __name__, url_prefix="/recycle")

PER_PAGE = 10

MODELS = {
    "case": (TestCase, "测试用例"),
    "requirement": (Requirement, "软件需求"),
}


def _target(kind: str):
    if kind not in MODELS:
        abort(404)
    return MODELS[kind]


def _may_manage(obj) -> bool:
    """管理员可管理全部；普通用户仅能管理本人创建的数据。"""
    return current_user.is_admin or obj.created_by_id == current_user.id


@bp.route("/")
@login_required
def index():
    kind = request.args.get("type", "case")
    model, label = _target(kind)
    page = request.args.get("page", 1, type=int)
    keyword = (request.args.get("q") or "").strip()

    query = db.session.query(model).filter_by(is_deleted=True)
    if not current_user.is_admin:
        query = query.filter(model.created_by_id == current_user.id)
    if keyword:
        like = f"%{keyword}%"
        column = model.name if kind == "requirement" else model.title
        query = query.filter(db.or_(model.code.like(like), column.like(like)))

    # SQLite 中 NULL 最小，deleted_at DESC 时 NULL 自然排在末尾
    pagination = query.order_by(model.deleted_at.desc(),
                                model.updated_at.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False)

    return render_template("recycle.html", pagination=pagination, kind=kind,
                           label=label, keyword=keyword,
                           counts={
                               "case": db.session.query(TestCase).filter_by(
                                   is_deleted=True).count(),
                               "requirement": db.session.query(Requirement).filter_by(
                                   is_deleted=True).count(),
                           })


@bp.route("/<kind>/<int:obj_id>/restore", methods=["POST"])
@login_required
def restore(kind, obj_id):
    model, label = _target(kind)
    obj = db.session.get(model, obj_id)
    if obj is None or not obj.is_deleted:
        flash("记录不存在或未被删除。", "warning")
        return redirect(url_for("recycle.index", type=kind))
    if not _may_manage(obj):
        log_action("还原记录", target_type=kind, target_id=obj_id,
                   detail="权限不足：非本人创建且非管理员", result="failed")
        flash("只能还原本人创建的数据，或联系管理员。", "danger")
        return redirect(url_for("recycle.index", type=kind))

    obj.is_deleted = False
    obj.deleted_at = None
    obj.deleted_by_id = None
    db.session.commit()
    log_action("还原记录", target_type=kind, target_id=obj_id,
               detail=f"还原{label} {obj.code}")
    flash(f"{label} {obj.code} 已还原。", "success")
    return redirect(url_for("recycle.index", type=kind))


@bp.route("/<kind>/<int:obj_id>/purge", methods=["POST"])
@login_required
@role_required(ROLE_ADMIN)
def purge(kind, obj_id):
    """彻底删除（仅管理员，不可恢复）。"""
    model, label = _target(kind)
    obj = db.session.get(model, obj_id)
    if obj is None:
        flash("记录不存在。", "warning")
        return redirect(url_for("recycle.index", type=kind))

    code = obj.code
    if kind == "requirement":
        # 关联用例一并彻底删除，避免产生无法识别的记录（6.2 数据一致性）
        (db.session.query(TestCase)
         .filter_by(requirement_id=obj.id)
         .delete(synchronize_session=False))
    db.session.delete(obj)
    db.session.commit()
    log_action("彻底删除", target_type=kind, target_id=obj_id,
               detail=f"彻底删除{label} {code}")
    flash(f"{label} {code} 已彻底删除，此操作不可恢复。", "info")
    return redirect(url_for("recycle.index", type=kind))


@bp.route("/clear", methods=["POST"])
@login_required
@role_required(ROLE_ADMIN)
def clear():
    """清空回收站（仅管理员）。"""
    kind = request.form.get("type", "case")
    model, label = _target(kind)
    items = db.session.query(model).filter_by(is_deleted=True).all()
    codes = [i.code for i in items]
    for obj in items:
        if kind == "requirement":
            (db.session.query(TestCase)
             .filter_by(requirement_id=obj.id)
             .delete(synchronize_session=False))
        db.session.delete(obj)
    db.session.commit()
    log_action("清空回收站", target_type=kind, target_id="-",
               detail=f"清空{label}回收站，共 {len(codes)} 条")
    flash(f"已清空{label}回收站，共 {len(codes)} 条记录。", "info")
    return redirect(url_for("recycle.index", type=kind))
