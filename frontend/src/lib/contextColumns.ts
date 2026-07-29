export function availableContextColumns(
  headers: string[],
  sourceColumn: string,
  targetColumn: string,
): string[] {
  return headers.filter(
    (header) => header !== sourceColumn && header !== targetColumn,
  );
}

export function previewColumnValues(
  preview: Record<string, string>[],
  column: string,
  limit = 3,
): string[] {
  const seen = new Set<string>();
  for (const row of preview) {
    const value = String(row[column] ?? "").trim();
    if (value) seen.add(value);
    if (seen.size >= limit) break;
  }
  return [...seen];
}
