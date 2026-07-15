import type { IngredientRefDto } from './api';

export interface NamedItem {
  id: string;
  name: string;
}

export interface AllergyInfo {
  selected: NamedItem[];
  custom: string;
}

export interface AuthUser {
  id: string;
  username: string;
  name: string;
}

export interface AuthInfo {
  accessToken: string;
  user: AuthUser;
}

const KEYS = {
  ingredients: 'ratbox_ingredients',
  selectedCategories: 'ratbox_selected_categories',
  allergies: 'ratbox_allergies',
  selectedRecipe: 'ratbox_selected_recipe',
  selectedRecipeId: 'ratbox_selected_recipe_id',
  auth: 'ratbox_auth',
  recommendCache: 'ratbox_recommend_cache',
} as const;

export interface CachedRecipeSummary {
  id: string;
  name: string;
  cooking_time: number | null;
  missing_ingredients: IngredientRefDto[];
}

export function getIngredients(): NamedItem[] {
  try {
    return JSON.parse(localStorage.getItem(KEYS.ingredients) || '[]');
  } catch {
    return [];
  }
}

export function setIngredients(ingredients: NamedItem[]): void {
  localStorage.setItem(KEYS.ingredients, JSON.stringify(ingredients));
}

// 사용자에게 "선택한 재료"로 보여주는 건 카테고리명이다 (예: "우유").
// 카테고리 안의 구체적인 세부 재료(ingredients)는 recommend 호출에만 쓰이고 화면에 노출하지 않는다.
export function getSelectedCategories(): NamedItem[] {
  try {
    return JSON.parse(localStorage.getItem(KEYS.selectedCategories) || '[]');
  } catch {
    return [];
  }
}

export function setSelectedCategories(categories: NamedItem[]): void {
  localStorage.setItem(KEYS.selectedCategories, JSON.stringify(categories));
}

export function getAllergies(): AllergyInfo {
  try {
    return JSON.parse(
      localStorage.getItem(KEYS.allergies) || '{"selected":[],"custom":""}',
    );
  } catch {
    return { selected: [], custom: '' };
  }
}

export function setAllergies(allergies: AllergyInfo): void {
  localStorage.setItem(KEYS.allergies, JSON.stringify(allergies));
}

export function getSelectedRecipe(): string {
  return localStorage.getItem(KEYS.selectedRecipe) || '두부계란덮밥';
}

export function setSelectedRecipe(name: string): void {
  localStorage.setItem(KEYS.selectedRecipe, name);
}

export function getSelectedRecipeId(): string {
  return localStorage.getItem(KEYS.selectedRecipeId) || '';
}

export function setSelectedRecipeId(id: string): void {
  localStorage.setItem(KEYS.selectedRecipeId, id);
}

export function getAuth(): AuthInfo | null {
  try {
    const raw = localStorage.getItem(KEYS.auth);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setAuth(auth: AuthInfo): void {
  localStorage.setItem(KEYS.auth, JSON.stringify(auth));
}

export function clearAuth(): void {
  localStorage.removeItem(KEYS.auth);
}

export function getRecommendCache(signature: string): CachedRecipeSummary[] | null {
  try {
    const raw = localStorage.getItem(KEYS.recommendCache);
    if (!raw) return null;
    const cache: { signature: string; recipes: CachedRecipeSummary[] } = JSON.parse(raw);
    return cache.signature === signature ? cache.recipes : null;
  } catch {
    return null;
  }
}

export function setRecommendCache(signature: string, recipes: CachedRecipeSummary[]): void {
  localStorage.setItem(KEYS.recommendCache, JSON.stringify({ signature, recipes }));
}
