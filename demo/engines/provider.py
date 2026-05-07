import json
import os
import re
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional


def _extract_json_from_text(text: str) -> Optional[str]:
    candidates = []

    # 模式1: ```json ... ```
    for m in re.finditer(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL):
        candidates.append(m.group(1).strip())

    # 模式2: 查找裸 JSON 数组 [...]
    for m in re.finditer(r"(\[[\s\S]*?\])", text, re.DOTALL):
        candidates.append(m.group(1).strip())

    # 模式3: 查找裸 JSON 对象 {...}
    for m in re.finditer(r"(\{[\s\S]*?\})", text, re.DOTALL):
        candidates.append(m.group(1).strip())

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
            _log("_extract_json", f"✅ 从文本中成功解析 JSON, 类型={type(parsed).__name__}, 长度={len(candidate)}")
            return candidate
        except (json.JSONDecodeError, ValueError):
            continue

    return None


def _log(step: str, msg: str = "", data: Any = None) -> None:
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    parts = [f"[{ts}]", f"[Provider-{step}]"]
    if msg:
        parts.append(msg)
    if data is not None:
        preview = str(data)[:200].replace("\n", "\\n")
        parts.append(f"| {preview}")
    print(" ".join(parts), file=sys.stderr)


class LLMProvider:
    def __init__(self, provider_type: str = "anthropic"):
        self.provider_type = provider_type
        _log("__init__", f"provider_type={provider_type}")
        if provider_type == "openai":
            from openai import OpenAI
            import httpx
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            api_key = os.getenv("OPENAI_API_KEY")
            ssl_verify_str = os.getenv("OPENAI_SSL_VERIFY", "true")
            ssl_verify = ssl_verify_str.lower() not in ("false", "0", "no")
            _log("__init__", f"OPENAI_BASE_URL={base_url}, API_KEY={'***' + str(api_key)[-4:] if api_key else '(not set)'}, SSL_VERIFY={ssl_verify}")
            if ssl_verify:
                self.client = OpenAI(api_key=api_key, base_url=base_url) if api_key else OpenAI(base_url=base_url)
            else:
                _log("__init__", "⚠️  SSL 验证已禁用（适用于企业代理/自签名证书环境）")
                http_client = httpx.Client(verify=False)
                self.client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client) if api_key else OpenAI(base_url=base_url, http_client=http_client)
        else:
            import anthropic
            self.client = anthropic.Anthropic()

    def _convert_system(self, system: Any) -> str:
        if isinstance(system, list):
            parts = []
            for item in system:
                if isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
            return "\n".join(parts)
        if isinstance(system, str):
            return system
        return ""

    def messages_create(self, model: str, max_tokens: int, system=None, messages=None, **kwargs):
        if self.provider_type == "openai":
            oai_messages = []
            if system:
                sys_text = self._convert_system(system)
                oai_messages.append({"role": "system", "content": sys_text})
            if messages:
                oai_messages.extend(messages)
            kwargs.pop("thinking", None)
            kwargs.pop("output_config", None)

            _log("messages_create",
                 f"model={model}, max_tokens={max_tokens}, messages_count={len(oai_messages)}",
                 f"last_user_msg={messages[-1]['content'][:120] if messages else 'N/A'}" if not system else
                 f"system_preview={sys_text[:100]}...")

            try:
                response = self.client.chat.completions.create(
                    model=model, max_tokens=max_tokens, messages=oai_messages, **kwargs
                )
                _log("messages_create", "OpenAI 请求成功",
                     f"usage={response.usage}, finish_reason={response.choices[0].finish_reason}")
                return response
            except Exception as e:
                _log("messages_create", f"OpenAI 请求失败: {type(e).__name__}: {e}")
                traceback.print_exc(file=sys.stderr)
                raise
        else:
            _log("messages_create",
                 f"model={model}, max_tokens={max_tokens}, system_prompt_len={len(self._convert_system(system))}")
            try:
                response = self.client.messages.create(
                    model=model, max_tokens=max_tokens, system=system, messages=messages, **kwargs
                )
                _log("messages_create", "Anthropic 请求成功")
                return response
            except Exception as e:
                _log("messages_create", f"Anthropic 请求失败: {type(e).__name__}: {e}")
                traceback.print_exc(file=sys.stderr)
                raise

    def extract_text(self, response) -> str:
        _log("extract_text", f"response_type={type(response).__name__}")
        if self.provider_type == "openai":
            message = response.choices[0].message
            content = message.content
            _log("extract_text", f"content type={type(content).__name__}, value={repr(content)[:100]}")
            if content and content.strip():
                text = content.strip()
                _log("extract_text", f"extracted_len={len(text)}", f"preview={text[:80]}...")
                return text
            # DeepSeek 推理模型: 内容在 reasoning_content 中(可能混有推理过程)
            reasoning = getattr(message, "reasoning_content", None) or ""
            if reasoning:
                _log("extract_text", f"reasoning_content 长度={len(reasoning)}", f"preview={reasoning[:80]}...")
                # 优先尝试从推理文本中提取 JSON
                found = _extract_json_from_text(reasoning)
                if found:
                    _log("extract_text", "✅ 从 reasoning_content 中成功提取 JSON")
                    return found
                _log("extract_text", "⚠️ reasoning_content 中未发现 JSON，返回完整文本（可能需要在调用方进行后处理）")
                return reasoning.strip()
            _log("extract_text", "⚠️ content 和 reasoning_content 均为空，转储完整 message 结构")
            for attr in dir(message):
                if not attr.startswith("_"):
                    try:
                        val = getattr(message, attr)
                        _log("extract_text", f"  message.{attr}={repr(val)[:200]}")
                    except Exception:
                        pass
            return ""
        text = response.content[0].text.strip()
        _log("extract_text", f"extracted_len={len(text)}", f"preview={text[:80]}...")
        return text

    def extract_content_blocks(self, response) -> List[Dict[str, str]]:
        if self.provider_type == "openai":
            message = response.choices[0].message
            content = message.content or ""
            reasoning = getattr(message, "reasoning_content", None) or ""
            blocks = []
            if reasoning:
                blocks.append({"type": "thinking", "text": reasoning.strip()})
            if content:
                blocks.append({"type": "text", "text": content.strip()})
            if not blocks:
                _log("extract_content_blocks", "⚠️ 无可用内容，返回空 text block")
                blocks.append({"type": "text", "text": ""})
            return blocks
        # Anthropic 路径
        blocks = []
        for block in response.content:
            if block.type == "thinking":
                blocks.append({
                    "type": "thinking",
                    "text": getattr(block, "summary", "") or getattr(block, "thinking", ""),
                })
            elif block.type == "text":
                blocks.append({"type": "text", "text": block.text})
        _log("extract_content_blocks", f"blocks_count={len(blocks)}")
        return blocks


def get_provider() -> LLMProvider:
    provider_type = os.getenv("LLM_PROVIDER", "anthropic")
    _log("get_provider", f"LLM_PROVIDER={provider_type}")
    return LLMProvider(provider_type)
