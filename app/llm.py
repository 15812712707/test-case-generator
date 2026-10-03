"""R03 测试用例自动生成：调用大语言模型（DeepSeek）根据软件需求生成结构化用例。

设计要点（对应说明书 3.3 的约束"异常时提示、不伪造结果"）：
  - 未配置 API Key -> 抛出 LLMConfigError，前端给出明确提示，绝不返回编造内容；
  - 网络 / HTTP / 返回格式异常 -> 抛出 LLMError，携带可读原因；
  - 解析出的用例做字段级规整与校验，保证结构统一。
"""
from __future__ import annotations

import json
import re

import requests
from flask import current_app

SYSTEM_PROMPT = (
    "你是一位资深软件测试工程师，擅长依据软件需求设计结构化测试用例。"
    "你的输出必须是严格合法的 JSON，不要输出任何解释性文字或 Markdown 代码块。"
)

USER_PROMPT_TEMPLATE = """请依据下面的软件需求，设计 {count} 条测试用例。

【需求名称】
{name}

【需求描述】
{description}

【业务规则】
{business_rules}

要求：
1. 覆盖正常场景与异常场景（如必填为空、边界值、权限不足等），至少包含 1 条异常场景。
2. 严格按以下 JSON 结构输出，顶层为对象，键为 "testcases"，值为数组：
{{
  "testcases": [
    {{
      "title": "用例名称，简洁明确",
      "category": "分类，如 功能测试/边界测试/异常测试/权限测试",
      "priority": "high 或 medium 或 low",
      "precondition": "前置条件",
      "steps": ["步骤1", "步骤2", "步骤3"],
      "test_data": "测试数据说明",
      "expected_result": "预期结果"
    }}
  ]
}}
3. steps 必须是字符串数组，每条步骤独立成项，不要带序号前缀。
4. 只输出 JSON，不要有任何多余文字。"""


class LLMError(Exception):
    """模型调用或返回解析失败。"""


class LLMConfigError(LLMError):
    """未配置模型凭据。"""


def resolve_config() -> dict:
    """解析模型配置：数据库设置优先，其次环境变量。

    说明书 5.2 中模型、协议、鉴权与参数格式标记为"待确定"，
    本系统统一采用 DeepSeek 的 OpenAI 兼容接口（/chat/completions）。
    """
    cfg = {
        "api_key": (current_app.config.get("DEEPSEEK_API_KEY") or "").strip(),
        "base_url": (current_app.config.get("DEEPSEEK_BASE_URL") or "").rstrip("/"),
        "model": current_app.config.get("DEEPSEEK_MODEL") or "deepseek-chat",
        "timeout": int(current_app.config.get("DEEPSEEK_TIMEOUT") or 90),
        "source": "环境变量(.env)",
    }
    try:
        from .models import LlmSetting
        setting = LlmSetting.get()
    except Exception:  # 数据库尚未就绪时不阻断页面渲染
        return cfg

    if (setting.api_key or "").strip():
        cfg["api_key"] = setting.api_key.strip()
        cfg["source"] = "系统设置"
    if (setting.base_url or "").strip():
        cfg["base_url"] = setting.base_url.strip().rstrip("/")
    if (setting.model or "").strip():
        cfg["model"] = setting.model.strip()
    if setting.timeout:
        cfg["timeout"] = int(setting.timeout)
    return cfg


def is_configured() -> bool:
    return bool(resolve_config()["api_key"])


def _extract_json(text: str) -> dict:
    """从模型返回中稳健地提取 JSON 对象。"""
    if not text or not text.strip():
        raise LLMError("模型返回内容为空。")
    text = text.strip()
    # 去掉可能的 ```json ... ``` 包裹
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 退一步：截取第一个 { 到最后一个 }
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"模型返回内容不是合法 JSON：{exc}") from exc
    raise LLMError("模型返回内容中未找到 JSON 结构。")


def _normalize(raw: dict) -> list[dict]:
    """将模型返回规整为统一的用例字段列表。"""
    items = raw.get("testcases") if isinstance(raw, dict) else None
    if items is None and isinstance(raw, list):
        items = raw
    if not isinstance(items, list) or not items:
        raise LLMError("模型返回的 JSON 中缺少 testcases 数组或数组为空。")

    results = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        steps = item.get("steps", "")
        if isinstance(steps, list):
            steps_text = "\n".join(str(s).strip() for s in steps if str(s).strip())
        else:
            steps_text = str(steps or "").strip()

        title = str(item.get("title") or "").strip() or f"未命名用例 {idx}"
        priority = str(item.get("priority") or "medium").strip().lower()
        if priority not in ("high", "medium", "low"):
            priority = "medium"
        results.append({
            "title": title[:200],
            "category": (str(item.get("category") or "功能测试").strip() or "功能测试")[:64],
            "priority": priority,
            "precondition": str(item.get("precondition") or "").strip(),
            "steps": steps_text,
            "test_data": str(item.get("test_data") or "").strip(),
            "expected_result": str(item.get("expected_result") or "").strip(),
        })

    if not results:
        raise LLMError("模型返回的用例条目均不可用。")
    return results


def generate_testcases(name: str, description: str, business_rules: str,
                       count: int = 5) -> list[dict]:
    """调用 DeepSeek 生成测试用例。失败时抛 LLMError，绝不返回伪造内容。"""
    conf = resolve_config()
    api_key = conf["api_key"]
    if not api_key:
        raise LLMConfigError(
            "未配置大语言模型凭据（DEEPSEEK_API_KEY）。系统无法调用模型，"
            "因此不会生成任何内容：请在 .env 中配置 API Key，"
            "或由管理员在【系统管理 → 系统设置】中填写后重试。"
        )

    base_url = conf["base_url"].rstrip("/")
    model = conf["model"]
    timeout = conf["timeout"]

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
                count=count,
                name=name or "（未填写）",
                description=description or "（未填写）",
                business_rules=business_rules or "（未填写）",
            )},
        ],
        "temperature": 0.3,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(f"{base_url}/chat/completions", json=payload,
                             headers=headers, timeout=timeout)
    except requests.Timeout as exc:
        raise LLMError(f"调用模型超时（{timeout}s），请稍后重试。") from exc
    except requests.RequestException as exc:
        raise LLMError(f"网络异常，无法连接模型服务：{exc}") from exc

    if resp.status_code != 200:
        snippet = resp.text[:300].replace("\n", " ")
        raise LLMError(f"模型服务返回错误（HTTP {resp.status_code}）：{snippet}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"模型返回结构异常，无法解析：{exc}") from exc

    return _normalize(_extract_json(content))


def test_connection(overrides: dict | None = None) -> str:
    """连通性自检：向模型发送一次最小请求，返回模型回显内容。

    用于管理员在"系统设置"中确认凭据可用，不产生任何测试用例，
    也不会写入用例数据。overrides 可传入界面上尚未保存的临时配置。
    """
    conf = resolve_config()
    for key in ("api_key", "base_url", "model", "timeout"):
        value = (overrides or {}).get(key)
        if value not in (None, ""):
            conf[key] = value
    conf["base_url"] = str(conf["base_url"]).rstrip("/")
    conf["timeout"] = int(conf["timeout"])
    if not conf["api_key"]:
        raise LLMConfigError("未配置 API Key，无法测试连接。")

    payload = {
        "model": conf["model"],
        "messages": [{"role": "user", "content": "请只回复两个字：连通"}],
        "temperature": 0,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {conf['api_key']}",
               "Content-Type": "application/json"}
    try:
        resp = requests.post(f"{conf['base_url']}/chat/completions", json=payload,
                             headers=headers, timeout=min(conf["timeout"], 30))
    except requests.RequestException as exc:
        raise LLMError(f"连接失败：{exc}") from exc
    if resp.status_code != 200:
        raise LLMError(f"模型服务返回 HTTP {resp.status_code}：{resp.text[:200]}")
    try:
        return resp.json()["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"返回结构异常：{exc}") from exc
