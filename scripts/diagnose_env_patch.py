# -*- coding: utf-8 -*-
"""诊断 screen_then_analyze 运行时的环境变量状态。"""
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
print("screen_then_analyze 运行前环境变量")
print("=" * 60)

# 在 _call_alphasift_screen 之前
print(f"\nLLM_API_KEY: {'[SET]' if os.getenv('LLM_API_KEY') else '[EMPTY]'}")
print(f"OPENAI_API_KEY: {'[SET]' if os.getenv('OPENAI_API_KEY') else '[EMPTY]'}")
print(f"LLM_BASE_URL: {os.getenv('LLM_BASE_URL') or '(empty)'}")
print(f"OPENAI_BASE_URL: {os.getenv('OPENAI_BASE_URL') or '(empty)'}")

# 模拟 _call_alphasift_screen 的环境切换
from src.services.alphasift_service import (
    _alphasift_runtime_env,
    _alphasift_dsa_daily_history_provider,
    _alphasift_litellm_headers,
)

runtime_env_updates = {}

def capture_env():
    global runtime_env_updates
    runtime_env_updates = {
        'LLM_API_KEY': os.getenv('LLM_API_KEY', ''),
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY', ''),
        'LLM_BASE_URL': os.getenv('LLM_BASE_URL', ''),
        'OPENAI_BASE_URL': os.getenv('OPENAI_BASE_URL', ''),
        'LITELLM_MODEL': os.getenv('LITELLM_MODEL', ''),
    }

with _alphasift_runtime_env(config, max_results=12):
    capture_env()
    print("\n进入 _alphasift_runtime_env 后的环境变量:")
    for k, v in runtime_env_updates.items():
        if v:
            if 'KEY' in k and len(v) > 8:
                v = v[:4] + '...' + v[-4:]
        print(f"  {k}: {v}")

print("\n结论:")
if runtime_env_updates.get('LLM_API_KEY'):
    print("  ✅ LLM_API_KEY 已设置")
else:
    print("  ❌ LLM_API_KEY 为空")
