const trimTrailingSlash = (value: string) => value.replace(/\/+$/, "");
const ensureLeadingSlash = (value: string) =>
  value.startsWith("/") ? value : `/${value}`;

export const API_BASE_URL = trimTrailingSlash(
  import.meta.env.VITE_API_BASE_URL ?? "",
);

export function buildApiUrl(path: string) {
  return `${API_BASE_URL}${ensureLeadingSlash(path)}`;
}
