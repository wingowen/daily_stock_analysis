# -*- coding: utf-8 -*-
"""精确诊断 AlphaSift Pipeline 内部 LLM ranking 的调用参数。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import setup_env
setup_env()

from alphasift.config import Config

config = Config.from_env()

print("=" * 60)
print("AlphaSift Pipeline LLM Ranking 调用参数")
print("=" * 60)

print(f"\nconfig.llm_api_key: {'[SET]' if config.llm_api_key else '[EMPTY]'}")
print(f"config.llm_model: {config.llm_model}")
print(f"config.llm_base_url: {config.llm_base_url or '(default)'}")
print(f"config.llm_channels count: {len(config.llm_channels)}")
if config.llm_channels:
    for ch in config.llm_channels:
        print(f"  channel: {ch.get('name')}, models={ch.get('models')}, keys={[k[:4]+'...' for k in (ch.get('api_keys') or [])]}")

# 模拟 rank_candidates 调用
from alphasift.ranker import rank_candidates, Pick

print("\n模拟 LLM ranking 调用:")
print(f"  rank_candidates(candidates, hints, api_key='{config.llm_api_key[:4] if config.llm_api_key else ''}...', model='{config.llm_model}', base_url='{config.llm_base_url or 'default'}', channels={json.dumps(config.llm_channels, indent=4)[:200]}...)")

# 拦截 litellm.completion 调用
original_completion = None
captured_args = {}

def capture_litellm_completion(*args, **kwargs):
    captured_args['args'] = args
    captured_args['kwargs'] = kwargs
    print(f"\nlitellm.completion 被调用时参数:")
    print(f"  model: {kwargs.get('model')}")
    print(f"  api_key: {'[SET]' if kwargs.get('api_key') else '[EMPTY]'}")
    print(f"  api_base: {kwargs.get('api_base') or '(default)'}")
    print(f"  messages count: {len(kwargs.get('messages', []))}")
    print(f"  response_format: {kwargs.get('response_format')}")
    print(f"  timeout: {kwargs.get('timeout')}")
    
    # 实际调用
    try:
        import litellm
        response = litellm.completion(**kwargs)
        return response
    except Exception as exc:
        print(f"\n  ❌ LLM 调用失败: {exc}")
        raise

try:
    with patch('alphasift.ranker.litellm.completion', side_effect=capture_litellm_completion):
        picks = [Pick(code="601318", name="中国平安", screen_score=75.0)]
        rank_candidates(
            picks,
            "测试排序",
            config.llm_api_key,
            config.llm_model,
            config.llm_base_url,
            context="",
            rank_weight=config.llm_rank_weight,
            max_retries=config.llm_max_retries,
            min_coverage=config.llm_min_coverage,
            fallback_models=config.llm_fallback_models,
            temperature=config.llm_temperature,
            json_mode=config.llm_json_mode,
            silent=config.llm_silent,
            channels=config.llm_channels,
            config_path=str(config.llm_config_path or ""),
            timeout_sec=config.llm_timeout_sec,
            max_tokens=config.llm_max_tokens,
        )
except Exception as exc:
    print(f"\nrank_candidates 抛出异常: {exc}")
