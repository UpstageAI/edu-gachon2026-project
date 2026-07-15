# 의존성과 CI/CD 공급망

1. 새 dependency, container image, GitHub Action이 신뢰 경계를 넓히거나 secret·write permission을 얻는지 확인한다.
2. lockfile과 manifest가 함께 갱신됐는지, immutable reference 또는 팀 정책에 맞는 version pin을 사용하는지 확인한다.
3. 버전이 오래됐다는 추측만으로 지적하지 않고 실제 권한 확대, 재현성 저하, 알려진 CI 경고가 있을 때만 finding을 만든다.
