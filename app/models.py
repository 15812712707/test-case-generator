"""数据模型：用户 / 软件需求 / 测试用例 / 操作日志。

对应《软件需求规格说明书》6.1 数据需求：
  - 用户数据：用户标识、账号、角色及必要状态信息
  - 需求数据：需求名称、需求描述、业务规则及关联信息
  - 测试用例数据：名称、前置条件、测试步骤、测试数据、预期结果等
  - 日志数据：用户、操作类型、操作时间、操作结果等
删除统一采用逻辑删除（is_deleted），保证 6.2 数据一致性要求。
"""
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager

ROLE_ADMIN = "admin"
ROLE_USER = "user"

ROLE_NAMES = {ROLE_ADMIN: "管理员", ROLE_USER: "普通用户"}

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"

CASE_STATUS_DRAFT = "draft"
CASE_STATUS_CONFIRMED = "confirmed"
CASE_STATUS_NAMES = {CASE_STATUS_DRAFT: "草稿", CASE_STATUS_CONFIRMED: "已确认"}

PRIORITY_NAMES = {"high": "高", "medium": "中", "low": "低"}


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    real_name = db.Column(db.String(64), default="")
    email = db.Column(db.String(128), default="")
    role = db.Column(db.String(16), nullable=False, default=ROLE_USER)
    status = db.Column(db.String(16), nullable=False, default=STATUS_ACTIVE)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # 关系（Requirement / TestCase 均有两个指向 users 的外键，必须显式指定）
    requirements = db.relationship(
        "Requirement", backref="creator", lazy="dynamic",
        foreign_keys="Requirement.created_by_id")
    testcases = db.relationship(
        "TestCase", backref="creator", lazy="dynamic",
        foreign_keys="TestCase.created_by_id")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_active(self) -> bool:  # Flask-Login 会调用
        return self.status == STATUS_ACTIVE

    @property
    def role_name(self) -> str:
        return ROLE_NAMES.get(self.role, self.role)

    def __repr__(self) -> str:
        return f"<User {self.username} {self.role}>"


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


class Requirement(db.Model):
    __tablename__ = "requirements"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    business_rules = db.Column(db.Text, default="")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    testcases = db.relationship("TestCase", backref="requirement", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Requirement {self.code} {self.name}>"


class TestCase(db.Model):
    __tablename__ = "testcases"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    requirement_id = db.Column(db.Integer, db.ForeignKey("requirements.id"))
    precondition = db.Column(db.Text, default="")
    steps = db.Column(db.Text, default="")
    test_data = db.Column(db.Text, default="")
    expected_result = db.Column(db.Text, default="")
    category = db.Column(db.String(64), default="功能测试")
    priority = db.Column(db.String(16), default="medium")
    status = db.Column(db.String(16), default=CASE_STATUS_DRAFT, nullable=False)
    source = db.Column(db.String(16), default="manual")  # llm / manual
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def status_name(self) -> str:
        return CASE_STATUS_NAMES.get(self.status, self.status)

    @property
    def priority_name(self) -> str:
        return PRIORITY_NAMES.get(self.priority, self.priority)

    @property
    def step_list(self):
        return [s.strip() for s in (self.steps or "").splitlines() if s.strip()]

    def __repr__(self) -> str:
        return f"<TestCase {self.code} {self.title}>"


class LlmSetting(db.Model):
    """R03 大语言模型接口配置（5.2）。

    说明书 5.2 指出"具体模型、协议、鉴权和参数格式待确定"，本系统统一采用
    DeepSeek 的 OpenAI 兼容接口。凭据既可由 .env 注入，也可由管理员在
    "系统设置"页面维护；数据库中仅保存一条配置记录。
    界面中不回显完整 Key，只显示掩码，避免敏感信息直接暴露（4.2）。
    """

    __tablename__ = "llm_settings"

    id = db.Column(db.Integer, primary_key=True)
    api_key = db.Column(db.String(255), default="")
    # 留空表示"未在界面配置"，此时回退使用 .env 中的配置（说明书 5.2）
    base_url = db.Column(db.String(255), default="")
    model = db.Column(db.String(64), default="")
    timeout = db.Column(db.Integer)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    @staticmethod
    def get() -> "LlmSetting":
        """取配置（不存在则创建默认记录）。"""
        setting = db.session.query(LlmSetting).order_by(LlmSetting.id.asc()).first()
        if setting is None:
            setting = LlmSetting()
            db.session.add(setting)
            db.session.commit()
        return setting

    @property
    def masked_key(self) -> str:
        key = (self.api_key or "").strip()
        if not key:
            return ""
        if len(key) <= 8:
            return "****"
        return f"{key[:4]}{'*' * 8}{key[-4:]}"


class OperationLog(db.Model):
    __tablename__ = "operation_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    username = db.Column(db.String(64), default="")
    action = db.Column(db.String(64), nullable=False, index=True)
    target_type = db.Column(db.String(32), default="")
    target_id = db.Column(db.String(64), default="")
    detail = db.Column(db.Text, default="")
    result = db.Column(db.String(16), default="success")  # success / failed
    ip = db.Column(db.String(64), default="")
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    user = db.relationship("User", backref="logs")

    def __repr__(self) -> str:
        return f"<OperationLog {self.username} {self.action}>"
