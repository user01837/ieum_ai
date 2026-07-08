# **AI 서버 개발 환경 설정**

이음표(공공이음) AI 서버 — RAG 파이프라인 + 파인튜닝 분류기 + 답변 생성

---

###### **0. 사전 준비물 (필수)**

이 서버는 아래 2가지가 로컬에 준비돼 있어야 정상 동작합니다.

1. **Ollama 설치 및 모델 등록**
   - [ollama.com](https://ollama.com) 에서 설치
   - 아래 2개 모델이 등록돼 있어야 함:
     ```
     ollama list
     ```
     결과에 `handover-classifier`, `llama3.1:8b` 둘 다 있어야 정상
   - 없다면 팀장(김민준)에게 GGUF 파일 + Modelfile 요청

2. **Conda 설치**
   - 이미 설치돼 있다면 생략

---

###### **1. Conda 환경 생성 (최초 1회)**

```bash
conda create -n ieum_ai python=3.12
conda activate ieum_ai
python --version
```

`Python 3.12.x`가 출력되면 정상입니다.

===================================================================

###### **2. 라이브러리 설치**

가상환경이 활성화된 상태에서 실행합니다.

```bash
pip install -r requirements.txt
```

> ⚠️ `torch`, `transformers`, `sentence-transformers`는 **버전이 서로 안 맞으면 임포트 에러**가 납니다.
> `requirements.txt`에 이미 호환되는 버전으로 고정해뒀으니, 별도로 `pip install torch` 등을 임의로 업그레이드하지 마세요.

======================================================================

###### **3. .env 파일 설정 (최초 1회)**

```bash
copy .env.example .env
```
*(Mac/Linux는 `cp .env.example .env`)*

`.env` 파일을 열어 아래 값을 확인/수정합니다. 로컬에서 Ollama가 기본 포트로 돌고 있다면 대부분 그대로 사용 가능합니다.

```
CHROMA_PERSIST_DIR=./chroma_data
EMBEDDING_MODEL=jhgan/ko-sbert-nli
OLLAMA_HOST=http://localhost:11434
CLASSIFIER_MODEL_NAME=handover-classifier
GENERATION_MODEL_NAME=llama3.1:8b
AI_SERVER_PORT=8100
```

============================================================================

###### **4. 새로운 라이브러리 설치 시**

새로운 라이브러리를 설치한 경우 requirements.txt도 함께 업데이트해야 합니다.

```bash
pip install <라이브러리명>
pip freeze > requirements.txt

git add requirements.txt
git commit -m "Update requirements"
git push
```

다른 팀원은 아래 명령으로 최신 환경을 적용합니다.

```bash
git pull
pip install -r requirements.txt
```

============================================================================

###### **5. 작업 전 반드시 가상환경 활성화**

라이브러리 설치 및 서버 실행 전 반드시 아래 명령을 실행합니다.

```bash
conda activate ieum_ai
```

프롬프트 앞에 아래처럼 표시되면 정상입니다.

```
(ieum_ai)
```

=========================================================================

###### **6. 현재 사용 중인 Python 확인**

```bash
python --version
```

또는 (Windows)

```bash
where python
```

=====================================================================

###### **7. 현재 활성화된 Conda 환경 확인**

```bash
conda info --envs
```

예시

```
# conda environments:
#
base
ieum_ai    *
```

`*`가 붙은 환경이 현재 활성화된 환경입니다.

**주의**: base 환경에서 작업하지 말고, 반드시 `ieum_ai` 환경을 활성화한 후 작업해주세요.

===========================================================================

###### **8. 서버 실행**

```bash
uvicorn app.main:app --reload --port 8100
```

> ⚠️ **포트 번호를 꼭 `--port 8100`으로 지정하세요.** `ieum_backend`가 기본 포트(8000)를 이미 쓰고 있어서, 지정하지 않으면 포트가 겹칠 수 있습니다.

실행 후 아래 주소에서 확인할 수 있습니다.

```
API     : http://127.0.0.1:8100
Swagger : http://127.0.0.1:8100/docs
ReDoc   : http://127.0.0.1:8100/redoc
```

===========================================================================

###### **9. 제공하는 API 엔드포인트**

| Method | Endpoint | 설명 |
|---|---|---|
| POST | `/api/classify` | 텍스트를 8개 도메인 중 하나로 분류 (Qwen2.5-3B QLoRA) |
| POST | `/api/similar-cases` | 같은 부서 내 유사 민원 검색 (ChromaDB) |
| POST | `/api/draft` | 유사사례 근거로 답변 초안 생성 (Llama3.1) |
| POST | `/api/index-complaint` | 완료된 민원 1건을 ChromaDB에 색인 |

Swagger UI(`/docs`)에서 각 엔드포인트를 직접 테스트해볼 수 있습니다.

===========================================================================

###### 📌 **개발 순서**

1. `git pull`
2. `conda activate ieum_ai`
3. `pip install -r requirements.txt` (requirements.txt가 변경된 경우)
4. Ollama 실행 확인 (`ollama list`)
5. `uvicorn app.main:app --reload --port 8100`

===========================================================================

###### **10. 자주 발생하는 에러**

**`ImportError: cannot import name 'NP_SUPPORTED_MODULES' from 'torch._dynamo.utils'`**
→ torch/transformers 버전이 안 맞아서 발생. `requirements.txt`에 지정된 버전 그대로 재설치:
```bash
pip uninstall -y torch transformers sentence-transformers
pip install -r requirements.txt
```

**`/api/similar-cases` 호출했는데 결과가 항상 빈 배열(`[]`)**
→ ChromaDB에 아직 색인된 민원이 없는 정상 상태. `/api/index-complaint`로 데이터를 먼저 넣어야 검색됨.

**Ollama 연결 실패 (`ConnectionError`)**
→ Ollama 앱이 백그라운드에서 실행 중인지 확인 (`ollama list`가 정상 응답하면 실행 중).
