"""AI Brain — подключение LLM через OpenRouter.

Когда сцена в режиме free_talk — персонаж ведёт живой разговор
с ребёнком. Работаем через OpenRouter (openai-совместимый API).
Модель по умолчанию: google/gemini-2.5-flash
"""
import os
import httpx

# OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash"


async def chat_with_character(
    character: dict,
    scene: dict,
    history: list,
    child_message: str,
    memory: list,
    ethics: dict,
    config: dict,
) -> str:
    """Отправить сообщение ребёнка персонажу и получить ответ."""
    if not OPENROUTER_API_KEY:
        return "(Ключ не настроен. Установи OPENROUTER_API_KEY.)"

    # ─── Собираем системный промпт ───
    system_parts = []

    # Кто ты
    system_parts.append(character.get("system_prompt", ""))

    # Характер
    personality = character.get("personality", "")
    if personality:
        system_parts.append(f"Твой характер: {personality}")

    # Контекст сцены
    context = scene.get("context", "")
    if context:
        system_parts.append(f"Ситуация: {context}")

    # Инструкции
    ai_instructions = scene.get("ai_instructions", "")
    if ai_instructions:
        system_parts.append(f"Правила: {ai_instructions}")

    # Память
    if memory:
        tags = ", ".join(
            m.replace("memory:", "").replace("artifact:", "") for m in memory
        )
        system_parts.append(f"Ребёнок уже сделал выборы: {tags}")

    # Этика
    if ethics:
        forbidden = ethics.get("forbidden_topics", [])
        if forbidden:
            system_parts.append(
                f"ЗАПРЕЩЕНО затрагивать темы: {', '.join(forbidden)}"
            )
        forbidden_phrases = ethics.get("forbidden_phrases", [])
        if forbidden_phrases:
            system_parts.append(
                f"ЗАПРЕЩЕНО использовать фразы: {', '.join(forbidden_phrases)}"
            )

    # Общие правила
    system_parts.append(
        "Отвечай коротко — 2-3 предложения. "
        "Говори от первого лица как персонаж. "
        "Не выходи из роли."
    )

    system_prompt = "\n\n".join(system_parts)

    # ─── Собираем messages в OpenAI-формате ───
    messages = [
        {"role": "system", "content": system_prompt},
    ]

    # Первая реплика персонажа (вход в сцену)
    opening = scene.get("text", character.get("catchphrase", "Привет, путник."))
    messages.append({"role": "assistant", "content": opening})

    # История диалога
    for msg in history:
        role = "user" if msg["role"] == "child" else "assistant"
        messages.append({"role": role, "content": msg["text"]})

    # Новое сообщение ребёнка
    messages.append({"role": "user", "content": child_message})

    # ─── Настройки ───
    llm_config = config.get("llm", {})
    model = llm_config.get("model", DEFAULT_MODEL)

    payload = {
        "model": model,
        "messages": messages,
        "temperature": llm_config.get("temperature", 0.7),
        "top_p": llm_config.get("top_p", 0.9),
        "max_tokens": llm_config.get("max_tokens", 300),
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://alive-book.grondheim.com",
        "X-Title": "Alive Book",
    }

    # ─── Запрос ───
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                OPENROUTER_URL,
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            # Извлекаем ответ
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "...")

            return "..."

    except httpx.HTTPStatusError as e:
        return f"(Ошибка API: {e.response.status_code})"
    except Exception as e:
        return f"(Ошибка связи: {str(e)[:100]})"
