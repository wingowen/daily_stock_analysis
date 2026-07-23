# -*- coding: utf-8 -*-
"""检查 DSA adapter 扩展的 Config 属性。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import setup_env
setup_env()

from alphasift.config import Config
config = Config.from_env()

print("=" * 60)
print("AlphaSift Config 属性检查")
print("=" * 60)

# 列出所有属性
attrs = [a for a in dir(config) if not a.startswith('_')]
print(f"\nConfig 共有 {len(attrs)} 个属性:")
for attr in sorted(attrs):
    val = getattr(config, attr)
    if isinstance(val, (list, dict)):
        print(f"  {attr}: {type(val).__name__} (len={len(val)})")
    elif isinstance(val, str) and len(val) > 50:
        print(f"  {attr}: '{val[:50]}...'")
    else:
        print(f"  {attr}: {val}")
