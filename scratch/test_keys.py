import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from src.config import Config

load_dotenv()

print("Loaded keys from Config.GOOGLE_API_KEYS:")
for idx, key in enumerate(Config.GOOGLE_API_KEYS):
    print(f"Key {idx}: ...{key[-6:]} (len: {len(key)})")

print("\nTesting each key...")
for idx, key in enumerate(Config.GOOGLE_API_KEYS):
    print(f"\n--- Testing Key {idx} (...{key[-6:]}) ---")
    try:
        llm = ChatGoogleGenerativeAI(
            model="gemini-3.5-flash",
            google_api_key=key,
            temperature=0.1
        )
        res = llm.invoke([HumanMessage(content="Hello")])
        print(f"✅ Success! Response: {res.content}")
    except Exception as e:
        print(f"❌ Failed: {e}")
