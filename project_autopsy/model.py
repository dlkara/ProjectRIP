from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def object_schema(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}

INTERPRETATION_SCHEMA = object_schema(
    {
        "facts": {"type": "array", "items": object_schema({"text": STRING, "quote": STRING})},
        "assumptions": {"type": "array", "items": object_schema({"text": STRING, "based_on": STRING})},
        "gaps": STRINGS,
    }
)

RISK_SCHEMA = object_schema(
    {
        "mechanism_key": STRING,
        "title": STRING,
        "condition_quote": STRING,
        "assumption": STRING,
        "mechanism": STRING,
        "early_signal": STRING,
        "outcome": STRING,
        "action": STRING,
        "action_when": STRING,
        "done_when": STRING,
        "evidence_id": STRING,
        "similarity": STRING,
        "difference": STRING,
        "impact": {"type": "string", "enum": ["low", "medium", "high"]},
    }
)

REPORT_SCHEMA = object_schema(
    {
        "headline": STRING,
        "summary": STRING,
        "risks": {"type": "array", "items": RISK_SCHEMA},
    }
)

CHANGE_SCHEMA = object_schema(
    {
        "mechanism_key": STRING,
        "status": {"type": "string", "enum": ["해소", "완화", "유지", "새로 발생", "판단 보류"]},
        "reason": STRING,
        "plan_quote": STRING,
    }
)

COMPARISON_SCHEMA = object_schema({"changes": {"type": "array", "items": CHANGE_SCHEMA}})


class ModelError(RuntimeError):
    pass


class OpenAIModel:
    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ModelError("OPENAI_API_KEY가 설정되지 않았습니다.")

    def structured(self, name: str, schema: dict, instructions: str, data: dict) -> dict:
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": json.dumps(data, ensure_ascii=False),
            "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise ModelError("모델 API 인증에 실패했습니다. OPENAI_API_KEY를 확인해 주세요.") from exc
            if exc.code == 429:
                raise ModelError("모델 API 사용 한도에 도달했습니다. 잠시 뒤 다시 시도해 주세요.") from exc
            raise ModelError(f"모델 API 요청이 실패했습니다 (HTTP {exc.code}).") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ModelError(f"모델 API에 연결하지 못했습니다: {exc}") from exc

        if result.get("status") != "completed":
            raise ModelError(f"모델 응답이 완료되지 않았습니다: {result.get('status')}")
        texts = []
        for item in result.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "refusal":
                    raise ModelError("모델이 요청을 거절했습니다.")
                if content.get("type") == "output_text":
                    texts.append(content.get("text", ""))
        if not texts:
            raise ModelError("모델이 분석 결과를 반환하지 않았습니다.")
        try:
            parsed = json.loads("".join(texts))
        except json.JSONDecodeError as exc:
            raise ModelError("모델 결과를 JSON으로 읽을 수 없습니다.") from exc
        if not isinstance(parsed, dict):
            raise ModelError("모델 결과가 객체 형식이 아닙니다.")
        return parsed
