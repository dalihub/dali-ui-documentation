# 제안: Doxygen 파서 (`doxygen_parser.py`) 구현 계획

`Phase 1`의 핵심 컴포넌트인 `doxygen_parser.py`의 구현 계획입니다.
이 모듈은 `doxygen_runner`가 생성한 방대한 XML 파일들을 분석하여, 메모리와 LLM 컨텍스트 한도를 절약할 수 있는 경량화된 구조화 JSON으로 변환합니다.

## 제안하는 변경 사항

### 1. 파서 기본 구조 및 실행 흐름

`src/00_extract/doxygen_parser.py`에 다음과 같은 로직을 구현합니다.

- **`index.xml` 파싱**: Doxygen이 생성한 `cache/doxygen_json/{package}/xml/index.xml`을 열어 `kind`가 `class`, `struct`, `namespace`인 요소(Compound)들을 식별합니다.
- **개별 `.xml` 파싱**: 식별된 각 `refid`를 기반으로 `refid.xml` 파일을 열어 구체적인 API 데이터를 추출합니다.
- **불필요한 데이터 제거**: 파일 오프셋, 내부 ID 등은 버려 결과 JSON의 크기를 최소화(약 60~70% 절감 예상)합니다.
- **파일 경로 기반 API Tier 분류**: XML 내의 `<location file="...">` 속성 문자열을 분석하여 해당 API가 `public-api`, `devel-api`, `integration-api` 중 어디에 속하는지 판별합니다.

### 2. 패키지 별 출력 데이터 모델 (JSON 스키마)

추출이 완료되면 각 패키지(예: `dali-core`) 마다 아래와 같은 형태의 경량 JSON을 생성합니다:

```json
{
  "package": "dali-core",
  "classes": [
    {
      "name": "Dali::Actor",
      "kind": "class",
      "file": "public-api/actors/actor.h",
      "api_tier": "public-api",
      "brief": "Actor is the primary object with which Dali applications interact.",
      "methods": [
        {
          "name": "Add",
          "signature": "void Add(Actor child)",
          "brief": "Adds a child Actor to this Actor.",
          "since": "1_0.0",
          "params": [
            {
              "name": "child",
              "type": "Actor",
              "description": "The child"
            }
          ],
          "returns": "",
          "notes": ["If the child already has a parent..."]
        }
      ]
    }
  ]
}
```

### 3. 주요 정보 추출 세부 규칙

- **Brief / Detailed Description**: `<briefdescription>` 및 `<detaileddescription>` 요소 하위의 `<para>` 내용을 파싱.
- **Since 및 Tag 처리**: `detaileddescription`의 텍스트에 포함된 `@SINCE_...` 등 특정 태그들을 정규표현식이나 문자열 검색으로 파싱하여 별도 필드(`since`)로 분리. `note`, `warning` 등은 `<simplesect kind="note">` 등의 요소에서 텍스트 기반 추출.
- **출력 경로 지정**: `cache/parsed_doxygen/` 와 같은 별도 디렉터리를 두어 원본 XML 데이터(`cache/doxygen_json/.../xml`)와 파싱 결과물을 분리.

## User Review Required

> [!IMPORTANT]
> - 결과 JSON이 저장될 경로로 `cache/parsed_doxygen/{package}.json`을 제안합니다. 기존 `dali_doc_system_dev_plan.md`에는 `cache/doxygen_json/{package}.json`으로 적혀 있었으나, 명확히 디렉토리를 분리하는 것이 관리에 유리해보입니다. 이렇게 진행해도 괜찮을까요?
> - `namespace` 전체에 포함된 함수/변수들(예: 전역 함수들)도 대상에 포함시키는 것이 맞을까요? (일반적으로 필수입니다.)

## Verification Plan

### Manual Verification
- `repo_manager` 및 `doxygen_runner`가 성공적으로 XML을 생성한 이후 이 모듈을 단독 실행 (`python src/00_extract/doxygen_parser.py`)
- `cache/parsed_doxygen/dali-core.json`이 정상적으로 생성되며, 용량이 원래의 XML 폴더합(MB 단위)에 비해 크게 줄어들었는지(수십~수백 KB 안팎) 확인.
- JSON 내부 구조에 API tier (`public-api` 등)가 잘 나타나고 있는지 확인.
