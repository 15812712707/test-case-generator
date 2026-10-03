"""端到端验证脚本（不需要真实大模型 API Key）。

覆盖《软件需求规格说明书》R01～R10 的全部主要流程：
    R01 登录/登出/个人信息      R02 需求增删改查
    R03 用例生成（含未配置/异常/正常三种路径，正常路径用桩响应模拟模型返回）
    R04 查看编辑  R05 保存  R06 查询  R07 删除（含回收站）
    R08 导出（xlsx/csv/json/md）  R09 角色权限  R10 操作日志

运行：
    python tests/test_e2e.py
"""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app                      # noqa: E402
from app.config import Config                   # noqa: E402
from app.extensions import db                   # noqa: E402
from app.models import (CASE_STATUS_CONFIRMED, OperationLog, Requirement,  # noqa: E402
                        TestCase, User)

TMP_DB = os.path.join(tempfile.mkdtemp(prefix="tc_e2e_"), "test.db")


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + TMP_DB
    DEEPSEEK_API_KEY = ""            # 默认未配置，用于验证"不伪造结果"
    DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    DEEPSEEK_MODEL = "deepseek-chat"
    DEEPSEEK_TIMEOUT = 10


def fake_post(payload):
    """构造一个与 DeepSeek /chat/completions 响应结构一致的桩对象。"""
    class Resp:
        status_code = 200
        text = "ok"

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(payload,
                                                                   ensure_ascii=False)}}]}

    return Resp()


FAKE_CASES = {
    "testcases": [
        {
            "title": "登录成功",
            "category": "功能测试",
            "priority": "high",
            "precondition": "已打开登录页面",
            "steps": ["输入正确的用户名密码", "点击登录按钮"],
            "test_data": "admin / Admin@123",
            "expected_result": "登录成功并跳转到系统首页",
        },
        {
            "title": "密码错误 5 次锁定账号",
            "category": "异常测试",
            "priority": "high",
            "precondition": "账号未被锁定",
            "steps": ["连续输入错误密码 5 次", "第 6 次尝试登录"],
            "test_data": "任意错误密码",
            "expected_result": "账号被锁定 10 分钟并给出提示",
        },
    ]
}


class SystemE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(TestConfig)
        cls.app.config["SERVER_NAME"] = None
        with cls.app.app_context():
            db.create_all()
            for username, password, role in [("admin", "Admin@123", "admin"),
                                             ("tester", "Tester@123", "user")]:
                user = User(username=username, real_name=username, role=role, status="active")
                user.set_password(password)
                db.session.add(user)
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.drop_all()

    def setUp(self):
        self.client = self.app.test_client()

    # ---------------- 工具 ----------------
    def login(self, username="admin", password="Admin@123"):
        return self.client.post("/login", data={"username": username, "password": password},
                                follow_redirects=True)

    def logout(self):
        return self.client.get("/logout", follow_redirects=True)

    def req_id(self, code):
        with self.app.app_context():
            return db.session.query(Requirement).filter_by(code=code).first().id

    def case_id(self, code):
        with self.app.app_context():
            return db.session.query(TestCase).filter_by(code=code).first().id

    def latest_case_id(self):
        """取最新创建的用例 id（业务编号随执行顺序变化，故不硬编码）。"""
        with self.app.app_context():
            return db.session.query(TestCase).order_by(TestCase.id.desc()).first().id

    # ---------------- R01 ----------------
    def test_01_login_and_profile(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

        r = self.client.post("/login", data={"username": "admin", "password": "wrong"},
                             follow_redirects=True)
        self.assertIn("账号不存在或密码错误", r.get_data(as_text=True))

        r = self.login()
        self.assertIn("工作台", r.get_data(as_text=True))
        self.assertIn("欢迎回来", r.get_data(as_text=True))

        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 200)
        self.assertIn("工作台", r.get_data(as_text=True))

        r = self.client.post("/profile", data={"action": "info", "real_name": "黄漪菲",
                                               "email": "test@example.com"},
                             follow_redirects=True)
        self.assertIn("个人信息已更新", r.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.query(User).filter_by(username="admin").first().real_name,
                             "黄漪菲")

    def test_02_role_permission(self):
        """R09：普通用户访问管理页必须被拒绝。"""
        self.login("tester", "Tester@123")
        for path in ["/admin/users", "/admin/logs", "/admin/settings"]:
            self.assertEqual(self.client.get(path).status_code, 403, path)
        self.assertEqual(self.client.get("/requirements/").status_code, 200)

    def test_03_requirement_crud(self):
        self.login()
        r = self.client.post("/requirements/new",
                             data={"name": "用户登录",
                                   "description": "用户输入用户名和密码进行登录，登录成功后进入系统首页。",
                                   "business_rules": "1. 用户名密码必填；2. 连续错误 5 次锁定。"},
                             follow_redirects=True)
        self.assertIn("创建成功", r.get_data(as_text=True))
        rid = self.req_id("REQ-0001")
        self.assertEqual(self.client.get(f"/requirements/{rid}").status_code, 200)
        self.assertEqual(self.client.get("/requirements/").status_code, 200)
        self.assertEqual(
            self.client.get("/requirements/").get_data(as_text=True).count("用户登录") > 0, True)

        r = self.client.post(f"/requirements/{rid}/edit",
                             data={"name": "用户登录（已修改）", "description": "x" * 20,
                                   "business_rules": "规则"}, follow_redirects=True)
        self.assertIn("需求已更新", r.get_data(as_text=True))

        # 必填校验
        r = self.client.post("/requirements/new", data={"name": "", "description": "a"},
                             follow_redirects=True)
        self.assertIn("需求名称不能为空", r.get_data(as_text=True))

    # ---------------- R03 ----------------
    def test_04_generate_without_key(self):
        """未配置 Key 时必须明确报错，绝不返回伪造内容。"""
        self.login()
        rid = self.req_id("REQ-0001")
        r = self.client.post("/testcases/generate",
                             data={"requirement_id": rid, "count": 5},
                             headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(r.status_code, 502)
        data = r.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("未配置大语言模型凭据", data["error"])
        with self.app.app_context():
            self.assertEqual(db.session.query(TestCase).count(), 0)

    def test_05_generate_validation(self):
        """3.3：需求描述为空或过短时不允许提交生成。"""
        self.login()
        self.client.post("/requirements/new", data={"name": "短需求", "description": "太短"},
                         follow_redirects=True)
        rid = self.req_id("REQ-0002")
        r = self.client.post("/testcases/generate", data={"requirement_id": rid, "count": 3},
                             headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("过短", r.get_json()["error"])

    def test_06_generate_network_error(self):
        """模型服务不可达时应提示失败原因，且不写入任何用例。"""
        import requests

        self.login()
        rid = self.req_id("REQ-0001")
        self.app.config["DEEPSEEK_API_KEY"] = "sk-test-invalid-key-0001"
        try:
            with mock.patch("app.llm.requests.post",
                            side_effect=requests.ConnectionError("connection refused")):
                r = self.client.post("/testcases/generate", data={"requirement_id": rid, "count": 3},
                                     headers={"X-Requested-With": "XMLHttpRequest"})
            self.assertEqual(r.status_code, 502)
            self.assertIn("网络异常", r.get_json()["error"])
            with self.app.app_context():
                self.assertEqual(db.session.query(TestCase).count(), 0)

            # 超时异常同样应给出可读提示
            with mock.patch("app.llm.requests.post",
                            side_effect=requests.Timeout("read timed out")):
                r = self.client.post("/testcases/generate", data={"requirement_id": rid, "count": 3},
                                     headers={"X-Requested-With": "XMLHttpRequest"})
            self.assertIn("超时", r.get_json()["error"])

            # 返回结构异常时同样不得写入数据
            class BadResp:
                status_code = 200
                text = "not json"

                def json(self):
                    raise ValueError("invalid json")

            with mock.patch("app.llm.requests.post", return_value=BadResp()):
                r = self.client.post("/testcases/generate", data={"requirement_id": rid, "count": 3},
                                     headers={"X-Requested-With": "XMLHttpRequest"})
            self.assertEqual(r.status_code, 502)
            self.assertIn("返回结构异常", r.get_json()["error"])
            with self.app.app_context():
                self.assertEqual(db.session.query(TestCase).count(), 0)
        finally:
            self.app.config["DEEPSEEK_API_KEY"] = ""

    def test_07_generate_and_save(self):
        """正常路径：用桩响应模拟模型返回，验证 解析 → 展示 → 确认保存 → 查询。"""
        self.login()
        rid = self.req_id("REQ-0001")
        self.app.config["DEEPSEEK_API_KEY"] = "sk-test-key-for-stub"
        try:
            with mock.patch("app.llm.requests.post", return_value=fake_post(FAKE_CASES)):
                r = self.client.post("/testcases/generate", data={"requirement_id": rid, "count": 2},
                                     headers={"X-Requested-With": "XMLHttpRequest"})
        finally:
            self.app.config["DEEPSEEK_API_KEY"] = ""
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["results"][0]["title"], "登录成功")
        self.assertEqual(data["requirement"]["code"], "REQ-0001")

        # 保存勾选的两条（模拟用户核对后提交表单）
        rows = {"requirement_id": rid, "row_total": 2}
        for i, item in enumerate(data["results"]):
            rows[f"rows-{i}-selected"] = "on"
            rows[f"rows-{i}-title"] = item["title"]
            rows[f"rows-{i}-category"] = item["category"]
            rows[f"rows-{i}-priority"] = item["priority"]
            rows[f"rows-{i}-precondition"] = item["precondition"]
            rows[f"rows-{i}-steps"] = item["steps"]
            rows[f"rows-{i}-test_data"] = item["test_data"]
            rows[f"rows-{i}-expected_result"] = item["expected_result"]
        r = self.client.post("/testcases/save-batch", data=rows, follow_redirects=True)
        self.assertIn("已保存 2 条测试用例", r.get_data(as_text=True))

        with self.app.app_context():
            cases = db.session.query(TestCase).order_by(TestCase.id).all()
            self.assertEqual(len(cases), 2)
            self.assertEqual(cases[0].source, "llm")
            self.assertEqual(cases[0].status, CASE_STATUS_CONFIRMED)
            self.assertEqual(cases[0].requirement_id, rid)

        # 删除一行后再保存，索引断档不得导致漏存
        rows2 = {"requirement_id": rid, "row_total": 3,
                 "rows-1-selected": "on", "rows-1-title": "断档测试用例",
                 "rows-1-priority": "medium", "rows-1-steps": "步骤1"}
        r = self.client.post("/testcases/save-batch", data=rows2, follow_redirects=True)
        self.assertIn("已保存 1 条测试用例", r.get_data(as_text=True))

    # ---------------- R04 / R05 / R06 ----------------
    def test_08_manual_case_and_query(self):
        self.login()
        rid = self.req_id("REQ-0001")
        r = self.client.post("/testcases/new",
                             data={"title": "手工用例-用户名不存在", "requirement_id": rid,
                                   "category": "异常测试", "priority": "high",
                                   "precondition": "已打开登录页", "steps": "1. 输入不存在的用户名\n2. 点击登录",
                                   "test_data": "nouser / any", "expected_result": "提示账号或密码错误"},
                             follow_redirects=True)
        self.assertIn("创建成功", r.get_data(as_text=True))
        cid = self.latest_case_id()
        self.assertEqual(self.client.get(f"/testcases/{cid}").status_code, 200)

        r = self.client.post(f"/testcases/{cid}/edit",
                             data={"title": "手工用例-用户名不存在（已改）", "requirement_id": rid,
                                   "category": "异常测试", "priority": "high",
                                   "steps": "1. 输入不存在的用户名", "expected_result": "提示错误"},
                             follow_redirects=True)
        self.assertIn("已保存", r.get_data(as_text=True))

        r = self.client.post(f"/testcases/{cid}/confirm", follow_redirects=True)
        self.assertIn("已确认为正式用例", r.get_data(as_text=True))

        # R06 查询：关键词 / 分类 / 优先级 / 需求 组合筛选
        self.assertEqual(self.client.get("/testcases/?q=用户名").status_code, 200)
        r = self.client.get("/testcases/?category=异常测试&priority=high")
        self.assertEqual(r.status_code, 200)
        self.assertIn("手工用例", r.get_data(as_text=True))
        r = self.client.get("/testcases/?q=不存在的关键词xyz")
        self.assertIn("没有符合条件的测试用例", r.get_data(as_text=True))
        r = self.client.get(f"/testcases/?req={rid}")
        self.assertEqual(r.status_code, 200)

        # 需求详情应展示关联用例
        r = self.client.get(f"/requirements/{rid}")
        self.assertIn("关联测试用例", r.get_data(as_text=True))

    # ---------------- R08 ----------------
    def test_09_export_all_formats(self):
        self.login()
        expect = {"xlsx": "spreadsheetml", "csv": "text/csv",
                  "json": "application/json", "md": "text/markdown"}
        for fmt, mime in expect.items():
            r = self.client.get(f"/testcases/export?format={fmt}")
            self.assertEqual(r.status_code, 200, fmt)
            self.assertIn(mime, r.headers["Content-Type"], fmt)
            self.assertGreater(len(r.data), 200, fmt)
            self.assertIn("attachment", r.headers.get("Content-Disposition", ""), fmt)

        # 导出的 xlsx 必须能被 Excel 库正常打开
        r = self.client.get("/testcases/export?format=xlsx")
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(r.data))
        ws = wb.active
        self.assertEqual(ws.cell(row=1, column=1).value, "用例编号")
        self.assertGreater(ws.max_row, 1)

        # 按 id 导出单条
        cid = self.latest_case_id()
        r = self.client.get(f"/testcases/export?format=json&ids={cid}")
        self.assertEqual(len(json.loads(r.data)), 1)
        # 不支持的格式
        r = self.client.get("/testcases/export?format=docx", follow_redirects=True)
        self.assertIn("不支持的导出格式", r.get_data(as_text=True))

    # ---------------- R07 + 回收站 ----------------
    def test_10_delete_restore_purge(self):
        self.login()
        rid = self.req_id("REQ-0001")
        self.client.post("/testcases/new",
                         data={"title": "待删除用例", "requirement_id": rid}, follow_redirects=True)
        cid = self.latest_case_id()

        r = self.client.post(f"/testcases/{cid}/delete", follow_redirects=True)
        self.assertIn("可在回收站中还原", r.get_data(as_text=True))
        with self.app.app_context():
            self.assertTrue(db.session.get(TestCase, cid).is_deleted)
            self.assertIsNotNone(db.session.get(TestCase, cid).deleted_at)

        r = self.client.get("/recycle/?type=case")
        self.assertIn("待删除用例", r.get_data(as_text=True))

        r = self.client.post(f"/recycle/case/{cid}/restore", follow_redirects=True)
        self.assertIn("已还原", r.get_data(as_text=True))
        with self.app.app_context():
            self.assertFalse(db.session.get(TestCase, cid).is_deleted)

        # 批量删除 + 彻底删除
        self.client.post("/testcases/batch-delete", data={"ids": [str(cid)]},
                         follow_redirects=True)
        r = self.client.post(f"/recycle/case/{cid}/purge", follow_redirects=True)
        self.assertIn("已彻底删除", r.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(db.session.get(TestCase, cid))

    def test_11_permission_on_delete(self):
        """普通用户不得删除他人创建的用例（R07 + R09）。"""
        self.login()
        rid = self.req_id("REQ-0001")
        self.client.post("/testcases/new",
                         data={"title": "管理员创建的用例", "requirement_id": rid},
                         follow_redirects=True)
        cid = self.latest_case_id()
        self.logout()

        self.login("tester", "Tester@123")
        r = self.client.post(f"/testcases/{cid}/delete", follow_redirects=True)
        self.assertIn("只能删除本人创建的用例", r.get_data(as_text=True))
        with self.app.app_context():
            self.assertFalse(db.session.get(TestCase, cid).is_deleted)
        # 普通用户不得彻底删除
        self.assertEqual(self.client.post(f"/recycle/case/{cid}/purge").status_code, 403)

    # ---------------- R09 / R10 ----------------
    def test_12_user_management(self):
        self.login()
        r = self.client.post("/admin/users/new",
                             data={"username": "tester2", "password": "Tester2@123",
                                   "real_name": "测试二号", "role": "user"},
                             follow_redirects=True)
        self.assertIn("创建成功", r.get_data(as_text=True))
        # 重复用户名
        r = self.client.post("/admin/users/new",
                             data={"username": "tester2", "password": "Tester2@123"},
                             follow_redirects=True)
        self.assertIn("该用户名已存在", r.get_data(as_text=True))
        # 短密码
        r = self.client.post("/admin/users/new",
                             data={"username": "tester3", "password": "123"}, follow_redirects=True)
        self.assertIn("密码长度不得少于 6 位", r.get_data(as_text=True))

        with self.app.app_context():
            uid = db.session.query(User).filter_by(username="tester2").first().id
            self.assertNotIn("Tester2@123", db.session.query(User)
                             .filter_by(username="tester2").first().password_hash)

        r = self.client.post(f"/admin/users/{uid}/toggle-status", follow_redirects=True)
        self.assertIn("已禁用用户", r.get_data(as_text=True))
        # 被禁用账号不能登录
        self.logout()
        r = self.client.post("/login", data={"username": "tester2", "password": "Tester2@123"},
                             follow_redirects=True)
        self.assertIn("已被禁用", r.get_data(as_text=True))
        self.login()
        self.client.post(f"/admin/users/{uid}/toggle-status", follow_redirects=True)
        r = self.client.post(f"/admin/users/{uid}/reset-password",
                             data={"new_password": "NewPass@123"}, follow_redirects=True)
        self.assertIn("已重置", r.get_data(as_text=True))
        # 删除未被引用的用户
        r = self.client.post(f"/admin/users/{uid}/delete", follow_redirects=True)
        self.assertIn("已删除", r.get_data(as_text=True))
        # 有数据的用户不允许删除
        with self.app.app_context():
            admin_id = db.session.query(User).filter_by(username="admin").first().id
        r = self.client.post(f"/admin/users/{admin_id}/delete", follow_redirects=True)
        self.assertIn("不能删除自己的账号", r.get_data(as_text=True))

    def test_13_operation_logs(self):
        self.login()
        r = self.client.get("/admin/logs")
        text = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("操作日志", text)
        self.assertIn("用户登录", text)
        with self.app.app_context():
            actions = {a for (a,) in db.session.query(OperationLog.action).distinct()}
        for expected in ["用户登录", "新建需求", "生成测试用例", "保存测试用例", "删除测试用例"]:
            self.assertIn(expected, actions, f"缺少日志动作：{expected}")
        # 失败操作也要有记录
        self.assertIn("登录失败", actions)
        self.assertIn("权限拒绝", actions)

        r = self.client.get("/admin/logs?result=failed")
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/admin/logs/export")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])

    def test_14_model_settings(self):
        self.login()
        self.assertEqual(self.client.get("/admin/settings").status_code, 200)
        r = self.client.post("/admin/settings",
                             data={"action": "save", "api_key": "sk-abcdefghijklmnopqrst",
                                   "base_url": "https://api.deepseek.com",
                                   "model": "deepseek-chat", "timeout": 60},
                             follow_redirects=True)
        self.assertIn("模型配置已保存", r.get_data(as_text=True))
        text = self.client.get("/admin/settings").get_data(as_text=True)
        self.assertIn("sk-a********qrst", text)   # 掩码保留前 4 位与后 4 位
        self.assertNotIn("sk-abcdefghijklmnopqrst", text)   # 完整 Key 不回显

        # 非法配置被拒绝
        r = self.client.post("/admin/settings",
                             data={"action": "save", "base_url": "ftp://x", "model": "",
                                   "timeout": 1}, follow_redirects=True)
        self.assertIn("必须以 http:// 或 https:// 开头", r.get_data(as_text=True))

        # 配置后生成入口应启用（此处仅验证状态流转，不再请求真实网络）
        self.assertTrue(self.client.get("/testcases/generate")
                        .get_data(as_text=True).count("尚未配置") == 0)

        # 清除后回退 .env
        r = self.client.post("/admin/settings", data={"action": "clear_key"},
                             follow_redirects=True)
        self.assertIn("已清除系统中的 API Key", r.get_data(as_text=True))

    def test_15_requirement_delete_cascade(self):
        """删除需求时其关联用例一并进入回收站，且仅管理员可执行。"""
        self.login()
        r = self.client.post("/requirements/new",
                             data={"name": "待删除需求", "description": "用于验证级联逻辑删除"},
                             follow_redirects=True)
        rid = self.req_id("REQ-0003")
        self.client.post("/testcases/new",
                         data={"title": "级联用例", "requirement_id": rid},
                         follow_redirects=True)
        cid = self.latest_case_id()

        r = self.client.post(f"/requirements/{rid}/delete", follow_redirects=True)
        self.assertIn("可在回收站中还原", r.get_data(as_text=True))
        with self.app.app_context():
            self.assertTrue(db.session.get(Requirement, rid).is_deleted)
            self.assertTrue(db.session.get(TestCase, cid).is_deleted)
        r = self.client.get("/recycle/?type=requirement")
        self.assertIn("待删除需求", r.get_data(as_text=True))

    def test_16_pages_render(self):
        """所有页面均可正常渲染（4.4 可用性：界面与错误提示完整）。"""
        self.login()
        pages = ["/", "/dashboard", "/requirements/", "/requirements/new",
                 "/testcases/", "/testcases/new", "/testcases/generate",
                 "/recycle/", "/recycle/?type=requirement", "/profile",
                 "/admin/users", "/admin/logs", "/admin/settings"]
        for p in pages:
            r = self.client.get(p)
            self.assertEqual(r.status_code, 200, f"{p} -> {r.status_code}")
            self.assertNotIn("Traceback", r.get_data(as_text=True), p)
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
        # 不存在的资源应给出友好提示而非堆栈
        r = self.client.get("/testcases/999999")
        self.assertEqual(r.status_code, 200)
        self.assertIn("不存在或已被删除", r.get_data(as_text=True))
        r = self.client.get("/no-such-page")
        self.assertEqual(r.status_code, 404)
        self.assertIn("请求的页面不存在", r.get_data(as_text=True))

    def test_17_static_assets(self):
        """前端静态资源（含本地化的 Bootstrap）应可访问。"""
        for path in ["/static/css/app.css", "/static/js/app.js", "/static/js/generate.js",
                     "/static/vendor/bootstrap/bootstrap.min.css",
                     "/static/vendor/bootstrap/bootstrap.bundle.min.js",
                     "/static/vendor/bootstrap-icons/bootstrap-icons.css"]:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
