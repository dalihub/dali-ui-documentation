# TODO

## [ENH-26] 시그널 패턴 및 code_patterns 사용자 검토 필요

ENH-26 구현 시 아래 두 항목에 예시값이 삽입됩니다.
실제 DALi 헤더에서 확인 후 수정해주세요.

---

### 1. 시그널 연결 패턴

**파일:** `dali-doc-gen/src/02_llm/stage_c_writer.py`  
**검색어:** `CRITICAL ARCHITECTURE CONTEXT`  
**위치:** `view_context` 문자열 블록 끝부분

현재 삽입된 예시:
```
view.SignalName().Connect(this, &MyClass::OnHandler);   ← Style 1
view.SignalName().Connect(&OnHandler);                  ← Style 2
```

수정 방법:
- `SignalName()` 을 실제 DALi UI 시그널 접근자 이름으로 교체  
  (예: `TouchedSignal()`, `KeyEventSignal()`, `FocusChangedSignal()` 등 실제 존재하는 것으로)
- DALi에서 권장하는 연결 스타일을 Style 1로 배치
- 두 스타일 모두 DALi에서 동일하게 지원된다면 현재 순서 유지

---

### 2. code_patterns (공통 코드 관용 패턴)

**파일:** `dali-doc-gen/config/doc_config.yaml`  
**위치:** 파일 최하단 `code_patterns:` 섹션

현재 삽입된 예시 패턴:
- `Dali::Animation::New()` + `AnimateTo()` + `Play()`
- `SetProperty()` with `Dali::Ui::ImageView::Property::RESOURCE_URL`
- `SetProperty()` with `Dali::Actor::Property::SIZE`

수정 방법:
- 각 패턴의 API 이름, 네임스페이스, 파라미터 타입을 실제 DALi 헤더 기준으로 검토
- 잘못된 API명이 있으면 해당 줄을 수정하거나 해당 패턴 블록을 삭제
- 추가하고 싶은 관용 패턴이 있으면 동일 형식(`// ── 설명 ──` + 코드)으로 추가

> 이 패턴들은 stage_c Pass 1 프롬프트에 직접 주입되어 LLM이 코드 예시 작성 시 참고합니다.
> 잘못된 API가 있으면 오히려 할루시네이션을 유발할 수 있으므로 반드시 검토해주세요.

---

### 3. typical_use_cases (피처별 사용 시나리오 힌트)

**파일:** `dali-doc-gen/config/doc_config.yaml`  
**위치:** `feature_hints` 섹션 내 각 피처 항목

이 항목은 **사용자가 직접 작성**해야 합니다. Claude가 DALi 실제 사용 시나리오를 정확히 알 수 없어 자동 생성하지 않습니다.

작성 방법:
- TOC 개선 효과를 원하는 피처에 한해 선택적으로 추가 (없으면 기존 동작 유지)
- `extra_context`와 동일 레벨에 `typical_use_cases:` 리스트로 추가

```yaml
feature_hints:
  image-view:
    extra_context: "..."       # 기존 필드
    typical_use_cases:         # 새 필드 (선택적)
      - "정적 이미지를 지정된 영역에 맞게 표시"
      - "URL 기반 비동기 이미지 로딩 및 로딩 상태 처리"
      - "FittingMode/SamplingMode로 스케일 정책 제어"
```

> stage_b TOC 설계 시 이 시나리오들을 섹션 구성 힌트로 사용합니다.
> 실제 개발자가 해당 피처를 어떤 목적으로 사용하는지 기준으로 작성해주세요.
