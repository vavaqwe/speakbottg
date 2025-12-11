import asyncio
import logging
import os
import json
import re
import wave
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from vosk import Model, KaldiRecognizer
from openai import OpenAI
from pydub import AudioSegment

TELEGRAM_TOKEN = '...'
OPENAI_API_KEY = '...'

MENU_FILE = 'products.json'
VOSK_MODEL_PATH = "models\\vosk-model-small-uk-v3-small"

if not os.path.exists(VOSK_MODEL_PATH):
    print(f"❌ Помилка: Не знайдено шлях: {VOSK_MODEL_PATH}")
    exit()

print("⏳ Завантаження...")
vosk_model = Model(VOSK_MODEL_PATH)

openai_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=OPENAI_API_KEY
)
print("✅ Система готова.")

# Завантаження меню
try:
    with open(MENU_FILE, "r", encoding="utf-8") as f:
        MENU = json.load(f)
except Exception as e:
    print(f"❌ Помилка меню: {e}")
    MENU = []

USER_DATA = {}

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📜 Меню"), KeyboardButton(text="💰 Розрахувати чек")],
            [KeyboardButton(text="🗑 Очистити кошик")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Натисніть кнопку або скажіть замовлення..."
    )

def parse_price(price_str):
    if not price_str: return 0
    match = re.search(r'(\d+)', str(price_str))
    if match: return int(match.group(1))
    return 0

def find_product_by_name(name):
    if not name: return None
    name_lower = str(name).lower()
    for item in MENU:
        if item['name'].lower() == name_lower:
            return item
    for item in MENU:
        if name_lower in item['name'].lower():
            return item
    return None

def generate_receipt_text(cart):
    if not cart:
        return "🛒 Ваш кошик порожній.", 0
    
    total = 0
    lines = []
    
    valid_cart = [item for item in cart if item]
    
    for item in valid_cart:
        if isinstance(item, str):
            found_item = find_product_by_name(item)
            if found_item:
                item = found_item 
            else:
                continue
        
        # Тепер item точно словник
        price_str = item.get('price', '0')
        price = parse_price(price_str)
        total += price
        lines.append(f"▫️ {item.get('name', 'Товар')} — {price} грн")
    
    text = (
        "🧾 <b>ВАШЕ ЗАМОВЛЕННЯ:</b>\n\n" +
        "\n".join(lines) +
        f"\n\n💰 <b>ВСЬОГО ДО СПЛАТИ: {total} грн</b>"
    )
    return text, total

def process_stt_vosk(file_path):
    try:
        audio = AudioSegment.from_file(file_path)
        audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        wav_path = file_path + ".wav"
        audio.export(wav_path, format="wav")

        rec = KaldiRecognizer(vosk_model, 16000)
        with wave.open(wav_path, "rb") as wf:
            while True:
                data = wf.readframes(4000)
                if len(data) == 0: break
                if rec.AcceptWaveform(data): pass 

        final_json = json.loads(rec.FinalResult())
        if os.path.exists(wav_path): os.remove(wav_path)
        return final_json.get('text', '')
    except Exception:
        return ""

async def ask_brain(text, history, cart):
    # Оптимізація: відправляємо тільки назви страв у промпт, щоб не перевантажувати контекст
    menu_names = [m['name'] for m in MENU]
    
    system_prompt = f"""
    Ти - офіціант піцерії. 
    Ось повний список страв: {json.dumps(menu_names, ensure_ascii=False)}
    
    Твоя задача:
    1. Зрозуміти, що хоче клієнт.
    2. Якщо він замовляє страву, додай її НАЗВУ у список `cart_update`.
    3. Якщо просять "рахунок" або "чек" -> `action`: "checkout".
    
    Історія: {history}
    Кошик: {json.dumps(cart, ensure_ascii=False)}
    
    Відповідай ТІЛЬКИ у форматі JSON:
    {{
        "reply_text": "Відповідь українською",
        "cart_update": ["Назва страви 1", "Назва страви 2"],
        "action": "continue" або "checkout"
    }}
    """
    
    try:
        response = await asyncio.to_thread(
            openai_client.chat.completions.create,
            model="openai/gpt-oss-20b", 
            messages=[
                {"role": "system", "content": system_prompt}, 
                {"role": "user", "content": text}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logging.error(f"AI Error: {e}")
        return {"reply_text": "Помилка AI.", "action": "continue"}

router = Router()

@router.message(CommandStart())
async def command_start(message: Message):
    user_id = message.from_user.id
    if user_id not in USER_DATA: USER_DATA[user_id] = {"cart": [], "history": []}
    
    await message.answer(
        "🍕 <b>Вітаю у Фіче Піца!</b>\n\n"
        "Натисніть кнопку меню або надішліть голосове повідомлення із замовленням.",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.HTML
    )


@router.message(F.text == "📜 Меню")
async def show_menu(message: Message):
    menu_text = "📜 <b>МЕНЮ ПІЦЕРІЇ:</b>\n\n"
    for item in MENU[:30]: 
        menu_text += f"🍕 <b>{item['name']}</b>: {item['price']}\n"
    
    menu_text += "\n<i>...та багато іншого! Скажіть, що бажаєте.</i>"
    await message.answer(menu_text, parse_mode=ParseMode.HTML)

@router.message(F.text == "💰 Розрахувати чек")
async def checkout_button(message: Message):
    user_id = message.from_user.id
    data = USER_DATA.get(user_id, {"cart": []})
    
    text, total = generate_receipt_text(data["cart"])
    
    await message.answer(text, parse_mode=ParseMode.HTML)
    
    if total > 0:
        current_names = []
        for item in data["cart"]:
             name = item['name'] if isinstance(item, dict) else str(item)
             current_names.append(name)
             
        data["history"].extend(current_names)
        data["cart"] = [] # Очищення
        USER_DATA[user_id] = data
        await message.answer("✅ Замовлення оформлено! Чекайте на доставку.")

@router.message(F.text == "🗑 Очистити кошик")
async def clear_cart(message: Message):
    user_id = message.from_user.id
    if user_id in USER_DATA:
        USER_DATA[user_id]["cart"] = []
    await message.answer("🗑 Кошик очищено.")

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot):
    user_id = message.from_user.id
    if user_id not in USER_DATA: USER_DATA[user_id] = {"cart": [], "history": []}
    
    wait_msg = await message.answer("🎧 Слухаю...")
    
    file = await bot.get_file(message.voice.file_id)
    file_path = f"voice_{user_id}.ogg"
    await bot.download_file(file.file_path, file_path)
    
    try:
        text_input = await asyncio.to_thread(process_stt_vosk, file_path)
        
        if not text_input:
            await wait_msg.edit_text("😕 Не розібрав слів.")
            return

        await wait_msg.edit_text(f"🗣 <b>Ви сказали:</b> {text_input}", parse_mode=ParseMode.HTML)
        
        data = USER_DATA[user_id]
        ai_resp = await ask_brain(text_input, data["history"], data["cart"])
        
        if ai_resp.get("cart_update"):
            new_items = []
            for item_raw in ai_resp["cart_update"]:
                # Якщо AI повернув просто назву (рядок)
                if isinstance(item_raw, str):
                    product = find_product_by_name(item_raw)
                    if product:
                        new_items.append(product)
                # Якщо AI повернув об'єкт (словник)
                elif isinstance(item_raw, dict):
                    new_items.append(item_raw)
            
            data["cart"].extend(new_items)
            
        reply_text = ai_resp.get("reply_text", "Зрозумів.")
        
        if ai_resp.get("action") == "checkout":
            text, total = generate_receipt_text(data["cart"])
            full_resp = f"{reply_text}\n\n{text}"
            await message.answer(full_resp, parse_mode=ParseMode.HTML)
            
            # Очищення
            current_names = [i['name'] if isinstance(i, dict) else str(i) for i in data["cart"]]
            data["history"].extend(current_names)
            data["cart"] = []
        else:
            await message.answer(reply_text)

    except Exception as e:
        logging.error(f"Global Error: {e}")
        await message.answer("Сталася помилка.")
    finally:
        if os.path.exists(file_path): os.remove(file_path)

async def main():
    bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Бот (Версія: Fix Error) запущено!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Стоп")