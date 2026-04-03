# Doxygen 컨텍스트 품질 강화 구현 계획

## 배경 및 문제 인식

dali-guide 파이프라인은 Doxygen에서 파싱한 API 정보를 기반으로 LLM이 문서를 작성하는 구조다.
`doxygen_parser.py`는 이미 `@param`, `@return`, `@note`, `@warning`, `@code` 블록을 파싱할 능력이 있거나
쉽게 추가할 수 있는 구조임에도, 정작 `stage_c_writer.py`의 `get_api_specs()`가 LLM에 넘기는 정보는
`name`, `brief`, `signature` 정도에 그치고 있다.

이로 인해 발생하는 문제:

- LLM이 파라미터의 의미, 반환값, 주의사항을 Doxygen 원본 기준으로 쓰지 못하고 자체 추론에 의존
- 호출 순서나 사이드이펙트 같은 비자명한 정보가 문서에 빠지거나 할루시네이션으로 채워질 수 있음
- `@code` 예제가 헤더에 있어도 LLM이 전달받지 못해 사용 패턴을 스스로 만들어냄

---

## 작업 목표

### 작업 1: stage_c에 params / returns / notes / warnings 전달

**대상 파일:** `dali-doc-gen/src/02_llm/stage_c_writer.py`

**현재 상태:**
`get_api_specs()` 함수가 member spec을 LLM에 넘길 때 `name`, `kind`, `brief`, `signature`만 포함.
`doxygen_parser.py`는 이미 `params`, `returns`, `notes`, `warnings`를 파싱해 JSON에 저장하고 있음.

**수정 내용:**
member spec dict에 다음 필드를 추가로 포함:
- `params`: `[{type, name, description}]` — 각 파라미터의 타입, 이름, 설명
- `returns`: 반환값 설명 문자열
- `notes`: `@note` 내용 리스트
- `warnings`: `@warning` 내용 리스트

**기대 효과:**
- LLM이 파라미터별 설명을 Doxygen 원문 기반으로 작성 가능
- 반환값, 주의사항을 정확하게 반영한 문서 생성
- 할루시네이션 감소 (특히 파라미터 타입/의미 오류)

---

### 작업 2: doxygen_parser에 @code 블록 추출 추가

**대상 파일:** `dali-doc-gen/src/00_extract/doxygen_parser.py`

**현재 상태:**
`parse_description()` 함수가 `simplesect`(note/warning/return)와 `parameteritem`(@param)은 처리하지만,
`<programlisting>` 태그(Doxygen의 `@code`~`@endcode` 파싱 결과)는 무시하고 있음.

**수정 내용:**
`parse_description()`에서 `<programlisting>` 태그를 추출해 `code_examples` 리스트로 반환.
추출된 코드 예제는 member_data에 `code_examples` 필드로 저장.

이후 `get_api_specs()` (stage_c)에서도 해당 필드를 포함해 LLM에 전달.

**기대 효과:**
- Doxygen에 `@code` 예제가 있는 API는 LLM이 실제 사용 패턴을 참고해 작성 가능
- 특히 Tizen/DALi 특화 호출 패턴(초기화 순서, 플래그 조합 등)이 있는 경우 그대로 반영

---

## 작업 범위 및 주의사항

- 두 작업 모두 기존 파싱 로직을 덮어쓰지 않으며, 필드 추가 방식이므로 하위 호환성 유지
- `code_examples`가 없는 API는 빈 리스트 또는 필드 미포함으로 처리 (LLM 프롬프트 노이즈 방지)
- stage_c의 `max_apidocs_to_extract = 40` 캡은 유지 (LLM 토큰 과부하 방지)
- stage_d 검증 로직은 변경 없음 (심볼 추출 기준이 달라지지 않음)

---

## 작업 순서

1. `doxygen_parser.py` — `parse_description()`에 `<programlisting>` 추출 추가
2. `stage_c_writer.py` — `get_api_specs()`에 `params`, `returns`, `notes`, `warnings`, `code_examples` 전달 추가
3. Doxygen 재파싱 필요 (작업 1 적용 후): `python src/00_extract/doxygen_parser.py`
4. Stage C 재실행으로 효과 확인

---

## 관련 파일

| 파일 | 역할 |
|------|------|
| `src/00_extract/doxygen_parser.py` | Doxygen XML → JSON 파싱 |
| `src/02_llm/stage_c_writer.py` | JSON spec → LLM 프롬프트 조립 및 문서 생성 |
| `cache/parsed_doxygen/*.json` | 파싱 결과 캐시 (재파싱 시 갱신됨) |
