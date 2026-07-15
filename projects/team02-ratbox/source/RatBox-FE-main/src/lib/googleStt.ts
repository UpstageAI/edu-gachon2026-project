const STT_ENDPOINT = 'https://speech.googleapis.com/v1/speech:recognize';

export async function transcribeAudio(audioBlob: Blob): Promise<string> {
  const apiKey = import.meta.env.VITE_GOOGLE_STT_API_KEY;
  if (!apiKey) {
    throw new Error('Google STT API 키가 설정되지 않았어요. .env의 VITE_GOOGLE_STT_API_KEY를 확인해주세요.');
  }

  const base64Audio = await blobToBase64(audioBlob);

  const response = await fetch(`${STT_ENDPOINT}?key=${apiKey}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      config: {
        encoding: 'WEBM_OPUS',
        sampleRateHertz: 48000,
        languageCode: 'ko-KR',
      },
      audio: { content: base64Audio },
    }),
  });

  if (!response.ok) {
    const errText = await response.text();
    throw new Error(`음성 인식 요청이 실패했어요 (${response.status}): ${errText}`);
  }

  const data = await response.json();
  const transcript = (data.results ?? [])
    .map((result: { alternatives?: { transcript?: string }[] }) => result.alternatives?.[0]?.transcript ?? '')
    .join(' ')
    .trim();

  if (!transcript) {
    throw new Error('음성을 인식하지 못했어요. 다시 말씀해주세요.');
  }

  return transcript;
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result as string;
      resolve(result.split(',')[1] ?? '');
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
