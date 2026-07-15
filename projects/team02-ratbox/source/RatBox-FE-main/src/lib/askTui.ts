const CANNED_ANSWERS = [
  '괜찮아요! 비슷한 재료로 대신해도 맛에는 큰 차이가 없어요.',
  '재료가 없다면 조금 적은 양으로 진행해도 괜찮아요.',
  '불 세기를 약불로 줄이고 조금 더 오래 익히면 실수를 만회할 수 있어요.',
  '지금 단계는 순서가 중요하지 않으니 다음 단계로 넘어가도 돼요.',
];

export function pickCannedAnswer(question: string): string {
  return CANNED_ANSWERS[Math.abs(hashCode(question)) % CANNED_ANSWERS.length];
}

function hashCode(text: string): number {
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = (hash << 5) - hash + text.charCodeAt(i);
    hash |= 0;
  }
  return hash;
}
