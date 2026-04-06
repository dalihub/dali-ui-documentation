# Implementation Plan - Phase 2 Stage C (Content Writer)

## Goal Description
Stage B에서 LLM을 이용해 기획했던 문서 목차(`stage_b_blueprints.json`) 철골 위에, 실제 살을 붙여 **"진짜 Markdown 파일"**을 찍어내는 **Stage C (Instruct Writer)** 단계입니다. 
지금까지는 이름만 오가던 메타데이터 작업이었다면, 이번엔 Phase 1에서 우리가 Doxygen으로 뽑아두었던 "진짜 API 스펙(파라미터 타입, 주석 등)"(`parsed_doxygen/*.json`)을 원본으로 끌고 와서 LLM에게 던져주고, "이 재료들로 코딩 예제가 포함된 설명서를 작성해라"라고 명령합니다.

## Proposed Changes

### [NEW] `src/02_llm/stage_c_writer.py`
다음 파이프라인으로 구성된 Markdown 생성 AI 자동화 스크립트를 작성합니다.

1. **지형지물 및 스펙 로드**
   - Stage B가 만든 목차 설계도 `stage_b_blueprints.json`을 읽어 순회합니다.
   - 각 Feature(`actors`, `rendering`)가 가진 API 문자열(`Dali::Actor`)을 토대로, **Phase 1의 오리지널 스펙 파일(`parsed_doxygen/dali-core.json` 등)을 검색하여 진짜 파라미터(`argsstring`)와 주석(`brief`) 데이터**를 역참조(Join)하여 수집합니다.

2. **LLM Prompting (작가 - Instruct 모델 호출)**
   - 수집된 실제 API 스펙과 방금 짰던 `outline` (목차)를 묶어, `llm_client.py`의 `Instruct` (가볍고 빠른 저술용 모델)에게 프롬프트를 전송합니다.
   - *"너는 공식 문서 집필자야. 주어진 목차 순서에 맞춰 이 API 스펙들만 사용해서 마크다운 문서를 통째로 작성해. C++ 코드 예시를 꼭 포함하고, 없는 함수를 뇌피셜로 지어내지 마."*

3. **마크다운(MD) 포맷팅 및 파일 I/O 산출**
   - LLM이 텍스트로 응답한 결과를 파싱합니다. (쓸데없는 Markdown Code Block 포맷팅 기호 ` ```markdown ` 등을 제거하는 정규화 수행)
   - 파이프라인의 최종 종착지 형태인 **`cache/markdown_drafts/{feature_name}.md`** 파일로 물리적 저장(Export)합니다.
   - 이로써, 로컬 디렉터리에 30여 개의 개발용 MD 가이드 문서 초안이 탄생하게 됩니다!
