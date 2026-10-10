"""LLM 客户端 — 智谱云 API / 任何 OpenAI 兼容 endpoint。

只暴露本管线需要的 `_chat(system, user, ...)` 一个调用面
(逐页 SVG 生成 / 批量 KPI 抽取共用)。配置读仓库根 .env:

     LLM_BACKEND=glm          # 启用真实调用 (缺省 stub 报错提示)
     GLM_API_KEY=...          # 智谱云 key (id.secret) 或兼容端点 token
     GLM_MODEL=glm-5.3-flash  # 可选
     GLM_BASE_URL=            # 可选; 空 → 智谱云
"""
from __future__ import annotations
import os
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """读仓库根 .env (不覆盖已有环境变量)。"""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

ZHIPU_CLOUD_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
# "始终思考"模型 (关思考报 400): disable_thinking 对它们 = {"level":"low"}
ALWAYS_THINKING_MODELS = {"glm-5.3", "glm-5.3-flash"}


def _is_zhipu_cloud(base_url: str, api_key: str, model: str) -> bool:
    """识别是否走智谱云 (JWT 鉴权); 显式配置其他端点一律按 Bearer 处理。"""
    if "open.bigmodel.cn" in base_url or "z.ai" in base_url:
        return True
    if base_url:
        return False
    if api_key and "." in api_key:
        return True
    return model.lower() in {"glm-4", "glm-4-plus", "glm-4-flash", "glm-4-long",
                             "glm-4.5", "glm-4.6", "glm-4.1", "glm-4.7",
                             "glm-5", "glm-5.1", "glm-5.2", "glm-5.3",
                             "glm-5.3-flash"}


def _zhipu_jwt(api_key: str) -> str:
    """智谱 api_key (id.secret) → 1 小时 JWT。"""
    try:
        import jwt as pyjwt
    except ImportError as e:
        raise RuntimeError("智谱云鉴权需要 PyJWT: pip install 'PyJWT[crypto]'") from e
    api_id, api_secret = api_key.split(".", 1)
    payload = {
        "api_key": api_id,
        "exp": int(round(time.time() * 1000)) + 60 * 60 * 1000,
        "timestamp": int(round(time.time() * 1000)),
    }
    return pyjwt.encode(
        payload, api_secret, algorithm="HS256",
        headers={"alg": "HS256", "sign_type": "SIGN"},
    )


class LLMClient:
    """OpenAI 兼容 chat 客户端 (智谱云自动 JWT)。"""

    def __init__(self, model: str | None = None):
        self.api_key = os.getenv("GLM_API_KEY", "")
        self.base_url = os.getenv("GLM_BASE_URL", "").rstrip("/")
        if not self.base_url and self.api_key:
            self.base_url = ZHIPU_CLOUD_BASE_URL
        elif not self.base_url:
            raise RuntimeError(
                "未配置模型: 复制 .env.example 为 .env 并填 GLM_API_KEY "
                "(或设置 GLM_BASE_URL 指向 OpenAI 兼容端点)")
        self.model = model or os.getenv("GLM_MODEL", "glm-5.3-flash")
        self.is_cloud = _is_zhipu_cloud(self.base_url, self.api_key, self.model)
        # 始终思考模型即使 low 档, 大 prompt 也可能超时 → 超时档上调
        self.timeout = 300.0 if self.model.lower() in ALWAYS_THINKING_MODELS else 180.0
        self._token: str | None = None
        self._token_exp: float = 0

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if not self.is_cloud:
            if self.api_key:
                h["Authorization"] = f"Bearer {self.api_key}"
            return h
        now = time.time()
        if not self._token or now >= self._token_exp - 300:
            self._token = _zhipu_jwt(self.api_key)
            self._token_exp = now + 3600
        h["Authorization"] = f"Bearer {self._token}"
        return h

    def _chat(self, system: str, user: str, *, json_mode: bool = False,
              max_retries: int = 2, disable_thinking: bool = False,
              temperature: float = 0.2, timeout: float | None = None) -> str:
        """一次 chat 调用: 429 指数退避 / 5xx 短退避 / thinking 参数自动降级。"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        _m = self.model.lower()
        use_low = disable_thinking and self.is_cloud and _m in ALWAYS_THINKING_MODELS
        use_off = disable_thinking and self.is_cloud and not use_low
        use_qwen_off = _m.startswith("qwen") and not self.is_cloud
        eff_timeout = timeout if timeout is not None else self.timeout
        url = f"{self.base_url}/chat/completions"
        tried_off = False
        last_exc: Exception | None = None
        for attempt in range(max_retries + 3):
            if use_qwen_off:
                payload["chat_template_kwargs"] = {"enable_thinking": False}
            elif use_low:
                payload["thinking"] = {"level": "low"}
            elif use_off and not tried_off:
                payload["thinking"] = {"type": "disabled"}
            elif "thinking" in payload and tried_off:
                del payload["thinking"]
            if tried_off and "chat_template_kwargs" in payload:
                del payload["chat_template_kwargs"]
            try:
                with httpx.Client(timeout=eff_timeout) as client:
                    resp = client.post(url, headers=self._headers(), json=payload)
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                last_exc = e
                code = e.response.status_code if e.response else 0
                if code == 400 and use_off and not tried_off:
                    tried_off = True
                    continue
                if code == 429:
                    if attempt < max_retries + 2:
                        time.sleep(2 * (2 ** attempt))
                        continue
                    raise RuntimeError(f"限流(429) 退避 {max_retries + 2} 次仍失败") from e
                if code in (500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(3)
                    continue
                body = e.response.text[:300] if e.response else ""
                raise RuntimeError(f"LLM 调用失败 [{code}]: {body}") from e
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                if attempt < max_retries:
                    time.sleep(3)
                    continue
                raise RuntimeError(f"LLM 超时/连接失败: {e}") from e
        raise RuntimeError(f"LLM 重试 {max_retries} 次仍失败: {last_exc}")
