// Cytoscape cannot resolve var(...), so graph styles read the computed value at call time.
export function resolveColors<K extends string>(names: readonly K[]): Record<K, string> {
  const styles = getComputedStyle(document.documentElement);
  return Object.fromEntries(names.map((name) => [name, styles.getPropertyValue(name).trim()])) as Record<K, string>;
}
