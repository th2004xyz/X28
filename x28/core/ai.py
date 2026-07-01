"""AI 生成适配层: 支持 Gemini / OpenAI / Anthropic 三家 API。

直接用 requests 调用，无重 SDK，保持轻量。
"""

import logging

import requests

log = logging.getLogger("x28.ai")


class AIGenerator:
    """多模型 AI 生成适配器。

    Args:
        provider: gemini | openai | anthropic
        api_key:  对应提供商的 API Key
        model:    模型名 (留空使用默认)
        base_url: OpenAI 自定义中转地址 (可选)
    """

    def __init__(self, provider: str = "gemini", api_key: str = "",
                 model: str = "", base_url: str = ""):
        self.provider = provider.lower().strip()
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.base_url = base_url.strip()

    def generate(self, prompt: str) -> str:
        """根据 provider 路由到对应实现。"""
        if not self.api_key:
            raise Exception(
                f"未配置 {self.provider.upper()} API Key！请检查项目目录下的 .env 文件。")
        log.info("调用 %s 生成内容 (model=%s, prompt=%d chars)",
                 self.provider, self.model or "(默认)", len(prompt))
        if self.provider == "gemini":
            return self._gemini(prompt)
        if self.provider == "openai":
            return self._openai(prompt)
        if self.provider == "anthropic":
            return self._anthropic(prompt)
        raise Exception(f"不支持的 AI 提供商: {self.provider}")

    # ---------- Gemini ----------
    def _gemini(self, prompt: str) -> str:
        model = self.model or "gemini-3.5-flash"
        url = (f"https://generativelanguage.googleapis.com/v1beta"
               f"/models/{model}:generateContent?key={self.api_key}")
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            headers={"Content-Type": "application/json"},
            timeout=45,
        )
        if resp.status_code != 200:
            raise Exception(f"Gemini API 错误 ({resp.status_code}): {resp.text[:300]}")
        try:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise Exception(f"Gemini 响应格式异常: {resp.text[:300]}")

    # ---------- OpenAI ----------
    def _openai(self, prompt: str) -> str:
        base = self.base_url or "https://api.openai.com/v1"
        resp = requests.post(
            f"{base.rstrip('/')}/chat/completions",
            json={"model": self.model or "gpt-4o-mini",
                  "messages": [{"role": "user", "content": prompt}]},
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            timeout=45,
        )
        if resp.status_code != 200:
            raise Exception(f"OpenAI API 错误 ({resp.status_code}): {resp.text[:300]}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise Exception(f"OpenAI 响应格式异常: {resp.text[:300]}")

    # ---------- Anthropic ----------
    def _anthropic(self, prompt: str) -> str:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            json={"model": self.model or "claude-5-fable", "max_tokens": 1024,
                  "messages": [{"role": "user", "content": prompt}]},
            headers={"x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            timeout=45,
        )
        if resp.status_code != 200:
            raise Exception(f"Anthropic API 错误 ({resp.status_code}): {resp.text[:300]}")
        try:
            return resp.json()["content"][0]["text"]
        except (KeyError, IndexError):
            raise Exception(f"Anthropic 响应格式异常: {resp.text[:300]}")
