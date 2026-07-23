# -*- coding: utf-8 -*-
"""在 screen_then_analyze 运行期间注入诊断日志。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import setup_env
setup_env()

# 在导入 AlphaSift 之前 patch ranker 模块
import alphasift.ranker as ranker_module

_original_call_llm = None

def patched_call_llm(prompt, api_key, model, base_url, **kwargs):
    print(f"\n[DIAG] _call_llm called with:")
    print(f"  api_key: {'[SET]' if api_key else '[EMPTY]'} (len={len(api_key) if api_key else 0})")
    print(f"  model: {model}")
    print(f"  base_url: {base_url or '(default)'}")
    print(f"  channels count: {len(kwargs.get('channels', []))}")
    
    # 实际调用
    try:
        result = _original_call_llm(prompt, api_key, model, base_url, **kwargs)
        print(f"  [DIAG] LLM response (first 200 chars): {result[:200]}")
        return result
    except Exception as exc:
        print(f"  [DIAG] LLM exception: {exc}")
        raise

def main():
    global _original_call_llm
    _original_call_llm = ranker_module._call_llm
    ranker_module._call_llm = patched_call_llm
    
    # 现在导入并运行 AlphaSift
    from alphasift.config import Config
    config = Config.from_env()
    
    print(f"Config llm_api_key: {'[SET]' if config.llm_api_key else '[EMPTY]'}")
    print(f"Config llm_model: {config.llm_model}")
    print(f"Config llm_base_url: {config.llm_base_url or '(default)'}")
    
    from alphasift.pipeline import screen
    from alphasift.dsa_adapter import run_screen
    
    kwargs = {"market": "cn", "max_output": 12, "use_llm": True}
    
    # 调用 screen
    result = screen("balanced_alpha", **kwargs)
    
    print(f"\nScreen result candidates: {len(result.get('candidates', []))}")
    for c in result.get('candidates', [])[:3]:
        print(f"  {c.get('code')} {c.get('name')}: screen_score={c.get('score')}, llm_score={c.get('llm_score')}")

if __name__ == "__main__":
    main()
