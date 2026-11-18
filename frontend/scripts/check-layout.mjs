import { readdir } from 'node:fs/promises';

// Only the application entry belongs directly under src; all other sources have an owner.
const entries = await readdir(new URL('../src/', import.meta.url), { withFileTypes: true });
const unowned = entries.filter((entry) => entry.isFile() && entry.name !== 'main.tsx').map((entry) => entry.name);
if (unowned.length) {
  console.error(`Move unowned frontend sources into an owning directory: ${unowned.join(', ')}`);
  process.exitCode = 1;
}
