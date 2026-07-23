# -*- coding: utf-8 -*-
"""AlphaSift Config 适配器。

将 AlphaSift 原生 Config 的属性名转换为 DSA adapter 期望的格式，
避免修改原有项目代码。
"""
from __future__ import annotations

from typing import Any


class AlphasiftConfigAdapter:
    """适配 AlphaSift Config 与 DSA adapter 之间的属性名差异。

    AlphaSift Config 使用 llm_model, llm_fallback_models 等属性，
    DSA adapter 代码中引用了 litellm_model, llm_model_list 等不存在的属性。

    本适配器通过 getattr 包装提供兼容访问。
    """

    def __init__(self, config: Any) -> None:
        self._config = config

    def __getattr__(self, name: str) -> Any:
        """代理到原始 Config，处理属性名映射。"""
        # 属性名映射：AlphaSift 期望的名称 -> DSA Config 实际名称
        name_map = {
            'llm_model': 'litellm_model',
            'llm_fallback_models': 'litellm_fallback_models',
            'llm_config_path': 'litellm_config_path',
            'llm_model_list': None,  # 不存在，返回 None
            'gemini_api_keys': None,
            'anthropic_api_keys': None,
            'openai_api_keys': None,
            'deepseek_api_keys': None,
            'openai_base_url': None,
        }

        if name in name_map:
            target = name_map[name]
            if target is None:
                return None
            return getattr(self._config, target, None)

        # 其他属性直接代理
        return getattr(self._config, name)
