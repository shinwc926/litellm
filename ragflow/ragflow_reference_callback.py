"""
ragflow_reference_callback.py
──────────────────────────────────────────────────────────────────────────────
Ragflow 응답의 reference 필드를 LiteLLM proxy HTTP 응답 헤더로 전달하는 callback.

== 동작 원리 ==

1. Ragflow가 응답 JSON에 choices[0].message.reference 포함 (비표준 필드)
2. OpenAI SDK (extra='allow') → ChatCompletion 파싱 시 reference 보존
3. LiteLLM convert_to_model_response_object():
   choice["message"].keys() - _MESSAGE_FIELDS 루프로 비표준 필드를
   message.provider_specific_fields 에 저장
   (litellm/litellm_core_utils/llm_response_utils/convert_dict_to_response.py:558)
4. [이 callback] async_post_call_response_headers_hook:
   provider_specific_fields["reference"] 추출 →
   {"x-ragflow-reference": json} 반환
5. LiteLLM proxy가 HTTP 응답 헤더에 포함
   (litellm/proxy/common_request_processing.py:1021)

== 설정 ==

litellm_config.yaml:
  litellm_settings:
    callbacks:
      - ragflow_reference_callback.proxy_handler   ← module_name.instance_name 형식 필수
                                                     (get_instance_fn은 . 기준으로 module/instance 분리)

Docker: config_file_path=/app/config.yaml 기준으로
  → /app/ragflow_reference_callback.py 를 로드하고 proxy_handler 인스턴스를 가져옴
  → docker-compose.yml에 반드시 마운트 필요:
       - ./ragflow_reference_callback.py:/app/ragflow_reference_callback.py

== 클라이언트 사용 ==

  import json, openai
  client = openai.OpenAI(api_key="sk-...", base_url="http://proxy:4000")

  resp = client.chat.completions.with_raw_response.create(
      stream=False,
      model="ragflow-chat-ollama:8b",
      messages=[{"role": "user", "content": "질문"}],
      extra_body={"extra_body": {"reference": True}},
  )
  content   = json.loads(resp.http_response.text)["choices"][0]["message"]["content"]
  ref_json  = resp.headers.get("x-ragflow-reference")
  reference = json.loads(ref_json) if ref_json else None
"""

import json
from typing import Any, Dict, Optional

import litellm
from litellm.integrations.custom_logger import CustomLogger


class RagflowReferenceCallback(CustomLogger):
    """
    LiteLLM CustomLogger: Ragflow reference 필드를 HTTP 응답 헤더로 노출.

    LiteLLM proxy는 async_post_call_response_headers_hook 반환값을
    HTTP 응답 헤더에 그대로 추가한다.
    (litellm/proxy/common_request_processing.py base_process_llm_request 참조)
    """

    async def async_post_call_response_headers_hook(
        self,
        data: dict,
        user_api_key_dict: Any,
        response: Any,
        request_headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, str]]:
        """
        LiteLLM proxy가 클라이언트에 응답을 반환하기 전 마지막으로 호출됨.
        반환한 dict는 HTTP 응답 헤더에 추가된다.
        """
        try:
            reference = self._extract_reference(response)
            if reference is None:
                return None

            return {
                "x-ragflow-reference": json.dumps(reference, ensure_ascii=True)
            }
        except Exception as e:
            litellm.print_verbose(
                f"[RagflowReferenceCallback] header injection failed: {e}"
            )
            return None

    def _extract_reference(self, response: Any) -> Optional[Any]:
        """
        LiteLLM ModelResponse.choices[0].message.provider_specific_fields 에서
        reference 추출.

        LiteLLM의 convert_to_model_response_object 는 OpenAI 표준 스펙(_MESSAGE_FIELDS)에
        없는 필드를 provider_specific_fields dict 에 저장한다.
        Ragflow의 reference 필드도 이 경로로 보존된다.
        """
        choices = getattr(response, "choices", None)
        if not choices:
            return None

        message = getattr(choices[0], "message", None)
        if message is None:
            return None

        # provider_specific_fields: Ragflow reference가 저장되는 위치
        provider_fields = getattr(message, "provider_specific_fields", None)
        if not provider_fields:
            return None

        return provider_fields.get("reference")


# LiteLLM proxy가 이 이름으로 callback 인스턴스를 참조
proxy_handler = RagflowReferenceCallback()
