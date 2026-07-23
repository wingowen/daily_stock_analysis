# -*- coding: utf-8 -*-
"""精确诊断 AlphaSift Config 内部 LLM 配置。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import setup_env
setup_env()

from alphasift.config import Config

config = Config.from_env()

print("=" * 60)
print("AlphaSift Config 内部 LLM 配置")
print("=" * 60)

print(f"\nhas_llm_config(): {config.has_llm_config()}")
print(f"llm_api_key: {'[SET]' if config.llm_api_key else '[EMPTY]'}")
print(f"llm_model: {config.llm_model}")
print(f"llm_base_url: {config.llm_base_url or '(default)'}")
print(f"llm_channels count: {len(config.llm_channels)}")

if config.llm_channels:
    for ch in config.llm_channels:
        print(f"  channel: {ch.get('name')}")
        print(f"    models: {ch.get('models')}")
        print(f"    api_keys: {[k[:4]+'...' if len(k)>8 else k for k in (ch.get('api_keys') or [])]}")
        print(f"    base_url: {ch.get('base_url')}")

# 测试 AlphaSift 内部 LLM 调用
print("\n测试 AlphaSift 内部 litellm.completion:")
try:
    import litellm
    
    kwargs = {
        "model": config.llm_model,
        "messages": [{"role": "user", "content": "返回JSON: {\"test\": true}"}],
        "temperature": 0.2,
        "max_tokens": 100,
        "timeout": 30,
    }
    if config.llm_api_key:
        kwargs["api_key"] = config.llm_api_key
    if config.llm_base_url:
        kwargs["base_url"] = config.llm_base_url
    
    print(f"  使用参数: model={kwargs['model']}, api_key={'[SET]' if 'api_key' in kwargs else '[EMPTY]'}, base_url={kwargs.get('base_url', '(default)')}")
    
    response = litellm.completion(**kwargs)
    content = response.choices[0].message.content or ""
    print(f"  响应: {content[:200]}")
    
    try:
        parsed = json.loads(content)
        print(f"  JSON 解析: 成功 -> {parsed}")
    except json.JSONDecodeError:
        print(f"  JSON 解析: 失败")
        
except Exception as exc:
    print(f"  错误: {exc}")
