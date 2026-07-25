# Enterprise Voice Engine (STT & TTS)

Sentinel includes an enterprise-grade voice interface supporting hands-free Speech-to-Text (STT) input and Text-to-Speech (TTS) report read-aloud capabilities.

---

## Key Libraries & APIs Used

* **Groq Whisper API (`groq.Groq`)**: Powers Speech-to-Text using `whisper-large-v3`.
* **WebSpeech API (`webkitSpeechRecognition` / `SpeechRecognition`)**: Provides real-time browser text preview as the user speaks.
* **MediaRecorder API (`MediaRecorder`)**: Captures 16kHz audio in `audio/webm` format for backend transcription.
* **SpeechSynthesis API (`window.speechSynthesis`)**: Renders native browser Text-to-Speech for reading reports out loud.

---

## Speech-to-Text Pipeline (`src/tools/voice.py`)

```
User Voice ──► WebSpeech API Preview ──► MediaRecorder Audio Blob (WebM)
 │
 ▼
 7s Silence VAD Timeout ──► POST /api/voice/stt
 │
 ▼
 Groq Whisper-large-v3 ◄── Prompt Vocabulary Boost
 │
 ▼
 Transcribed Query Text
```

### Groq Whisper-large-v3 Transcription (`src/tools/voice.py`)
To prevent technical domain terms from being misheard by Whisper (e.g. transcribing "RAG" as "rag", or "Pinecone" as "pine cone"), Sentinel uses Groq's `prompt` parameter to prime the model's vocabulary:

```python
DOMAIN_PROMPT = (
 "Sentinel geopolitical intelligence research system. "
 "Domain terms: RAG, Pinecone, Supabase, GDELT, LLM, Vector, BM25, "
 "Reciprocal Rank Fusion, Groq, FastEmbed, ONNX, Semantics."
)

def transcribe_audio_groq(file_bytes: bytes, filename: str = "voice.webm") -> str:
 client = Groq(api_key=Config.get_groq_api_key())
 transcription = client.audio.transcriptions.create(
 file=(filename, file_bytes),
 model="whisper-large-v3",
 prompt=DOMAIN_PROMPT,
 response_format="text",
 language="en"
 )
 return str(transcription).strip()
```

---

## Voice Activity Detection (VAD) & Silence Timeout (`src/web/static/voice.js`)

To ensure the microphone turns off automatically when the user stops talking, `VoiceController` implements a **7-second VAD silence timer**:

```javascript
resetSilenceTimer() {
 if (this.silenceTimer) clearTimeout(this.silenceTimer);
 this.silenceTimer = setTimeout(() => {
 console.log('[Voice] 7s silence detected. Auto-stopping recording.');
 this.stopRecording();
 }, 7000);
}
```

---

## Text-to-Speech (TTS) Read-Aloud (`src/web/static/voice.js`)

Users can click the speaker icon on any assistant message to trigger browser TTS:

```javascript
speakText(text) {
 if ('speechSynthesis' in window) {
 window.speechSynthesis.cancel();
 const utterance = new SpeechSynthesisUtterance(text);
 utterance.rate = 1.0;
 utterance.pitch = 1.0;
 window.speechSynthesis.speak(utterance);
 }
}
```
