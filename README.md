# InvestHelper

CLI-помощник для анализа **российского** инвестиционного портфеля: локальный файл позиций, котировки с [MOEX ISS](https://iss.moex.com/), рекомендации через вашу LLM по **OpenAI-compatible** API.

> Это не индивидуальная инвестиционная консультация. Решения о сделках принимаете вы.

## Возможности

- Портфель в YAML/JSON (тикер MOEX, количество, средняя цена, опционально board)
- Котировки с Мосбиржи без ключа брокера
- Базовые метрики: стоимость, P&L, доли, концентрация
- Рекомендации по вашему промпту через собственную модель (`OPENAI_BASE_URL`)

T-Invest API пока не подключён; позже его можно добавить как источник того же формата портфеля.

## Установка

Требуется Python 3.11+.

```bash
cd InvestHelper
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
cp portfolio.example.yaml portfolio.yaml
```

Отредактируйте `.env` (ключ, base URL, имя модели) и `portfolio.yaml` под свои позиции.

## Конфигурация

См. [`.env.example`](.env.example):

| Переменная | Описание |
| --- | --- |
| `OPENAI_API_KEY` | API-ключ вашей модели |
| `OPENAI_BASE_URL` | Базовый URL OpenAI-compatible API (`.../v1`) |
| `OPENAI_MODEL` | Имя модели |
| `OPENAI_TIMEOUT_SECONDS` | Таймаут LLM (по умолчанию 120) |
| `MOEX_TIMEOUT_SECONDS` | Таймаут MOEX ISS (по умолчанию 30) |
| `SYSTEM_PROMPT_PATH` | Путь к файлу или каталогу промптов (по умолчанию все `.md`/`.txt` из `prompts/`) |

## Системный промпт

Базовые инструкции — [`prompts/system.md`](prompts/system.md).

В модель уходят **все** `.md` / `.txt` из каталога `prompts/`: сначала `system.md`, затем остальные по имени файла. Дополнительные файлы в git не попадают.

Можно переопределить путь к файлу или каталогу через `SYSTEM_PROMPT_PATH` или флаг `--system-prompt`.

## Формат портфеля

```yaml
currency: RUB
cash: 50000
positions:
  - ticker: SBER
    quantity: 100
    avg_price: 280.5
    board: TQBR          # опционально
  - ticker: LQDT
    quantity: 20
    avg_price: 1.45
    board: TQBR
```

Поддерживаются `.yaml` / `.yml` / `.json`.

## Использование

```bash
# Проверка окружения и MOEX
invest-helper doctor

# Только снимок портфеля (без LLM)
invest-helper analyze \
  --portfolio portfolio.yaml \
  --prompt "Что ребалансировать?" \
  --dry-run

# Полный анализ с рекомендациями
invest-helper analyze \
  --portfolio portfolio.yaml \
  --prompt "Что ребалансировать на горизонте 3–6 месяцев?"

# Свой файл или каталог промптов
invest-helper analyze \
  --portfolio portfolio.yaml \
  --prompt "..." \
  --system-prompt prompts
```

Эквивалентно: `python -m invest_helper ...`.

## Архитектура

```
portfolio.yaml ──► CLI ──► MOEX ISS ──► snapshot ──► LLM ──► markdown
                   ▲                      ▲
                   └── user prompt ───────┘
```

## Лицензия

См. [LICENSE](LICENSE).
