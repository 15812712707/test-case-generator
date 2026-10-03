# 基于大语言模型的软件测试用例自动生成与管理系统

依据《软件需求规格说明书 V1.0》实现的完整系统，功能覆盖 R01～R10。

## 一、快速启动

```bash
cd llm-testcase-system

# 1) 安装依赖（Python 3.12+）
pip install -r requirements.txt

# 2) 配置大语言模型（二选一）
cp .env.example .env
#   方式 A：编辑 .env，填写 DEEPSEEK_API_KEY=sk-xxxx
#   方式 B：启动后在【系统管理 → 模型与系统设置】页面填写

# 3) 启动
python run.py
```

启动后访问 <http://127.0.0.1:5000>

| 账号 | 密码 | 角色 |
|---|---|---|
| `admin` | `Admin@123` | 管理员 |
| `tester` | `Tester@123` | 普通用户 |

> 首次启动自动建表并创建上述初始账号，请登录后尽快修改密码。
> 手动初始化：`flask init-db`，写入示例需求：`flask seed-demo`

可选环境变量：`HOST`、`PORT`、`FLASK_DEBUG`、`DATABASE_URL`、`DEEPSEEK_MODEL`、`DEEPSEEK_TIMEOUT`。

## 二、功能与需求对应关系

| 编号 | 功能 | 实现位置 |
|---|---|---|
| R01 | 用户管理（登录/个人信息） | `app/blueprints/auth.py`、`templates/login.html`、`templates/profile.html` |
| R02 | 软件需求管理 | `app/blueprints/requirements.py`、`templates/requirements/` |
| R03 | 测试用例自动生成 | `app/llm.py`、`testcases.generate`、`static/js/generate.js` |
| R04 | 测试用例查看与编辑 | `testcases.detail` / `testcases.edit` |
| R05 | 测试用例保存与管理 | `testcases.save_batch`、`testcases.new`、`testcases.confirm` |
| R06 | 测试用例查询 | `testcases.list_testcases`（关键词/需求/分类/优先级/状态 + 分页） |
| R07 | 测试用例删除 | `testcases.delete`、`testcases.batch_delete`、`app/blueprints/recycle.py` |
| R08 | 测试用例导出 | `testcases.export`（xlsx / csv / json / md） |
| R09 | 角色与权限管理 | `app/security.py`、`app/blueprints/admin.py`、`templates/admin/users.html` |
| R10 | 操作日志 | `app/security.py:log_action`、`admin.logs`、`admin.logs_export` |

## 三、技术栈（对应说明书 2.5）

- 语言：Python 3.12+
- 后端：Flask 3 + Flask-SQLAlchemy + Flask-Login
- 前端：HTML / CSS / JavaScript / Bootstrap 5（已本地化，离线可用）
- 数据库：SQLite + SQLAlchemy ORM
- 大模型：DeepSeek（OpenAI 兼容 `/chat/completions`）
- 前后端交互：HTTP / JSON（生成接口支持 AJAX 返回 JSON）

## 四、目录结构

```
llm-testcase-system/
├── run.py                      # 启动入口（自动建表 + 初始账号）
├── requirements.txt
├── .env.example                # 配置模板（复制为 .env）
├── app/
│   ├── __init__.py             # 应用工厂、蓝图注册、CLI 命令
│   ├── config.py               # 配置（全部来自环境变量）
│   ├── extensions.py           # db / login_manager 单例
│   ├── models.py               # 用户/需求/用例/日志/模型配置
│   ├── security.py             # 权限装饰器、操作日志、编号生成
│   ├── llm.py                  # R03 大模型调用与结果解析
│   ├── blueprints/             # auth / main / requirements / testcases / recycle / admin
│   ├── templates/              # 18 个 Jinja2 页面
│   └── static/                 # 自定义样式脚本 + 本地化 Bootstrap
└── tests/test_e2e.py           # 端到端验证脚本（17 个用例，无需真实 API Key）
```

## 五、说明书"待确定"项的落地选择

说明书中标注"待确定"的条目，本项目做如下选择，便于直接运行：

| 说明书条目 | 选择 | 说明 |
|---|---|---|
| 1.5 / 3.1 认证方式 | Flask-Login 会话认证 + `pbkdf2:sha256` 密码摘要 | 不存储、不回显明文密码 |
| 3.2 需求字段与长度 | 名称(必填,≤200)、描述、业务规则 | 描述是生成用例的主要输入 |
| 3.3 模型与接口 | DeepSeek `/chat/completions`，`response_format=json_object` | 严格 JSON 解析，失败即报错 |
| 3.5 用例数据结构 | 名称/前置条件/步骤/测试数据/预期结果/分类/优先级/状态/来源 | 每条记录带唯一编号 `TC-xxxx` |
| 3.6 查询字段与分页 | 关键词(名称/编号/预期结果)+需求+分类+优先级+状态，10 条/页 | |
| 3.7 是否逻辑删除 | **逻辑删除** + 回收站（可还原；仅管理员可彻底删除） | 删除前二次确认，越权拒绝 |
| 3.8 导出格式 | xlsx / csv / json / markdown | csv 带 BOM，Excel 直接打开不乱码 |
| 3.9 角色与权限矩阵 | 管理员 / 普通用户两级，矩阵见【用户与角色】页面 | 普通用户仅能操作本人创建的数据 |
| 5.2 模型鉴权与参数 | Bearer Token，地址/模型/超时均可在界面配置 | Key 在界面中仅显示掩码 |
| 5.3 数据库 | SQLite（可经 `DATABASE_URL` 换成 MySQL/PostgreSQL） | |
| 4.6 日志保存周期 | 支持按天筛选与 CSV 导出，默认保留全部 | |

## 六、关键设计说明（对应非功能需求）

1. **不伪造结果（3.3 异常处理）**
   未配置 API Key、网络异常、超时、返回结构异常、JSON 解析失败等情况，
   一律返回明确错误原因，**不会生成任何用例数据**。

2. **处理状态可见（4.1 性能需求）**
   生成过程采用异步提交，页面显示"正在调用大模型…"状态，
   成功显示返回条数，失败显示具体原因。

3. **数据不丢失（4.3 可靠性需求）**
   生成失败不影响已保存数据；所有写操作均有事务保护；
   删除为逻辑删除，可还原。

4. **数据一致性（6.2）**
   删除需求时级联逻辑删除其关联用例；
   创建过数据的用户不允许物理删除（改为禁用）。

5. **模块相对独立（4.5 可维护性）**
   用户、需求、模型调用、用例管理、日志分属独立蓝图/模块。

## 七、运行验证

```bash
python tests/test_e2e.py
```

17 个端到端用例覆盖 R01～R10 的全部主流程与异常分支，
通过桩响应模拟模型返回，因此**无需真实 API Key 即可完整验证**。

## 八、已知限制

- 开发服务器仅用于本地运行；生产部署建议使用 gunicorn/uWSGI + Nginx。
- 生成任务为进程内异步，未引入 Celery 等任务队列；单机小规模使用足够。
- 大模型输出质量取决于需求描述与业务规则的完整程度，生成结果须人工审核后保存。
