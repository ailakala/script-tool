import json
import re


def extract_json(response: str) -> dict:
    """从 AI 响应中稳健提取 JSON 对象。

    支持以下格式：
    1. ```json{...}```  / ```{...}``` 代码块
    2. 纯 JSON 文本
    3. 文本中嵌入的首个 {...} 对象

    解析失败时打印诊断信息并返回空 dict。
    """
    if not response or not response.strip():
        print("[extract_json] WARNING: AI 返回了空响应")
        return {}

    text = response.strip()

    # 策略 1：提取 ```json ... ``` 或 ``` ... ``` 代码块
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        text = m.group(1).strip()
        print("[extract_json] 策略1（代码块）匹配成功")

    # 策略 2：提取首个完整的 {...} JSON 对象（处理嵌套）
    if not text.startswith('{'):
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            text = m.group(0)
            print("[extract_json] 策略2（花括号提取）匹配成功")
        else:
            print("[extract_json] WARNING: 策略1和2均未匹配到 JSON 结构，将尝试直接解析原始文本")
            print(f"[extract_json] 原始响应前 500 字符：\n{response[:500]}")

    # 策略 3：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[extract_json] ERROR: JSON 解析失败 — {e}")
        print(f"[extract_json] 待解析文本前 500 字符：\n{text[:500]}")
        print(f"[extract_json] 原始响应前 500 字符：\n{response[:500]}")
        return {}
