import { clearAuth, getAuth, setAuth } from './storage';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface RefreshResponseDto {
  access_token: string;
  token_type: string;
}

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const response = await fetch(`${API_URL}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!response.ok) return null;
  const data: RefreshResponseDto = await response.json();
  return data.access_token;
}

function redirectToLanding(): void {
  clearAuth();
  window.location.href = '/';
}

// 인증이 필요한 요청을 보내고, access token이 만료되어 401이 오면
// refresh token으로 재발급을 시도한 뒤 한 번만 재요청한다.
// refresh token마저 만료됐다면 랜딩페이지로 이동시킨다.
async function authorizedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const auth = getAuth();
  const headers = new Headers(init.headers);
  if (auth) headers.set('Authorization', `Bearer ${auth.accessToken}`);

  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (response.status !== 401 || !auth) return response;

  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  const newAccessToken = await refreshPromise;

  if (!newAccessToken) {
    redirectToLanding();
    return response;
  }

  setAuth({ accessToken: newAccessToken, user: auth.user });
  headers.set('Authorization', `Bearer ${newAccessToken}`);
  return fetch(`${API_URL}${path}`, { ...init, headers });
}

export interface AllergenDto {
  id: string;
  allergen_name: string;
  category: string;
}

export interface IngredientDto {
  id: string;
  name: string;
  description?: string | null;
  allergen?: AllergenDto | null;
}

export interface IngredientCategoryDto {
  id: string;
  name: string;
}

export interface ConfirmIngredientSelectionResponseDto {
  ingredients: IngredientDto[];
  allergens: AllergenDto[];
}

export interface IngredientRefDto {
  name: string;
  category: string | null;
}

export interface RecipeSummaryDto {
  id: string;
  name: string;
  cooking_time: number | null;
  missing_ingredients: IngredientRefDto[];
}

export interface SubstituteDto {
  ingredient_name: string;
  substitute_name: string;
  note: string | null;
  allergy_conflict: boolean;
}

export interface ClassificationDto {
  required: string[];
  optional: string[];
  reason: string | null;
}

export interface RecipeDetailDto {
  recipe_id: string;
  name: string;
  cooking_time: number | null;
  difficulty: string | null;
  category: string | null;
  cooking_method: string | null;
  owned_ingredients: IngredientRefDto[];
  missing_ingredients: IngredientRefDto[];
  classification: ClassificationDto | null;
  substitutes: SubstituteDto[];
  cooking_steps: string[];
}

export interface RecommendResponseDto {
  recipes: RecipeSummaryDto[];
  detail: RecipeDetailDto | null;
  message: string;
}

export interface RecommendStatusEvent {
  node: string;
  message: string;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`);
  if (!response.ok) {
    throw new Error(`요청이 실패했어요 (${response.status})`);
  }
  return response.json();
}

const VALIDATION_FIELD_LABELS: Record<string, string> = {
  username: '아이디',
  password: '비밀번호',
  name: '이름',
};

function translateValidationError(error: { loc?: unknown[]; msg?: string }): string {
  const loc = Array.isArray(error.loc) ? error.loc : [];
  const field = String(loc[loc.length - 1] ?? '');
  const label = VALIDATION_FIELD_LABELS[field] ?? field;
  const msg = error.msg ?? '';

  const atLeast = msg.match(/at least (\d+) characters?/);
  if (atLeast) return `${label}는 ${atLeast[1]}자 이상이어야 해요.`;

  const atMost = msg.match(/at most (\d+) characters?/);
  if (atMost) return `${label}는 ${atMost[1]}자 이하여야 해요.`;

  return label ? `${label}: ${msg}` : msg;
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => null);
  if (!body) return fallback;
  if (typeof body.detail === 'string') return body.detail;
  if (Array.isArray(body.detail)) {
    const messages = body.detail.map(translateValidationError).filter(Boolean);
    if (messages.length) return messages.join(' ');
  }
  return fallback;
}

export function getIngredients(): Promise<IngredientCategoryDto[]> {
  return getJson<IngredientCategoryDto[]>('/ingredients');
}

export async function confirmIngredientSelection(
  categoryId: string,
): Promise<ConfirmIngredientSelectionResponseDto> {
  const response = await authorizedFetch('/ingredients/selection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category_id: categoryId }),
  });
  if (!response.ok) {
    throw new Error(`재료 카테고리 조회에 실패했어요 (${response.status})`);
  }
  return response.json();
}

export function getAllergens(): Promise<AllergenDto[]> {
  return getJson<AllergenDto[]>('/allergens');
}

// /recommend는 SSE로 응답한다: 노드가 끝날 때마다 status 이벤트, 끝나면 final(+done) 이벤트.
// onStatus를 넘기면 진행상황을 실시간으로 받아 로딩 화면에 반영할 수 있다.
export async function recommend(
  ingredientIds: string[],
  allergenIds: string[],
  recipeId?: string,
  onStatus?: (status: RecommendStatusEvent) => void,
): Promise<RecommendResponseDto> {
  const response = await fetch(`${API_URL}/recommend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ingredient_ids: ingredientIds,
      allergen_ids: allergenIds,
      ...(recipeId ? { recipe_id: recipeId } : {}),
    }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`레시피 추천 요청이 실패했어요 (${response.status})`);
  }
  return readRecommendStream(response.body, onStatus);
}

async function readRecommendStream(
  body: ReadableStream<Uint8Array>,
  onStatus?: (status: RecommendStatusEvent) => void,
): Promise<RecommendResponseDto> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let result: RecommendResponseDto | null = null;
  let errorMessage: string | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split('\n\n');
    buffer = events.pop() ?? '';

    for (const rawEvent of events) {
      const lines = rawEvent.split('\n');
      const eventLine = lines.find((line) => line.startsWith('event: '));
      const dataLine = lines.find((line) => line.startsWith('data: '));
      if (!dataLine) continue;

      const eventType = eventLine ? eventLine.slice('event: '.length) : 'message';
      const payload = JSON.parse(dataLine.slice('data: '.length));

      if (eventType === 'status') {
        onStatus?.(payload as RecommendStatusEvent);
      } else if (eventType === 'final') {
        result = payload as RecommendResponseDto;
      } else if (eventType === 'error') {
        errorMessage = typeof payload.message === 'string' ? payload.message : null;
      }
    }
  }

  if (errorMessage) throw new Error(errorMessage);
  if (!result) throw new Error('레시피 추천 응답을 받지 못했어요.');
  return result;
}

export interface AuthUserDto {
  id: string;
  username: string;
  name: string;
}

export interface LoginResponseDto {
  access_token: string;
  token_type: string;
  user: AuthUserDto;
}

export async function signup(username: string, password: string, name: string): Promise<AuthUserDto> {
  const response = await fetch(`${API_URL}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, name }),
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `회원가입에 실패했어요 (${response.status})`));
  }
  return response.json();
}

export async function login(username: string, password: string): Promise<LoginResponseDto> {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `로그인에 실패했어요 (${response.status})`));
  }
  return response.json();
}

export async function logout(): Promise<void> {
  await fetch(`${API_URL}/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  });
}

export interface MyInfoDto {
  id: string;
  username: string;
  name: string;
  allergens: AllergenDto[];
}

export async function getMyInfo(): Promise<MyInfoDto> {
  const response = await authorizedFetch('/users/me');
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `내 정보를 불러오지 못했어요 (${response.status})`));
  }
  return response.json();
}

export async function updateMyAllergens(allergenIds: string[]): Promise<MyInfoDto> {
  const response = await authorizedFetch('/users/me/allergens', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ allergen_ids: allergenIds }),
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `알레르기 정보 저장에 실패했어요 (${response.status})`));
  }
  return response.json();
}
