from langchain_groq import ChatGroq

llm = ChatGroq(model="llama-3.3-70b-versatile", groq_api_key="dummy")
print("Model fields:")
for field in llm.model_fields:
    if "timeout" in field or "client" in field or "option" in field:
        print(f"  {field}: {llm.model_fields[field]}")
