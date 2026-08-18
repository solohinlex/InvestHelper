"""OpenAI-compatible LLM client."""

from __future__ import annotations

from pathlib import Path

from openai import OpenAI

from invest_helper.config import Settings
from invest_helper.models import PortfolioSnapshot
from invest_helper.prompts import load_system_prompt


def build_user_message(user_prompt: str, snapshot: PortfolioSnapshot) -> str:
    snapshot_json = snapshot.model_dump_json(indent=2)
    return (
        f"Запрос пользователя:\n{user_prompt.strip()}\n\n"
        f"Снимок портфеля (JSON, источник котировок — MOEX ISS):\n```json\n{snapshot_json}\n```"
    )


def generate_recommendations(
    settings: Settings,
    user_prompt: str,
    snapshot: PortfolioSnapshot,
    system_prompt_path: Path | str | None = None,
) -> str:
    if not settings.llm_configured():
        raise RuntimeError(
            "LLM не настроен. Заполните OPENAI_API_KEY и OPENAI_MODEL в .env "
            "(см. .env.example)."
        )

    path = system_prompt_path or (settings.system_prompt_path.strip() or None)
    system_prompt = load_system_prompt(path)

    client = OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.openai_timeout_seconds,
    )

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_message(user_prompt, snapshot)},
        ],
        temperature=0.3,
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM вернул пустой ответ")
    return content.strip()
