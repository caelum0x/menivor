/**
 * Minimal ambient jest globals so the project `tsc` typechecks the ClipMarket
 * tests without the `@types/jest` package (this workspace ships no test runner
 * yet). At runtime the real jest provides these; this only covers the API
 * surface the tests use. Delete this shim once `jest` + `@types/jest` are added.
 */

declare function describe(name: string, fn: () => void): void;
declare function it(name: string, fn: () => unknown): void;
declare function beforeEach(fn: () => unknown): void;
declare function afterEach(fn: () => unknown): void;

interface JestMatchers {
  toBe(expected: unknown): void;
  toEqual(expected: unknown): void;
  toContain(expected: unknown): void;
  toHaveLength(length: number): void;
  toBeUndefined(): void;
  toBeNull(): void;
  toBeInstanceOf(cls: unknown): void;
  toBeGreaterThan(n: number): void;
  toMatchObject(shape: unknown): void;
  readonly not: JestMatchers;
  readonly rejects: JestMatchers;
  readonly resolves: JestMatchers;
}

declare function expect(actual: unknown): JestMatchers;

declare namespace jest {
  interface Mock<T = unknown> {
    (...args: unknown[]): T;
    readonly mock: { readonly calls: unknown[][] };
    mockResolvedValueOnce(value: unknown): Mock<T>;
    mockResolvedValue(value: unknown): Mock<T>;
  }
  function fn<T = unknown>(impl?: (...args: unknown[]) => T): Mock<T>;
  function resetAllMocks(): void;
}
