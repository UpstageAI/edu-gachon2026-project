# Performance and Maintainability Policy

## 적용 범위

반복문, database query, collection, cache, recursion, serialization, network call, large diff,
background workflow, 공통 interface를 변경하는 PR과 수동 심층 리뷰에 적용한다.

## PERF-001 시간 복잡도

변경된 실행 경로에서 입력 크기에 따라 반복 횟수나 query 수가 증가하면 입력 변수를 명시하고
Big-O를 추정한다. loop 내부 network/database 호출, 동일 데이터의 반복 scan, 불필요한
정렬처럼 diff로 입증 가능한 경우만 finding을 생성한다.

## PERF-002 공간 복잡도

입력 크기에 비례해 collection, buffer, cache 또는 recursion depth가 증가하면 메모리 증가량과
해제 시점을 검토한다. 근거 없는 메모리 최적화 제안은 하지 않는다.

## CLEAN-001 코드 간소화

동일 조건의 중복 branch, 불필요한 상태, 한 번만 쓰는 wrapper, 중복 serialization을 제거해
동작을 유지하면서 코드와 interface를 줄일 수 있는지 검토한다. 단순 취향이나 축약 표현은
간소화 finding으로 취급하지 않는다.

## CLEAN-002 변경 범위

함수와 모듈은 하나의 책임을 유지한다. 현재 PR 목적과 무관한 추상화나 미래 요구를 위한
일반화는 제안하지 않는다. 제안에는 기대 효과와 trade-off를 함께 적는다.
