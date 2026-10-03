"""R02 软件需求管理：录入、查看、维护软件需求。"""
from datetime import datetime

from flask import (Blueprint, flash, redirect, render_template, request, url_for)
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Requirement, TestCase
from ..security import flash_errors, log_action, next_code

bp = Blueprint("requirements", __name__, url_prefix="/requirements")


@bp.route("/")
@login_required
def list_requirements():
    keyword = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 10

    query = db.session.query(Requirement).filter_by(is_deleted=False)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(db.or_(Requirement.name.like(like),
                                    Requirement.code.like(like),
                                    Requirement.description.like(like)))
    pagination = query.order_by(Requirement.updated_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False)

    return render_template("requirements/list.html", pagination=pagination,
                           keyword=keyword, total=pagination.total)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        business_rules = (request.form.get("business_rules") or "").strip()

        errors = flash_errors({"name": name}, [("name", "需求名称")])
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("requirements/form.html", item=None,
                                   form=request.form)

        item = Requirement(
            code=next_code(Requirement, "REQ"),
            name=name,
            description=description,
            business_rules=business_rules,
            created_by_id=current_user.id,
        )
        db.session.add(item)
        db.session.commit()
        log_action("新建需求", target_type="requirement", target_id=item.id,
                   detail=f"创建需求 {item.code} {item.name}")
        flash(f"需求 {item.code} 创建成功。", "success")
        return redirect(url_for("requirements.detail", req_id=item.id))

    return render_template("requirements/form.html", item=None, form={})


@bp.route("/<int:req_id>")
@login_required
def detail(req_id):
    item = db.session.get(Requirement, req_id)
    if item is None or item.is_deleted:
        flash("需求不存在或已被删除。", "warning")
        return redirect(url_for("requirements.list_requirements"))
    cases = (db.session.query(TestCase)
             .filter_by(requirement_id=req_id, is_deleted=False)
             .order_by(TestCase.created_at.desc()).all())
    return render_template("requirements/detail.html", item=item, cases=cases)


@bp.route("/<int:req_id>/edit", methods=["GET", "POST"])
@login_required
def edit(req_id):
    item = db.session.get(Requirement, req_id)
    if item is None or item.is_deleted:
        flash("需求不存在或已被删除。", "warning")
        return redirect(url_for("requirements.list_requirements"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        errors = flash_errors({"name": name}, [("name", "需求名称")])
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("requirements/form.html", item=item,
                                   form=request.form)

        item.name = name
        item.description = (request.form.get("description") or "").strip()
        item.business_rules = (request.form.get("business_rules") or "").strip()
        db.session.commit()
        log_action("修改需求", target_type="requirement", target_id=item.id,
                   detail=f"更新需求 {item.code}")
        flash("需求已更新。", "success")
        return redirect(url_for("requirements.detail", req_id=item.id))

    return render_template("requirements/form.html", item=item, form={
        "name": item.name,
        "description": item.description,
        "business_rules": item.business_rules,
    })


@bp.route("/<int:req_id>/delete", methods=["POST"])
@login_required
def delete(req_id):
    item = db.session.get(Requirement, req_id)
    if item is None or item.is_deleted:
        flash("需求不存在或已被删除。", "warning")
        return redirect(url_for("requirements.list_requirements"))

    if not current_user.is_admin:
        log_action("删除需求", target_type="requirement", target_id=req_id,
                   detail="权限不足", result="failed")
        flash("仅管理员可以删除需求。", "danger")
        return redirect(url_for("requirements.detail", req_id=req_id))

    # 逻辑删除，并级联逻辑删除其下用例，保证数据一致性（6.2）
    now = datetime.now()
    item.is_deleted = True
    item.deleted_at = now
    item.deleted_by_id = current_user.id
    (db.session.query(TestCase)
     .filter_by(requirement_id=req_id, is_deleted=False)
     .update({"is_deleted": True, "deleted_at": now,
              "deleted_by_id": current_user.id}, synchronize_session=False))
    db.session.commit()
    log_action("删除需求", target_type="requirement", target_id=req_id,
               detail=f"逻辑删除需求 {item.code} 及其关联用例")
    flash(f"需求 {item.code} 已删除（含其关联用例），可在回收站中还原。", "success")
    return redirect(url_for("requirements.list_requirements"))
