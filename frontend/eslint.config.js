import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import hooks from 'eslint-plugin-react-hooks';
import refresh from 'eslint-plugin-react-refresh';
import accessibility from 'eslint-plugin-jsx-a11y-x';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'test-results', 'playwright-report'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked.map((config) => ({
    ...config,
    files: ['src/**/*.{ts,tsx}', 'test-utils/**/*.{ts,tsx}', 'tests/**/*.ts', 'live-tests/**/*.ts', '*.ts'],
  })),
  { files: ['**/*.{cjs,mjs}'], languageOptions: { globals: globals.node } },
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { 'react-hooks': hooks, 'react-refresh': refresh },
    rules: {
      ...hooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
  { files: ['src/**/*.{ts,tsx}'], languageOptions: { globals: globals.browser } },
  {
    files: ['test-utils/**/*.{ts,tsx}', 'tests/**/*.ts', 'live-tests/**/*.ts'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
  { files: ['*.config.ts'], languageOptions: { globals: globals.node } },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/**/*.test.{ts,tsx}'],
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    rules: {
      '@typescript-eslint/consistent-type-imports': 'error',
      '@typescript-eslint/switch-exhaustiveness-check': 'error',
      complexity: ['error', { max: 15, variant: 'modified' }],
      'max-depth': ['error', 4],
    },
  },
  {
    files: ['src/**/*.test.{ts,tsx}', 'test-utils/**/*.{ts,tsx}', 'tests/**/*.ts', 'live-tests/**/*.ts', '*.config.ts'],
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    rules: {
      // Promise-shaped test doubles deliberately model asynchronous transport contracts.
      '@typescript-eslint/require-await': 'off',
    },
  },
  {
    files: ['src/**/*.tsx'],
    ignores: ['src/**/*.test.tsx'],
    plugins: { 'jsx-a11y-x': accessibility },
    rules: { ...accessibility.configs.recommended.rules },
  },
);
