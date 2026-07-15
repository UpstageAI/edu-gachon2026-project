# GitHub Review Workflow Policy

## 적용 범위

GitHub App, pull request, check suite, check run, installation token, PR comment 또는 Checks API를
변경하는 PR에 적용한다. 관련 경로는 `github_app.py`, `publisher.py`, webhook handler다.

## GH-001 CI 이후 자동 리뷰

운영 기본 모드 `after_checks`에서는 `pull_request` event로 리뷰를 실행하지 않는다.
`check_suite.completed` 이후 같은 head SHA의 lint와 test 결과를 다시 조회한 뒤 자동 리뷰한다.

## GH-002 선택적 심층 리뷰

자동 리뷰는 실패 원인 빠른 리뷰 또는 정책 기반 표준 리뷰를 생성한다. 심층 품질 리뷰는
`AI Code Review` Check Run의 `심층 리뷰 실행` action을 사용자가 요청했을 때만 실행한다.

## GH-003 자기 이벤트와 중복 방지

서비스가 만든 Check Run event는 다시 리뷰 trigger로 사용하지 않는다. idempotency key에는
repository, PR number, head SHA, review mode를 포함한다.

## GH-004 최소 권한

GitHub App installation token을 사용하고 Contents read, Pull requests write, Checks write 범위를
넘는 권한을 요구하지 않는다. token을 DB, comment, application log에 기록하지 않는다.
