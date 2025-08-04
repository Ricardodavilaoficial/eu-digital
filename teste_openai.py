import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

try:
    resposta = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": "Olá, você está funcionando?"}]
    )
    print("✅ Sucesso! Resposta:", resposta.choices[0].message.content)
except Exception as e:
    print("❌ Erro com OpenAI:", e)
