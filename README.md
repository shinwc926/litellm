# 외부 GPT 연동 서비스 개발 검토 
LiteLLM의 문서는 아래 링크를 참고

[LiteLLM 문서 링크](https://docs.litellm.ai/docs/)

## 1. 외부 GPT 연계 API 개발 

* 엔드포인트: `/chat/completion`
* **LiteLLM 도입:** OpenAI 호환 LLM API를 제공하여 범용성 확보
* **지원 환경:** Python SDK(`litellm`) 및 HTTP API 적용 가능
* **모델 관리:** `model_list` 설정을 통해 각 Provider와 LLM 모델 지정
* API Key는 `.env` 형태로 관리 및 전달
* 코레일 계열사별로 LLM 모델 키 관리 필요. 계열사별로 모델이름을 다르게 생성해서 키 관리 가능
```yaml
  # Gemini 2.5 Pro A
  - model_name: gemini-2.5-pro-a
    litellm_params:
      model: gemini/gemini-2.5-pro
      api_key: os.environ/GEMINI_API_KEY_A
    model_info:
      mode: chat
      supports_function_calling: true
      supports_vision: true
  # Gemini 2.5 Pro B
    - model_name: gemini-2.5-pro-b
    litellm_params:
      model: gemini/gemini-2.5-pro
      api_key: os.environ/GEMINI_API_KEY_B
    model_info:
      mode: chat
      supports_function_calling: true
      supports_vision: true
```
* 개별 Provider 별 API Key 호출 없이 **Master Key**를 사용하여 통합 관리.



## 2. 외부 검색 엔진 연계 API 개발 
* 엔드포인트: `/search`
* **설정:** `llm-setting` 내 `websearch_interception` 활성화
* **구성:** `enable-provider`와 `search_tool_name` 지정
* **특이사항 (Naver Search):**
  - Naver Search는 기본 Provider에 포함되지 않으므로 별도의 **Proxy** 구현 필요
  - `searxng`로 Provider를 등록하고 `search_tool`에 Naver Search 관련 변수 추가
* TODO: LLM 모델로 직접 API를 호출하는 경우 
* `websearch_interception`이 동작하려면 tools에 `litellm_web_search` 이름을 명시해야 함

### Naver Search Proxy (`naver-search-proxy/`)

네이버 검색 API를 LiteLLM SearXNG 프로바이더와 호환되도로 래핑하는 FastAPI 프록시 서버

```
naver-search-proxy/
├── main.py                  # FastAPI 서버 (SearXNG 호환 /search 엔드포인트)
├── naver_unified_search.py  # 네이버 통합 검색 엔진 (병렬 검색 + 람킹)
├── config.py                # 카테고리 매핑 설정
├── Dockerfile               # Docker 이미지 빌드
├── docker-compose.yml       # 컨테이너 실행 설정 (8001 포트)
├── .env.example             # NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
└── test_api.ipynb           # API 테스트 노트북
```

| 엔드포인트 | 설명 |
|---|---|
| `GET /health` | 서버 상태 확인 |
| `GET /categories` | 지원 검색 카테고리 목록 |
| `GET /naver/search` | 네이버 직접 검색 |
| `GET /search` | **SearXNG 호환 엔드포인트** (LiteLLM이 호출) |

SearXNG 카테고리 → Naver 카테고리 자동 매핑:

| SearXNG | Naver |
|---|---|
| `general`, `web` | blog, news |
| `news` | news |
| `science`, `it` | blog, news, book |
| `shopping` | shop |

**LiteLLM 연동 설정** (`litellm_config.yaml`):
```yaml
litellm_settings:
  websearch_params:
    searxng_api_base: http://naver-search-proxy:8001
    search_tool_name: litellm_web_search
```

```python
# LiteLLM이 LLM 응답에서 이 tool_call을 감지하면 자동으로 Naver 검색을 실행하고
# 검색 결과를 포함해 LLM에 재요청함
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "litellm_web_search",
        "description": "Search the web for current information",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }
    }
}
response = client.chat.completions.create(
    model="openai/qwen3:8b",
    messages=[
        {
            "role": "user",
            "content": "유즈라멘 본점 전화번호와 추천 메뉴 알려줘"
        }
    ],
    tools=[WEB_SEARCH_TOOL],   # ← 이게 없으면 web search 미실행
#   tool_choice="auto"
)
```


## 3. API Key 및 권한 관리

* **Master Key:** 모든 Provider의 모델에 연동 가능한 마스터 권한.
* **Virtual Key:** 사용자/팀별로 생성하여 예산(`budget`) 및 사용량(`usage`) 관리.

## 4. Guardrail 및 보안 설정

### 4.1. 데이터 유출 방지 및 필터링
#### 가드레일 커스텀 구현
* PII(Personal Idenfiable Information) 처리
* **Custom Guardrail:** 유료 API 기반 솔루션 대신 `custom_guardrail.py`를 직접 구현하여 적용.
* **이벤트 기반 호출:** `pre-call`, `post-call`, `during-call` 시점에 콜백 구현.
* **필터링:** Regex 기반 조건 필터링 및 LLM 유해 답변 필터링

### PII shield API 서버
* **PII-Shield:** `pii-shield` 솔루션 활용
* **기능:** PII 노출 감지(`/detect`) 및 마스킹(`/mask`) API 제공
* **NER (개체명 인식):** MS Presidio 패키지를 활용하여 개인정보 로직 설정
* `pii-shield` API 기반으로 `pre-call`, `post-call` 이벤트 발생 시 호출될 콜백을 pii_shield_guardrail.py에 구현. __(TASK_1)__
* 참고: [링크](https://ploomber.io/blog/presidio/)
* 참고: Presidio PII Masking with LiteLLM - Complete Tutorial
[링크](https://docs.litellm.ai/docs/tutorials/presidio_pii_masking)

### 4.2. Microsoft Presidio PII Masking (`presidio-pii/`)

LiteLLM 내장 `presidio` 가드레일과 Microsoft Presidio를 연동하여
한국어 PII를 자동 감지·마스킹하고 LLM 응답에서 원본으로 복원하는 독립 컨테이너 구성.

```
presidio-pii/
├── docker-compose.yml           # Presidio Analyzer(5002) + Anonymizer(5001)
├── Dockerfile.analyzer          # 한국어 spaCy 모델 포함 커스텀 이미지
├── analyzer_config.yaml         # ANALYZER_CONF_FILE: supported_languages
├── nlp_config.yaml              # NLP_CONF_FILE: en+ko spaCy 모델
├── recognizer_registry.yaml     # RECOGNIZER_REGISTRY_CONF_FILE: en/ko + recognizers
├── proxy_config_pii.yaml        # LiteLLM 가드레일 설정
└── custom_recognizers.json      # 한국어 PII 커스텀 인식기 (8종)
```

**지원 엔티티 (8종):** `KR_NAME`, `KR_SSN`, `KR_PHONE_NUMBER`, `KR_BANK_ACCOUNT`,
`KR_EMAIL`, `KR_BUSINESS_NUMBER`, `KR_DRIVER_LICENSE`, `KR_PASSPORT`

**동작 흐름:**
```
사용자 입력 → [pre_call] PII 마스킹 → LLM 처리 → [output_parse_pii] 원본 복원 → 사용자
"홍길동, 010-1234-5678"  →  "<KR_NAME_1>, <KR_PHONE_NUMBER_1>"  →  "홍길동, 010-1234-5678"
```

> **한국어 지원을 위해 3개 환경변수로 설정 파일 분리 필요**
> - `ANALYZER_CONF_FILE` → `analyzer_config.yaml` : AnalyzerEngine 언어 목록
> - `NLP_CONF_FILE` → `nlp_config.yaml` : NlpEngineProvider en+ko 모델 등록  
> - `RECOGNIZER_REGISTRY_CONF_FILE` → `recognizer_registry.yaml` : registry 언어+인식기 (없으면 default `['en']` 고정 → 크래시)

### 4.3. 프롬프트 보안 및 로깅

* **프롬프트 인젝션:** In-memory 기반의 인젝션/탈옥 시도 탐지.
* **Audit Log:** 모든 질의응답 내역 저장 (`logs` 기능).
* **사용량 추적:** 외부 GPT 사용량 및 과금 관리 (`usage` 기능)
* Team, User별로 virtual key를 생성해서 관리 가능
* 상용버전에서는 Org를 지원하는데 open source 버전에서는 팀까지만 지원. 코레일 계열사별로 team 계정을 생성하고 team으로 `Budget`을 할당하고 관리. team내에 user를 생성할 수도 있고 개별 user로 생성할 수 있음
* Team별로 budget과 사용량 등을 UI에 제공하려면 해당 API나 DB를 조회할 수 있도록 확인필요 
* Spend Log
__(TASK_2)__


## 5. Router 기능 상세 및 기술 검토

### 5.1. 라우팅 방식

1. **Complexity Router:** 질문의 복잡도를 지표로 점수화하여 모델 배분. 비용 최적화에 적합
2. **Semantic Router:** 임베딩 모델을 활용하여 사용자 쿼리를 벡터로 변환 후, 유사도가 높은 Router로 전달 (`router.json`에 규칙 및 Utterance 정의)

### 5.2. Ragflow 연동 이슈
* __(필요없어짐)__
* **문제점:** Ragflow 응답 시 Reference(참조문헌) 데이터가 LiteLLM을 거치면서 누락되는 현상 발생.
* **해결책:** * `async_post_call_response_headers_hook()` 콜백 함수를 구현하여 `X-ragflow-reference` 헤더 생성 및 추가.
* Client 단에서 해당 헤더를 별도로 처리하도록 설계.
* `chat.create()` 호출 시 `stream=False` 및 `reference: true` 설정 필수.

## 6. 향후 To-Do (LiteLLM 관련)

* **Router 기능 고도화:** 복잡도 지표 및 임베딩 기반 라우팅 로직 구현 및 테스트.
* **내/외부 판별:** 외부 GPT 모델과 내부 LLM 모델 중 어떤 모델을 호출할 지 결정하는 로직을 구현할 필요있을지 검토 필요. 현재 LiteLLM에 Auto-Router 기능을 활용하면 LLM 호출이 없어 응답이 빠를 수 있지만 따로 로직을 구현한다면 결국 LLM을 활용할 수 밖에 없어 응답시간이 길어
* **웹 서치 호출 시점:** LLM 호출 시 웹 서치를 해야 할지 판단하는 로직 검토 필요. 
* **Agent:** LLM을 사용해서 
  - 사용자 query 기반으로 어떤 LLM 모델을 사용할 지 판단
  - 사용자 query가 웹 서치가 필요한 질문일지 판단 
  - 어떤 category의 질문일지 판단
하는 agent 구현이 필요할지도...
