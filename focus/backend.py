"""Focus Agent — 后端抽象层（实施手册 §6 预留）

统一模型推理接口，屏蔽 MLX/llama.cpp/ollama 差异。
Phase 2 用 MLX 后端（本地 Ornith-9B-mlx-4Bit）。
Phase 6+ 适配 Windows 时可新增 llama_cpp/ollama 后端，不改上层。

实现要点：
- generate() 流式回调，返回生成文本 + finish_reason
- 不缓存 KV（每念头独立 prefill，念头后 KV 自然丢弃）
"""

from __future__ import annotations

import abc
from loguru import logger
from typing import Callable, Optional

# 流式回调：收到增量文本
TokenCB = Callable[[str], None]


class BackendError(Exception):
    """后端调用失败（模型未加载/推理错误）。"""


class BaseBackend(abc.ABC):
    """模型后端抽象。"""

    name: str = "base"

    # KV 缓存支持标志（任务书 §5：系统KV永驻+念头KV丢弃）
    supports_kv_cache: bool = False

    @abc.abstractmethod
    def load(self) -> None:
        """加载模型（幂等）。"""

    # ── KV 缓存协议（supports_kv_cache=True 时实现）──
    def kv_save_system(self, prompt: str) -> None:
        """把 prompt 的 KV 存为系统基线（仅建一次）。"""

    def kv_restore_system(self) -> None:
        """恢复系统基线（丢弃念头 KV）。"""

    @abc.abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 2000,
        stop: Optional[list[str]] = None,
        on_token: Optional[TokenCB] = None,
        use_kv: bool = False,
        kv_prompt: str = "",
    ) -> tuple[str, str]:
        """生成文本。

        Args:
            use_kv: 是否用 KV 续接（supports_kv_cache 后端启用）。
            kv_prompt: KV 续接时的完整 prompt（与 prompt 相同，供缓存层区分）。

        Returns:
            (text, finish_reason) — finish_reason ∈ {stop, length, eos}
        """

    @abc.abstractmethod
    def unload(self) -> None:
        """释放模型（Phase 6+ 跨平台切换用）。"""

    @abc.abstractmethod
    def stats(self) -> dict:
        """推理统计（tokens/耗时）。"""


class MLXBackend(BaseBackend):
    """MLX 本地推理后端。"""

    name = "mlx"

    def load(self) -> None:
        if self._model is not None:
            return
        try:
            from mlx_lm import load
            self._model, self._tokenizer = load(self.model_path)
        except Exception as e:  # pragma: no cover
            raise BackendError(f"MLX 加载失败 {self.model_path}: {e}") from e

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 2000,
        stop: Optional[list[str]] = None,
        on_token: Optional[TokenCB] = None,
        use_kv: bool = False,
        kv_prompt: str = "",
    ) -> tuple[str, str]:
        if self._model is None:
            self.load()
        try:
            from mlx_lm import stream_generate
            import time

            start = time.monotonic()

            # 用 stream_generate 拿 finish_reason + 实时回调
            gen_kwargs = dict(
                model=self._model,
                tokenizer=self._tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
            )
            # stop 序列：mlx 支持 eos_token 但 stop 序列需要拼接；走简化路径
            if stop:
                gen_kwargs["stop_strings"] = stop

            pieces: list[str] = []
            finish = "length"

            try:
                for resp in stream_generate(**gen_kwargs):
                    piece = resp.text
                    pieces.append(piece)
                    if on_token:
                        on_token(piece)
                    if resp.finish_reason is not None:
                        finish = resp.finish_reason
            except TypeError:
                # 老接口：stream_generate 不支持 stop_strings → 降级
                gen_kwargs.pop("stop_strings", None)
                for resp in stream_generate(**gen_kwargs):
                    piece = resp.text
                    pieces.append(piece)
                    if on_token:
                        on_token(piece)
                    if resp.finish_reason is not None:
                        finish = resp.finish_reason

            elapsed = (time.monotonic() - start) * 1000
            self._total_ms += elapsed
            text = "".join(pieces)
            self._total_tokens += len(self._tokenizer.encode(text)) if self._tokenizer else 0
            return text, str(finish)
        except Exception as e:  # pragma: no cover
            raise BackendError(f"MLX 推理失败: {e}") from e

    def unload(self) -> None:
        self._model = None
        self._tokenizer = None
        self._system_cache = None

    def stats(self) -> dict:
        return {
            "model": self.model_path,
            "total_tokens": self._total_tokens,
            "total_ms": self._total_ms,
            "tok_per_s": (self._total_tokens / (self._total_ms / 1000))
            if self._total_ms > 0 else 0.0,
        }

    # ── KV 缓存（任务书 §5 首选：make_prompt_cache）──
    supports_kv_cache = True

    def __init__(self, model_path: str, *, max_kv_tokens: int = 8192,
                 temperature: float = 0.8):
        self.model_path = model_path
        self.max_kv_tokens = max_kv_tokens
        self.temperature = temperature
        self._model = None
        self._tokenizer = None
        self._total_tokens = 0
        self._total_ms = 0.0
        self._system_cache = None  # 系统 KV 基线（birth 时建）
        self._kv_loaded = False

    def kv_save_system(self, prompt: str) -> None:
        """把系统 prompt 的 KV 存为基线。幂等（只建一次，除非 unload）。"""
        if self._system_cache is not None or self._model is None:
            return
        try:
            import copy
            import mlx.core as mx
            from mlx_lm.cache_prompt import make_prompt_cache, generate_step
            cache = make_prompt_cache(self._model, self.max_kv_tokens)
            tokens = self._tokenizer.encode(prompt)
            y = mx.array(tokens)
            # prefill 系统 prompt（max_tokens=0 只 prefill 不生成）
            for _ in generate_step(y, self._model, max_tokens=0,
                                   prompt_cache=cache):
                pass
            # 深拷贝作为不可变基线
            self._system_cache = copy.deepcopy(cache)
            self._kv_loaded = True
            import time
            self._total_ms += (time.monotonic() - self._kv_t0) * 1000 if hasattr(self, "_kv_t0") else 0
        except Exception as e:
            logger.warning("KV 系统基线建立失败({}), 退路: 全量 prefill", e)
            self._kv_loaded = False

    def kv_restore_system(self) -> None:
        """丢弃念头 KV，恢复到系统基线。"""
        if self._system_cache is None:
            return
        try:
            import copy
            self._cache = copy.deepcopy(self._system_cache)
        except Exception as e:
            logger.warning("KV 恢复失败({})", e)

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 2000,
        stop: Optional[list[str]] = None,
        on_token: Optional[TokenCB] = None,
        use_kv: bool = False,
        kv_prompt: str = "",
    ) -> tuple[str, str]:
        if self._model is None:
            self.load()
        try:
            import mlx.core as mx
            import time

            start = time.monotonic()

            if use_kv and getattr(self, "_cache", None) is not None:
                # ── KV 续接：从系统基线 prefill 念头 → 生成 ──
                from mlx_lm.cache_prompt import generate_step
                pieces: list[str] = []
                finish = "length"
                tokens = self._tokenizer.encode(prompt)
                y = mx.array(tokens)
                gen = generate_step(y, self._model, max_tokens=max_tokens,
                                    prompt_cache=self._cache)
                sampled_count = 0
                for token, logprobs in gen:
                    piece = self._tokenizer.decode(token)
                    pieces.append(piece)
                    if on_token:
                        on_token(piece)
                    sampled_count += 1
                    # 简易 stop：命中 stop 序列或 [DONE] 截断
                    text_now = "".join(pieces)
                    if stop and any(s in text_now for s in stop):
                        break
                    if "[DONE]" in text_now:
                        break
                    if sampled_count >= max_tokens:
                        break
                finish = "stop" if sampled_count < max_tokens else "length"
            else:
                # ── 退路：全量 prefill（无 KV 续接）──
                from mlx_lm import stream_generate
                gen_kwargs = dict(
                    model=self._model,
                    tokenizer=self._tokenizer,
                    prompt=prompt,
                    max_tokens=max_tokens,
                )
                if stop:
                    gen_kwargs["stop_strings"] = stop
                pieces = []
                finish = "length"
                try:
                    for resp in stream_generate(**gen_kwargs):
                        piece = resp.text
                        pieces.append(piece)
                        if on_token:
                            on_token(piece)
                        if resp.finish_reason is not None:
                            finish = resp.finish_reason
                except TypeError:
                    gen_kwargs.pop("stop_strings", None)
                    for resp in stream_generate(**gen_kwargs):
                        piece = resp.text
                        pieces.append(piece)
                        if on_token:
                            on_token(piece)
                        if resp.finish_reason is not None:
                            finish = resp.finish_reason

            elapsed = (time.monotonic() - start) * 1000
            self._total_ms += elapsed
            text = "".join(pieces)
            self._total_tokens += len(self._tokenizer.encode(text)) if self._tokenizer else 0
            return text, str(finish)
        except Exception as e:  # pragma: no cover
            raise BackendError(f"MLX 推理失败: {e}") from e


class DummyBackend(BaseBackend):
    """无模型后端（测试/开发用）：按模板生成文本，模拟流式。"""

    name = "dummy"

    def __init__(self, responses: Optional[list[str]] = None, **_kwargs):
        # **_kwargs：容忍 main.py 统一传入的 model_path（dummy 无模型，忽略）
        self.responses = responses or [
            "【思考】我看到了这个节点的核心。\n"
            "结论：这是一个测试节点，处理完成。\n"
            "接下来：下一步处理相邻节点。\n[DONE]",
            "【思考】继续推进。\n结论：第二个测试完成。\n[DONE]",
            "【思考】第三个节点。\n结论：完成。\n[DONE]",
        ]
        self._idx = 0
        self._tokens = 0
        self._ms = 0.0

    def load(self) -> None:
        pass

    def generate(self, prompt: str, *, max_tokens: int = 2000,
                 stop: Optional[list[str]] = None,
                 on_token: Optional[TokenCB] = None,
                 use_kv: bool = False,
                 kv_prompt: str = "") -> tuple[str, str]:
        import time
        text = self.responses[self._idx % len(self.responses)]
        self._idx += 1
        start = time.monotonic()
        for i in range(0, len(text), 8):
            chunk = text[i:i + 8]
            if on_token:
                on_token(chunk)
        self._ms += (time.monotonic() - start) * 1000
        self._tokens += max(1, len(text) // 4)
        return text, "stop"

    def unload(self) -> None:
        pass

    def stats(self) -> dict:
        return {"model": "dummy", "total_tokens": self._tokens, "total_ms": self._ms}


class OpenAICompatibleBackend(BaseBackend):
    """OpenAI 兼容 HTTP 后端。

    同一接口覆盖两个场景：
    - sensenova 云端大模型（大模型兜底）：base_url=https://token.sensenova.cn/v1
    - LM Studio 本地 0.8B：base_url=http://localhost:1234/v1

    sensenova 的 deepseek 系模型会先输出 reasoning_content（思维链），
    这本身是模型正常行为，不做抑制；content 为空时用 reasoning 兜底。
    """

    name = "openai"

    def __init__(self, base_url: str, api_key: str = "", model: str = "",
                 *, temperature: float = 0.8):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self._total_tokens = 0
        self._total_ms = 0.0
        self._loaded = False

    def load(self) -> None:
        self._loaded = True  # 无状态，仅标记

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 2000,
        stop: Optional[list[str]] = None,
        on_token: Optional[TokenCB] = None,
        use_kv: bool = False,
        kv_prompt: str = "",
    ) -> tuple[str, str]:
        import json
        import time
        import urllib.request

        self.load()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            "stream": True,
        }
        if stop:
            body["stop"] = stop

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
        )
        start = time.monotonic()
        pieces: list[str] = []
        finish = "length"
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                for raw in resp:
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        finish = "stop"
                        break
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choice = (obj.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    piece = delta.get("content") or ""
                    if not piece:
                        # sensenova deepseek 系：思维链在 reasoning_content
                        piece = delta.get("reasoning_content") or ""
                    if piece:
                        pieces.append(piece)
                        if on_token:
                            on_token(piece)
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
        except Exception as e:
            raise BackendError(f"OpenAI 兼容 API 调用失败: {e}") from e

        elapsed = (time.monotonic() - start) * 1000
        self._total_ms += elapsed
        text = "".join(pieces)
        self._total_tokens += max(1, len(text) // 3)
        return text, str(finish)

    def unload(self) -> None:
        self._loaded = False

    def stats(self) -> dict:
        return {
            "model": self.model,
            "total_tokens": self._total_tokens,
            "total_ms": self._total_ms,
            "tok_per_s": (self._total_tokens / (self._total_ms / 1000))
            if self._total_ms > 0 else 0.0,
        }


def create_backend(name: str, **kwargs) -> BaseBackend:
    if name == "mlx":
        return MLXBackend(**kwargs)
    if name == "dummy":
        return DummyBackend(**kwargs)
    if name == "openai":
        return OpenAICompatibleBackend(**kwargs)
    raise ValueError(f"未知后端: {name}")
