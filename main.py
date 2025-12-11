import sys
import numpy as np
import sounddevice as sd
import queue
import json
from vosk import Model, KaldiRecognizer
import os
import ollama
from piper import PiperVoice
import time

MODEL_NAME = "gemma2:2b"
voice = PiperVoice.load("models\\uk_UA-ukrainian_tts-medium.onnx")
model_path = "models\\vosk-model-small-uk-v3-small" 


SYSTEM_INSTRUCTION = (
    "Ти — доброзичливий та трішки агресивний голосовий асистент. "
    "Відповідай коротко максимум 1 речення, лаконічно і українською мовою. Не використовуй довгих списків."
)

samplerate = 16000  
device_id = None    

q = queue.Queue()

def callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr)
    q.put(bytes(indata))

def sound(txt):
    try:
        print("➡️ Синтез...")

        audio_all = b""
        sample_rate = None

        for chunk in voice.synthesize(txt.lower()):
            if sample_rate is None:
                sample_rate = chunk.sample_rate
            audio_all += chunk.audio_int16_bytes

        print("➡️ Програвання...")

        audio_np = np.frombuffer(audio_all, dtype=np.int16)

        sd.play(audio_np, sample_rate)
        sd.wait()

        print("✔️ Готово")

    except Exception as e:
        print("Помилка звуку:", e)


def ai_response(req):
    try:
        # Виклик локальної моделі через Ollama
        response = ollama.chat(model=MODEL_NAME, messages=[
            {
                'role': 'system',
                'content': SYSTEM_INSTRUCTION,
            },
            {
                'role': 'user',
                'content': req,
            },
        ])
        
        answer = response['message']['content']
        
        if "<think>" in answer:
            import re
            answer = re.sub(r'<think>.*?</think>', '', answer, flags=re.DOTALL).strip()
        # ----------------------------------

        return answer

    except Exception as e:
        print(f"Помилка при генерації відповіді Ollama: {e}")
        return "Вибач, у мене стався збій системи."


print("Завантажую модель (це займе пару секунд)...")
try:
    model = Model(model_path)
except Exception as e:
    print(f"Помилка: не знайшов папку 'model'. Перевір шлях! {e}")
    sys.exit(1)

rec = KaldiRecognizer(model, samplerate)

print("🎧 Слухаю... Скажи щось українською!")

try:
    with sd.RawInputStream(samplerate=samplerate, blocksize=8000, device=device_id,
                           dtype='int16', channels=1, callback=callback):
        while True:
            data = q.get()
            
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = result.get('text', '')
                
                if text and len(text) > 1:
                    print(f"🗣️ Ти сказав: {text}")
                    response = ai_response(text)

                    print(f"🤖 Бот: {response}")
                    sound(response)

                    with q.mutex:
                        q.queue.clear()

                    rec.Reset()
                    time.sleep(0.3)
                    print("🎧 Знову слухаю...")

except KeyboardInterrupt:
    print("\nРоботу завершено.")