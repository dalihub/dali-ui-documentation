# ENH-15: API Tier 기반 Blueprint 분리 생성 및 필터링 개선

## 작성 목적
현재 `stage_b_blueprints.json`이 통합 생성되면서 `--tier=app` 모드로 동작할 때에도 `devel-api/integration-api`가 포함되어 문서를 생성하게 되는 문제를 해결하기 위해, Blueprint 생성 시 Tier를 기준으로 분리하여 `stage_b_blueprints_app.json` 및 `stage_b_blueprints_platform.json`으로 쪼개서 유지보수성과 API 데이터 정합성을 확보한다.

## 제안된 변경 사항

### 1. `src/02_llm/stage_b_mapper.py` 변경
- **`OUT_BLUEPRINTS_PATH` 동적 처리**: 하드코딩된 `stage_b_blueprints.json` 대신 `main()` 안에서 `--tier` 파라미터를 기반으로 `stage_b_blueprints_app.json` 또는 `stage_b_blueprints_platform.json`으로 동적으로 할당
- **`build_api_tier_index()` 멤버 포함 개선**: 파싱된 Compound(클래스)의 티어뿐아니라 해당하는 Members(메서드) 전체에 대해서도 `api_tier_index`에 등록, 이후 필터링에서 멤버 이름이 누락되지 않도록 반영
- **사전 API 필터링 적용**:
  - 기존에는 `sample_apis()` 이후에 제한된 개수에 대해서 API를 다루었으나, 앞으로는 `main()`에서 루프를 돌 때 **우선적으로 `filter_apis_by_tier()`를 실행**한 뒤 남은 목록에 대해서만 `sample_apis()` 수행
  - Child Feature 주입 시에도 `build_child_entries()` -> `find_child_api_names()` 과정에서 Doxygen을 리딩할 때 **미리 `allowed_tiers`로 필터링**하여 매칭 한도를 초과하지 않게 조정
- **Blueprint 저장 필드 수정**: 필터링된 최종 `apis`와 추가적으로 `allowed_tiers` 메타데이터를 Blueprint 항목에 보존

### 2. `src/02_llm/stage_c_writer.py` 변경
- **Blueprint 동적 로드**: 전역 상수로 정의된 `BLUEPRINTS_PATH` 의존성을 제거
- `main()` 초반에서 인자로 받은 `--tier` 값에 맞춰 `doc_blueprints/stage_b_blueprints_{args.tier}.json` 파일을 읽어들여 작업 수행하도록 수정. 기존 파일과의 호환성을 고려해 분리된 파일이 없을 시 기존 명칭 파일로 폴백하도록 보완 가능.

### 3. `src/02_llm/stage_d_validator.py` 변경
- **재검증 시 Blueprint 참조 로직 수정**:
  - 동일하게 `BLUEPRINTS_PATH` 전역 상수를 제거
  - `--tier` 플래그나 validator에 전달된 tier를 기반으로 `load_blueprints(tier)` 함수 내부에서 `stage_b_blueprints_{tier}.json` 파일을 읽어 수행.

## 검증 계획
1. `python dali-doc-gen/src/pipeline.py --mode full --tier app --limit 1` 실행
2. `cache/doc_blueprints/stage_b_blueprints_app.json` 이 제대로 생성되었는지 확인
3. 위 생성본 내 `apis` 리스트에 `devel-api` 가 속해있지 않은지 검토
4. 정상적으로 `app/` 타겟 폴더에 파일이 발행되는지 확인
5. `python dali-doc-gen/src/pipeline.py --mode full --tier platform --limit 1` 실행 후 platform 타겟에 대한 이상유무 점검
