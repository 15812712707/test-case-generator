"""权限控制与操作日志（R09 / R10）。"""
from functools import wraps

from flask import abort, redirect, request, url_for
from flask_login import current_user

from .extensions import db
from .models import OperationLog


def role_required(*roles):
    """限定只有指定角色可访问的视图装饰器（R09 角色与权限管理）。"""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.path))
            if current_user.role not in roles:
                log_action("权限拒绝", target_type="route", detail=f"访问 {request.path} 被拒绝",
                           result="failed")
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def log_action(action: str, target_type: str = "", target_id: str = "",
               detail: str = "", result: str = "success") -> None:
    """写入一条操作日志（R10 操作日志）。任何关键操作都应调用。"""
    entry = OperationLog(
        user_id=current_user.id if getattr(current_user, "is_authenticated", False) else None,
        username=getattr(current_user, "username", "anonymous") if getattr(current_user, "is_authenticated", False) else "anonymous",
        action=action,
        target_type=target_type,
        target_id=str(target_id or ""),
        detail=detail,
        result=result,
        ip=request.remote_addr or "",
    )
    db.session.add(entry)
    db.session.commit()


def next_code(model, prefix: str) -> str:
    """生成业务编号，如 REQ-0001 / TC-0001。"""
    last = db.session.query(model).order_by(model.id.desc()).first()
    seq = (last.id + 1) if last else 1
    code = f"{prefix}-{seq:04d}"
    # 极端并发下防重
    while db.session.query(model).filter_by(code=code).first() is not None:
        seq += 1
        code = f"{prefix}-{seq:04d}"
    return code


def flash_errors(form_data: dict, required: list) -> list:
    """简单必填校验，返回错误信息列表。"""
    errors = []
    for field, label in required:
        if not str(form_data.get(field, "")).strip():
            errors.append(f"{label}不能为空。")
    return errors
