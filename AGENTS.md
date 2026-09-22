# AGENTS.md

CLI-помощник анализа российского портфеля (MOEX ISS) с рекомендациями через OpenAI-compatible LLM. Python 3.11+, `hatchling`, Typer CLI. Код в `src/invest_helper/`.

## Команды

- Установка/запуск — только через виртуальное окружение: `source .venv/bin/activate` (Python 3.14 в `.venv`). Пакет уже установлен в `.venv`.
- `invest-helper doctor` — проверка окружения, конфигурации и доступности MOEX. Это единственная команда быстрой верификации изменений (внешних зависимостей MOEX/LLM требует).
- `python -m invest_helper ...` — эквивалент `invest-helper`.
- **Тестов нет, CI нет, линтера/форматтера нет.** Не ищи `pytest`/`ruff` — их не будет. Верификация = `doctor` + ручной прогон `analyze --dry-run`.

## Критично для агента

- `.env` содержит реальные ключи и не попадает в git — не коммить и не логировать ключ. `.env.example` — эталон для документирования.
- `portfolio.yaml` и `reports/` в gitignore: содержат реальные позиции/данные, не попадают в git. В `git status` они отсутствуют намеренно. Для работы руками используй `portfolio.yaml` (реальный) и `portfolio.example.yaml` (эталон).
- Конфигурация читается из `.env` через pydantic-settings (`config.py`). Ключи именами через `SettingsConfigDict`, `extra="ignore"` — новые переменные не поломят загрузку.

## Промпты (легко ошибиться)

- В LLM уходит **все** `.md`/`.txt` из `prompts/`, склеенные в один системный промпт: сначала `system.md`, затем остальные **по имени файла** (`prompts.py`). `system.md` идёт первым всегда.
- Git отслеживает **только** `prompts/system.md`. `prompts/reports.md` в gitignore (личный), но реально используется и присутствует в репозитории на диске. Правя промпты — не удали `reports.md`, он часть рабочего системного промпта.
- Поиск промптов: cwd, затем корень проекта (`src/.../prompts.py` → `_project_root()`). `resolve_prompt_files()` кидает `FileNotFoundError`, если ничего не найдено — не глотать.

## Архитектура

```
portfolio.yaml → cli.py → moex.py (MOEX ISS) → analytics.py (snapshot)
                                              → llm.py (OpenAI-compatible) → reports/*.md
```

- `cli.py` — Typer entrypoints (`analyze`, `doctor`). `__main__.py` делегирует в `app`.
- `moex.py` — HTTP к MOEX ISS, `MoexError`. Сетевой, может падать без сети.
- `analytics.py` — расчёт метрик/снимка, `build_snapshot()`.
- `llm.py` — вызов LLM, только если `llm_configured()` в `config.py` (`OPENAI_API_KEY` + `OPENAI_MODEL` заданы).
- `reports.py` — сохранение markdown-отчёта в `reports/YYYY-MM-DD_HHMMSS_<запрос>.md`.

## Стиль

- Код с `from __future__ import annotations` и аннотациями типов. Следуй этому в новых модулях.
- Без докстрингов-туториалов, без лишних комментариев. Комментарии только где логика неочевидна.
- Промпты/отчёты/сообщения — на русском, вывод CLI и markdown.
