# [BUG] Integration::XxxImpl 클래스가 child feature로 remapping되지 않는 문제

## 현상

taxonomy에 의해 `image-view`가 `animated-image-view`, `lottie-animation-view`로 분리될 때,
`Dali::Ui::AnimatedImageView`는 `animated-image-view`로 올바르게 remapping되지만
`Dali::Ui::Integration::AnimatedImageViewImpl`과 그 하위 클래스(`::Property`)는
여전히 `image-view` 소속으로 남는다.

## 근본 원인

두 곳의 매칭 로직 한계:

**① `find_child_api_names()`**
```python
simple_name = comp_name.split("::")[-1].lower()
if simple_name == search_name:  # "animatedimageviewimpl" != "animatedimageview"
```
`AnimatedImageViewImpl`의 마지막 세그먼트가 `search_name`과 정확히 일치하지 않아
child entry의 apis에 포함되지 않음.

**② `update_class_feature_map_for_children()`**
child entry의 apis 목록에 없는 항목은 remapping 대상이 안 됨.
`AnimatedImageViewImpl::Property`는 별도 compound라 apis에도 없고 members에도 없음.

## 영향 범위

- **app-guide**: 영향 없음 (integration-api 티어 필터가 먼저 작동)
- **platform-guide**:
  - 수정 전: `AnimatedImageViewImpl` 스펙이 image-view 문서에 잘못 포함
  - 수정 전: `animated-image-view` 문서에 impl 스펙 누락
  - 수정 후 (Stage B 재실행 포함): 올바른 child 문서에 impl 스펙 포함

## 해결 방법: 2곳 수정

### ① `src/02_llm/stage_b_mapper.py` — `find_child_api_names()`

`startswith(search_name + "impl")` 조건 추가로 `XxxImpl` 클래스를 child apis에 포함:

```python
# 수정 전
if simple_name == search_name:

# 수정 후
if simple_name == search_name or simple_name.startswith(search_name + "impl"):
```

효과: `AnimatedImageViewImpl`이 `animated-image-view` child entry의 apis에 포함됨
      → blueprint에 impl 클래스가 전달됨
      → Stage C에서 impl 스펙 조회 가능해짐

### ② `src/02_llm/stage_b_mapper.py` — `update_class_feature_map_for_children()`

Pass 1(기존)에서 remapping된 클래스들을 기록하고,
Pass 2에서 해당 클래스명을 포함하는 관련 항목(`::Property` 등)을 추가 remapping:

```python
# Pass 1 후 remapped_classes = {"AnimatedImageView": "animated-image-view", ...}

# Pass 2: 관련 variant 클래스 전파
for key in cfm:
    for simple_class, child_name in remapped_classes.items():
        if len(simple_class) < 6:
            continue  # 너무 짧은 이름 오매칭 방지
        if simple_class in key and cfm[key] != child_name:
            cfm[key] = child_name
```

효과: `AnimatedImageViewImpl::Property` 등 별도 compound가 올바른 child feature로 배정됨

## 수정 후 파이프라인 효과

| 대상 | 수정 전 | 수정 후 |
|------|---------|---------|
| app-guide 전체 | 변화 없음 | 변화 없음 |
| platform animated-image-view | impl 스펙 누락 | impl + Property 스펙 포함 |
| platform lottie-animation-view | impl 스펙 누락 | impl + Property 스펙 포함 |
| platform image-view | impl 스펙 잘못 포함 | impl 제거, 올바른 범위로 축소 |

## 주의: Stage B 재실행 필요

fix 적용 후 아래 feature의 Stage B를 반드시 재실행해야 blueprint와 스펙이 일치함:
- `image-view`
- `animated-image-view`
- `lottie-animation-view`

재실행 없이 Stage C만 돌리면 image-view blueprint가 impl 섹션을 가정한 TOC를 가지고 있으나
Stage C에서 impl 스펙이 foreign filter로 제거되어 Stage D FAIL 가능성 있음.

## 구현 체크리스트

- [ ] `find_child_api_names()` — `startswith(search_name + "impl")` 조건 추가
- [ ] `update_class_feature_map_for_children()` — Pass 2 substring 스캔 추가
