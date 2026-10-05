# InvestHelper

CLI-помощник для анализа **российского** инвестиционного портфеля: локальный файл позиций, котировки с [MOEX ISS](https://iss.moex.com/), рекомендации через вашу LLM по **OpenAI-compatible** API.

> Это не индивидуальная инвестиционная консультация. Решения о сделках принимаете вы.

## Возможности

- Портфель в YAML/JSON (тикер MOEX, количество, средняя цена, опционально board)
- Котировки с Мосбиржи без ключа брокера: last, дневной ход, OHLC, оборот, капитализация выпуска, доходности 1н/1м/3м/1г по дневным свечам
- Базовые метрики: стоимость, P&L, доли, концентрация
- Рекомендации по вашему промпту через собственную модель (`OPENAI_BASE_URL`)
- Отчёты в `reports/` (markdown с датой в имени файла; в git не попадают)

`analyze` по-прежнему считает отчёт только по файлу портфеля и MOEX ISS. Команда `sync` отдельно подтягивает фактические деньги и позиции со счёта Т-Инвестиций в `portfolio.yaml`.

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
| `TINVEST_TOKEN` | Токен T-Invest API с правом «только чтение». Нужен только команде `sync` |
| `TINVEST_MCP_URL` | MCP-контур. По умолчанию боевой `https://invest-public-api.tbank.ru/mcp`. Песочница: `https://sandbox-invest-public-api.tbank.ru/mcp` |
| `TINVEST_TIMEOUT_SECONDS` | Таймаут MCP (по умолчанию 60) |

### Токен Т-Инвестиций

`analyze` токен не читает. Он нужен команде `sync`, которая обновляет в `portfolio.yaml` только `cash` и `positions`.

1. В кабинете Т-Инвестиций выпустите токен API и выберите уровень **только чтение**. Торговля и переводы этой команде не нужны. Описание токена: [T-Bank Dev Portal](https://developer.tbank.ru/invest/intro/intro/token).
2. Откройте локальный `.env` (его нет в git) и добавьте строку `TINVEST_TOKEN=` и сразу за ней токен, без кавычек и пробелов.
3. Для проверки на демо-счёте укажите `TINVEST_MCP_URL=https://sandbox-invest-public-api.tbank.ru/mcp` и токен песочницы.
4. Запуск из каталога проекта, где лежит `.env`:

```bash
invest-helper sync --portfolio portfolio.yaml
```

Читаются все открытые брокерские счета. Деньги складываются, одинаковые тикеры объединяются: количество суммируется, средняя цена — средневзвешенная. Банковские и закрытые счета не входят. Валютные позиции, кроме рублей, и ЦФА в файл не пишутся — команда перечисляет, что пропустила.

Для доступа к `tbank.ru` в системе должны быть сертификаты Минцифры, иначе соединение не поднимется.

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

Опциональный блок `allocation` в файле портфеля задаёт **вашу** схему классов и тикеры вне базы (`exclude`). Если блока нет — считаются только позиции и доли от всего портфеля. В таблице позиций «Доля %» всегда от всего капитала.

## Использование

```bash
# Проверка окружения и MOEX
invest-helper doctor

# Только снимок портфеля (без LLM)
invest-helper analyze \
  --portfolio portfolio.yaml \
  --prompt "Что ребалансировать?" \
  --dry-run

# Полный анализ: отчёт в reports/YYYY-MM-DD_HHMMSS_<запрос>.md
invest-helper analyze \
  --portfolio portfolio.yaml \
  --prompt "Еженедельный отчёт"

# Карточки позиций (рынок бумаги из снимка, без МСФО)
invest-helper analyze \
  --portfolio portfolio.yaml \
  --prompt "Состояние позиций"

# Свой файл или каталог промптов
invest-helper analyze \
  --portfolio portfolio.yaml \
  --prompt "..." \
  --system-prompt prompts
```

Эквивалентно: `python -m invest_helper ...`.

## Архитектура

```
portfolio.yaml ──► CLI ──► MOEX ISS ──► snapshot ──► LLM ──► reports/*.md
                   ▲                      ▲
                   └── user prompt ───────┘
```

## Лицензия

См. [LICENSE](LICENSE).
