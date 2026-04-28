# [ENH-29] dali-guide_auto를 상태 저장소로 사용하는 Workflow 재설계

## 개요

ENH-28을 대체한다. ENH-28은 cache 보존을 위해 dali-ui-documentation에 PR을 올리고
on-docs-merged.yml로 2단계 반영하는 구조였다.
ENH-29는 dali-guide_auto를 cache + docs의 단일 저장소로 사용하여 구조를 단순화한다.

---

## 4가지 시나리오 검증

### 경로 정리

| 항목 | 실제 경로 |
|------|-----------|
| cache | `dali-ui-documentation/dali-doc-gen/cache/` |
| app-guide | `dali-ui-documentation/app-guide/` |
| platform-guide | `dali-ui-documentation/platform-guide/` |
| dali-guide_auto 저장 구조 | `cache/`, `app-guide/`, `platform-guide/` (레포 루트 기준) |

`pipeline.py`의 `PROJECT_ROOT`는 `dali-doc-gen/`이므로 cache는 `dali-doc-gen/cache/`에 생성된다.
dali-guide_auto에는 `cache/`로 저장하고, workflow에서 경로를 매핑하여 복사한다.

---

### 시나리오 1: Action Full

```
1. dali-ui-documentation checkout (fresh)
2. pipeline.py --mode full 실행
   → app-guide/, platform-guide/, dali-doc-gen/cache/ 생성
3. 결과물을 dali-guide_auto에 push → PR 생성
   · dali-doc-gen/cache/  →  dali-guide_auto/cache/
   · app-guide/           →  dali-guide_auto/app-guide/
   · platform-guide/      →  dali-guide_auto/platform-guide/
```

> environment=internal이면 push/PR 스텝 skip (사내 dali-guide_auto 미등록)

---

### 시나리오 2: Action Weekly (Update)

```
1. dali-ui-documentation checkout (fresh)
2. dali-guide_auto checkout → 파일 복사
   · dali-guide_auto/cache/         →  dali-doc-gen/cache/
   · dali-guide_auto/app-guide/     →  app-guide/
   · dali-guide_auto/platform-guide/ → platform-guide/
3. pipeline.py --mode update 실행 (복사된 cache 참조)
   → app-guide/, platform-guide/, dali-doc-gen/cache/ 업데이트
4. 결과물을 dali-guide_auto에 push → PR 생성 (시나리오 1과 동일)
```

> environment=internal이면 2, 4번 스텝 skip

---

### 시나리오 3: 로컬 Full

```
1. cd dali-ui-documentation/dali-doc-gen
2. python src/pipeline.py --mode full
   → app-guide/, platform-guide/, dali-doc-gen/cache/ 생성
```

pipeline.py 변경 없음. 결과물이 dali-ui-documentation 내에 생성되는 기존 동작 유지.

---

### 시나리오 4: 로컬 Update (Partial)

```
1. dali-ui-documentation/app-guide/, platform-guide/, dali-doc-gen/cache/ 존재
2. cd dali-ui-documentation/dali-doc-gen
3. python src/pipeline.py --mode update
   → 기존 cache 참조하여 업데이트
```

pipeline.py 변경 없음. 이전 로컬 실행 결과물을 그대로 참조.

---

## 변경 사항

### ENH-28 대비 달라지는 점

| 항목 | ENH-28 | ENH-29 |
|------|--------|--------|
| cache 저장 위치 | dali-ui-documentation main | dali-guide_auto main |
| PR 단계 | 2단계 (dali-ui-doc → dali-guide_auto) | 1단계 (dali-guide_auto 직접) |
| on-docs-merged.yml | 필요 | **삭제** |
| auto-approve.yml | dali-ui-documentation PR 자동 머지 | dali-guide_auto PR 자동 머지 |
| .gitignore 충돌 | `git add -f` 필요 | 없음 (다른 레포에 push) |

---

## 작업 1: `initial-full-gen.yml` 수정

### 변경

`Create PR to dali-ui-documentation` 스텝을 `Push docs to dali-guide_auto` 스텝으로 교체.

```yaml
- name: Push docs to dali-guide_auto and create PR
  if: github.event.inputs.environment != 'internal'
  env:
    GH_TOKEN: ${{ secrets.DOCS_REPO_TOKEN }}
    DOCS_REPO_TOKEN: ${{ secrets.DOCS_REPO_TOKEN }}
    TIER: ${{ github.event.inputs.tier }}
  run: |
    DOCS_REPO_URL="https://x-access-token:${DOCS_REPO_TOKEN}@github.com/dalihub/dali-guide_auto.git"
    BRANCH="docs/initial-full-${TIER}"

    # dali-guide_auto 클론 (빈 레포면 init으로 대체)
    if git clone --depth 1 "$DOCS_REPO_URL" docs-output; then
      echo "[docs] Cloned dali-guide_auto"
    else
      mkdir -p docs-output
      git -C docs-output init
      git -C docs-output remote add origin "$DOCS_REPO_URL"
    fi

    # 기존 파일 제거 후 새 결과물 복사
    rm -rf docs-output/app-guide docs-output/platform-guide docs-output/cache
    [ -d app-guide/ ]           && cp -r app-guide/           docs-output/app-guide/
    [ -d platform-guide/ ]      && cp -r platform-guide/      docs-output/platform-guide/
    [ -d dali-doc-gen/cache/ ]  && cp -r dali-doc-gen/cache/  docs-output/cache/

    cd docs-output
    git config user.name "github-actions[bot]"
    git config user.email "github-actions[bot]@users.noreply.github.com"
    git add .

    if [ -z "$(git status --porcelain)" ]; then
      echo "[skip] No changes."
      exit 0
    fi

    if git ls-remote --heads origin | grep -q 'refs/heads/main'; then
      git switch -C "$BRANCH"
      git commit -m "docs(auto): initial full generation for ${TIER}"
      git push origin "$BRANCH" --force
      gh pr create \
        --repo dalihub/dali-guide_auto \
        --title "docs: Initial Full Generation (${TIER})" \
        --body "Generated docs + cache state from initial-full-gen workflow." \
        --base main \
        --head "$BRANCH" \
      || gh pr edit "$BRANCH" \
        --repo dalihub/dali-guide_auto \
        --body "Generated docs + cache state. (updated: $(date -u +%Y-%m-%dT%H:%M:%SZ))"
    else
      git switch -C main
      git commit -m "docs(auto): initial full generation for ${TIER}"
      git push origin main
    fi
```

> `if: github.event.inputs.environment != 'internal'` 조건으로 internal 시 스텝 전체 skip.

### 영향 범위

| 파일 | 변경 내용 |
|------|-----------|
| `.github/workflows/initial-full-gen.yml` | PR 스텝 교체, internal 조건 추가 |

---

## 작업 2: `weekly-update.yml` 수정

### 변경

pipeline 실행 전 dali-guide_auto 데이터 복사 스텝 추가 + PR 대상을 dali-guide_auto로 변경.

```yaml
- name: Restore state from dali-guide_auto
  if: >
    github.event.inputs.environment != 'internal' &&
    !(github.event.inputs.environment == '' && vars.DEFAULT_ENVIRONMENT == 'internal')
  env:
    DOCS_REPO_TOKEN: ${{ secrets.DOCS_REPO_TOKEN }}
  run: |
    DOCS_REPO_URL="https://x-access-token:${DOCS_REPO_TOKEN}@github.com/dalihub/dali-guide_auto.git"

    if git clone --depth 1 "$DOCS_REPO_URL" dali-guide-state; then
      [ -d dali-guide-state/cache/ ]        && cp -r dali-guide-state/cache/        dali-doc-gen/cache/
      [ -d dali-guide-state/app-guide/ ]    && cp -r dali-guide-state/app-guide/    app-guide/
      [ -d dali-guide-state/platform-guide/ ] && cp -r dali-guide-state/platform-guide/ platform-guide/
      echo "[state] Restored cache, app-guide, platform-guide from dali-guide_auto"
    else
      echo "[state] dali-guide_auto clone failed or empty — running full regeneration"
    fi

# ... (Run Pipeline 스텝은 기존과 동일) ...

- name: Push docs to dali-guide_auto and create PR
  if: >
    github.event.inputs.environment != 'internal' &&
    !(github.event.inputs.environment == '' && vars.DEFAULT_ENVIRONMENT == 'internal')
  env:
    GH_TOKEN: ${{ secrets.DOCS_REPO_TOKEN }}
    DOCS_REPO_TOKEN: ${{ secrets.DOCS_REPO_TOKEN }}
  run: |
    # initial-full-gen과 동일한 push 로직, BRANCH="docs/weekly-update"
```

> `Restore state` clone 실패 시 cache 없이 진행 → `pipeline.py`가 자동으로 전체 재생성 fallback.

### 영향 범위

| 파일 | 변경 내용 |
|------|-----------|
| `.github/workflows/weekly-update.yml` | `Restore state from dali-guide_auto` 스텝 추가, PR 스텝 교체, internal 조건 추가 |

---

## 작업 3: `on-docs-merged.yml` 삭제

ENH-28에서 추가된 파일. ENH-29에서는 불필요하므로 삭제한다.

---

## 작업 4: `auto-approve.yml` 수정

ENH-28에서는 dali-ui-documentation의 PR을 자동 머지했으나,
ENH-29에서는 dali-guide_auto의 PR을 자동 머지한다.

```yaml
- name: Auto-merge pending docs PR in dali-guide_auto
  env:
    GH_TOKEN: ${{ secrets.DOCS_REPO_TOKEN }}
  run: |
    PR_NUMBER=$(gh pr list \
      --repo dalihub/dali-guide_auto \
      --head docs/weekly-update \
      --state open \
      --json number \
      --jq '.[0].number')

    if [ -z "$PR_NUMBER" ] || [ "$PR_NUMBER" = "null" ]; then
      echo "[skip] No open docs/weekly-update PR in dali-guide_auto."
      exit 0
    fi

    gh pr merge "$PR_NUMBER" \
      --repo dalihub/dali-guide_auto \
      --squash \
      --subject "docs(auto): weekly update auto-merge" \
      --delete-branch
```

### 영향 범위

| 파일 | 변경 내용 |
|------|-----------|
| `.github/workflows/auto-approve.yml` | PR 대상 레포를 dali-guide_auto로 변경, DOCS_REPO_TOKEN 사용 |

---

## 전체 영향 범위 요약

| 파일 | 변경 종류 |
|------|-----------|
| `.github/workflows/initial-full-gen.yml` | 수정 |
| `.github/workflows/weekly-update.yml` | 수정 |
| `.github/workflows/on-docs-merged.yml` | **삭제** |
| `.github/workflows/auto-approve.yml` | 수정 |

## 작업 순서

작업 3 (삭제) → 작업 1, 2, 4 (병렬 진행 가능)
