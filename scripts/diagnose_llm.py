# -*- coding: utf-8 -*-
"""诊断 AlphaSift 的 LLM 配置，确认 ranking 为什么返回空 JSON。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import setup_env
setup_env()

# 导入 AlphaSift 的 Config
from alphasift.config import Config, _resolve_llm_model, _resolve_llm_api_key, _resolve_llm_base_url, _parse_llm_channels_env

config = Config.from_env()

print("=" * 60)
print("AlphaSift LLM 配置诊断")
print("=" * 60)

print(f"\n1. has_llm_config(): {config.has_llm_config()}")
print(f"   llm_api_key: {'[SET]' if config.llm_api_key else '[EMPTY]'} (len={len(config.llm_api_key)})")
print(f"   llm_model: {config.llm_model}")
print(f"   llm_base_url: {config.llm_base_url or '(default)'}")
print(f"   llm_channels: {json.dumps(config.llm_channels, ensure_ascii=False, indent=2)}")
print(f"   llm_json_mode: {config.llm_json_mode}")
print(f"   llm_temperature: {config.llm_temperature}")
print(f"   llm_max_retries: {config.llm_max_retries}")
print(f"   llm_min_coverage: {config.llm_min_coverage}")
print(f"   llm_timeout_sec: {config.llm_timeout_sec}")

# 检查环境变量
print("\n2. 相关环境变量:")
for key in sorted(os.environ.keys()):
    if 'LLM' in key or 'LITELLM' in key or 'AGENT' in key:
        val = os.environ[key]
        # 隐藏 API key 的完整值
        if 'KEY' in key and len(val) > 10:
            val = val[:4] + '...' + val[-4:]
        print(f"   {key}={val}")

# 模拟一次 LLM 调用测试
print("\n3. 测试 LLM 连通性:")
try:
    import litellm
    
    model = config.llm_model
    api_key = config.llm_api_key
    base_url = config.llm_base_url
    
    messages = [{"role": "user", "content": "返回JSON: {\"test\": true}"}]
    
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 100,
        "timeout": 30,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    
    response = litellm.completion(**kwargs)
    content = response.choices[0].message.content or ""
    print(f"   模型: {model}")
    print(f"   Base URL: {base_url or '(default)'}")
    print(f"   响应: {content[:200]}")
    
    # 检查是否能解析 JSON
    try:
        parsed = json.loads(content)
        print(f"   JSON 解析: 成功 -> {parsed}")
    except json.JSONDecodeError:
        print(f"   JSON 解析: 失败（这是 LLM ranking 失败的原因！）")
        
except Exception as exc:
    print(f"   错误: {exc}")
    import traceback
    traceback.print_exc()

print("\n4. 结论:")
if not config.has_llm_config():
    print("   ❌ AlphaSift 未检测到有效的 LLM 配置")
elif not config.llm_api_key:
    print("   ❌ llm_api_key 为空")
else:
    print("   ✅ LLM 配置看起来正常")
