import { readFile, readdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import ts from 'typescript';

// Only these source roots and product capabilities have defined dependency policies.
const source = process.argv[2] ? resolve(process.argv[2]) : new URL('../src/', import.meta.url);
const roots = new Set(['app', 'modules', 'infrastructure', 'shared']);
const owners = new Set(['session', 'investigations', 'runtime', 'actions', 'model-selection', 'system-status']);
const entries = await readdir(source, { withFileTypes: true });
const unowned = entries
  .filter((entry) => (entry.isDirectory() ? !roots.has(entry.name) : entry.name !== 'main.tsx'))
  .map((entry) => entry.name);
const modules = process.argv[2] ? resolve(process.argv[2], 'modules') : new URL('../src/modules/', import.meta.url);
const moduleEntries = await readdir(modules, { withFileTypes: true });
unowned.push(
  ...moduleEntries
    .filter((entry) => !entry.isDirectory() || !owners.has(entry.name))
    .map((entry) => `modules/${entry.name}`),
);
const presentationPath = process.argv[2]
  ? resolve(process.argv[2], 'modules/runtime/presentation.ts')
  : new URL('../src/modules/runtime/presentation.ts', import.meta.url);
const presentation = ts.createSourceFile(
  'presentation.ts',
  await readFile(presentationPath, 'utf8'),
  ts.ScriptTarget.Latest,
  true,
);
const [entry] = presentation.statements;
const exports =
  entry &&
  ts.isExportDeclaration(entry) &&
  !entry.isTypeOnly &&
  entry.exportClause &&
  ts.isNamedExports(entry.exportClause) &&
  entry.moduleSpecifier &&
  ts.isStringLiteral(entry.moduleSpecifier) &&
  entry.moduleSpecifier.text === './ui/RuntimeContent' &&
  entry.exportClause.elements.length === 2 &&
  entry.exportClause.elements.every((element) => !element.isTypeOnly && !element.propertyName) &&
  entry.exportClause.elements
    .map((element) => element.name.text)
    .sort()
    .join(',') === 'EnvironmentContent,LogContent';
if (presentation.statements.length !== 1 || !exports) {
  unowned.push('modules/runtime/presentation.ts (runtime-presentation-is-read-only)');
}
if (unowned.length) {
  console.error(`Move unowned frontend sources into an owning directory: ${unowned.join(', ')}`);
  process.exitCode = 1;
}
